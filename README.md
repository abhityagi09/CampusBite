# CampusBite

**CampusBite** is a campus food ordering and delivery platform. Customers order from campus
restaurants and track deliveries, restaurant owners run their kitchens and menus, and delivery
partners deliver. Payments are simulated; customer order insights use the OpenAI API.

## 1. Capstone objectives
- A full-stack, role-based web application: React frontend, FastAPI REST API, PostgreSQL database.
- Correct business rules for an order lifecycle, dummy payments, a payment ledger, reviews and refunds.
- Security: JWT authentication, bcrypt passwords, server-side authorization and data isolation.
- Operability: Docker Compose, migrations, request logging, a scheduled reminder worker, automated tests.
- An AI feature (OpenAI) that answers questions using only the signed-in customer's real orders.

## 2. Technology stack
| Layer | Technology |
|---|---|
| Frontend | React 18, React Router 7, Axios, Context API + hooks, Lucide icons, Vite 6 |
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PyJWT, bcrypt |
| Database | PostgreSQL 16 |
| Background jobs | APScheduler worker (`python -m app.worker`) |
| AI | Official OpenAI Python SDK (server-side only) |
| Containers | Docker Compose: `db`, `backend`, `scheduler`, `frontend` (nginx) |
| Tests | pytest (SQLite and PostgreSQL), Playwright (Chrome) |

## 3. Features by role
**Customer** – register / log in · browse restaurants (search, cuisine, open-now, pagination) · menus with
filters and sorting · dish search across restaurants with price range · one-restaurant cart (saved in the
browser, re-validated against live prices) · checkout with simulated payment (`mock_paid`), duplicate-safe ·
order history (status and date filters, payment and refund status) · live tracking timeline · cancel while
placed · star review once per delivered order · one refund request per delivered order · AI order insights chat.

**Restaurant owner** – dashboard (total / pending / completed orders, revenue, refunds, per-restaurant
performance, top dishes) · idle-order reminders with read/unread · incoming orders by status and date ·
accept → preparing → ready → assign courier · reject before preparation · approve / reject refunds ·
restaurant and menu CRUD, dish availability.

**Delivery partner** – only assigned deliveries · address and notes · picked up (out for delivery) →
delivered · history and status filter · stats.

## 4. Folder structure
```
docker-compose.yml        db + backend + scheduler + frontend
docker-compose.e2e.yml    E2E only: mock OpenAI server for deterministic browser tests
backend/
  app/main.py             FastAPI app, middleware (logging, timing, CORS), error handlers
  app/core/               settings, security (JWT, bcrypt), exceptions, permissions
  app/models/             SQLAlchemy models          app/schemas/   Pydantic schemas
  app/routers/            REST endpoints              app/services/  business logic
  app/worker.py           reminder scheduler          app/seed.py    demo data
  alembic/versions/       migrations 0001–0006        tests/         pytest suite
frontend/
  src/api/                Axios client + every endpoint call
  src/contexts/           AuthContext, CartContext    src/routes/    role guards
  src/components/         Layout, UI kit              src/pages/     customer, owner/, delivery/
  e2e/                    Playwright tests (+ mock OpenAI server)
```

## 5. Prerequisites
Docker Desktop (with Compose) · Node.js 18+ (22 tested) · Python 3.12 only for running backend tests or the
API outside Docker · Google Chrome only for the Playwright tests.

## 6. Environment variables
```bash
cp backend/.env.example backend/.env       # backend, database, scheduler, AI (secrets live here only)
cp frontend/.env.example frontend/.env     # frontend (no secrets)
```
| Variable (`backend/.env`) | Default | Purpose |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | – (required) | Database credentials (used by the db container too) |
| `POSTGRES_HOST`, `POSTGRES_PORT` | localhost, 5432 | Compose overrides the host to `db` |
| `SECRET_KEY` | placeholder | JWT signing key; **required, ≥32 chars when `ENVIRONMENT=production`** |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `JWT_ALGORITHM`, `JWT_ISSUER`, `BCRYPT_ROUNDS` | 60, HS256, campusbite-api, 12 | Auth |
| `STAFF_REGISTRATION_KEY` | empty (disabled) | Header value needed to register owners / delivery partners |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Explicit origins only (`*` is rejected) |
| `PAYMENT_SIMULATOR_OUTCOME`, `PAYMENT_SIMULATOR_METHOD_OUTCOMES` | success, – | Dummy gateway outcome (`success`/`decline`/`error`) |
| `REMINDER_SCHEDULER_ENABLED`, `ORDER_REMINDER_CHECK_INTERVAL_SECONDS`, `ORDER_REMINDER_THRESHOLD_MINUTES` | true, 60, 15 | Reminder worker |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES` | –, gpt-4.1-mini, 30, 2 | AI insights |
| `AI_RATE_LIMIT_REQUESTS`, `AI_RATE_LIMIT_WINDOW_SECONDS` | 10, 3600 | Per-customer AI budget |

Frontend (`frontend/.env`): `VITE_API_BASE_URL` (default `http://localhost:8000/api/v1`), `VITE_CURRENCY_SYMBOL` (₹).

