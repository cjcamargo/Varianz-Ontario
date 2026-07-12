# Authentication and public demo deployment

## Authentication contract

The web application uses Supabase email/password authentication. The browser restores and
refreshes its Supabase session, and sends the current access token as `Authorization: Bearer`
on every Varianz API request. The dashboard is not mounted without an authenticated session.

The public deployment must set `AUTH_REQUIRED=true`. Demo users are created and disabled in
Supabase Auth; there is no public sign-up flow in Varianz 0.2. Logout is local to the current
browser session.

Required web variables:

- `NEXT_PUBLIC_API_URL`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`

Required API variables:

- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_JWT_SECRET`
- `OPENAI_API_KEY`
- `AUTH_REQUIRED=true`
- `DATA_BACKEND=supabase`
- `CORS_ORIGINS=https://<public-web-host>`

Publishable keys are intentionally browser-visible. Service-role, database, JWT signing and
OpenAI secrets remain backend-only.

## Render blueprint

`render.yaml` defines separate `varianz-web` and `varianz-api` services. After creating the
blueprint, configure all `sync: false` values in Render. Set `NEXT_PUBLIC_API_URL` to the API
public URL plus `/api/v1`, then set `CORS_ORIGINS` to the exact web origin without a trailing
slash. Deploy the API first and the web application second.

## Acceptance check

1. Anonymous visitors see only the sign-in page.
2. Invalid credentials reveal no account-existence detail.
3. A valid user reaches Overview and all API requests contain a bearer token.
4. Refresh restores the session; logout returns to sign-in.
5. An expired or invalid token returns `401` and the UI signs out.
6. Ask Varianz and tariff writes work only after authentication.
