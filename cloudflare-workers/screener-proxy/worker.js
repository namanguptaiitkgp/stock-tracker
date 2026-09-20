// Cloudflare Worker: Screener.in re-fetch proxy
// Purpose: bypass Screener's block on OCI egress IPs by re-fetching via Cloudflare edge.
//
// Auth: requires header  X-Proxy-Auth: <SHARED_SECRET>
// Usage: GET https://<your-worker>.workers.dev/?url=https://www.screener.in/company/RELIANCE/
//
// SHARED_SECRET is read from an environment variable set in the Worker dashboard,
// NOT hard-coded here.

const ALLOWED_HOST = "www.screener.in";
const CACHE_TTL_SECONDS = 3600; // 1 hour edge cache

export default {
  async fetch(request, env, ctx) {
    // --- 1. Auth ---
    const auth = request.headers.get("X-Proxy-Auth");
    if (!env.SHARED_SECRET || auth !== env.SHARED_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    // --- 2. Parse target URL from ?url=... ---
    const url = new URL(request.url);
    const target = url.searchParams.get("url");
    if (!target) {
      return new Response("Missing ?url= parameter", { status: 400 });
    }

    let targetUrl;
    try {
      targetUrl = new URL(target);
    } catch {
      return new Response("Invalid URL", { status: 400 });
    }

    // --- 3. Allow-list: only Screener ---
    if (targetUrl.hostname !== ALLOWED_HOST) {
      return new Response(`Only ${ALLOWED_HOST} is allowed`, { status: 403 });
    }

    // --- 4. Cache lookup ---
    const cacheKey = new Request(targetUrl.toString(), { method: "GET" });
    const cache = caches.default;
    let response = await cache.match(cacheKey);

    if (!response) {
      // --- 5. Cache miss: fetch from Screener with a real browser UA ---
      const upstream = await fetch(targetUrl.toString(), {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "Accept-Language": "en-US,en;q=0.9",
          "Accept-Encoding": "gzip, deflate, br",
          "Referer": "https://www.screener.in/",
        },
      });

      // Rebuild so we can set our own cache headers
      response = new Response(upstream.body, upstream);
      response.headers.set("Cache-Control", `public, max-age=${CACHE_TTL_SECONDS}`);

      // Only cache successful responses (2xx)
      if (upstream.ok) {
        ctx.waitUntil(cache.put(cacheKey, response.clone()));
      }
    }

    return response;
  },
};
