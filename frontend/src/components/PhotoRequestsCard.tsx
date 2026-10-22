"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import { IssuedLink, PhotoRequestDrawer } from "@/components/PhotoRequestDrawer";
import {
  type IssuedLinkOut,
  type PhotoLinkOptionsOut,
  type PhotoRequestOut,
  photoStatusLabel,
} from "@/lib/photoRequests";

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
          <CreateForm
            customerId={customerId}
            onCancel={() => setCreating(false)}
            onCreated={(out) => {
              setCreating(false);
              setIssued(out.portal_url);
              toast.push("Photo request created");
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
          <table className="table">
            <thead>
              <tr><th>Request</th><th>Status</th><th>Photos</th><th>Updated</th><th><span className="sr-only">Open</span></th></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td style={{ fontWeight: 700 }}>{r.title}</td>
                  <td><span className="badge">{photoStatusLabel(r.status)}</span></td>
                  <td className="muted">{r.photo_count}</td>
                  <td className="muted">{fmtDateTime(r.updated_at)}</td>
                  <td><button className="btn" onClick={() => setOpenId(r.id)} aria-label={`Open photo request ${r.title}`}>Open</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {openId && <PhotoRequestDrawer requestId={openId} onClose={() => setOpenId(null)} onChanged={() => void load()} />}
    </section>
  );
}

function CreateForm({ customerId, onCancel, onCreated }: { customerId: string; onCancel: () => void; onCreated: (o: IssuedLinkOut) => void }) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [appointmentId, setAppointmentId] = useState("");
  const [dealId, setDealId] = useState("");
  const [options, setOptions] = useState<PhotoLinkOptionsOut>({ appointments: [], deals: [] });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<PhotoLinkOptionsOut>(`/customers/${customerId}/photo-requests/link-options`).then(setOptions).catch(() => undefined);
  }, [customerId]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    try {
      onCreated(
        await apiFetch<IssuedLinkOut>(`/customers/${customerId}/photo-requests`, {
          method: "POST",
          body: JSON.stringify({
            title: title.trim(),
            instructions: instructions.trim() || null,
            appointment_id: appointmentId || null,
            deal_id: dealId || null,
          }),
        }),
      );
    } catch (err: any) {
      toast.push(err?.status === 403 ? "Your role cannot create photo requests" : err?.message || "Failed to create request", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: 8, padding: 10, border: "1px solid var(--border)", borderRadius: 12 }}>
      <label htmlFor="pr-title" style={{ fontSize: 12, fontWeight: 700 }}>Title (shown to the patient)</label>
      <input id="pr-title" className="formField" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required placeholder="e.g. Hair transplant assessment" />
      <label htmlFor="pr-instructions" style={{ fontSize: 12, fontWeight: 700 }}>Which photos are needed (shown to the patient)</label>
      <textarea id="pr-instructions" rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={4000} placeholder="e.g. Front, top and back of the head in good daylight." />
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div style={{ display: "grid", gap: 4 }}>
          <label htmlFor="pr-appt" style={{ fontSize: 12, fontWeight: 700 }}>Appointment (optional)</label>
          <select id="pr-appt" value={appointmentId} onChange={(e) => setAppointmentId(e.target.value)}>
            <option value="">None</option>
            {options.appointments.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </div>
        <div style={{ display: "grid", gap: 4 }}>
          <label htmlFor="pr-deal" style={{ fontSize: 12, fontWeight: 700 }}>Treatment enquiry (optional)</label>
          <select id="pr-deal" value={dealId} onChange={(e) => setDealId(e.target.value)}>
            <option value="">None</option>
            {options.deals.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btnPrimary" type="submit" disabled={saving || !title.trim()}>{saving ? "Creating…" : "Create and get link"}</button>
        <button className="btn" type="button" onClick={onCancel} disabled={saving}>Cancel</button>
      </div>
    </form>
  );
}
