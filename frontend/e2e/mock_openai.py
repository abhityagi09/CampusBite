"""Deterministic stand-in for the OpenAI Chat Completions API (E2E only, never production).
The reply quotes figures from the order data the backend sent, proving real data flowed through."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        ok = self.path.endswith("/chat/completions") and self.headers.get("authorization", "").startswith("Bearer ")
        if not ok:
            self.send_response(404); self.end_headers(); return
        data = json.loads(body["messages"][1]["content"].split("\n", 1)[1])
        f = data["facts"]
        top = f["most_ordered_dishes"][0]["dish"] if f["most_ordered_dishes"] else "none"
        text = (f"MOCK-AI: {f['orders_included']} orders analysed.\n- Spent this week: {f['spent_this_week']}\n"
                f"- Most ordered dish: **{top}**")
        out = json.dumps({"id": "mock", "object": "chat.completion", "created": 0, "model": body.get("model"),
                          "choices": [{"index": 0, "finish_reason": "stop",
                                       "message": {"role": "assistant", "content": text}}],
                          "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
