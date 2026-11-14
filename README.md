# CampusBite

Campus food ordering. Customers browse campus restaurants, order and track deliveries;
restaurant owners manage menus, orders, couriers and refunds; delivery partners deliver.

```
React (Vite) ──HTTP/JSON + JWT──> FastAPI ──SQLAlchemy──> PostgreSQL 16
frontend/                          backend/app                (Docker volume)
                                   ├─ routers/   HTTP + auth dependencies
                                   ├─ services/  business rules (lifecycle, checkout, refunds, AI…)
                                   ├─ models/    SQLAlchemy models, Alembic migrations in backend/alembic
                                   └─ tests/     pytest (SQLite by default, PostgreSQL optional)
```

**Stack:** React 18, React Router 6, Axios, Context API, Lucide icons, Vite 5 · FastAPI, Pydantic 2,
SQLAlchemy 2, Alembic, PostgreSQL 16, JWT (PyJWT + bcrypt), httpx (OpenAI) · pytest, Playwright · Docker Compose.

## Features
- **Customers:** register/login, browse and search restaurants and dishes (price filters, sorting,
  pagination), one-restaurant cart with live price/availability re-check, idempotent checkout with a
  simulated payment (`mock_paid`), order history with status/date filters, live tracking, cancel while
  placed, star reviews (once per delivered order), one refund request per delivered order, AI insights chat.
- **Owners:** dashboard (orders, pending, completed, revenue, refunds, per-restaurant performance, top
  dishes), reminders for orders idle 15+ minutes, order queue (accept → preparing → ready, reject), courier
  assignment once ready, refund approve/reject, restaurant and menu CRUD with availability.
- **Delivery partners:** assigned deliveries only, picked up → delivered, history, stats.
- All rules are enforced by the backend (roles, ownership, state machine, row locks / compare-and-set).

## Quick start (Docker)
```bash
cp backend/.env.example backend/.env      # set POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / SECRET_KEY
docker compose up -d --build              # db + backend (:8000) + scheduler (reminders) + frontend (:3000)
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed      # sample data, password Campus123
```
Open **http://localhost:3000** · API docs **http://localhost:8000/docs** · health `http://localhost:8000/health/db`.
Never run `docker compose down -v` unless you want to delete the database volume.

## Frontend development
```bash
cd frontend
cp .env.example .env     # VITE_API_BASE_URL=http://localhost:8000/api/v1, VITE_CURRENCY_SYMBOL=₹
npm install
npm run dev              # http://localhost:5173
npm run build            # production build -> frontend/dist
```

## Backend without Docker for the API
```bash
docker compose up -d db
cd backend && python -m venv .venv && .venv\Scripts\activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload            # POSTGRES_HOST=localhost
```

## Environment variables (`backend/.env`)
| Variable | Purpose |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT` | Database (Compose sets host `db`). `DATABASE_URL` overrides them if set. |
| `SECRET_KEY` | JWT signing key (32+ random chars in production). |
| `STAFF_REGISTRATION_KEY` | Required header value to register owners / delivery partners. |
| `CORS_ORIGINS` | Default `http://localhost:3000,http://localhost:5173`. |
| `PAYMENT_SIMULATOR_OUTCOME` | `success` / `decline` / `error` for the dummy gateway. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` (gpt-4.1-mini), `OPENAI_TIMEOUT_SECONDS` (30), `OPENAI_MAX_RETRIES` (2) | AI insights via the official OpenAI SDK, server-side only. Empty key → 503. |
| `AI_RATE_LIMIT_REQUESTS` (10), `AI_RATE_LIMIT_WINDOW_SECONDS` (3600) | Per-customer AI budget (sliding window, both AI endpoints). |
| `REMINDER_SCHEDULER_ENABLED` (true), `ORDER_REMINDER_CHECK_INTERVAL_SECONDS` (60), `ORDER_REMINDER_THRESHOLD_MINUTES` (15) | Reminder worker. |

Frontend (`frontend/.env`): `VITE_API_BASE_URL`, `VITE_CURRENCY_SYMBOL`. No secrets live in the frontend.

## Sample accounts (after `python -m app.seed`, password `Campus123`)
| Role | E-mail |
|---|---|
| Customer | `asha@example.com`, `ben@example.com`, `chen@example.com` |
| Owner | `grill.owner@example.com` (Campus Grill, Late Night Bites), `dosa.owner@example.com` |
| Delivery partner | `dev.courier@example.com`, `eva.courier@example.com` |

## Role workflows
1. **Customer:** Restaurants → restaurant → *Add* → Cart → address + payment method → *Pay and place order* → order page (tracking, cancel while placed).
2. **Owner:** Orders → *Accept* → *Start preparing* → *Mark ready* → *Assign courier*. Refund requests appear at the top of Orders.
3. **Delivery partner:** My deliveries → *Picked up* → *Mark delivered*.
4. **Customer:** delivered order → *Write a review* / *Request refund*; AI Insights → ask about your orders.

Order lifecycle (`backend/app/services/order_lifecycle.py`):
`pending_payment → placed → accepted → preparing → ready_for_pickup → out_for_delivery → delivered`;
customers cancel before acceptance, owners reject before preparation.

## API
Interactive docs at `/docs`. Every route, its role and the frontend function that calls it: [`API_ENDPOINT_MAP.md`](API_ENDPOINT_MAP.md).

## Tests
```bash
cd backend && pytest -q                                  # in-memory SQLite; OpenAI is always mocked
# PostgreSQL (also runs the migration tests); database name must contain "test":
docker compose exec db createdb -U <user> campusbite_test
TEST_DATABASE_URL=postgresql+psycopg://<user>:<pw>@127.0.0.1:5432/campusbite_test pytest -q

