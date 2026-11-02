"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/Toast";
import {
  type DealSelection,
  type IssuedLinkOut,
  type LinkDelivery,
  type PhotoLinkOptionsOut,
  dealSelectionFrom,
  errorDetail,
} from "@/lib/photoRequests";

/** Create a photo request (CRM contact page and doctor interface). Emails the link by default. */
export function NewPhotoRequestForm({
  customerId,
  onCancel,
  onCreated,
  showAppointment = true,
}: {
  customerId: string;
  onCancel: () => void;
  onCreated: (o: IssuedLinkOut, contact: { method: LinkDelivery; firstName: string; whatsappPhone: string | null }) => void;
  showAppointment?: boolean;
}) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [appointmentId, setAppointmentId] = useState("");
  const [dealId, setDealId] = useState("");
  const [options, setOptions] = useState<PhotoLinkOptionsOut | null>(null);
  // Chosen by staff; until then: email if there is an address, else WhatsApp, else copy.
  const [picked, setPicked] = useState<LinkDelivery | null>(null);
  const [selection, setSelection] = useState<DealSelection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<PhotoLinkOptionsOut>(`/customers/${customerId}/photo-requests/link-options`)
      .then(setOptions)
      .catch(() => setOptions({ appointments: [], deals: [], has_email: false, whatsapp_phone: null, patient_first_name: "" }));
  }, [customerId]);

  const hasEmail = !!options?.has_email;
  const whatsappPhone = options?.whatsapp_phone || null;
  const method: LinkDelivery = picked ?? (hasEmail ? "email" : whatsappPhone ? "whatsapp" : "copy");
  const sendEmail = method === "email";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const out = await apiFetch<IssuedLinkOut>(`/customers/${customerId}/photo-requests`, {
          method: "POST",
          body: JSON.stringify({
            title: title.trim(),
            instructions: instructions.trim() || null,
            appointment_id: appointmentId || null,
            deal_id: dealId || null,
            send_email: sendEmail,
          }),
        });
      onCreated(out, { method, firstName: options?.patient_first_name || "", whatsappPhone });
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

  const dealChoices = selection ? selection.deals : options?.deals || [];

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
              {(options?.appointments || []).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
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
      <fieldset style={{ border: "none", padding: 0, margin: 0, display: "grid", gap: 6 }}>
        <legend style={{ fontSize: 12, fontWeight: 700, marginBottom: 4 }}>How should the patient get the link?</legend>
        {(
          [
            { value: "email", label: "Email it now", hint: hasEmail ? "Sent through the CRM outbox. The email contains only the link." : "This patient has no email address.", disabled: !hasEmail },
            { value: "whatsapp", label: "Send by WhatsApp", hint: whatsappPhone ? "After creating, open WhatsApp with a ready-made message containing the link." : "No phone number you can use for this patient.", disabled: !whatsappPhone },
            { value: "copy", label: "Copy the link", hint: "Paste it into a message yourself.", disabled: false },
          ] as { value: LinkDelivery; label: string; hint: string; disabled: boolean }[]
        ).map((o) => (
          <label key={o.value} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, opacity: o.disabled ? 0.55 : 1 }}>
            <input type="radio" name={`delivery-${customerId}`} value={o.value} checked={method === o.value} disabled={o.disabled || !options} onChange={() => setPicked(o.value)} />
            <span>
              {o.label}
              <span className="muted" style={{ display: "block", fontSize: 12 }}>{o.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {error && <div role="alert" style={{ color: "var(--danger)", fontSize: 13 }}>{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btnPrimary" type="submit" disabled={saving || !options || !title.trim() || (!!selection && !dealId)}>
          {saving ? "Working…" : method === "email" ? "Create and email link" : method === "whatsapp" ? "Create link for WhatsApp" : "Create and get link"}
        </button>
        <button className="btn" type="button" onClick={onCancel} disabled={saving}>Cancel</button>
      </div>
    </form>
  );
}
