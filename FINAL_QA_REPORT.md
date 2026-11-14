# CampusBite – Final QA report (2026-11-15)

Every result below comes from commands actually executed on this machine (Windows 11, Docker 29.9,
Node 22.17, Python 3.12, Chrome) against the running stack: PostgreSQL 16 + FastAPI in Docker Compose,
frontend via the Vite dev server (:5173) and the nginx Docker build (:3000).

## Results
| Check | Command | Result |
|---|---|---|
| Frontend build | `cd frontend && npm run build` | ✓ 1653 modules transformed, built in 5.86 s, no errors |
| Backend tests (SQLite) | `cd backend && pytest -q` | **255 passed, 5 skipped** (the 5 are PostgreSQL-only migration tests) |
| Backend tests (PostgreSQL) | `TEST_DATABASE_URL=… pytest -q` (Phase 2 full run) | 244 passed, 0 skipped; after Phase 3, `test_migrations`, `test_phase3`, `test_refunds` re-run on PostgreSQL: 30 passed |
| E2E + responsive (dev server) | `cd frontend && npx playwright test` | **12 passed** (2.5 min) |
| E2E workflows (Docker build :3000) | `E2E_BASE_URL=http://localhost:3000 npx playwright test e2e/workflows.spec.js` | **7 passed** |
| API smoke (live stack) | scripted HTTP checks of all three roles | 30/30 passed |
| Migrations on PostgreSQL | `docker compose exec backend alembic upgrade head` | 0001 → 0004 applied |
| Health / docs | `GET /health`, `/health/db`, `/docs`; frontend `:3000/` and SPA route | all 200 |
| CORS | preflight from `localhost:3000` and `localhost:5173` | allowed |
| Secrets | `git status` / `git check-ignore` | `backend/.env`, `.env.bak`, `frontend/.env` ignored; nothing secret tracked |
| Lint / frontend unit tests | – | none configured in the project (not run) |

## Verified end-to-end workflows (browser, real backend + PostgreSQL)
1. Register customer → dish search with price filter → add to cart → checkout (mock payment) → order page.
2. Cancel while placed → order cancelled, payment shows Refunded; history filter by status.
3. Owner: Accept → Start preparing → Mark ready → assign "Dev Courier" (assignment only offered when ready).
4. Courier: Picked up → Mark delivered (confirmation dialog); no further actions offered.
5. Customer: 4-star review (button disappears afterwards) → refund request (button disappears) → owner approves (confirmation) → customer sees "Refund approved · refunded" and payment Refunded.
6. AI insights: the page shows the backend's real response (here 503 "not configured" because no `OPENAI_API_KEY` is set).
7. Guards: customer opening `/owner` or `/delivery` → "Not allowed"; unknown route → 404 page; forged/expired token → token cleared, redirected to login.
8. Validation: empty registration shows inline errors; wrong password shows the backend message.
9. Layout: 11 pages × 5 widths (375, 430, 768, 1024, 1440 px) for guest, customer, owner, courier – no horizontal overflow, navigation visible (top bar ≥ 820 px, bottom bar below); add-to-cart buttons ≥ 32 px tall.

Backend tests additionally cover: auth/JWT hardening, every role/ownership rule, lifecycle (skips, reversals,
repeats, terminal states, concurrent writes), checkout (idempotency, tampering, rollback), payments, refunds
(duplicates, concurrency, rollback), reminders (dedupe, retry, stale orders → owner), statistics scoping,
privacy sweep, AI endpoint (scoping to own orders, 429/502/503 handling, key never echoed).

## Features
Complete: auth (JWT persistence, logout, expiry), role routing, restaurants/menus/search/filters/pagination,
cart + idempotent checkout with mock payment, order history + tracking + cancellation, owner dashboard +
statistics + menu CRUD + availability, order acceptance/preparation/ready/assignment, delivery dashboard +
history, reviews, refunds (request/approve/reject with ledger reversal), owner reminders (idle 15+ min),
AI insights endpoint + chat UI, loading/error/empty states, confirmation dialogs, responsive layout.

