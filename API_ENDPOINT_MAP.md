# CampusBite API endpoint map

Base URL: `VITE_API_BASE_URL` (default `http://localhost:8000/api/v1`). Auth: `Authorization: Bearer <access_token>`.
Errors: `{"detail": "..."}`; validation errors (422): `{"detail": "Validation error", "errors": [{loc, msg, ...}]}`.
Pages: `{items, total, limit, offset}` with `limit` 1–100, `offset` ≥ 0. Ids are UUID strings, money is a decimal string.
Roles: `customer`, `owner`, `delivery_partner`.

Frontend function = `frontend/src/api/endpoints.js`.

## Auth
| Method | Path | Who | Body / params → response | Frontend |
|---|---|---|---|---|
| POST | /auth/register | public (owner / courier need `X-Registration-Key`) | `{email, password, name, phone?, role}` → UserRead | `authApi.register` |
| POST | /auth/login/json | public | `{email, password}` → `{access_token, token_type, user}` | `authApi.login` |
| POST | /auth/login | public | OAuth2 form (Swagger) | – |
| GET / PATCH | /auth/me | signed in | → UserRead `{id, email, name, phone, role, is_active, ...}` | `authApi.me` |
| POST | /auth/change-password | signed in | `{current_password, new_password}` → 204 | – |

## Browse (public)
| Method | Path | Params → response | Frontend |
|---|---|---|---|
| GET | /restaurants | `q, cuisine, location, open_only, limit, offset` → Page[Restaurant] | `restaurantApi.list` |
| GET | /restaurants/{id} | → RestaurantDetail (available `menu_items`, `average_rating`, `review_count`) | `restaurantApi.get` |
| GET | /restaurants/{id}/menu | `q, category, min_price, max_price, limit, offset` → Page[MenuItem] (available only) | `restaurantApi.menu` |
| GET | /restaurants/{id}/reviews | `limit, offset` → Page[{id, restaurant_id, rating, comment, created_at}] | `restaurantApi.reviews` |
| GET | /menu-items | `q, category, min_price, max_price, restaurant_id, open_only, limit, offset` → Page[MenuItem + restaurant_name, restaurant_is_open] | `restaurantApi.searchItems` |

## Owner: restaurants & menus
| Method | Path | Body / params | Frontend |
|---|---|---|---|
| GET | /restaurants/mine | `limit, offset` → Page[RestaurantDetail incl. disabled items] | `restaurantApi.mine` |
| GET | /restaurants/mine/menu-items | `restaurant_id, is_available, q, category, min/max_price` | – |
| POST | /restaurants | `{name, description?, cuisine?, location?, is_open?}` → 201 | `restaurantApi.create` |
| PATCH | /restaurants/{id} | any of the above + `is_active` (null clears optional fields) | `restaurantApi.update` |
| POST | /restaurants/{id}/menu | `{name, price>0, category?, description?, is_available?}` → 201 | `restaurantApi.addItem` |
| PATCH | /restaurants/{id}/menu/{item} | partial | `restaurantApi.updateItem` |
| POST | /restaurants/{id}/menu/{item}/enable · /disable | – | `restaurantApi.setItemAvailable` |
| DELETE | /restaurants/{id}/menu/{item} | 204 (soft-disables if ever ordered) | `restaurantApi.deleteItem` |

