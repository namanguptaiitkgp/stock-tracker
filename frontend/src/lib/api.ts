const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "algo_trader_token";

function getAuthHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...extra,
  };

  if (typeof window !== "undefined" && !headers.Authorization) {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }

  return headers;
}

async function request<T>(
  path: string,
  options?: RequestInit,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: getAuthHeaders({
      ...extraHeaders,
      ...(options?.headers as Record<string, string>),
    }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const message = body.detail || `API error: ${res.status} ${res.statusText}`;
    throw new Error(message);
  }

  return res.json();
}

export const api = {
  get: <T>(path: string, extraHeaders?: Record<string, string>) =>
    request<T>(path, undefined, extraHeaders),
  post: <T>(path: string, body?: unknown, extraHeaders?: Record<string, string>) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }, extraHeaders),
  put: <T>(path: string, body?: unknown, extraHeaders?: Record<string, string>) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }, extraHeaders),
  patch: <T>(path: string, body?: unknown, extraHeaders?: Record<string, string>) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }, extraHeaders),
  delete: <T>(path: string, extraHeaders?: Record<string, string>) =>
    request<T>(path, { method: "DELETE" }, extraHeaders),
};
