CampusBite PostgreSQL update (overlay)

1. Back up / commit your project first.
2. Extract this zip INTO your project root (the folder that has docker-compose.yml
   and backend/), choosing "replace" when asked. It never touches backend\.env,
   backend\.venv, frontend\ or database\.
3. Delete your old migration:  backend\alembic\versions\387748ecb3be_initial_schema.py
4. Edit backend\.env (see backend\.env.example): remove any old DATABASE_URL line, then set
   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, SECRET_KEY.
5. Append these lines to your root .gitignore:
       .env
       backend/.env
6. docker-compose.yml in this zip REPLACES yours. If yours had extra services, merge them back.
