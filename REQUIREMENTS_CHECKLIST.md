# CampusBite – capstone requirement checklist

Status is based on code **and** executed tests (see FINAL_QA_REPORT.md for commands and counts).
Paths: `B/` = `backend/app/`, `T/` = `backend/tests/`, `F/` = `frontend/src/`, `E/` = `frontend/e2e/`.

Legend: ✅ implemented and verified · ⚠️ implemented, verification limited by an external dependency

## Technology
| Requirement | Status | Evidence |
|---|---|---|
| React (ES6+, hooks, React Router, Axios) | ✅ | `F/App.jsx`, `F/api/client.js`, `F/hooks/useAsync.js` |
| FastAPI, Pydantic, SQLAlchemy, JWT | ✅ | `B/main.py`, `B/schemas/`, `B/models/`, `B/core/security.py` |
| PostgreSQL + Alembic migrations 0001–0006 | ✅ | `backend/alembic/versions/`, `T/test_migrations.py` (PostgreSQL) |
| Docker Compose (db, backend, scheduler, frontend) | ✅ | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` |
| OpenAI API (backend only) | ⚠️ | `B/services/ai_service.py`; mocked SDK tests `T/test_ai.py` – no API key available here |

## 1. Authentication and RBAC
| Requirement | Status | Evidence |
|---|---|---|
| Customer registration/login; owner and courier login | ✅ | `B/routers/auth.py`; `T/test_auth.py`, `E/workflows.spec.js` |
| bcrypt hashing | ✅ | `B/core/security.py`; `T/test_security.py` |
| JWT issue/validate (type, iss, exp; role from DB) | ✅ | `B/core/security.py`, `B/dependencies/auth.py`; `T/test_security.py` |
| Current user endpoint `GET /auth/me` | ✅ | `B/routers/auth.py` |
| No role escalation at sign-up (staff key for owner/courier) | ✅ | `B/services/auth_service.py`; `T/test_auth.py` |
| Backend role checks on every protected route + service-level re-checks | ✅ | `B/dependencies/auth.py`, `B/core/permissions.py`; `T/test_security.py` |
| Data isolation (customers, owners, couriers) | ✅ | `T/test_stats_and_privacy.py::test_customer_cannot_read_another_customers_records`, `T/test_owner_reminders.py`, `T/test_ai.py` |
| Token in localStorage; invalid/expired token → logout + login | ✅ | `F/contexts/AuthContext.jsx`, `F/api/client.js`; `E/workflows.spec.js` (forged token) |
| Role-based navigation and protected routes | ✅ | `F/routes/guards.jsx`, `F/components/Layout.jsx`; `E/workflows.spec.js` (role guards) |

## 2. Customer
| Requirement | Status | Evidence |
|---|---|---|
| Restaurant listing, menus with details/prices | ✅ | `B/routers/restaurants.py`; `F/pages/Restaurants.jsx`; `T/test_restaurants.py` |
| Dish search by name, price filter | ✅ | `GET /menu-items`; `F/pages/Restaurants.jsx` (DishSearchPage); `E/workflows.spec.js` |
| Cart add/update/remove, one restaurant | ✅ | `F/contexts/CartContext.jsx`, `F/pages/Cart.jsx` |
| Checkout with dummy payment (`mock_paid`), idempotent | ✅ | `B/services/order_service.py::checkout`; `T/test_checkout.py` |
| Order history (status + date filters, payment & refund status) | ✅ | `GET /orders/me`; `F/pages/Orders.jsx`; `T/test_frontend_support.py` |
| Tracking (timeline, refresh) and cancellation while placed | ✅ | `F/pages/Orders.jsx`; `T/test_lifecycle.py` |
| Reviews/ratings after delivery (once) | ✅ | `B/services/review_service.py`; `T/test_stats_and_privacy.py`, `E/workflows.spec.js` |
| Refund request after delivery (reason, once per order) | ✅ | `B/services/refund_service.py`; `T/test_refunds.py` |
| AI insights from own order history | ⚠️ | `POST /ai/insights`, `GET /ai/summary`; `F/pages/AiInsights.jsx`; `T/test_ai.py`, `T/test_phase_verification.py` |

## 3. Restaurant owner
| Requirement | Status | Evidence |
|---|---|---|
| Dashboard + statistics (orders, pending, completed, revenue, per restaurant) | ✅ | `GET /statistics/owner`; `F/pages/owner/OwnerPages.jsx`; `T/test_stats_and_privacy.py` |
| Menu CRUD, availability | ✅ | `B/routers/restaurants.py`; `T/test_restaurants.py` |
| Incoming orders filtered by status and date, paginated | ✅ | `GET /orders?status=&created_from=&created_to=`; `T/test_phase3.py` |
| Accept → preparing → ready | ✅ | `B/services/order_lifecycle.py`; `T/test_lifecycle.py` |
| Assign courier only when READY | ✅ | `B/services/order_service.py::assign_delivery`; `T/test_capstone_rules.py` |
| Approve/reject refunds | ✅ | `B/services/refund_service.py`; `T/test_refunds.py`, `T/test_capstone_rules.py` |
| Stale-order reminders on dashboard | ✅ | `B/routers/owner_reminders.py`; `T/test_owner_reminders.py` |
| No access to other restaurants' data | ✅ | `T/test_restaurants.py`, `T/test_security.py`, `T/test_owner_reminders.py` |

## 4. Delivery partner
| Requirement | Status | Evidence |
|---|---|---|
| Only assigned deliveries; delivery details | ✅ | `GET /deliveries/me`; `B/services/order_service.py::can_view`; `F/pages/delivery/DeliveryPage.jsx` |
| ASSIGNED → OUT_FOR_DELIVERY → DELIVERED | ✅ | `B/services/order_lifecycle.py`; `T/test_capstone_rules.py` |
| History and status filter | ✅ | `GET /deliveries/me?status=`; `E/workflows.spec.js` |
| No changes to unassigned orders (no self-claim) | ✅ | `T/test_orders.py::test_couriers_cannot_self_assign`, `T/test_lifecycle.py` |

## 5. Order lifecycle
| Requirement | Status | Evidence |
|---|---|---|
| PLACED → ACCEPTED → PREPARING → READY → ASSIGNED → OUT_FOR_DELIVERY → DELIVERED | ✅ | `B/services/order_lifecycle.py::TRANSITIONS`, migration `0006`; `T/test_orders.py`, `T/test_capstone_rules.py` |
| CANCELLED and REFUNDED states | ✅ | REFUNDED set by approved refund (`B/services/refund_service.py`); `T/test_capstone_rules.py` |
| Customer cancels only PLACED (and unpaid pending) | ✅ | `T/test_lifecycle.py`, `T/test_phase3.py` |
| Skips / reversals / repeats rejected | ✅ | `T/test_lifecycle.py` |
| Transactions; concurrent updates (row lock + compare-and-set) | ✅ | `B/services/order_lifecycle.py::compare_and_set`; `T/test_lifecycle.py` (stale writers) |

## 6. Payments and refunds
| Requirement | Status | Evidence |
|---|---|---|
| Dummy gateway, `mock_paid`, configurable outcomes | ✅ | `B/services/payment_gateway.py`; `T/test_checkout.py` |
| Payment ledger (charge, refund) | ✅ | `B/models/ledger.py`; `T/test_refunds.py` |
| Refund only after delivery, reason required, one per order | ✅ | `T/test_refunds.py` |
| Approval: request processed + payment refunded + ledger reversal + order refunded, atomically | ✅ | `B/services/refund_service.py::decide_refund`; `T/test_refunds.py` (rollback, concurrency) |
| Rejection → request rejected, order stays delivered | ✅ | `T/test_capstone_rules.py` |

## 7. AI order insights
| Requirement | Status | Evidence |
|---|---|---|
| Backend-only OpenAI SDK, key in env | ✅ | `B/services/ai_service.py`, `B/core/config.py`; bundle scan |
| Own orders only; exact figures computed in Python | ✅ | `T/test_ai.py`, `T/test_phase_verification.py` |
| Missing key / timeout / rate limit / errors handled | ✅ | `T/test_ai.py` (503/504/429/502) |
| Real model answer observed | ⚠️ | **needs `OPENAI_API_KEY`** |

## 8. Background reminders
| Requirement | Status | Evidence |
|---|---|---|
| Scheduled job independent of the API (APScheduler worker) | ✅ | `B/worker.py`, `scheduler` service; live container check |
| PLACED/ACCEPTED idle > 15 min (`status_updated_at`) | ✅ | `B/services/reminder_service.py`; `T/test_owner_reminders.py` |
| No duplicates per status period (UNIQUE event_key), no duplicate jobs (advisory lock) | ✅ | `B/models/reminder.py`; `T/test_owner_reminders.py`, `T/test_phase_verification.py` |
| Shown on owner dashboard with read state | ✅ | `F/pages/owner/OwnerPages.jsx` |

## 9. Database
| Table | Status | Evidence |
|---|---|---|
| users, restaurants, menu_items, orders, order_items, order_status_events, payments, payment_ledger, reviews, refund_requests, reminder_logs | ✅ | `B/models/`; FKs, CHECKs, unique and partial indexes; `T/test_constraints.py`, `T/test_migrations.py` |

## 10. Frontend
| Requirement | Status | Evidence |
|---|---|---|
| All pages/dashboards on real endpoints, no mock data | ✅ | `F/api/endpoints.js` (every call matches OpenAPI) |
| Loading / error / success / empty states, pagination | ✅ | `F/components/ui.jsx` |
| Responsive 375–1440 px | ✅ | `E/responsive.spec.js` |

## 11. Middleware and API quality
| Requirement | Status | Evidence |
|---|---|---|
| Request method/path logging + response time (`X-Process-Time-Ms`) | ✅ | `B/main.py::log_and_time_requests`; `T/test_capstone_rules.py` |
| Consistent errors (`{"detail"}`, 422 with `errors`) | ✅ | `B/main.py::register_exception_handlers` |
| Pydantic validation, `extra="forbid"` on write bodies | ✅ | `B/schemas/` |
| Pagination (`{items,total,limit,offset}`) | ✅ | `B/schemas/common.py` |

## External blockers
- **OpenAI**: no `OPENAI_API_KEY` in this environment. Every AI path is tested with a mocked SDK; a live answer
  requires setting the key in `backend/.env` and `docker compose up -d backend`.
- **Notifications**: reminders are persisted and shown in the dashboard; no e-mail/push provider is configured
  (`B/services/notifications.py` is a mock adapter by design).
