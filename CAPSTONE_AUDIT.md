# CampusBite – capstone completion and release audit (2026-11-15)

## A. Executive summary
CampusBite is a working React + FastAPI + PostgreSQL application with three role-specific experiences,
a strictly enforced order lifecycle, dummy payments with a ledger, reviews, refunds, OpenAI-backed
order insights, a scheduled reminder worker, request logging/timing middleware and Docker Compose
deployment. In this final pass every result below was re-executed, not copied from earlier reports.

**81 requirements: 80 PASS, 0 FAIL, 0 PARTIAL, 1 BLOCKED (live OpenAI answer – no API key), 0 NOT RUN.**
Verdict: **ready for submission**, with the single external blocker documented.

## B. Requirement checklist
Evidence key: **T** = pytest (`backend/tests/…`), **E** = Playwright browser test (`frontend/e2e/…`),
**L** = live check against the running Docker stack, **C** = code inspection.

| # | Area / requirement | Status | Evidence |
|---|---|---|---|
| 1 | Stack: React, hooks, React Router, Axios | PASS | C `frontend/src/App.jsx`, `src/api/client.js`; E |
| 2 | Stack: FastAPI, Pydantic, SQLAlchemy | PASS | C `backend/app/`; T (770) |
| 3 | Stack: JWT authentication | PASS | T `test_security.py` |
| 4 | Stack: PostgreSQL | PASS | T on PostgreSQL (775); L `pg_isready` |
| 5 | Stack: Docker / Docker Compose | PASS | L 4 containers healthy |
| 6 | Stack: OpenAI integration (backend SDK) | PASS | T `test_ai.py` (SDK mocked); E with mock server |
| 7 | Stack: Git-compatible structure | PASS | C `.gitignore`; `git status` (secrets ignored) |
| 8 | Customer: restaurant listing | PASS | T `test_restaurants.py`; E |
| 9 | Customer: menus with details and prices | PASS | T; E |
| 10 | Customer: search dishes by name | PASS | T; E (dish search) |
| 11 | Customer: filter by price | PASS | T; E (max price) |
| 12 | Customer: cart add/update/remove | PASS | C `CartContext.jsx`; E |
| 13 | Customer: checkout with dummy payment | PASS | T `test_checkout.py`; E; L |
| 14 | Customer: order history | PASS | T; E |
| 15 | Customer: order tracking | PASS | T (`status_timestamps`); E |
| 16 | Customer: eligible cancellation | PASS (see K) | T `test_transition_matrix.py`; E |
| 17 | Customer: reviews/ratings after delivery, once | PASS | T `test_stats_and_privacy.py`; E |
| 18 | Customer: refund request after delivery | PASS | T `test_refunds.py`; E |
| 19 | Customer dashboard: status, date, payment, refund status | PASS | T `test_frontend_support.py`; E |
| 20 | Owner: restaurant dashboard + statistics | PASS | T `test_stats_and_privacy.py`; E |
| 21 | Owner: create/update menu items | PASS | T `test_restaurants.py` |
| 22 | Owner: dish availability | PASS | T; L (disable/enable) |
| 23 | Owner: incoming orders by status and date | PASS | T `test_phase3.py` |
| 24 | Owner: accept → preparing → ready | PASS | T; E |
| 25 | Owner: assign courier only when READY | PASS | T `test_capstone_rules.py`, matrix; L |
| 26 | Owner: approve/reject refunds | PASS | T `test_refunds.py`, `test_capstone_rules.py`; E |
| 27 | Owner: stale-order reminders | PASS | T `test_owner_reminders.py`; L demo data |
| 28 | Owner: isolation from other restaurants | PASS | T `test_security.py`, `test_restaurants.py`; L |
| 29 | Courier: assigned deliveries only | PASS | T `test_orders.py`; L |
| 30 | Courier: necessary delivery details | PASS | C `DeliveryPage.jsx` (address, notes) |
| 31 | Courier: ASSIGNED → OUT_FOR_DELIVERY | PASS | T; E |
| 32 | Courier: mark DELIVERED | PASS | T; E |
| 33 | Courier: delivery history | PASS | T `test_capstone_rules.py`; E |
| 34 | Courier: filter by status | PASS | T; E |
| 35 | Courier: cannot change unassigned orders | PASS | T; L |
| 36 | Auth: customer registration | PASS | T `test_auth.py`; E |
| 37 | Auth: login for all three roles | PASS | T `test_seed.py`; E |
| 38 | Auth: bcrypt hashing | PASS | T `test_security.py` |
| 39 | Auth: JWT generation and validation | PASS | T `test_security.py` |
| 40 | Auth: current-user endpoint | PASS | T; L |
| 41 | Auth: role navigation + protected routes (frontend) | PASS | E (role guards) |
| 42 | Auth: backend authorization on every protected endpoint | PASS | T `test_security.py`, `test_*`; L 29/29 |
| 43 | Auth: customer/owner/courier data isolation | PASS | T privacy sweep; L |
| 44 | Auth: token persistence in localStorage | PASS | C `AuthContext.jsx`; E |
| 45 | Auth: invalid/expired tokens | PASS | T; E (forged token) |
| 46 | Auth: no role escalation at registration | PASS | T `test_auth.py`; L |
| 47 | Lifecycle: PLACED→…→DELIVERED incl. READY, ASSIGNED | PASS | T `test_orders.py`, matrix (484 cases) |
| 48 | Lifecycle: CANCELLED and REFUNDED states | PASS | T `test_capstone_rules.py` |
| 49 | Lifecycle: customers cancel only PLACED | PASS (see K) | T matrix |
| 50 | Lifecycle: owners manage only own orders | PASS | T; L |
| 51 | Lifecycle: invalid/skipped transitions rejected | PASS | T matrix; L |
| 52 | Lifecycle: delivered orders cannot be cancelled | PASS | T matrix, `test_phase3.py` |
| 53 | Lifecycle: transactions + concurrency safety | PASS | T `test_lifecycle.py` (stale writers), `test_refunds.py` |
| 54 | Payments: dummy gateway, `mock_paid` | PASS | T `test_checkout.py`; L |
| 55 | Payments: ledger records | PASS | T; L (charge + refund) |
| 56 | Refunds: only after delivery, reason required | PASS | T `test_refunds.py` |
| 57 | Refunds: one request per order | PASS | T; E; L |
| 58 | Refunds: correct owner approves/rejects | PASS | T `test_refunds.py` |
| 59 | Refunds: request, payment, ledger, order consistent | PASS | T `test_capstone_rules.py`; L |
| 60 | Role-specific dashboards | PASS | E (customer, owner, courier) |
| 61 | Search, filtering, pagination | PASS | T `test_restaurants.py`, `test_frontend_support.py` |
| 62 | AI: key only on backend | PASS | C; bundle scan; T (key never in responses/logs) |
| 63 | AI: only the authenticated customer's real orders | PASS | T `test_ai.py`, `test_phase_verification.py` |
| 64 | AI: missing config, timeouts, rate limits handled | PASS | T `test_ai.py` (503/504/429/502) |
| 65 | AI: no fabricated history (no orders → factual reply) | PASS | T `test_ai.py` |
| 66 | AI: live response from OpenAI | **BLOCKED** | no `OPENAI_API_KEY` in this environment |
| 67 | Middleware: request method/path logging + response time | PASS | T `test_capstone_rules.py`; L backend logs |
| 68 | API quality: status codes, Pydantic validation, consistent errors | PASS | T |
| 69 | Reminders: scheduled job independent of API | PASS | C `app/worker.py`; L scheduler container |
| 70 | Reminders: PLACED/ACCEPTED idle > 15 min | PASS | T `test_owner_reminders.py` |
| 71 | Reminders: no duplicates per status period | PASS | T; L (rerun + restart) |
| 72 | Reminders: shown on owner dashboard | PASS | C `OwnerPages.jsx`; L |
| 73 | Reminders: no duplicate jobs across workers | PASS | T (advisory lock path on PostgreSQL); C |
| 74 | React: loading/error/empty states, responsive | PASS | E `responsive.spec.js` (5 widths) |
| 75 | Models: relationships, FKs, constraints, indexes | PASS | T `test_constraints.py` |
| 76 | Migrations 0001–0006 | PASS | T `test_migrations.py` (PostgreSQL); L `alembic current` |
| 77 | REST endpoints + Swagger `/docs` | PASS | L `/docs` 200, 45 OpenAPI paths |
| 78 | Docker: build, health checks, restart | PASS | L |
| 79 | Environment configuration (`.env.example`) | PASS | C `backend/.env.example`, `frontend/.env.example` |
| 80 | Git readiness: secrets excluded | PASS | `git check-ignore`; history scan |
| 81 | Deployment documentation | PASS | C `README.md` §19 |