cd frontend && npm run test:e2e        # Playwright with local Chrome: role workflows + layout at 375–1440 px
E2E_BASE_URL=http://localhost:3000 npm run test:e2e     # against the Docker build
```
E2E tests need the stack running and seeded; they create real orders.

## AI order insights
Customers ask questions about **their own** order history ("How much did I spend this week?",
"Which orders are still pending?") or request a summary.

- `POST /api/v1/ai/insights` – optional body `{"question": "..."}` (3–500 characters).
- `GET /api/v1/ai/summary` – summary of previous orders.
- Both require a JWT for a **customer** (401 without a token, 403 for owners / delivery partners).
- The customer is taken from the token; the newest 50 orders are loaded with SQLAlchemy. Totals,
  counts, pending orders and top dishes are computed in Python, then OpenAI (official SDK, server-side
  only) writes the explanation. No names, e-mails, phones or addresses are sent. No orders → a factual
  reply without calling OpenAI.
- Limits and errors: `AI_RATE_LIMIT_REQUESTS` per `AI_RATE_LIMIT_WINDOW_SECONDS` per customer → 429 with
  `Retry-After`; OpenAI rate limit → 429; quota exhausted / no key → 503; timeout → 504; other provider
  errors → 502. Errors contain only a safe `detail` message.

**Configure:** put `OPENAI_API_KEY=sk-...` (and optionally `OPENAI_MODEL`) in `backend/.env` – never in
`frontend/.env` – then `docker compose up -d backend`. **Verify:** log in as `asha@example.com`, open
*AI Insights*, click a suggestion or *Summarize my order history*.

## Automated order reminders
- Every order has `status_updated_at` (set on creation and on every status change only).
- The `scheduler` service (`python -m app.worker`, APScheduler) checks every
  `ORDER_REMINDER_CHECK_INTERVAL_SECONDS` (60) without needing any HTTP request. Orders that have been
  **placed** or **accepted** for more than `ORDER_REMINDER_THRESHOLD_MINUTES` (15) create one reminder
  for the restaurant owner per status period (`reminder_logs.event_key` is UNIQUE). A new eligible
  period (e.g. accepted and idle again) creates a new reminder. A PostgreSQL advisory lock stops extra
  worker copies from overlapping; failures are logged and retried on the next tick.
- Owner API (JWT, owner role, own restaurants only):
  `GET /api/v1/owner/reminders?unread_only=&limit=&offset=`, `GET /api/v1/owner/reminders/unread-count`,
  `PATCH /api/v1/owner/reminders/{id}/read`.
- The owner dashboard lists reminders (unread markers, *Mark read*), refreshing every minute.

```bash
docker compose up -d scheduler            # start (also part of `docker compose up -d`)
docker compose logs -f scheduler          # "reminder worker started (every 60s, threshold 15 min)"
docker compose exec scheduler python -m app.services.reminder_service   # one immediate pass
```
**Verify manually:** place an order as a customer, leave it *placed* for 16 minutes (or in a dev database:
`UPDATE orders SET status_updated_at = now() - interval '16 minutes' WHERE id = '<id>';`), wait for the
next minute, then open the owner dashboard as `grill.owner@example.com`.
