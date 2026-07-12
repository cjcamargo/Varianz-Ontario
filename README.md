# Varianz MVP

Operational Intelligence for Controlled Environment Agriculture. The repository is local-first: the Wageningen demo, analytics contracts and replay engine run without cloud credentials. Supabase and OpenAI are adapters activated later through environment variables.

## Structure

- `apps/web`: Next.js dashboard shell.
- `services/api`: FastAPI application and domain logic.
- `supabase/migrations`: PostgreSQL schema and tenant RLS.
- `tests`: dependency-light domain tests.
- `docs`: approved product and architecture baseline.

## Bootstrap

Use Python 3.12 and Node 20+. Copy `.env.example` to `.env`, then install `pip install -e ".[dev]"` and `npm install --prefix apps/web`. Run `uvicorn varianz.main:app --app-dir services/api --reload` and `npm run dev --prefix apps/web`. Cloud variables may remain empty for local demo work.

Run the credential-free checks with `python -m unittest discover -s tests -v`.

## Supabase bootstrap

After configuring `DATABASE_URL` with the Supabase session-pooler URI, run:

```bash
python scripts/db_admin.py status
python scripts/db_admin.py migrate
python scripts/db_admin.py seed
```

The migration is transactional. The Wageningen seed uses deterministic identifiers and conflict
handling, so rerunning it does not duplicate observations.