## Orders, checkout, payments
| Method | Path | Who | Body / params → response | Frontend |
|---|---|---|---|---|
| POST | /orders | customer | `{restaurant_id, items:[{menu_item_id, quantity 1–50}], delivery_address, notes?, payment_method?, expected_total?}` + header `Idempotency-Key` (required with `payment_method`) → 201 OrderDetail (200 + `Idempotent-Replayed` on replay; 402 declined; 409 total changed) | `orderApi.checkout` |
| GET | /orders/me | customer | `status, created_from, created_to (YYYY-MM-DD, UTC), limit, offset` → Page[Order] | `orderApi.mine` |
| GET | /orders | signed in | `status, created_from, created_to, limit, offset` → list (owner: own restaurants, courier: assigned) | `orderApi.list` |
| GET | /orders/{id} | customer / owner / assigned courier | → OrderDetail (`items, events, payment, status_timestamps, delivery_partner_id`) | `orderApi.get` |
| GET | /orders/{id}/payment · /tracking | same | Payment · status events | – |
| POST | /orders/{id}/cancel | customer | allowed in pending_payment, placed | `orderApi.cancel` |
| PATCH | /orders/{id}/status | owner / assigned courier | `{status}` (see lifecycle) | `orderApi.setStatus` |
| POST | /orders/{id}/assign-delivery | owner | `{delivery_partner_id}`: `ready` → `assigned` (re-assign allowed while `assigned`) | `orderApi.assign` |
| GET | /users/delivery-partners | owner | → `[{id, name}]` active couriers | `userApi.deliveryPartners` |
| GET | /deliveries/me | courier | `status, limit, offset` → Page[Order] | `orderApi.myDeliveries` |
| POST | /payments/orders/{id}/pay | customer | `{method}` → Payment (pay a pending order) | `orderApi.pay` |
| GET | /payments/orders/{id} · /ledger | customer / owner | Payment · ledger entries | – (not used by the UI) |

Lifecycle: `pending_payment → placed → accepted → preparing → ready → assigned → out_for_delivery → delivered → (refunded)`;
`cancelled` (customer, before acceptance), `rejected` (owner, before preparing). Owner moves placed…ready and assigns (→ assigned); the assigned courier moves assigned → out_for_delivery → delivered; an approved refund moves delivered → refunded.

## Reviews, refunds, statistics
| Method | Path | Who | Body / params | Frontend |
|---|---|---|---|---|
| POST | /reviews | customer | `{order_id, rating 1–5, comment?}` (delivered orders, one per order) | `reviewApi.create` |
| POST | /orders/{id}/refund-requests | customer | `{reason}` (delivered + mock_paid; one request per order) | `refundApi.request` |
| GET | /refund-requests/me | customer | Page[RefundRequest] | `refundApi.mine` |
| GET | /refund-requests/incoming | owner | `status, limit, offset` | `refundApi.incoming` |
| POST | /refund-requests/{id}/decision | owner | `{decision: "approve" \| "reject"}` | `refundApi.decide` |
| GET | /statistics/customer | customer | own totals, refunds, top restaurants | – (not used by the UI) |
| GET | /statistics/owner | owner | totals, per-restaurant performance, top items | `statsApi.owner` |
| GET | /statistics/me | any | role-specific (used for couriers) | `statsApi.me` |

Added for the frontend in this phase: `GET /users/delivery-partners`, and the `created_from` / `created_to` filters on `GET /orders/me`.

## Phase 3 additions
| Method | Path | Who | Notes | Frontend |
|---|---|---|---|---|
| POST | /ai/insights | customer | optional `{question: 3–500 chars}` → `{answer, source: openai\|no_orders, model, orders_considered, generated_at}`. OpenAI SDK, server-side, ONLY the caller's newest 50 orders; no orders → factual reply without calling OpenAI. 429 (rate limit, `Retry-After`), 502 (provider error), 503 (no key / quota), 504 (timeout). | `aiApi.ask` |
| GET | /ai/summary | customer | AI summary of previous orders; same response and errors; shares the per-customer rate limit | `aiApi.summary` |
| GET | /owner/reminders | owner | `unread_only, limit, offset` → Page of idle-order reminders (placed/accepted > 15 min in the same status) for the owner's restaurants, newest first: `status_snapshot, status_updated_at_snapshot, created_at, read_at, is_read, current_order_status, still_waiting` | `reminderApi.list` |
| GET | /owner/reminders/unread-count | owner | → `{unread}` | `reminderApi.unreadCount` |
| PATCH | /owner/reminders/{id}/read | owner | idempotent; another owner's reminder → 404 | `reminderApi.markRead` |

`GET /orders/{id}` now also returns `review` (or null) and `refund_requests`. Payment status after a successful dummy charge is `mock_paid`.
