import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, savedSession, setSession, whenSignedOut, type Health, type Role, type User } from "../api";

interface SessionValue {
  user: User | null;
  health: Health | null;
  can: (role: Role) => boolean;
  signIn: (token: string, user: User) => void;
  signOut: () => void;
  refreshHealth: () => void;
  toast: (message: string, tone?: "ok" | "bad") => void;
}

const SessionContext = createContext<SessionValue | null>(null);
const RANK: Record<Role, number> = { viewer: 1, analyst: 2, supervisor: 3 };

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => savedSession()?.user ?? null);
  const [health, setHealth] = useState<Health | null>(null);
  const [toasts, setToasts] = useState<{ id: number; message: string; tone: "ok" | "bad" }[]>([]);

  const refreshHealth = useCallback(() => {
    api.get<Health>("/api/health").then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    refreshHealth();
    whenSignedOut(() => setUser(null));
  }, [refreshHealth]);

  const toast = useCallback((message: string, tone: "ok" | "bad" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "bad" ? 7000 : 4000);
  }, []);

  const value = useMemo<SessionValue>(() => ({
    user,
    health,
    can: (role) => !!user && RANK[user.role] >= RANK[role],
    signIn: (token, u) => {
      setSession(token, u);
      setUser(u);
    },
    signOut: () => {
      setSession(null);
      setUser(null);
    },
    refreshHealth,
    toast,
  }), [user, health, refreshHealth, toast]);

  return (
    <SessionContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast--${t.tone}`}>{t.message}</div>
        ))}
      </div>
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const v = useContext(SessionContext);
  if (!v) throw new Error("useSession outside SessionProvider");
  return v;
}