## Update: OpenAI SDK insights (2026-11-15)
- `POST /api/v1/ai/insights` (optional question) and `GET /api/v1/ai/summary`, official `openai` SDK 1.109.1,
  timeout + `OPENAI_MAX_RETRIES` (default 2), per-customer rate limit, 429/502/503/504 mapping.
- Backend tests: **262 passed, 5 skipped** (`tests/test_ai.py`: 17 tests). Frontend build ✓.
  Playwright workflows against the Docker build: **7 passed** (AI page: question, summary, no-orders customer).

## Update: automated idle-order reminders (2026-11-15)
- Migration 0005 (`orders.status_updated_at`, reminder event keys/snapshots/read state) applied to PostgreSQL;
  upgrade/downgrade + model drift check pass on PostgreSQL.
- Dedicated `scheduler` service (APScheduler, every 60 s, advisory lock); API no longer schedules anything.
- Backend: **269 passed, 5 skipped** (SQLite); PostgreSQL subset (migrations, reminders, constraints, lifecycle): **55 passed**.
- Live: real order backdated 16 min → worker created exactly 1 reminder without API calls; after SIGTERM
  restart + 2 more runs still 1; owner unread 0→1→0 after mark-read; other owner cannot see it.
- Playwright against the Docker build: **12 passed**. `npm run build` ✓.

## Final verification: AI insights + reminders (2026-11-15)
| Check | Result |
|---|---|
| Backend suite, SQLite (`pytest -q`) | 275 passed, 5 skipped (PostgreSQL-only migration tests) |
| Backend suite, PostgreSQL (`TEST_DATABASE_URL=… pytest -q`) | **280 passed, 0 skipped** |
| `npm run build` | ✓ 1653 modules |
| `docker compose config -q` | valid (db, backend, scheduler, frontend) |
| `alembic current` (Docker DB) | 0005 (head) |
| Backend + scheduler startup | healthy; worker logs "started (every 60s, threshold 15 min)" and successful runs |
| Live scheduler | backdated order → 1 reminder, unchanged after SIGTERM restart + 2 runs; duplicate periods in DB: 0 |
| Live API smoke (JWT, roles, customer/owner isolation) | 30/30 |
| Secret scan | no keys in tracked files, frontend source, bundle or Vite env; `backend/.env` ignored |
| **OpenAI live call** | **not executed** – no `OPENAI_API_KEY` available; AI success/failure paths verified with a mocked SDK only |

## Not verified / known limitations
- **AI answers from OpenAI were not observed live**: no `OPENAI_API_KEY` is configured here, so the endpoint
  correctly returns 503. The OpenAI request/response path is covered by tests with a faked HTTP response.
  To enable: set `OPENAI_API_KEY` in `backend/.env`, then `docker compose restart backend`.
- AI rate limit is in-process memory (not shared across several API instances).
- A stale-order reminder is sent once per order (event key = order + type).
- Status names in the API are `ready_for_pickup` / `out_for_delivery` (UI shows "Ready" / "Out for delivery").
- `POST /orders/{id}/claim` (courier self-assign) still exists in the API but is not used by the UI.
- Customers may also cancel unpaid `pending_payment` orders (nothing charged); paid orders only while `placed`.
- Currency symbol is a frontend setting (`VITE_CURRENCY_SYMBOL`); the API stores no currency.
- No ESLint config or frontend unit tests exist; coverage is via Playwright E2E.
- E2E tests create real orders in the development database.

## Files changed in this final pass
- `frontend/playwright.config.js`, `frontend/e2e/helpers.js`, `frontend/e2e/workflows.spec.js`, `frontend/e2e/responsive.spec.js` (new)
- `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore` (new); `docker-compose.yml` (frontend service on :3000)
- `frontend/package.json` (`@playwright/test`, `test:e2e`), `frontend/.gitignore`, `frontend/src/styles/global.css` (focus-visible)
- `README.md` (rewritten), `FINAL_QA_REPORT.md` (new)

## Run it
```bash
docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
# open http://localhost:3000   (API docs: http://localhost:8000/docs)
```
