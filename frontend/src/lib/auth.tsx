"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import { api } from "./api";

interface AuthUser {
  id: number;
  username: string;
  email: string | null;
}

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  setUser: (u: AuthUser) => void;
  login: (username: string, password: string) => Promise<void>;
  register: (
    username: string,
    password: string,
    email?: string
  ) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

const TOKEN_KEY = "algo_trader_token";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const saveToken = useCallback((t: string, u: AuthUser) => {
    localStorage.setItem(TOKEN_KEY, t);
    setToken(t);
    setUser(u);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    router.push("/login");
  }, [router]);

  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (!stored) {
      setIsLoading(false);
      if (pathname !== "/login") {
        router.push("/login");
      }
      return;
    }

    api
      .get<{
        id: number;
        username: string;
        email: string | null;
      }>("/api/user/me", { Authorization: `Bearer ${stored}` })
      .then((data) => {
        setToken(stored);
        setUser(data);
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        if (pathname !== "/login") {
          router.push("/login");
        }
      })
      .finally(() => setIsLoading(false));
  }, [pathname, router]);

  const login = async (username: string, password: string) => {
    const data = await api.post<{
      access_token: string;
      user: AuthUser;
    }>("/api/user/login", { username, password });
    saveToken(data.access_token, data.user);
    router.push("/dashboard");
  };

  const register = async (
    username: string,
    password: string,
    email?: string
  ) => {
    const data = await api.post<{
      access_token: string;
      user: AuthUser;
    }>("/api/user/register", { username, password, email });
    saveToken(data.access_token, data.user);
    router.push("/settings");
  };

  return (
    <AuthContext.Provider value={{ user, token, isLoading, setUser, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
