"use client";

import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";

type InboxCustomer = {
  id: string;
  name: string;
  phone?: string | null;
  email?: string | null;
  stage: string;
  tags: string[];
  bucket: string;
  next_follow_up_at?: string | null;
  last_activity_at?: string | null;
  last_activity_direction?: string | null;
};

export default function InboxPage() {
  useRequireAuth();
  const [bucket, setBucket] = useState<string>("followup_due");
  const [q, setQ] = useState<string>("");
  const [rows, setRows] = useState<InboxCustomer[]>([]);
  const [error, setError] = useState<string | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (bucket) params.set("bucket", bucket);
    if (q) params.set("q", q);
    return params.toString();
  }, [bucket, q]);

  useEffect(() => {
    let alive = true;
    setError(null);
    apiFetch<InboxCustomer[]>(`/inbox/customers?${query}`)
      .then((d) => alive && setRows(d))
      .catch((e: any) => alive && setError(e?.message || "Failed"));
    return () => {
      alive = false;
    };
  }, [query]);

  return (
    <div className="grid">
      <div>
        <h2 style={{ margin: 0 }}>Inbox</h2>
        <div className="muted" style={{ marginTop: 4 }}>
          Work follow-ups and ongoing conversations.
        </div>
      </div>

      <div className="card">
        <div className="cardBody" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <select value={bucket} onChange={(e) => setBucket(e.target.value)}>
          <option value="followup_due">Follow-up due</option>
          <option value="open">Open</option>
          <option value="waiting">Waiting</option>
          <option value="closed">Closed</option>
          </select>
          <input
            placeholder="Search name/phone/email"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ minWidth: 260 }}
          />
        </div>
      </div>

      {error && <div style={{ color: "var(--danger)" }}>{error}</div>}

      <div className="card">
        <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between" }}>
          <strong>Conversations</strong>
          <span className="muted" style={{ fontSize: 12 }}>
            {rows.length} items
          </span>
        </div>
        <div className="cardBody" style={{ display: "grid", gap: 10 }}>
          {rows.map((c) => (
            <a key={c.id} href={`/inbox/${c.id}`} className="card" style={{ boxShadow: "none" }}>
              <div className="cardBody">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                  <div style={{ fontWeight: 800 }}>{c.name}</div>
                  <span className="muted" style={{ fontSize: 13 }}>
                    {c.bucket} · {c.stage}
                  </span>
                </div>
                <div className="muted" style={{ marginTop: 6 }}>
                  {c.phone || c.email || ""}
                </div>
                <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {c.tags?.slice(0, 8).map((t) => (
                    <span key={t} className="chip">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            </a>
          ))}
          {!rows.length && !error && <p className="muted">No customers in this bucket.</p>}
        </div>
      </div>
    </div>
  );
}
