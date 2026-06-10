"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/Toast";

export default function ForgotPasswordPage() {
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [resetUrl, setResetUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setResetUrl(null);
    try {
      const out = await apiFetch<{ message: string; reset_url?: string | null }>("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setMessage(out.message || "If this email exists, a reset link has been sent.");
      setResetUrl(out.reset_url || null);
      toast.push("Password reset requested");
    } catch (err: any) {
      toast.push(err?.message || "Failed to request password reset", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="card" style={{ width: "min(520px, 100vw)", padding: 18 }}>
      <div style={{ fontSize: 18, fontWeight: 900 }}>Forgot your password?</div>
      <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>Enter your CRM email and we’ll send a reset link.</div>
      <form onSubmit={onSubmit} className="stack" style={{ marginTop: 14 }}>
        <label className="stack" style={{ gap: 6 }}>
          <span className="muted" style={{ fontSize: 12 }}>Email</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
        </label>
        <button className="btn btnPrimary" type="submit" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
        {message && <div className="muted" style={{ fontSize: 13 }}>{message}</div>}
        {resetUrl && <Link href={resetUrl}>Open reset link</Link>}
        <div className="muted" style={{ fontSize: 13 }}><Link href="/login">Back to login</Link></div>
      </form>
    </main>
  );
}
