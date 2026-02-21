"use client";

import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";

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
    <div>
      <h2>Inbox</h2>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
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
          style={{ padding: 8, minWidth: 260 }}
        />
      </div>

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <div style={{ display: "grid", gap: 8 }}>
        {rows.map((c) => (
          <a
            key={c.id}
            href={`/inbox/${c.id}`}
            style={{
              border: "1px solid #eee",
              padding: 12,
              borderRadius: 8,
              textDecoration: "none",
              color: "inherit",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <strong>{c.name}</strong>
              <span style={{ color: "#666" }}>{c.bucket} · {c.stage}</span>
            </div>
            <div style={{ color: "#666", marginTop: 6 }}>
              {c.phone || c.email || ""}
            </div>
            <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {c.tags?.slice(0, 8).map((t) => (
                <span key={t} style={{ fontSize: 12, border: "1px solid #ddd", borderRadius: 999, padding: "2px 8px" }}>
                  {t}
                </span>
              ))}
            </div>
          </a>
        ))}
        {!rows.length && !error && <p style={{ color: "#666" }}>No customers in this bucket.</p>}
      </div>
    </div>
  );
}
