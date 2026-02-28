"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch, setToken } from "@/lib/api";
import type { AuthTokenOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/dashboard";
  const toast = useToast();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const out = await apiFetch<AuthTokenOut>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(out.access_token);
      toast.push("Logged in");
      router.replace(next);
    } catch (err: any) {
      toast.push(err?.message || "Login failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="card" style={{ width: "min(520px, 100vw)", padding: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo.png" alt="HiClinic" width={40} height={40} style={{ borderRadius: 12 }} />
        <div>
          <div style={{ fontSize: 18, fontWeight: 900 }}>HiClinic CRM</div>
          <div className="muted" style={{ fontSize: 12 }}>Sign in</div>
        </div>
      </div>

      <form onSubmit={onSubmit} className="stack" style={{ marginTop: 14 }}>
        <label className="stack" style={{ gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>Email</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
        </label>
        <label className="stack" style={{ gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>Password</span>
          <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required />
        </label>

        <button className="btn btnPrimary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <div className="muted" style={{ fontSize: 13 }}>
          New here? <Link href="/register">Create an account</Link>
        </div>
      </form>
    </main>
  );
}
