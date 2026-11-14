"""AI order insights: OpenAI SDK faked at the client boundary; real DB, real auth."""

import json
import logging
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services import ai_service
from tests.conftest import deliver, place_order

INSIGHTS = "/api/v1/ai/insights"
SUMMARY = "/api/v1/ai/summary"
Q = {"question": "How much did I spend this week?"}
KEY = "sk-test-secret-123"
_REQ = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _status(cls, code, headers=None, body=None):
    return cls("upstream", response=httpx.Response(code, request=_REQ, headers=headers or {}), body=body)


class FakeCompletions:
    def __init__(self, content="You spent 13.25 this week.", exc=None):
        self.content, self.exc, self.calls = content, exc, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr(KEY))
    monkeypatch.setattr(settings, "AI_RATE_LIMIT_REQUESTS", 3)
    monkeypatch.setattr(settings, "AI_RATE_LIMIT_WINDOW_SECONDS", 3600)
    ai_service._calls.clear()
    completions = FakeCompletions()
    monkeypatch.setattr(ai_service, "_client", lambda *a: SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    return completions


def _data(call):
    msgs = call["messages"]
    assert msgs[0]["role"] == "system"
    return json.loads(msgs[1]["content"].split("\n", 1)[1]), msgs[2]["content"]


def test_insights_use_only_own_real_orders(client, make_user, owner, customer, courier, restaurant, fake):
    mine = deliver(client, owner, customer, courier, restaurant)  # 2 x Burger 5.50 + Fries 2.25
    other = make_user("customer", "other@example.com")
    theirs = place_order(client, other, restaurant)["id"]

    resp = client.post(INSIGHTS, json=Q, headers=customer)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "You spent 13.25 this week."
    assert body["source"] == "openai" and body["orders_considered"] == 1

    data, question = _data(fake.calls[0])
    assert [o["id"] for o in data["orders_newest_first"]] == [mine[-8:]]
    assert theirs[-8:] not in json.dumps(data)
    assert data["facts"]["spent_this_week"] == "13.25"
    assert data["facts"]["most_ordered_dishes"][0] == {"dish": "Burger", "quantity": 2}
    assert data["orders_newest_first"][0]["items"][0]["subtotal"] == "11.00"
    assert "How much did I spend this week?" in question and question.startswith("CUSTOMER QUESTION (untrusted)")
    # minimal personal data: no address, e-mail or names of people
    blob = json.dumps(fake.calls[0])
    for private in ("Hostel 3", "customer@example.com", "Test customer"):
        assert private not in blob
    assert KEY not in resp.text


def test_question_is_optional_and_summary_endpoint(client, owner, customer, courier, restaurant, fake):
    deliver(client, owner, customer, courier, restaurant)
    assert client.post(INSIGHTS, headers=customer).status_code == 200  # no body at all
    assert client.post(INSIGHTS, json={}, headers=customer).status_code == 200
    s = client.get(SUMMARY, headers=customer)
    assert s.status_code == 200 and s.json()["source"] == "openai"
    assert "Summarize my previous orders" in fake.calls[-1]["messages"][2]["content"]


def test_client_cannot_choose_whose_orders(client, customer, fake):
    resp = client.post(INSIGHTS, json={**Q, "customer_id": "00000000-0000-0000-0000-000000000000"}, headers=customer)
    assert resp.status_code == 422 and fake.calls == []


def test_no_orders_is_answered_without_calling_openai(client, customer, fake):
    for resp in (client.post(INSIGHTS, json=Q, headers=customer), client.get(SUMMARY, headers=customer)):
        body = resp.json()
        assert resp.status_code == 200 and body["source"] == "no_orders" and body["orders_considered"] == 0
        assert body["model"] is None
    assert fake.calls == []


def test_customer_only_and_validation(client, owner, courier, customer, fake):
    for path, method in ((INSIGHTS, "post"), (SUMMARY, "get")):
        assert getattr(client, method)(path).status_code == 401
        assert getattr(client, method)(path, headers=owner).status_code == 403
        assert getattr(client, method)(path, headers=courier).status_code == 403
    assert client.post(INSIGHTS, json={"question": "hi"}, headers=customer).status_code == 422
    assert client.post(INSIGHTS, json={"question": "x" * 501}, headers=customer).status_code == 422
    assert fake.calls == []


def test_missing_key_is_503(client, owner, customer, courier, restaurant, monkeypatch):
    deliver(client, owner, customer, courier, restaurant)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    resp = client.post(INSIGHTS, json=Q, headers=customer)
    assert resp.status_code == 503 and "answer" not in resp.json()


@pytest.mark.parametrize("exc,status", [
    (_status(openai.RateLimitError, 429, {"retry-after": "7"}), 429),
    (_status(openai.RateLimitError, 429, body={"code": "insufficient_quota"}), 503),
    (openai.APITimeoutError(request=_REQ), 504),
    (openai.APIConnectionError(request=_REQ), 502),
    (_status(openai.AuthenticationError, 401), 502),
    (_status(openai.InternalServerError, 500), 502),
])
def test_upstream_failures_are_safe(client, owner, customer, courier, restaurant, fake, caplog, exc, status):
    deliver(client, owner, customer, courier, restaurant)
    fake.exc = exc
    with caplog.at_level(logging.DEBUG):
        resp = client.post(INSIGHTS, json=Q, headers=customer)
    assert resp.status_code == status
    body = resp.json()
    assert set(body) == {"detail"} and "Traceback" not in body["detail"]
    assert KEY not in resp.text and KEY not in caplog.text
    if status == 429:
        assert resp.headers["retry-after"] == "7"


@pytest.mark.parametrize("content", ["", "   ", None])
def test_empty_model_output_is_502(client, owner, customer, courier, restaurant, fake, content):
    deliver(client, owner, customer, courier, restaurant)
    fake.content = content
    assert client.post(INSIGHTS, json=Q, headers=customer).status_code == 502


def test_per_customer_rate_limit(client, make_user, owner, customer, courier, restaurant, fake):
    deliver(client, owner, customer, courier, restaurant)
    for _ in range(3):
        assert client.post(INSIGHTS, json=Q, headers=customer).status_code == 200
    resp = client.get(SUMMARY, headers=customer)  # shared budget across both endpoints
    assert resp.status_code == 429 and int(resp.headers["retry-after"]) > 0
    assert len(fake.calls) == 3
    other = make_user("customer", "c2@example.com")
    assert client.post(INSIGHTS, json=Q, headers=other).status_code == 200  # separate budget


def test_sdk_client_has_bounded_timeout_and_retries():
    c = ai_service._client("sk-x", "https://api.openai.com/v1", 7.5, 2)
    assert c.max_retries == 2 and c.timeout == 7.5
