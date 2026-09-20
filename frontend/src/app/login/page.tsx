"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

export default function LoginPage() {
  const { login, register } = useAuth();
  // isSetup === null while we're still resolving; null shows the spinner.
  // After resolution: true → show login form, false → show register form.
  // We default to TRUE on any API error so a deploy-time race never sends a
  // returning user to the wrong screen. Real first-time users can still
  // reach the register form via the "First time setup?" link below.
  const [isSetup, setIsSetup] = useState<boolean | null>(null);
  // User-explicit override via `?mode=login` or `?mode=register`. Always wins
  // over the API result so you can force the right form during edge cases.
  const [modeOverride, setModeOverride] = useState<"login" | "register" | null>(null);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Effective mode: explicit override > API result > default-to-login.
  const effectiveIsSetup =
    modeOverride === "login" ? true
    : modeOverride === "register" ? false
    : (isSetup ?? true);

  useEffect(() => {
    // Read mode override from query string once on mount.
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const m = params.get("mode");
      if (m === "login" || m === "register") setModeOverride(m);
    }

    // Resolve setup status with one retry on failure (covers the 1-2s
    // window during a deploy when the backend is restarting).
    let cancelled = false;
    const fetchSetup = async (attempt: number) => {
      try {
        const data = await api.get<{ is_setup: boolean }>("/api/user/setup-status");
        if (!cancelled) setIsSetup(data.is_setup);
      } catch {
        if (attempt < 1) {
          setTimeout(() => fetchSetup(attempt + 1), 1500);
        } else if (!cancelled) {
          // Both attempts failed — default to login (safer than register)
          setIsSetup(true);
        }
      }
    };
    fetchSetup(0);
    return () => { cancelled = true; };
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      if (effectiveIsSetup) {
        await login(username, password);
      } else {
        if (password !== confirmPassword) {
          setError("Passwords do not match");
          setLoading(false);
          return;
        }
        if (password.length < 6) {
          setError("Password must be at least 6 characters");
          setLoading(false);
          return;
        }
        await register(username, password, email || undefined);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  if (isSetup === null && modeOverride === null) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold">{effectiveIsSetup ? "Login" : "Set up admin"}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {effectiveIsSetup
              ? "Sign in to your account"
              : "Create your admin account"}
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-gray-900 border border-gray-800 rounded-lg p-6 space-y-4"
        >
          {!effectiveIsSetup && (
            <div className="p-3 rounded text-xs font-medium" style={{ backgroundColor: "rgba(0,122,255,0.08)", color: "#007AFF", border: "1px solid rgba(0,122,255,0.15)" }}>
              First time setup. Create your admin account to get started.
            </div>
          )}

          <div>
            <label className="block text-sm text-gray-400 mb-1">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white text-sm focus:outline-none focus:border-blue-500"
              placeholder="Enter username"
            />
          </div>

          {!effectiveIsSetup && (
            <div>
              <label className="block text-sm text-gray-400 mb-1">
                Email (optional)
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white text-sm focus:outline-none focus:border-blue-500"
                placeholder="you@example.com"
              />
            </div>
          )}

          <div>
            <label className="block text-sm text-gray-400 mb-1">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white text-sm focus:outline-none focus:border-blue-500"
              placeholder="Enter password"
            />
          </div>

          {!effectiveIsSetup && (
            <div>
              <label className="block text-sm text-gray-400 mb-1">
                Confirm Password
              </label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white text-sm focus:outline-none focus:border-blue-500"
                placeholder="Confirm password"
              />
            </div>
          )}

          {error && (
            <div className="p-2 rounded text-xs font-medium" style={{ backgroundColor: "rgba(255,59,48,0.08)", color: "#D70015", border: "1px solid rgba(255,59,48,0.2)" }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-md transition-colors"
          >
            {loading
              ? "Please wait..."
              : effectiveIsSetup
                ? "Sign In"
                : "Create Account"}
          </button>
        </form>

        {/* Mode toggle — always present, lets the user override the API-resolved mode */}
        <p className="text-center text-xs text-gray-500 mt-4">
          {effectiveIsSetup ? (
            <>
              First time on this server?{" "}
              <button
                type="button"
                onClick={() => { setModeOverride("register"); setError(""); }}
                className="text-blue-400 hover:text-blue-300 underline-offset-2 hover:underline"
              >
                Set up admin account
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => { setModeOverride("login"); setError(""); }}
                className="text-blue-400 hover:text-blue-300 underline-offset-2 hover:underline"
              >
                Sign in instead
              </button>
            </>
          )}
        </p>

        {!effectiveIsSetup && (
          <p className="text-center text-xs text-gray-600 mt-2">
            After setup, configure your API keys in Settings
          </p>
        )}
      </div>
    </div>
  );
}
