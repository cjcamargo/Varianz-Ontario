# Connected Development Runbook

## Secret handling

Never commit `.env`, Supabase tokens/database passwords, service-role keys or `OPENAI_API_KEY`. Configure local secrets in `.env`; configure deployment secrets in the hosting provider. The browser receives only the Supabase publishable key and API base URL.

## Supabase

1. Authenticate locally with `supabase login` or a temporary `SUPABASE_ACCESS_TOKEN` environment variable.
2. Link using `supabase link --project-ref <ref>`; supply the database password through the prompt or `SUPABASE_DB_PASSWORD` environment variable.
3. Inspect with `supabase db push --dry-run`, then apply with `supabase db push`.
4. Generate TypeScript types after each schema change and commit them.
5. All remote schema changes go through migration files; do not edit production schema directly in Studio.

## OpenAI

Create a project-scoped API key and place it in local `.env` as `OPENAI_API_KEY`. The key is server-only. `OPENAI_MODEL` defaults to `gpt-5.6-luna` and remains configurable. Voice messages use the same server-side key and `OPENAI_TRANSCRIPTION_MODEL`, which defaults to `whisper-1`. Spoken replies use `OPENAI_SPEECH_MODEL=tts-1` and `OPENAI_VOICE=alloy`; the structured assistant contract selects English or Spanish from the current operator question. The interpretation endpoint sends `store: false`, bounded evidence and a bounded output budget.

## GitHub

The default branch is `main`; changes use feature branches and pull requests after the initial baseline. Required checks are API tests/lint and the production web build. Repository secrets are added only when a deployment workflow requires them.
