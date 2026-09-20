# Authentication

Two layers: **local admin auth** (log into the app) and **Kite OAuth** (authorize the app to trade on your behalf).

## Local admin auth

Single-admin by design — the app refuses to create more than one user. Passwords are stored as bcrypt hashes; auth is JWT bearer tokens.

### Endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/user/setup-status` | Returns `{is_setup, user_count}`. Frontend uses this to pick register vs login. |
| `POST` | `/api/user/register` | Creates the first (and only) admin. Rejects with 400 if a user already exists. Password min 6 chars. |
| `POST` | `/api/user/login` | Body: `{username, password}`. Returns `access_token`. |
| `GET` | `/api/user/me` | Requires bearer. Returns the current user row minus secrets. |

### Token

- JWT signed with `APP_SECRET_KEY`, subject = `user.id`, short expiry (see `dependencies.create_access_token`).
- Frontend stashes the token in localStorage and attaches `Authorization: Bearer <token>` to every API call.

### Resetting a forgotten password

There's no self-serve reset. Rewrite the hash in Postgres:

```bash
HASH=$(docker exec algo-trader-backend-1 python -c "
import bcrypt
print(bcrypt.hashpw(b'YOUR_NEW_PASSWORD', bcrypt.gensalt()).decode())
")
docker exec -i algo-trader-timescaledb-1 psql -U algotrader -d algotrader <<SQL
UPDATE users SET password_hash = '$HASH', updated_at = now() WHERE id = 1;
SQL
```

## Kite OAuth

Zerodha Kite Connect uses a redirect-based OAuth-lite flow. The app needs a *request token* from Kite, exchanges it for an *access token*, and stores the access token on the user row.

### Setup (one-time)

1. Create a Kite Connect app at [developers.kite.trade](https://developers.kite.trade/).
2. Set the redirect URL to `http://localhost:3000/auth/callback` (matches `KITE_REDIRECT_URL` in `.env`).
3. Copy API key + secret into **Settings** in the app, save.

### Flow

```
User clicks "Connect Kite" in Settings
  → GET  /api/auth/login            → returns {login_url}
  → browser redirects to login_url   (kite.trade hosted login)
  → Kite redirects back to /auth/callback?request_token=...
  → frontend POSTs token to /api/auth/callback
  → backend exchanges request_token for access_token via kite.generate_session
  → persists kite_access_token + kite_token_expiry on users row
```

### Expiry

Kite access tokens expire **daily at ~06:00 IST**. The `token-health-check` Celery task runs at 08:00 IST and flags the user (today page banner). Re-auth is manual: Settings → Connect Kite.

### Columns on `users`

| Column | Purpose |
|---|---|
| `kite_api_key` | Public app key (stored because app is self-hosted) |
| `kite_api_secret` | Secret — encrypt at rest if you deploy this anywhere shared |
| `kite_access_token` | Daily-rotating session token |
| `kite_token_expiry` | When the token dies |

## Other API keys

`gemini_api_key` and `anthropic_api_key` live on the same `users` row, set via Settings. Env-level defaults (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) act as fallbacks for background jobs if the user row is empty, but the UI reads/writes the user-row values.