## C. Features completed
All features in the brief for customers, owners and delivery partners (rows 8–35), the lifecycle, payments,
refunds, AI insights, reminders, middleware, Docker deployment and documentation.

## D. Missing features fixed in this final pass
- **Demo readiness:** `app/seed.py` now creates idempotent demo orders in every lifecycle state through the real
  services (stale placed/accepted for reminders, delivered for review/refund, pending refund, refunded,
  cancelled). Test: `tests/test_seed.py`.
- **Cleanup:** removed dead code (`RefundRequestCreate`, `ReminderLogCreate`, `ReminderLogRead`, unused `OPEN`
  constant, 12 unused imports, 2 unused frontend API functions), the obsolete duplicate
  `backend/docker-compose.yml`, the parked old migration and two applied update notes; replaced the misleading
  root `.env.example`.
- **README** rewritten end to end against the actual files, ports, variables and commands.

## E. Security issues discovered and resolved
| Finding | Severity | Resolution |
|---|---|---|
| axios 1.7.9 and React Router (`@remix-run/router`) advisories in the shipped bundle | high | axios → 1.21.x, react-router-dom → 7.x; `npm audit`: **0 vulnerabilities** |
| Playwright < 1.55.1, esbuild ≤ 0.24.2 (dev tooling) | high / moderate | @playwright/test 1.65, Vite 6 |
| `CORS_ORIGINS="*"` would be accepted with credentials enabled | medium | config now rejects `*` (test `test_cors_wildcard_is_rejected`) |
| Root `.env.example` listed variables nothing reads | low | replaced with pointers to the real example files |
| Secrets in tracked files or Git history | none found | history scan: only placeholders and fake test URLs; no `.env` ever committed |
| Python dependencies | none | `pip-audit -r requirements.txt`: no known vulnerabilities |
Verified unchanged: no secrets in frontend source or build; JWT secret required (≥32 chars) in production;
staff registration needs a key; server-side authorization everywhere; error bodies without stack traces; access
log without query strings/bodies/tokens.

