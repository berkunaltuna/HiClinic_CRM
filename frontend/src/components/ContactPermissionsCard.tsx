"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { AutomationSendOut, CustomerOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import { AutomationSendStatus, automationLabel, slotText } from "@/components/AutomationSendStatus";

export function ContactPermissionsCard({ customer, onSaved }: { customer: CustomerOut; onSaved: (c: CustomerOut) => void }) {
  const toast = useToast();
  const [canContact, setCanContact] = useState(customer.can_contact);
  const [source, setSource] = useState(customer.consent_source || "");
  const [saving, setSaving] = useState(false);
  const [sends, setSends] = useState<AutomationSendOut[]>([]);

  useEffect(() => {
    setCanContact(customer.can_contact);
    setSource(customer.consent_source || "");
    apiFetch<AutomationSendOut[]>(`/automations/sends?customer_id=${customer.id}&limit=20`).then(setSends).catch(() => setSends([]));
  }, [customer]);

  const dirty = canContact !== customer.can_contact || source !== (customer.consent_source || "");

  async function save() {
    setSaving(true);
    try {
      const updated = await apiFetch<CustomerOut>(`/customers/${customer.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          can_contact: canContact,
          consent_source: source.trim() || null,
        }),
      });
      toast.push("Contact permissions saved");
      onSaved(updated);
    } catch (err: any) {
      toast.push(err?.message || "Failed to save permissions", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <div className="cardHeader" style={{ fontWeight: 900 }}>Messaging permissions</div>
      <div className="cardBody" style={{ display: "grid", gap: 10 }}>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={!canContact} onChange={(e) => setCanContact(!e.target.checked)} />
          Patient has opted out of all contact
        </label>
        <div style={{ display: "grid", gap: 4 }}>
          <span className="muted" style={{ fontSize: 12 }}>Note</span>
          <input className="formField" value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. Replied STOP on WhatsApp, 14 Oct" maxLength={200} style={{ width: "100%" }} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <span className="muted" style={{ fontSize: 12 }}>
            Automated email and WhatsApp go to every patient with valid contact details. Tick opted out when someone replies STOP or asks not to be contacted.
            {customer.consent_updated_at ? ` Last updated ${fmtDateTime(customer.consent_updated_at)}.` : ""}
          </span>
          <button className="btn btnPrimary" type="button" disabled={!dirty || saving} onClick={() => void save()}>{saving ? "Saving…" : "Save"}</button>
        </div>

        {!!sends.length && (
          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10, display: "grid", gap: 8 }}>
            <div className="muted" style={{ fontSize: 12 }}>Automated messages</div>
            {sends.map((s) => (
              <div key={s.id} style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                <div style={{ fontSize: 13 }}>
                  <b>{automationLabel(s)}</b>{s.channel ? ` · ${s.channel}` : ""}
                  {s.slot_starts_at && <div className="muted" style={{ fontSize: 12 }}>{slotText(s.slot_starts_at, s.slot_ends_at)}</div>}
                  <div className="muted" style={{ fontSize: 12 }}>{fmtDateTime(s.sent_at || s.attempted_at || s.created_at)}</div>
                </div>
                <AutomationSendStatus send={s} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
