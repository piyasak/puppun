# Supabase Auth — browser identity (E-25, E-27)

PO decision 2026-10-07: email for sign-up and password reset goes through Supabase. Supabase
sends email only as part of Supabase Auth, so browser sign-up, sign-in, sign-out, email
confirmation and password reset all move to Supabase Auth. The ClipFlow API stores only the
application profile (username, Workspace, role, rights acceptance).

## Project

| Item | Value |
|---|---|
| Project | `punpun`, ref `wqcbubphiihpseqzglwe`, region ap-southeast-1, org "piyasak's Org" (Free plan, $0/month — confirmed by PO 2026-10-07) |
| URL | `https://wqcbubphiihpseqzglwe.supabase.co` (public) |
| JWT signing | Asymmetric **ES256**; public keys at `/auth/v1/.well-known/jwks.json` (checked 2026-10-07) |
| Used by the API | `SUPABASE_URL` only. The API never holds the service-role key or the JWT secret |
| Used by the web app | URL + **publishable** key (public by design), in `apps/web/.env.cloud.local` (gitignored) |

## Flow

1. Browser: `supabase.auth.signUp({email, password})` → Supabase sends a confirmation email.
2. Browser: `signInWithPassword` → access token (JWT, about 1 h) + refresh token.
3. Browser → API: `Authorization: Bearer <access token>` on every request (never a cookie, never a query string).
4. First time: `POST /v1/onboarding {username, workspace_name, accept_rights: true}` creates the profile, Workspace (Owner) and rights acceptance (Q-14). Until then the API answers `403 ONBOARDING_REQUIRED`.
5. Password reset: `supabase.auth.resetPasswordForEmail(email, {redirectTo})`. Supabase answers the same way whether or not the account exists. The email link opens `/auth/confirm?token_hash=…&type=recovery`; pressing the button calls `verifyOtp`, which signs the user in; then `updateUser({password})`.
6. Email confirmation works the same way (`type=email`) (E-28).

API check per request (`clipflow_api/identity.py`): signature with a JWKS key (ES256/RS256 only, never HS256 or none), `iss = <url>/auth/v1`, `aud = authenticated`, `exp`, `role = authenticated`, not `is_anonymous`, has an email. Every failure gives the same `401 UNAUTHENTICATED`.

## Dashboard settings the PO must set (the MCP tools cannot change auth settings)

Authentication → URL Configuration / Sign In / Providers / Emails:

| Setting | Value | Why |
|---|---|---|
| Email provider → Confirm email | On (default) | Sign-up must prove the address. Also hides whether an email is already registered (E-21) |
| Minimum password length | 10 | Same policy as before (E-23) |
| Site URL | `http://localhost:5173` for development; the real domain once D01 is decided | Reset and confirmation links return here |
| Redirect URLs | `http://localhost:5173/**` | Allows `redirectTo` on the reset page |
| Anonymous sign-ins | Off (default) | The API rejects anonymous users anyway |
| Leaked password protection | On if available on the plan | — |
| **Custom SMTP** | **Set by the PO on 2026-10-09:** Gmail (`smtp.gmail.com:465`, sender = the PO's Gmail, App Password entered by the PO in the dashboard only; never in chat, repo or logs) | Good for staging/pilot (about 500 recipients/day, `@gmail.com` sender). Before launch, move to a transactional provider on the punpun domain (SPF/DKIM) |
| **Email templates (E-28)** | Emails → Templates: paste the body of `supabase/templates/confirmation.html` into **Confirm signup** and `supabase/templates/recovery.html` into **Reset Password** (subjects are in `supabase/config.toml`) | Links open our `/auth/confirm` page; the token is used only when the person presses the button, so mail scanners cannot use it up |

## Local stack and browser E2E

- `supabase/config.toml` (Supabase CLI 2.120.0, run with `npx supabase start -x studio,storage-api,imgproxy,realtime,edge-runtime,logflare,vector,supavisor,postgres-meta`): auth + db + kong + Mailpit only. Same rules as the cloud project: ES256 signing key (`supabase/signing_keys.json`, generated locally and gitignored), Confirm email on, minimum password length 10, site URL `http://127.0.0.1:5173`.
- `py tasks.py test-e2e` recreates the `clipflow_e2e` database, starts the API (port 8001) and Vite (5173), then runs Playwright (`apps/web/e2e/`) in Edge. It reads confirmation and reset links from Mailpit (`http://127.0.0.1:54324`). The Playwright config refuses any non-local Supabase URL.
- Cloud manual test: `apps/web/.env.cloud.local` (gitignored; public URL + publishable key) + `npx vite --mode cloud --host localhost --port 3000`. Port 3000 matches the cloud project's default Site URL until the PO changes it. The PO types the email and password and confirms the email; Claude only checks the result.

## Known limits

- Signing out revokes the refresh token, but an already issued access token stays valid until it expires (about 1 h). Shorter JWT expiry is a Supabase setting if needed.
- Free plan: the project pauses after about 1 week without activity. Wake it from the dashboard before testing.
- The live end-to-end test (sign up → confirm → sign in → `/v1/onboarding` → reset) needs a real person and inbox. Claude may not create accounts on external services. The PO runs it with a team-member address. See `services/api/tests/test_supabase_live.py`.