## 7. PostgreSQL
Compose runs PostgreSQL 16 in the `db` service with the named volume `campusbite_pgdata`, published only on
`127.0.0.1:5432`. Credentials come from `backend/.env`. Health: `docker compose exec db pg_isready`.
**Never run `docker compose down -v`** unless you intend to delete all data.

## 8. Backend with Docker Compose
```bash
docker compose up -d --build          # db, backend (:8000), scheduler, frontend (:3000)
docker compose ps                     # all four should become "healthy"
docker compose logs -f backend        # e.g. "GET /api/v1/restaurants -> 200 (12.3 ms)"
```

## 9. Frontend
Already served by Compose at **http://localhost:3000** (production build in nginx). For development:
```bash
cd frontend && npm install && npm run dev      # http://localhost:5173
npm run build                                  # production build -> frontend/dist
```

## 10. Database migrations
The schema is managed only by Alembic (the app never creates tables):
```bash
docker compose exec backend alembic upgrade head     # apply 0001 … 0006
docker compose exec backend alembic current          # -> 0006 (head)
```

## 11. Demo data
```bash
docker compose exec backend python -m app.seed       # idempotent; refuses to run when ENVIRONMENT=production
```
Fictional accounts, password **`Campus123`** (development only):

| Role | E-mail |
|---|---|
| Customer | `asha@example.com` (owns the demo orders), `ben@example.com`, `chen@example.com` |
| Owner | `grill.owner@example.com` (Campus Grill, Late Night Bites), `dosa.owner@example.com` (Dosa Corner) |
| Delivery partner | `dev.courier@example.com` (demo deliveries), `eva.courier@example.com` |

Demo orders at Campus Grill (notes start with `[demo]`): placed and accepted orders already idle for 20
minutes (reminders appear within a minute), preparing, ready (assign a courier), assigned, out for delivery,
delivered (review / refund it), delivered + reviewed, delivered with a pending refund request (approve or
reject it), refunded, cancelled.

## 12. Authentication and RBAC
- `POST /auth/register` creates customers; owners and delivery partners need the `X-Registration-Key` header
  (`STAFF_REGISTRATION_KEY`), so nobody can grant themselves a staff role.
- Passwords are hashed with bcrypt. `POST /auth/login/json` returns a JWT (`sub`, `type`, `iss`, `exp`).
- The frontend keeps the token in `localStorage`, restores the session through `GET /auth/me`, and logs out
  on any 401 (expired or forged token).
- Every protected route checks the role (`CustomerUser`, `OwnerUser`, `DeliveryUser`) and services re-check
  ownership: other customers' orders, other restaurants' orders/menus/reminders and unassigned deliveries
  answer 404/403. The role is always read from the database, never from the token.

## 13. Order lifecycle
`backend/app/services/order_lifecycle.py` is the single source of truth:
```
pending_payment → placed → accepted → preparing → ready → assigned → out_for_delivery → delivered → refunded
```
- Payment success moves `pending_payment → placed` (checkout with a payment method does this at once).
- Customers cancel only `placed` (or unpaid `pending_payment`); delivered orders can never be cancelled.
- Owners accept, prepare, mark ready, reject (`placed`/`accepted` only) and assign a courier **only when ready**
  (`POST /orders/{id}/assign-delivery`, re-assignment allowed until pickup).
- Only the assigned courier moves `assigned → out_for_delivery → delivered`.
- `delivered → refunded` happens only when a refund request is approved.
- Skipped, reversed and repeated transitions get 409; wrong actor 403. Updates use row locks plus
  compare-and-set writes, so concurrent requests cannot corrupt state. Every change is recorded in
  `order_status_events` with its time (`status_timestamps` in the API).

## 14. Payments and refunds
- Checkout prices come only from the database; the client sends item ids and quantities (`expected_total`
  is only compared). An `Idempotency-Key` header makes retries safe.
- The dummy gateway charges in the same transaction as the order: payment `mock_paid` + a `charge` row in
  `payment_ledger`. Decline → 402, gateway error → 502, nothing is saved.
- Cancelling or rejecting a paid order refunds it automatically (ledger `refund` row).
- Refund requests: delivered + paid orders only, reason required, one per order. The restaurant owner
  approves (request `processed`, payment `refunded`, ledger `refund`, order `refunded` – one transaction)
  or rejects (request `rejected`, order stays delivered).

## 15. AI order insights
- `POST /api/v1/ai/insights` (optional `{"question"}`, 3–500 chars) and `GET /api/v1/ai/summary`, customers only.
- The customer comes from the JWT; their newest 50 orders are loaded, exact totals/counts/top dishes are
  computed in Python, and OpenAI explains them. No names, e-mails, phones or addresses are sent. No orders →
  factual reply without calling OpenAI.
