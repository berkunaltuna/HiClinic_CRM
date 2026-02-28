"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch, setToken } from "@/lib/api";
import type { AuthTokenOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

export default function RegisterPage() {
  const router = useRouter();
  const toast = useToast();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const out = await apiFetch<AuthTokenOut>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(out.access_token);
      toast.push("Account created");
      router.replace("/dashboard");
    } catch (err: any) {
      toast.push(err?.message || "Register failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="card" style={{ width: "min(520px, 100vw)", padding: 18 }}>
      <div style={{ fontSize: 18, fontWeight: 900 }}>Create account</div>
      <div className="muted" style={{ fontSize: 12 }}>Register to access your CRM workspace</div>

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
          {busy ? "Creating…" : "Create account"}
        </button>

        <div className="muted" style={{ fontSize: 13 }}>
          Already have an account? <Link href="/login">Sign in</Link>
        </div>
      </form>
    </main>
  );
}
