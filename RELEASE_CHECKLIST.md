# CampusBite release checklist (2026-11-15)

| Area | Status | Check |
|---|---|---|
| Source code | ✅ | Backend lint clean (unused/undefined names); dead code and duplicate compose file removed; diff reviewed |
| Backend | ✅ | `pytest -q`: 770 passed / 5 skipped (SQLite); 775 passed (PostgreSQL) |
| Frontend | ✅ | `npm run build` ✓; Playwright 12/12; `npm audit` 0 vulnerabilities · ⚪ no linter/unit tests configured |
| Database | ✅ | Migrations 0001–0006 at head; constraints and migration round-trip tested on PostgreSQL |
| Docker | ✅ | `docker compose config` valid; db, backend, scheduler, frontend healthy |
| Authentication / RBAC | ✅ | bcrypt, JWT, staff key, role + ownership checks; live cross-role checks 29/29 |
| AI integration | ⚠️ | Backend SDK integration, scoping and error handling tested with mocks; **live answer BLOCKED (no API key)** |
| Documentation | ✅ | README (24 sections), API_ENDPOINT_MAP, CAPSTONE_AUDIT, REQUIREMENTS_CHECKLIST, E2E_TEST_REPORT |
| Demo | ✅ | `python -m app.seed`: fictional accounts (password `Campus123`), 11 demo orders in every state, reminders |
| Security | ✅ | No secrets tracked or in history; `.env` ignored; CORS explicit origins; pip-audit / npm audit clean |

Before submitting: `git add -A && git commit` (includes new migration `0006`, tests and docs); optionally add
`OPENAI_API_KEY` to `backend/.env` to demonstrate live AI answers.
