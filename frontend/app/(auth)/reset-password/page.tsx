"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/Toast";

export default function ResetPasswordPage() {
  const params = useSearchParams();
  const router = useRouter();
  const toast = useToast();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) return toast.push("Passwords do not match", "error");
    setBusy(true);
    try {
      await apiFetch("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      toast.push("Password reset successfully");
      router.replace("/login");
    } catch (err: any) {
      toast.push(err?.message || "Failed to reset password", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="card" style={{ width: "min(520px, 100vw)", padding: 18 }}>
      <div style={{ fontSize: 18, fontWeight: 900 }}>Reset password</div>
      {!token ? (
        <div className="stack" style={{ marginTop: 14 }}>
          <div className="muted">Missing reset token.</div>
          <Link href="/forgot-password">Request a new link</Link>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="stack" style={{ marginTop: 14 }}>
          <label className="stack" style={{ gap: 6 }}>
            <span className="muted" style={{ fontSize: 12 }}>New password</span>
            <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" minLength={8} required />
          </label>
          <label className="stack" style={{ gap: 6 }}>
            <span className="muted" style={{ fontSize: 12 }}>Confirm password</span>
            <input value={confirm} onChange={(e) => setConfirm(e.target.value)} type="password" minLength={8} required />
          </label>
          <button className="btn btnPrimary" type="submit" disabled={busy}>{busy ? "Saving…" : "Reset password"}</button>
          <div className="muted" style={{ fontSize: 13 }}><Link href="/login">Back to login</Link></div>
        </form>
      )}
    </main>
  );
}
