CampusBite phase 2: UUID models, ledger / refunds / reminders (data-preserving)

READ THIS FIRST. Migration 0002 converts integer ids to UUIDs. It has NOT been run on a
real database by its author (no PostgreSQL was available when it was written). Rehearse it on
a copy of your data first.

1. Back up:   docker compose exec db pg_dump -U <POSTGRES_USER> -Fc <POSTGRES_DB> > backup.dump
   (PowerShell: use  cmd /c "docker compose exec -T db pg_dump ... > backup.dump"  so the file
   is not re-encoded.)
2. Extract this zip INTO your project root, choosing "replace". It does not touch
   backend\.env, backend\.venv, frontend\ or database\.
3. Rehearse on a scratch copy (does not touch your real database):
       docker compose exec db createdb -U <user> campusbite_rehearsal
       docker compose exec -T db pg_restore -U <user> -d campusbite_rehearsal --no-owner < backup.dump
       (point DATABASE_URL / POSTGRES_DB at campusbite_rehearsal, then)
       alembic upgrade head
   If the preflight finds bad rows it stops, changes nothing and lists them.
4. Real run:   cd backend ; alembic upgrade head      (one transaction: all or nothing)
5. Your old tables are KEPT as legacy_* (data untouched). legacy_id_map maps old integer id
   -> new UUID. They are removed only by a later migration, after you approve it.
6. NEVER run "docker compose down -v" if you want to keep your data (-v deletes the volume).

API changes that affect a frontend: ids are UUID strings (integers now give 422);
user field full_name -> name (requests still accept full_name; responses return name only);
order item line_total -> subtotal; restaurants gain is_active; new endpoint
GET /payments/orders/{id}/ledger; JWT "sub" is a UUID, so every existing login token stops
working and users must log in again.


--- Auth update (JWT hardening, roles) ---
* New setting STAFF_REGISTRATION_KEY in backend\.env (see .env.example). Without it nobody can
  register as owner / delivery_partner. Public sign-up creates customers only.
* Old login tokens are rejected (new tokens carry type/iss/iat claims): everyone logs in again.
* Passwords now need at least one letter and one digit.
* How to authorize in Swagger UI: backend\docs\AUTH.md
