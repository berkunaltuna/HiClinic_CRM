"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { type DealSelection, type IssuedLinkOut, type PhotoLinkOptionsOut, dealSelectionFrom, errorDetail } from "@/lib/photoRequests";

/** Create a photo request (CRM contact page and doctor interface). Emails the link by default. */
export function NewPhotoRequestForm({
  customerId,
  onCancel,
  onCreated,
  showAppointment = true,
}: {
  customerId: string;
  onCancel: () => void;
  onCreated: (o: IssuedLinkOut) => void;
  showAppointment?: boolean;
}) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [appointmentId, setAppointmentId] = useState("");
  const [dealId, setDealId] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [options, setOptions] = useState<PhotoLinkOptionsOut>({ appointments: [], deals: [] });
  const [selection, setSelection] = useState<DealSelection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<PhotoLinkOptionsOut>(`/customers/${customerId}/photo-requests/link-options`).then(setOptions).catch(() => undefined);
  }, [customerId]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      onCreated(
        await apiFetch<IssuedLinkOut>(`/customers/${customerId}/photo-requests`, {
          method: "POST",
          body: JSON.stringify({
            title: title.trim(),
            instructions: instructions.trim() || null,
            appointment_id: appointmentId || null,
            deal_id: dealId || null,
            send_email: sendEmail,
          }),
        }),
      );
    } catch (err: any) {
      const sel = dealSelectionFrom(err);
      if (sel) {
        setSelection(sel);
        setError(sel.message);
      } else {
        // Nothing was created or sent: show why, keep the form filled in.
        setError(err?.status === 403 ? "Your role cannot create photo requests." : errorDetail(err, "Failed to create the request"));
        toast.push("Photo request not sent", "error");
      }
    } finally {
      setSaving(false);
    }
  }

  const dealChoices = selection ? selection.deals : options.deals;

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: 8, padding: 10, border: "1px solid var(--border)", borderRadius: 12 }}>
      <label htmlFor="pr-title" style={{ fontSize: 12, fontWeight: 700 }}>Title (shown to the patient)</label>
      <input id="pr-title" className="formField" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required placeholder="e.g. Hair transplant assessment" />
      <label htmlFor="pr-instructions" style={{ fontSize: 12, fontWeight: 700 }}>Which photos are needed (shown to the patient)</label>
      <textarea id="pr-instructions" rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={4000} placeholder="e.g. Front, top and back of the head in good daylight." />
      <div className="grid" style={{ gridTemplateColumns: showAppointment ? "1fr 1fr" : "1fr", gap: 8 }}>
        {showAppointment && (
          <div style={{ display: "grid", gap: 4, minWidth: 0 }}>
            <label htmlFor="pr-appt" style={{ fontSize: 12, fontWeight: 700 }}>Appointment (optional)</label>
            <select id="pr-appt" value={appointmentId} onChange={(e) => setAppointmentId(e.target.value)}>
              <option value="">None</option>
              {options.appointments.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          </div>
        )}
        <div style={{ display: "grid", gap: 4, minWidth: 0 }}>
          <label htmlFor="pr-deal" style={{ fontSize: 12, fontWeight: 700 }}>
            Treatment enquiry {selection ? "(required)" : "(optional)"}
          </label>
          <select id="pr-deal" value={dealId} onChange={(e) => setDealId(e.target.value)} required={!!selection} aria-invalid={!!selection && !dealId}>
            <option value="">{selection ? "Choose the enquiry…" : "None"}</option>
            {dealChoices.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </div>
      </div>
      <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
        <input type="checkbox" checked={sendEmail} onChange={(e) => setSendEmail(e.target.checked)} />
        <span>
          Email the secure upload link to the patient now
          <span className="muted" style={{ display: "block", fontSize: 12 }}>
            Sent through the CRM outbox. The email contains only the link, never photos or clinical details. Untick to copy the link yourself.
          </span>
        </span>
      </label>
      {error && <div role="alert" style={{ color: "var(--danger)", fontSize: 13 }}>{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btnPrimary" type="submit" disabled={saving || !title.trim() || (!!selection && !dealId)}>
          {saving ? "Working…" : sendEmail ? "Create and email link" : "Create and get link"}
        </button>
        <button className="btn" type="button" onClick={onCancel} disabled={saving}>Cancel</button>
      </div>
    </form>
  );
}
