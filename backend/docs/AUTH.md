# CampusBite authentication and authorization

## How it works

| Piece | Where |
|---|---|
| Password hashing (bcrypt, `BCRYPT_ROUNDS`) | `app/core/security.py` |
| Token creation / verification | `app/core/security.py` (`create_access_token`, `decode_access_token`) |
| `OAuth2PasswordBearer`, current user, role dependencies | `app/dependencies/auth.py` |
| Registration policy, login | `app/services/auth_service.py` |
| Service-layer role guard | `app/core/permissions.py` (`ensure_role`) |
| Ownership / order access checks | `app/services/restaurant_service.py`, `order_service.py` |

**Token.** HS256 JWT containing `sub` (user UUID), `type` = `access`, `iss`, `iat`, `exp`, `jti`
(plus an informational `role`). Every request verifies the signature, the algorithm (only the
configured one; `alg: none` is rejected), `exp`, `iss`, `sub` and `type`. The user is then loaded
from the database; **the role is read from the database, never from the token**, so disabling or
changing a user takes effect immediately.

**Status codes.** `401` = missing / malformed / expired / invalid token, wrong credentials,
disabled account (`WWW-Authenticate: Bearer` is sent). `403` = authenticated but the role is not
allowed, or you do not own the restaurant. Orders that are not yours return `404` (so ids cannot
be probed).

**Defence in depth.** Routes use `CustomerUser` / `OwnerUser` / `DeliveryUser` (built with
`require_roles(...)`). The service functions *also* call `ensure_role(...)` and check ownership
(`_get_owned_restaurant`, `can_view`, `order.customer_id`, ...), so a service called from a new
route, job or test cannot skip authorization.

## Settings (`backend/.env`)

| Variable | Meaning |
|---|---|
| `SECRET_KEY` | Signing key. Required in production, at least 32 characters. |
| `JWT_ALGORITHM` | `HS256` (default), `HS384` or `HS512` only. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime, 1 to 1440 (default 60). |
| `JWT_ISSUER` | Issuer claim (default `campusbite-api`). |
| `BCRYPT_ROUNDS` | Cost factor, 4 to 18 (default 12). |
| `STAFF_REGISTRATION_KEY` | Secret that allows creating `owner` / `delivery_partner` accounts. **Empty = those roles cannot be registered at all.** |

## Registration and privileged roles

`POST /api/v1/auth/register` is public but only ever creates **customers**. To create an `owner` or
`delivery_partner`, send the staff key:

```
X-Registration-Key: <STAFF_REGISTRATION_KEY>
```

Without it (or with a wrong key, or if no key is configured) the API returns `403`. Hand the key
only to the people who run onboarding; do not ship it in the frontend. Unknown fields in the body
are rejected with `422`. Passwords: 8 to 72 bytes with at least one letter and one digit.

## Authorizing in Swagger UI

1. Start the API and open `http://localhost:8000/docs`.
2. Create an account with **POST /api/v1/auth/register** > *Try it out*. Use `"role": "customer"`
   for a customer. For `owner` or `delivery_partner` fill in the `x-registration-key` header field
   with your `STAFF_REGISTRATION_KEY`.
3. Click **Authorize** (top right, padlock).
4. In the dialog enter your **e-mail** in *username* and your **password**. Leave `client_id` and
   `client_secret` empty. Click **Authorize**, then **Close**.
5. Padlocks are now closed and every request carries `Authorization: Bearer <token>`. Try
   **GET /api/v1/auth/me**.
6. To switch user, click **Authorize** > **Logout**, then repeat step 4 with the other account.

Alternative without the dialog: call **POST /api/v1/auth/login/json**
(`{"email": ..., "password": ...}`), copy `access_token`, and paste it into the Authorize dialog's
*Bearer* box (or send the header yourself from the frontend).

If Swagger suddenly returns `401 Token has expired`, log in again.

## curl / PowerShell examples

```
curl -X POST http://localhost:8000/api/v1/auth/login -d "username=me@example.com&password=password123"
curl http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer <access_token>"
```

```powershell
$r = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/login/json `
  -ContentType 'application/json' -Body '{"email":"me@example.com","password":"password123"}'
Invoke-RestMethod http://localhost:8000/api/v1/auth/me -Headers @{ Authorization = "Bearer $($r.access_token)" }
```

## Known limits

- Tokens are stateless: a token stays valid until it expires, except that disabled users are
  rejected at once. Changing a password does not revoke older tokens; keep the lifetime short.
- There is no refresh token, logout endpoint or login rate limiting. Put a rate limiter (reverse
  proxy or e.g. slowapi) in front of `/auth/login` and `/auth/register` before going public.
- Run behind HTTPS in production; bearer tokens are credentials.
