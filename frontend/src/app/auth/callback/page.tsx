"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

/**
 * Kite OAuth redirect target. Sits OUTSIDE the `(app)` route group so it
 * doesn't get wrapped by `AppShell` (which renders nothing when no user
 * is loaded — and Kite redirects can land on a different hostname than
 * the user originally logged in on, where localStorage is empty).
 *
 * Flow:
 *   1. Read `request_token` from the query string (Kite appends it).
 *   2. If we have a JWT in localStorage on this origin, POST it through to
 *      the backend so it can `kite.generate_session(request_token,
 *      api_secret)` and persist the access token on the user row.
 *   3. If localStorage is empty BUT we appear to be on a localhost-family
 *      host (127.0.0.1 vs. localhost), bounce to the canonical host with
 *      the same query string — the user's JWT lives there.
 */

const TOKEN_KEY = "algo_trader_token";

function tokenInLocalStorage(): boolean {
  if (typeof window === "undefined") return false;
  return !!window.localStorage.getItem(TOKEN_KEY);
}

function alternateLocalhostHost(currentHost: string): string | null {
  // Map between the two equivalent loopback hostnames so we can ferry
  // the user back to whichever one actually holds their session.
  if (currentHost.startsWith("127.0.0.1")) {
    return currentHost.replace("127.0.0.1", "localhost");
  }
  if (currentHost.startsWith("localhost")) {
    return currentHost.replace("localhost", "127.0.0.1");
  }
  return null;
}

export default function AuthCallbackPage() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<string>("Connecting your Kite account…");
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    const requestToken = searchParams.get("request_token");

    if (!requestToken) {
      setStatus("No request token received from Kite. The OAuth handshake didn't complete.");
      setIsError(true);
      return;
    }

    if (!tokenInLocalStorage()) {
      // No app session on THIS origin. Bounce to the equivalent host so
      // the page can find the JWT in its localStorage and finish the
      // exchange. Preserve the full query string so request_token rides
      // along.
      const alt = alternateLocalhostHost(window.location.host);
      if (alt) {
        const target = `${window.location.protocol}//${alt}${window.location.pathname}${window.location.search}`;
        setStatus(`Redirecting to ${alt} to complete sign-in…`);
        window.location.replace(target);
        return;
      }
      setStatus(
        "You're not signed in on this host. Open the app on the same hostname you used to log in and retry."
      );
      setIsError(true);
      return;
    }

    api
      .get<{ status: string }>(`/api/auth/callback?request_token=${encodeURIComponent(requestToken)}`)
      .then(() => {
        setStatus("Connected. Redirecting…");
        setTimeout(() => {
          window.location.href = "/settings";
        }, 800);
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : "Failed to authenticate with Kite.";
        setStatus(msg);
        setIsError(true);
      });
  }, [searchParams]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg-grouped, #f5f5f7)",
        padding: 20,
        fontFamily: "Inter, system-ui, sans-serif",
      }}
    >
      <div
        style={{
          background: "var(--bg-primary, #ffffff)",
          border: "1px solid var(--separator-light, #e5e5ea)",
          borderRadius: 14,
          padding: "32px 36px",
          maxWidth: 460,
          textAlign: "center",
          boxShadow: "0 10px 30px rgba(0,0,0,0.06)",
        }}
      >
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>
          Kite authentication
        </h1>
        <p
          style={{
            marginTop: 14,
            fontSize: 14,
            lineHeight: 1.5,
            color: isError
              ? "var(--system-red, #d70015)"
              : "var(--label-secondary, #6e6e73)",
          }}
        >
          {status}
        </p>
        {isError && (
          <a
            href="/settings"
            style={{
              display: "inline-block",
              marginTop: 18,
              padding: "9px 16px",
              borderRadius: 8,
              background: "var(--label-primary, #1d1d1f)",
              color: "var(--bg-primary, #ffffff)",
              fontSize: 13,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            Back to Settings
          </a>
        )}
      </div>
    </div>
  );
}