- Errors: rate limit → 429 (`Retry-After`), no key / quota → 503, timeout → 504, provider error → 502.
- **Enable:** put `OPENAI_API_KEY=sk-...` in `backend/.env`, then `docker compose up -d backend`.

## 16. Reminder scheduler
The `scheduler` container runs `python -m app.worker` (APScheduler) every
`ORDER_REMINDER_CHECK_INTERVAL_SECONDS`. Orders in `placed` or `accepted` for more than
`ORDER_REMINDER_THRESHOLD_MINUTES` (based on `orders.status_updated_at`) get one reminder for the restaurant
owner per status period (UNIQUE `reminder_logs.event_key`). A PostgreSQL advisory lock prevents overlapping
workers; a heartbeat file drives the container health check; failures are logged and retried next tick.
```bash
docker compose logs -f scheduler
docker compose exec scheduler python -m app.services.reminder_service    # one immediate pass
```
Owners see reminders on their dashboard (`GET /owner/reminders`, `/owner/reminders/unread-count`,
`PATCH /owner/reminders/{id}/read`).

## 17. API reference
Base URL `http://localhost:8000/api/v1`. Interactive docs: **http://localhost:8000/docs** (OpenAPI JSON at
`/openapi.json`). Every route, its role and the frontend function that calls it:
[`API_ENDPOINT_MAP.md`](API_ENDPOINT_MAP.md). Lists return `{items, total, limit, offset}`; errors return
`{"detail": ...}` (422 adds `errors`). Responses carry `X-Process-Time-Ms`.

## 18. Testing
```bash
cd backend && pytest -q                                   # SQLite, OpenAI always mocked
# PostgreSQL (also runs the migration tests); database name must contain "test":
docker compose exec db createdb -U <POSTGRES_USER> campusbite_test
TEST_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/campusbite_test pytest -q

cd frontend && npm run build
E2E_BASE_URL=http://localhost:3000 npm run test:e2e       # Playwright: role workflows + layouts (stack must be seeded)
# deterministic AI end-to-end (mock OpenAI server):
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d backend mock-openai
E2E_BASE_URL=http://localhost:3000 E2E_MOCK_OPENAI=1 npm run test:e2e
docker rm -f campusbite-mock-openai && docker compose up -d backend      # back to normal
```

## 19. Deployment guidance
- Set `ENVIRONMENT=production`, a random `SECRET_KEY` (≥32 chars), strong database credentials, your real
  frontend origin in `CORS_ORIGINS`, and `DEBUG=false`.
- In production remove the backend bind mount and `--reload` from `docker-compose.yml` (the image default
  runs without reload); build the frontend with the public API URL:
  `docker compose build --build-arg VITE_API_BASE_URL=https://api.example.edu/api/v1 frontend`.
- Run `alembic upgrade head` on every release before starting the new backend; run exactly one scheduler.
- Put the API and frontend behind HTTPS (reverse proxy / load balancer). Back up the database volume.

## 20. Troubleshooting
| Symptom | Fix |
|---|---|
| `/health/db` 503 or backend unhealthy | `docker compose ps db`; check `POSTGRES_*` in `backend/.env`; `docker compose logs db` |
| "relation does not exist" | run `docker compose exec backend alembic upgrade head` |
| Browser shows CORS / network errors | frontend origin must be in `CORS_ORIGINS`; `VITE_API_BASE_URL` must point at the API |
| Logged out immediately | token expired or `SECRET_KEY` changed – log in again |
| Registering an owner gives 403 | set `STAFF_REGISTRATION_KEY` and send it as `X-Registration-Key` |
| AI page says not configured (503) | set `OPENAI_API_KEY`, `docker compose up -d backend` |
| No reminders | `docker compose ps scheduler` (healthy?), `REMINDER_SCHEDULER_ENABLED=true`, orders must be idle > threshold |
| Port 5432/8000/3000 in use | change the left side of the port mapping in `docker-compose.yml` |

## 21. Security notes
Secrets live only in `backend/.env` (git-ignored); the frontend has none. bcrypt + signed JWTs with type,
issuer and expiry checks; roles from the database; staff sign-up requires a key; every endpoint authorizes
on the server; others' resources answer 404; request bodies forbid unknown fields; prices are server-side;
errors never include stack traces; the access log records method, path, status and duration only (no query
strings, bodies or tokens); CORS uses explicit origins.

## 22. Known limitations
- AI answers need a valid `OPENAI_API_KEY` (verified here only with mocks).
- Notifications use a mock adapter: reminders are stored and shown in the dashboard, not e-mailed/pushed.
- The AI rate limit is per API process (in memory).
- Currency is a display setting; the API stores plain decimal amounts.
- No ESLint / frontend unit tests; the UI is covered by Playwright end-to-end tests.

Further reports: [`CAPSTONE_AUDIT.md`](CAPSTONE_AUDIT.md), [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md),
[`REQUIREMENTS_CHECKLIST.md`](REQUIREMENTS_CHECKLIST.md), [`E2E_TEST_REPORT.md`](E2E_TEST_REPORT.md).
