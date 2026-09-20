# Cloudflare Worker — Screener.in proxy setup

Total time: ~8 minutes. No CLI install, no credit card.

## 1. Sign up

Go to https://dash.cloudflare.com/sign-up. Email + password. Verify the email link they send.

You will land on the dashboard. You do NOT need to add a website / domain / DNS — those are for Cloudflare's CDN product, which we are not using. Skip every "add a site" prompt.

## 2. Reserve your workers.dev subdomain

In the left sidebar: **Workers & Pages** → **Overview**.

If this is your first time, it will ask you to pick a subdomain, e.g. `naman-1234.workers.dev`. Pick anything. This is the suffix your worker URL will have.

## 3. Create the Worker

Click **Create application** → **Create Worker**.

Name it `screener-proxy`. The full URL will be `https://screener-proxy.<your-subdomain>.workers.dev`.

Click **Deploy** — this deploys the default hello-world template. The deploy is just so the worker exists; we will overwrite the code in step 4.

## 4. Paste the proxy code

After the deploy screen, click **Edit code** (or **Continue to project** → **Quick edit**).

Delete everything in the editor and paste the contents of `worker.js` (sibling file in this directory).

Click **Save and deploy** (top right). Confirm.

## 5. Set the shared secret

Back on the worker's main page: **Settings** → **Variables and Secrets** → **Add variable**.

- Type: **Secret** (not "Text" — secrets are encrypted)
- Variable name: `SHARED_SECRET`
- Value: a long random string. Generate one in your terminal:

  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

  Save the output somewhere safe — you will use it in the OCI client.

Click **Deploy** to apply the secret.

## 6. Smoke test from your laptop

```bash
SECRET="paste-the-secret-here"
WORKER="https://screener-proxy.<your-subdomain>.workers.dev"

# Should print the Reliance page HTML (will be ~200 KB)
curl -H "X-Proxy-Auth: $SECRET" \
  "$WORKER/?url=https://www.screener.in/company/RELIANCE/" \
  | head -c 500
```

You should see HTML beginning with `<!DOCTYPE html>` and containing "Reliance Industries". If you get:

- `401 Unauthorized` → wrong / missing `X-Proxy-Auth` header
- `403 Only www.screener.in is allowed` → URL doesn't match the allow-list
- Empty / 5xx → check the worker logs: dashboard → your worker → **Logs** tab → **Real-time logs**

## 7. Smoke test from OCI

SSH into your OCI box and run the same curl. If it works there too, you're done — that was the whole point.

## 8. Use it from Python

```python
import os
import requests

WORKER_URL = os.environ["SCREENER_PROXY_URL"]   # https://screener-proxy.xxx.workers.dev
PROXY_SECRET = os.environ["SCREENER_PROXY_SECRET"]

def fetch_screener(path: str) -> str:
    """path: e.g. '/company/RELIANCE/' or full URL."""
    if path.startswith("http"):
        target = path
    else:
        target = f"https://www.screener.in{path}"

    r = requests.get(
        WORKER_URL,
        params={"url": target},
        headers={"X-Proxy-Auth": PROXY_SECRET},
        timeout=30,
    )
    r.raise_for_status()
    return r.text
```

Add `SCREENER_PROXY_URL` and `SCREENER_PROXY_SECRET` to your OCI env (`.env`, systemd unit, whatever you already use).

## What you don't have to do

- No domain registration
- No DNS configuration
- No Wrangler CLI install
- No `wrangler.toml`
- No CI/CD — the dashboard editor + Deploy button is the deploy

## What to keep an eye on

- **Dashboard → your worker → Metrics**: shows requests/day. You're capped at 100K/day; you'll be using ~500. If you ever see >50K, something has gone wrong (loop, leaked secret, retry storm).
- **CPU time**: also visible in Metrics. Each invocation budget is 10 ms. Pass-through proxying uses 1–3 ms.
- **Logs** tab: live tail. Useful the first time you wire it up; turn off after.

## If Cloudflare's edge IPs are also blocked by Screener

Less likely than OCI being blocked, but possible. Symptoms: the worker itself returns 403 from Screener.

Mitigations, in order of effort:
1. Rotate the User-Agent string in the worker (Screener's classifier may fingerprint exact UAs).
2. Deploy the same code to Deno Deploy as a hot standby with a different IP pool, and round-robin in your Python client.
3. If both edge-FaaS pools are blocked, you're looking at a cheap residential-IP-proxy service (~₹400–800/month) or a Hetzner box (~₹360/month) — but cross that bridge only if you actually hit it.
