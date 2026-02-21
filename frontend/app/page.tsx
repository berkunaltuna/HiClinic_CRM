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
      setOk("Token saved. Go to Inbox.");
    } catch (err: any) {
      setError(err?.message || "Failed");
    }
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <h2>Sign in</h2>
      <p style={{ marginTop: 0, color: "#555" }}>
        This is a minimal UI. It stores the JWT in <code>localStorage</code>.
      </p>

      <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
        <label>
          Email
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{ width: "100%", padding: 8, display: "block", marginTop: 4 }}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ width: "100%", padding: 8, display: "block", marginTop: 4 }}
          />
        </label>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button type="submit" style={{ padding: "8px 12px" }}>
            {mode === "login" ? "Login" : "Register"}
          </button>
          <button
            type="button"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
            style={{ padding: "8px 12px" }}
          >
            Switch to {mode === "login" ? "Register" : "Login"}
          </button>
        </div>
      </form>

      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {ok && <p style={{ color: "green" }}>{ok}</p>}
    </div>
  );
}
