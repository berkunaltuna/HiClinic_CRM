"use client";

import React, { useState } from "react";
import { apiFetch, setToken } from "@/lib/api";

export default function Home() {
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("ChangeMe123!");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    try {
      const path = mode === "login" ? "/auth/login" : "/auth/register";
      const data = await apiFetch<{ access_token: string }>(path, {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(data.access_token);
      setOk("Signed in. Redirecting…");
      window.location.href = "/inbox";
    } catch (err: any) {
      setError(err?.message || "Failed");
    }
  }

  return (
    <div style={{ maxWidth: 980, margin: "0 auto" }}>
      <div className="split" style={{ alignItems: "start" }}>
        <div className="card">
          <div className="cardHeader">
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <img src="/logo.png" alt="HealthClinicTurkiye" style={{ width: 180 }} />
              <div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>HiClinic CRM</div>
                <div className="muted" style={{ marginTop: 2 }}>
                  Clinical lead management workspace
                </div>
              </div>
            </div>
          </div>
          <div className="cardBody">
            <form onSubmit={submit} className="stack">
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Email
                </div>
                <input value={email} onChange={(e) => setEmail(e.target.value)} style={{ width: "100%" }} />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Password
                </div>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  style={{ width: "100%" }}
                />
              </div>

              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <button className="btn btnPrimary" type="submit">
                  {mode === "login" ? "Login" : "Register"}
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={() => setMode(mode === "login" ? "register" : "login")}
                >
                  Switch to {mode === "login" ? "Register" : "Login"}
                </button>
                <span className="muted" style={{ fontSize: 12 }}>
                  JWT is stored in localStorage
                </span>
              </div>

              {error && <p style={{ color: "var(--danger)", margin: 0 }}>{error}</p>}
              {ok && <p style={{ color: "var(--success)", margin: 0 }}>{ok}</p>}
            </form>
          </div>
        </div>

        <div className="card">
          <div className="cardHeader">
            <strong>Quick start</strong>
          </div>
          <div className="cardBody" style={{ lineHeight: 1.5 }}>
            <div className="chip" style={{ marginBottom: 10 }}>
              <span aria-hidden style={{ width: 10, height: 10, borderRadius: 999, background: "var(--primary)" }} />
              Brand palette applied
            </div>
            <p className="muted" style={{ marginTop: 0 }}>
              After signing in you can:
            </p>
            <ul style={{ marginTop: 0 }}>
              <li>Work the Inbox (follow-ups due).</li>
              <li>Create customers and track deals.</li>
              <li>Manage tags and review templates.</li>
            </ul>
            <div className="muted" style={{ fontSize: 12 }}>
              If your API runs on a different URL, set <code>NEXT_PUBLIC_API_URL</code>.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
