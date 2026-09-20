# Cloudflare Workers

External-IP proxies for services that block our cloud-provider egress IPs
at the TCP layer. Each worker is self-contained — `worker.js` — and
stateless (no bindings, no Workers KV, no D1).

## screener-proxy

Re-fetches `screener.in/company/...` pages via Cloudflare's edge so requests
appear to come from Cloudflare IPs rather than from OCI. Screener actively
refuses TCP connections from cloud-provider ranges (instant `Connection
refused`, see `docs/OCI_DEPLOYMENT_TODO.md` for the diagnosis).

**API shape:**

```
GET https://screener-proxy.<your-account>.workers.dev/?url=https://www.screener.in/company/RELIANCE/
Header: X-Proxy-Auth: <SHARED_SECRET>
```

- Allow-lists `www.screener.in` only — can't be repurposed as an open relay.
- 1h edge cache means concurrent backend runs amortize against the same
  upstream fetch.

### Setup

The Worker is deployed via the Cloudflare **dashboard** (not the wrangler CLI).
See `screener-proxy/SETUP.md` for the step-by-step.

Why dashboard not CLI: zero local install, no Node version juggling, no
`wrangler login` token in `~/.wrangler`. The 8-minute click-through is faster
than the CLI flow and produces identical output.

### Wire into the backend

On the OCI VM, add the two env vars to `.env.oci`:

```bash
ssh trader
cd ~/algo-trader
cat >> .env.oci <<'EOF'
SCREENER_PROXY_URL=https://screener-proxy.<your-account>.workers.dev
SCREENER_PROXY_SECRET=<the-secret-you-set-on-the-worker>
EOF
sudo docker compose --env-file .env.oci -f docker-compose.oci.yml up -d --no-deps backend celery-worker celery-beat
```

No image rebuild needed — `backend/app/services/screener_fetcher.py` reads
both env vars at process start and routes through the Worker when both are
set. Leave them unset locally on Mac — Screener is reachable directly from
residential IPs.

### Verify

```bash
# From inside the OCI backend container, fetch via the Worker
ssh trader 'sudo docker exec algo-trader-backend-1 bash -c "
  curl -sS -o /dev/null -w \"HTTP %{http_code} in %{time_total}s\\n\" \
       --max-time 12 \
       -H \"X-Proxy-Auth: \$SCREENER_PROXY_SECRET\" \
       \"\$SCREENER_PROXY_URL/?url=https://www.screener.in/company/TCS/consolidated/\"
"'
# Expect: HTTP 200 in ~1.5s
```

### Cost & limits

- Free tier: **100,000 requests/day**, well above our actual usage.
- Pipeline-induced traffic: each stock hits the proxy at most once per
  24h (the backend's `data_cache` TTL). Full portfolio + watchlist
  ≈ 500 stocks/day → 500 req/day → 0.5% of the daily quota.
- Worker CPU time: well within the 10ms/req free-tier limit (we just stream).
- Cloudflare edge caching (1h TTL set in `worker.js`) further reduces
  upstream Screener load.

### Security

- `ALLOWED_HOST = "www.screener.in"` in `worker.js` restricts the proxy
  to Screener only. Other hostnames return 403.
- Requests without a matching `X-Proxy-Auth` header return 401 immediately.
- The shared secret is set as a Worker **Secret** (encrypted at rest in the
  Cloudflare dashboard), not committed to this repo.

### When to refresh

Worker code is stateless. The only reasons to re-deploy:
- Screener changes their company-page URL structure
- We need to allow-list additional hostnames
- Cloudflare deprecates an API

In normal operation: deploy once, never touch.