## F. Verification commands and results (executed in this pass)
| Command | Result |
|---|---|
| `git log --all -p \| grep <secret patterns>`; working-tree scan | placeholders only |
| `npm audit` / `npm audit --omit=dev` | 0 vulnerabilities |
| `python -m pip_audit -r requirements.txt` | no known vulnerabilities |
| `ruff check app tests --select F401,F811,F841` | clean (F821 hits are SQLAlchemy string annotations, verified at runtime) |
| `cd backend && pytest -q` | **770 passed, 5 skipped, 0 failed, 0 errors** |
| `TEST_DATABASE_URL=…campusbite_test pytest -q` | **775 passed, 0 skipped, 0 failed, 0 errors** |
| `cd frontend && npm run build` | ✓ (Vite 6.4.6) |
| `docker compose config -q` | valid |
| `docker compose up -d --build` | db, backend, scheduler, frontend **healthy** |
| `docker compose exec backend alembic current` | `0006 (head)` |
| `docker compose exec backend python -m app.seed` (twice) | 11 demo orders, then 0 |
| scheduler tick | both stale demo orders → exactly 1 reminder each |
| live smoke (all roles) / live Workflows 6–8 | **30/30** / **29/29** |
| `E2E_BASE_URL=http://localhost:3000 npx playwright test` | **12 passed** |
| same with mock OpenAI (`docker-compose.e2e.yml`, `E2E_MOCK_OPENAI=1`), workflows | **7 passed** |
| `git status`, `git diff --stat` | 44 modified/deleted + 8 new files, all intended; `.env`, `.env.bak`, `dist`, `node_modules`, test output ignored |

## G. Backend test summary
SQLite 770 passed / 5 skipped (PostgreSQL-only migration tests); PostgreSQL 775 passed / 0 skipped. Includes
the exhaustive 484-case transition matrix, AI (mocked SDK), reminders, refunds, security and seed tests.

## H. Frontend build / test summary
`npm run build` succeeds. No ESLint or unit-test runner is configured (NOT CONFIGURED). UI verified by 12
Playwright tests (role workflows, guards, invalid tokens, layouts at 375/430/768/1024/1440 px).

## I. Docker startup
All four services healthy (backend `/health`, scheduler heartbeat, frontend HTTP, db `pg_isready`); migrations at
head; API on `:8000`, frontend on `:3000`; scheduler restart verified without duplicate reminders.

## J. API integration tests
Live smoke 30/30 (checkout, idempotency, tampering, lifecycle, assignment, review, refund, ledger, stats, RBAC);
live Workflows 6–8 29/29 (reminders, cross-role/customer/restaurant access, negative cases, AI unavailable → 503).

## K. Remaining issues and limitations
- **BLOCKED:** a live OpenAI answer needs `OPENAI_API_KEY` (all AI paths verified with mocks).
- Customers may cancel **unpaid `pending_payment`** orders (pay-later flow, nothing charged) in addition to
  `placed`; paid orders can be cancelled only while `placed`. Documented design choice.
- Reminder notifications use a mock adapter (records and dashboard are real).
- AI rate limit is per API process; no frontend linter/unit tests configured.
- The development database contains test orders created by the live checks (`[demo]` orders are the curated set).
- Changes are **not committed** (by instruction).

## L. Verdict
**Ready for capstone submission.** All mandatory requirements are implemented and verified except the live
OpenAI response, which is blocked only by the missing API key.
