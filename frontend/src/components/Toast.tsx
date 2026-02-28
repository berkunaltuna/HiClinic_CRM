"use client";

import { createContext, useContext, useMemo, useState } from "react";

type Toast = { id: string; message: string; kind: "info" | "error" };

const ToastCtx = createContext<{
  push: (message: string, kind?: Toast["kind"]) => void;
} | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const api = useMemo(() => ({
    push: (message: string, kind: Toast["kind"] = "info") => {
      const id = `${Date.now()}-${Math.random()}`;
      setToasts((t) => [...t, { id, message, kind }]);
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);
    },
  }), []);

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div style={{ position: "fixed", right: 16, bottom: 16, display: "grid", gap: 10, zIndex: 80 }}>
        {toasts.map((t) => (
          <div
            key={t.id}
            className="card"
            style={{
              padding: "10px 12px",
              borderLeft: t.kind === "error" ? "4px solid var(--danger)" : "4px solid var(--primary)",
              minWidth: 260,
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 13 }}>{t.kind === "error" ? "Error" : "Saved"}</div>
            <div className="muted" style={{ fontSize: 13 }}>{t.message}</div>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
