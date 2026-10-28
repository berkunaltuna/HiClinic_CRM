"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import { IssuedLink, PhotoRequestDrawer } from "@/components/PhotoRequestDrawer";
import { NewPhotoRequestForm } from "@/components/NewPhotoRequestForm";
import { EMAIL_STATUS_LABELS, type IssuedLinkOut, type PhotoRequestOut, photoStatusLabel } from "@/lib/photoRequests";

/** Patient-record card: photo request history/status, plus creating a new request. */
export function PhotoRequestsCard({ customerId }: { customerId: string }) {
  const toast = useToast();
  const [items, setItems] = useState<PhotoRequestOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [issued, setIssued] = useState<string | null>(null);

  async function load() {
    try {
      setItems(await apiFetch<PhotoRequestOut[]>(`/customers/${customerId}/photo-requests`));
      setError(null);
    } catch (err: any) {
      setError(err?.status === 403 ? "Your role cannot view photo requests." : "Could not load photo requests.");
    }
  }

  useEffect(() => { void load(); }, [customerId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="card" aria-labelledby="photo-requests-h">
      <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <div id="photo-requests-h" style={{ fontWeight: 900 }}>Photo requests</div>
        {!creating && !error && (
          <button className="btn btnPrimary" onClick={() => { setCreating(true); setIssued(null); }}>New photo request</button>
        )}
      </div>
      <div className="cardBody" style={{ display: "grid", gap: 10 }}>
        {issued && <IssuedLink url={issued} />}
        {creating && (
          <NewPhotoRequestForm
            customerId={customerId}
            onCancel={() => setCreating(false)}
            onCreated={(out: IssuedLinkOut) => {
              setCreating(false);
              setIssued(out.portal_url);
              toast.push(out.email ? `Photo request emailed to ${out.email.to_email}` : "Photo request created");
              void load();
            }}
          />
        )}
        {error ? (
          <div className="muted" role="alert">{error}</div>
        ) : items === null ? (
          <div className="muted" aria-live="polite">Loading…</div>
        ) : !items.length ? (
          <div className="muted">No photo requests yet.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr><th>Request</th><th>Status</th><th>Updated</th><th><span className="sr-only">Open</span></th></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td>
                    <div style={{ fontWeight: 700 }}>{r.title}</div>
                    <div className="muted" style={{ fontSize: 12 }}>{r.photo_count} photo{r.photo_count === 1 ? "" : "s"}</div>
                  </td>
                  <td>
                    <span className="badge">{photoStatusLabel(r.status)}</span>
                    {r.email_status && <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>{EMAIL_STATUS_LABELS[r.email_status] || r.email_status}</div>}
                  </td>
                  <td className="muted">{fmtDateTime(r.updated_at)}</td>
                  <td style={{ width: 1 }}><button className="btn" style={{ padding: "4px 10px", fontSize: 12 }} onClick={() => setOpenId(r.id)} aria-label={`Open photo request ${r.title}`}>Open</button></td>
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
