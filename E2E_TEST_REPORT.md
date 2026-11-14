# CampusBite – end-to-end verification report (2026-11-15)

Environment: Windows 11, Docker 29.9 (Compose), PostgreSQL 16 (container), Python 3.12, Node 22.17, Google Chrome (Playwright).
Every number below comes from a command executed in this session.

## Commands and results
| # | Command | Result |
|---|---|---|
| 1 | `pip check`; `pip install -r requirements.txt` | no broken requirements |
| 2 | `python -c "import app.main, app.worker"` | imports OK, 45 OpenAPI paths |
| 3 | `pytest -q` (SQLite) | **767 passed, 0 failed, 5 skipped, 0 errors** (skipped = PostgreSQL-only migration tests) |
| 4 | `TEST_DATABASE_URL=…campusbite_test pytest -q` (PostgreSQL) | **771 passed, 0 failed, 0 skipped, 0 errors** (run started before the heartbeat test was added; that test passes on SQLite) |
| 5 | `npm run build` | ✓ 1653 modules transformed, no errors |
| 6 | frontend lint / unit tests | **NOT CONFIGURED** (no ESLint/Vitest/Jest in the project); UI covered by Playwright |
| 7 | `docker compose config -q` | valid (db, backend, scheduler, frontend) |
| 8 | `docker compose up -d --build` | all images built; db, backend, scheduler, frontend **healthy** |
| 9 | `alembic upgrade head` / `alembic current` | `0006 (head)` |
| 10 | `pg_isready`, `GET /health/db` | accepting connections / `{"database":"connected"}` |
| 11 | `GET :8000/health`, `/docs`, `:3000/` | 200 / 200 / 200 |
| 12 | CORS preflight from `http://localhost:3000` | allowed (`authorization, idempotency-key`) |
| 13 | `docker compose logs --since 10m` | no errors / tracebacks |
| 14 | `E2E_BASE_URL=http://localhost:3000 E2E_MOCK_OPENAI=1 npx playwright test` (backend → mock OpenAI) | **12 passed, 0 failed** |
| 15 | live API script: Workflows 6–8 (`live_checks.py`) | **29/29** |
| 16 | live API smoke, all roles (`smoke.py`) | **30/30** |

## Workflows
| Workflow | How | Result |
|---|---|---|
| 1 Customer: register → login → browse → search → cart → checkout → mock payment → history | Playwright (UI) | PASS |
| 2 Owner: incoming order → accept → preparing → ready → assign courier | Playwright (UI) | PASS |
| 3 Courier: assigned order → out for delivery → delivered → history | Playwright (UI) | PASS |
| 4 Review + refund request → owner approves → order/payment `refunded`, ledger charge + refund | Playwright (UI) + smoke (API, DB records) | PASS |
| 5 AI summary: UI → backend → OpenAI SDK → **mock OpenAI server** → formatted answer quoting the customer's real figures | Playwright with `docker-compose.e2e.yml` | PASS (mock) |
| 5b AI with the real OpenAI API | – | **BLOCKED** (no `OPENAI_API_KEY`) |
| 6 Stale placed + accepted orders (2 restaurants) → scheduler → 3 reminders; rerun → 3; scheduler restart → 3; owner isolation; mark read | live script against the scheduler container | PASS |
| 7 Security: cross-customer, cross-restaurant, role, unassigned courier, staff sign-up without key | live script + pytest | PASS |
| 8 Negative: bad password, forged token, malformed JSON, empty cart, unavailable item, skipped transition, invalid cancel, early refund, AI unavailable (503) | live script + pytest | PASS |

## Bugs found and fixed in this pass
| Bug | Fix | Regression test |
|---|---|---|
| Scheduler and frontend containers had no health checks (a stalled worker would look "Up") | Worker writes a heartbeat after every run (also on failure); Compose health checks for scheduler (heartbeat age < 3 intervals) and frontend (HTTP); frontend waits for a *healthy* backend | `test_phase_verification.py::test_worker_heartbeat_written_even_when_a_run_fails` |
| No exhaustive check that the transition table matches the brief | Independent spec table, all 484 (from, to, actor) combinations | `test_transition_matrix.py` |
| AI workflow could not be exercised end-to-end without a paid key | Deterministic mock OpenAI server + Compose override (E2E only) | `e2e/workflows.spec.js` (E2E_MOCK_OPENAI) |

## Not executed
- **Live OpenAI call** – BLOCKED: no API key. All AI code paths ran against mocks (pytest SDK mock; E2E HTTP mock server).
- **Frontend lint/unit tests** – NOT CONFIGURED in the project.
- **Real e-mail/push notifications** – not implemented by design (mock notifier); reminder records are real.

## Reproduce
```bash
docker compose up -d --build && docker compose exec backend alembic upgrade head && docker compose exec backend python -m app.seed
cd backend && pytest -q
cd frontend && npm run build && E2E_BASE_URL=http://localhost:3000 npx playwright test
# deterministic AI E2E:
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d backend mock-openai
E2E_BASE_URL=http://localhost:3000 E2E_MOCK_OPENAI=1 npx playwright test
docker rm -f campusbite-mock-openai && docker compose up -d backend    # back to normal
```
