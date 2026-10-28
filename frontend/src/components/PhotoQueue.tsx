"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { fmtDateTime } from "@/lib/dates";
import { PhotoRequestDrawer } from "@/components/PhotoRequestDrawer";
import { EMAIL_STATUS_LABELS, type PhotoRequestQueueItem, photoStatusLabel } from "@/lib/photoRequests";

const FILTERS: { label: string; value: string }[] = [
  { label: "Needs review", value: "uploaded,in_review" },
  { label: "Waiting on patient", value: "requested,more_photos_needed" },
  { label: "Reviewed", value: "reviewed" },
  { label: "All", value: "" },
];

/** Photo requests the caller may see (the API scopes it: CRM access, or a doctor's assignments). */
export function PhotoQueue({ patientHref }: { patientHref: (customerId: string) => string }) {
  const [filter, setFilter] = useState(FILTERS[0].value);
  const [items, setItems] = useState<PhotoRequestQueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  async function load() {
    setItems(null);
    try {
      setItems(await apiFetch<PhotoRequestQueueItem[]>(`/photo-requests${filter ? `?status=${encodeURIComponent(filter)}` : ""}`));
      setError(null);
    } catch (err: any) {
      setError(err?.status === 403 ? "Your role cannot view photo requests." : err?.message || "Failed to load");
      setItems([]);
    }
  }

  useEffect(() => { void load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="card">
      <div className="cardHeader" style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "space-between" }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }} role="group" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button key={f.label} className={`btn ${filter === f.value ? "btnPrimary" : ""}`.trim()} aria-pressed={filter === f.value} onClick={() => setFilter(f.value)}>
              {f.label}
            </button>
          ))}
        </div>
        <button className="btn" onClick={() => void load()}>Refresh</button>
      </div>
      <div className="cardBody">
        {error && <div role="alert" className="muted">{error}</div>}
        {items === null ? (
          <div className="muted" aria-live="polite">Loading…</div>
        ) : !items.length && !error ? (
          <div className="muted">Nothing here.</div>
        ) : (
          <div className="tableWrap">
            <table className="table">
              <thead><tr><th>Patient</th><th>Request</th><th>Status</th><th>Photos</th><th>Updated</th><th><span className="sr-only">Open</span></th></tr></thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id}>
                    <td><Link href={patientHref(r.customer_id)}>{r.customer_name}</Link></td>
                    <td style={{ fontWeight: 700 }}>{r.title}</td>
                    <td>
                      <span className="badge">{photoStatusLabel(r.status)}</span>
                      {r.email_status && <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>{EMAIL_STATUS_LABELS[r.email_status] || r.email_status}</div>}
                    </td>
                    <td className="muted">{r.photo_count}</td>
                    <td className="muted">{fmtDateTime(r.updated_at)}</td>
                    <td><button className="btn" onClick={() => setOpenId(r.id)} aria-label={`Open ${r.title} for ${r.customer_name}`}>Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {openId && <PhotoRequestDrawer requestId={openId} onClose={() => setOpenId(null)} onChanged={() => void load()} />}
    </section>
  );
}
