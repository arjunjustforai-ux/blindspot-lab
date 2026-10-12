"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import * as React from "react";
import { api, getToken, setToken } from "./api";
import type { TokenOut, User } from "./types";

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, display_name: string) => Promise<void>;
  demo: () => Promise<void>;
  logout: () => void;
}

const AuthContext = React.createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<User | null>(null);
  const [ready, setReady] = React.useState(false);
  const qc = useQueryClient();

  React.useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    api<User>("/api/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, []);

  const accept = React.useCallback(
    (t: TokenOut) => {
      setToken(t.access_token);
      qc.clear();
      setUser(t.user);
    },
    [qc],
  );

  const value = React.useMemo<AuthState>(
    () => ({
      user,
      ready,
      login: async (email, password) => accept(await api<TokenOut>("/api/auth/login", { method: "POST", body: { email, password } })),
      register: async (email, password, display_name) =>
        accept(await api<TokenOut>("/api/auth/register", { method: "POST", body: { email, password, display_name } })),
      demo: async () => accept(await api<TokenOut>("/api/auth/demo", { method: "POST" })),
      logout: () => {
        setToken(null);
        qc.clear();
        setUser(null);
      },
    }),
    [user, ready, accept, qc],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

export function useRequireAuth(): AuthState {
  const auth = useAuth();
  const router = useRouter();
  React.useEffect(() => {
    if (auth.ready && !auth.user) router.replace("/login");
  }, [auth.ready, auth.user, router]);
  return auth;
}
