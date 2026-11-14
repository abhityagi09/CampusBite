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
| GET | /orders | signed in | `status, limit, offset` → list (owner: own restaurants, courier: assigned) | `orderApi.list` |
| GET | /orders/{id} | customer / owner / assigned courier | → OrderDetail (`items, events, payment, status_timestamps, delivery_partner_id`) | `orderApi.get` |
| GET | /orders/{id}/payment · /tracking | same | Payment · status events | – |
| POST | /orders/{id}/cancel | customer | allowed in pending_payment, placed, accepted | `orderApi.cancel` |
| PATCH | /orders/{id}/status | owner / assigned courier | `{status}` (see lifecycle) | `orderApi.setStatus` |
| POST | /orders/{id}/assign-delivery | owner | `{delivery_partner_id}` (accepted … ready_for_pickup) | `orderApi.assign` |
| GET | /users/delivery-partners | owner | → `[{id, name}]` active couriers | `userApi.deliveryPartners` |
| GET | /orders/available | courier | ready & unassigned → list | `orderApi.available` |
| POST | /orders/{id}/claim | courier | self-assign a ready order | `orderApi.claim` |
| GET | /deliveries/me | courier | `status, limit, offset` → Page[Order] | `orderApi.myDeliveries` |
| POST | /payments/orders/{id}/pay | customer | `{method}` → Payment (pay a pending order) | `orderApi.pay` |
| GET | /payments/orders/{id} · /ledger | customer / owner | Payment · ledger entries | `orderApi.ledger` |

Lifecycle: `pending_payment → placed → accepted → preparing → ready_for_pickup → out_for_delivery → delivered`;
`cancelled` (customer, before preparing), `rejected` (owner, before preparing). Owner moves placed…ready; the assigned courier moves ready → out_for_delivery → delivered.

## Reviews, refunds, statistics
| Method | Path | Who | Body / params | Frontend |
|---|---|---|---|---|
| POST | /reviews | customer | `{order_id, rating 1–5, comment?}` (delivered orders, one per order) | `reviewApi.create` |
| POST | /orders/{id}/refund-requests | customer | `{reason}` (delivered + paid) | `refundApi.request` |
| GET | /refund-requests/me | customer | Page[RefundRequest] | `refundApi.mine` |
| GET | /refund-requests/incoming | owner | `status, limit, offset` | `refundApi.incoming` |
| POST | /refund-requests/{id}/decision | owner | `{decision: "approve" \| "reject"}` | `refundApi.decide` |
| GET | /statistics/customer | customer | own totals, refunds, top restaurants | `statsApi.customer` |
| GET | /statistics/owner | owner | totals, per-restaurant performance, top items | `statsApi.owner` |
| GET | /statistics/me | any | role-specific (used for couriers) | `statsApi.me` |

Added for the frontend in this phase: `GET /users/delivery-partners`, and the `created_from` / `created_to` filters on `GET /orders/me`.
