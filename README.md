# CampusBite

Campus food ordering: customers order from campus restaurants, owners manage menus and
orders, delivery partners deliver. This repository currently contains the **backend API**
(FastAPI + PostgreSQL). `frontend/` is still empty.

```
backend/      FastAPI app (app/), Alembic migrations (alembic/), tests (tests/)
database/     reserved for database files
docker-compose.yml   PostgreSQL 16 + backend
```

## 1. Configure

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set at least `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
and a long random `SECRET_KEY`. Optional:

| Setting | Purpose |
|---|---|
| `STAFF_REGISTRATION_KEY` | Required (as `X-Registration-Key` header) to register owners / delivery partners. Unset = only customers can sign up. |
| `PAYMENT_SIMULATOR_OUTCOME` | `success` (default), `decline` or `error` for the dummy payment gateway. No real gateway is integrated. |
| `PAYMENT_SIMULATOR_METHOD_OUTCOMES` | Per-method override, e.g. `wallet=decline,card=error`. |

Do not set `DATABASE_URL` unless you need a full override; it takes precedence over `POSTGRES_*`.

## 2. Run with Docker Compose (recommended)

```bash
docker compose up -d --build                         # db + backend (http://localhost:8000)
docker compose exec backend alembic upgrade head     # create / upgrade the schema
docker compose exec backend python -m app.seed       # optional sample data
curl http://localhost:8000/health/db                 # {"status":"ok","database":"connected"}
```

The schema is managed **only** by Alembic; the app never creates tables. Data lives in the
`campusbite_pgdata` volume. **Never run `docker compose down -v`** unless you want to delete it.

## 3. Run the API on your machine (database still in Docker)

```bash
docker compose up -d db
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
alembic upgrade head
python -m app.seed               # optional
uvicorn app.main:app --reload    # POSTGRES_HOST=localhost in .env
```

## 4. Sample data

`python -m app.seed` is idempotent and refuses to run when `ENVIRONMENT=production`.
All accounts use the password `Campus123`.

| Role | Accounts |
|---|---|
| Customer | `asha@example.com`, `ben@example.com`, `chen@example.com` |
| Owner | `grill.owner@example.com` (Campus Grill, Late Night Bites), `dosa.owner@example.com` (Dosa Corner) |
| Delivery partner | `dev.courier@example.com`, `eva.courier@example.com` |

## 5. Tests

```bash
cd backend
pytest -q                        # fast: throwaway in-memory SQLite
```

Against PostgreSQL (also runs the Alembic migration tests, which are skipped on SQLite).
Use a **separate** database whose name contains `test`; the tests wipe it.

```bash
docker compose exec db createdb -U <POSTGRES_USER> campusbite_test
# PowerShell:  $env:TEST_DATABASE_URL = "postgresql+psycopg://<user>:<password>@127.0.0.1:5432/campusbite_test"
export TEST_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/campusbite_test
pytest -q
```

## 6. API

Interactive docs: **http://localhost:8000/docs** (OpenAPI JSON at `/openapi.json`).
Click **Authorize** and log in with an e-mail and password (see `backend/docs/AUTH.md`).
All endpoints are under `/api/v1`. Ids are UUIDs. List endpoints return
`{items, total, limit, offset}` and accept `limit` (1-100) and `offset`.

| Area | Endpoints | Who |
|---|---|---|
| Auth | `POST /auth/register`, `POST /auth/login` (form), `POST /auth/login/json`, `GET/PATCH /auth/me`, `POST /auth/change-password` | public / signed in |
| Browse | `GET /restaurants`, `GET /restaurants/{id}`, `GET /restaurants/{id}/menu`, `GET /restaurants/{id}/reviews`, `GET /menu-items` (search) | public |
| Restaurants | `POST /restaurants`, `PATCH /restaurants/{id}`, `GET /restaurants/mine`, `GET /restaurants/mine/menu-items` | owner (own only) |
| Menu | `POST /restaurants/{id}/menu`, `PATCH|DELETE /restaurants/{id}/menu/{item}`, `POST .../{item}/disable`, `POST .../{item}/enable` | owner (own only) |
| Checkout | `POST /orders` (`payment_method` + `Idempotency-Key` header = pay in the same transaction) | customer |
| Orders | `GET /orders/me`, `GET /orders/{id}`, `GET /orders/{id}/payment`, `GET /orders/{id}/tracking`, `POST /orders/{id}/cancel` | customer (own only) |
| Lifecycle | `PATCH /orders/{id}/status`, `POST /orders/{id}/assign-delivery` | owner / assigned courier |
| Delivery | `GET /deliveries/me`, `GET /orders/available`, `POST /orders/{id}/claim` | delivery partner |
| Payments | `POST /payments/orders/{id}/pay`, `GET /payments/orders/{id}`, `GET /payments/orders/{id}/ledger` | customer / owner |
| Reviews | `POST /reviews`, `DELETE /reviews/{id}` | customer (delivered orders) |
| Refunds | `POST /orders/{id}/refund-requests`, `GET /refund-requests/me` (customer); `GET /refund-requests/incoming`, `POST /refund-requests/{id}/decision` (owner) | |
| Statistics | `GET /statistics/customer`, `GET /statistics/owner`, `GET /statistics/me` | own data only |
| Health | `GET /health`, `GET /health/db` | public |

Order lifecycle (all rules in `backend/app/services/order_lifecycle.py`):

```
pending_payment -> placed -> accepted -> preparing -> ready_for_pickup -> out_for_delivery -> delivered
customer may cancel until preparation starts; owner may reject until preparation starts
```

Prices and totals are always computed on the server; the client sends only item ids and
quantities. Other users' orders, payments and refund requests return 404.

## 7. Background jobs

Reminders (payment pending, order ready, review request) are sent at most once per order and type:

```bash
docker compose exec backend python -m app.services.reminder_service
```

Run it periodically (cron / Task Scheduler). Notifications currently use a mock adapter.

## 8. Frontend (React + Vite)

```bash
cd frontend
cp .env.example .env        # VITE_API_BASE_URL=http://localhost:8000/api/v1
npm install
npm run dev                 # http://localhost:5173 (allowed by the backend's CORS_ORIGINS)
npm run build               # production build in frontend/dist
```

Customers browse, search, order and track; owners manage restaurants, menus, orders, couriers
and refunds; delivery partners claim and complete deliveries. Every screen uses the real API
(see `API_ENDPOINT_MAP.md`). Payments are simulated by the backend.
