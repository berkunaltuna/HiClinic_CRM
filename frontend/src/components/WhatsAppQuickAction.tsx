"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { CustomerOut, InboxCustomerOut, TemplateOut } from "@/lib/types";
import { buildWhatsAppLink, defaultWhatsAppMessage, renderTemplate, whatsappTemplates } from "@/lib/whatsapp";
import { fillFields } from "@/lib/messageFormat";

type MessageFields = { values: Record<string, string>; booking_problem: string | null; booking_fields: string[] };
const TOKEN_RE = /\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g;

export function WhatsAppQuickAction({
  customer,
  templates = [],
  compact = false,
  markConfirmation = false,
  onMarkedConfirmed,
}: {
  customer: CustomerOut | InboxCustomerOut;
  templates?: TemplateOut[];
  compact?: boolean;
  markConfirmation?: boolean;
  onMarkedConfirmed?: () => void | Promise<void>;
}) {
  const waTemplates = useMemo(() => whatsappTemplates(templates), [templates]);
  const [templateId, setTemplateId] = useState("");
  const selectedTemplate = waTemplates.find((t) => t.id === templateId) || null;
  // Event date, slot and venue come from the person's booking in the Events tab (server side).
  const [fields, setFields] = useState<MessageFields | null>(null);
  useEffect(() => {
    if (compact) return;
    let live = true;
    apiFetch<MessageFields>(`/customers/${customer.id}/message-fields`)
      .then((f) => { if (live) setFields(f); })
      .catch(() => { if (live) setFields(null); });
    return () => { live = false; };
  }, [customer.id, compact]);

  const bookingTokens = useMemo(() => {
    if (!selectedTemplate || !fields) return [];
    const used = Array.from(selectedTemplate.body.matchAll(TOKEN_RE), (m) => m[1]);
    return used.filter((t) => fields.booking_fields.includes(t));
  }, [selectedTemplate, fields]);
  const bookingError = bookingTokens.length && fields?.booking_problem ? fields.booking_problem : null;

  const renderedMessage = selectedTemplate
    ? renderTemplate(fields ? fillFields(selectedTemplate.body, fields.values) : selectedTemplate.body, customer)
    : defaultWhatsAppMessage(customer);
  const [message, setMessage] = useState(renderedMessage);

  useEffect(() => {
    setMessage(renderedMessage);
  }, [renderedMessage]);

  const href = buildWhatsAppLink(customer, message);

  // The chat happens in the staff member's own WhatsApp, so record in the activity feed
  // that it was opened. (Opening it isn't treated as contact by the follow-up automation.)
  function logChatOpened() {
    void apiFetch(`/inbox/customers/${customer.id}/whatsapp-opened`, { method: "POST" }).catch(() => undefined);
  }

  async function markAsConfirmation() {
    if (!markConfirmation || !message.trim()) return;
    await apiFetch(`/inbox/customers/${customer.id}/mark-confirmed`, {
      method: "POST",
      body: JSON.stringify({ channel: "whatsapp" }),
    });
    await onMarkedConfirmed?.();
  }

  if (compact) {
    return href ? (
      <a className="btn" href={href} target="_blank" rel="noreferrer" onClick={logChatOpened}>WhatsApp</a>
    ) : (
      <button className="btn" disabled>WhatsApp</button>
    );
  }

  return (
    <div className="card">
      <div className="cardHeader" style={{ fontWeight: 900 }}>WhatsApp quick message</div>
      <div className="cardBody" style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "grid", gap: 6 }}>
          <div className="muted" style={{ fontSize: 12 }}>Template</div>
          <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            <option value="">Default quick message</option>
            {waTemplates.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>
        {bookingError && (
          <div style={{ padding: 8, borderRadius: 10, fontSize: 12, background: "rgba(245,158,11,0.10)", border: "1px solid rgba(245,158,11,0.35)" }}>
            This template needs booking details that can&apos;t be filled in: {bookingError}. Book them into a slot in the Events tab, or pick another template.
          </div>
        )}
        <div style={{ display: "grid", gap: 6 }}>
          <div className="muted" style={{ fontSize: 12 }}>Editable message</div>
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5} />
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button className="btn" onClick={() => navigator.clipboard?.writeText(message)} disabled={!!bookingError}>Copy message</button>
          {markConfirmation && <button className="btn" type="button" onClick={() => void markAsConfirmation()} disabled={!!bookingError}>Mark confirmed</button>}
          {bookingError ? (
            <button className="btn btnPrimary" disabled>Booking details missing</button>
          ) : href ? (
            <a className="btn btnPrimary" href={href} target="_blank" rel="noreferrer" onClick={logChatOpened}>
              Open WhatsApp
            </a>
          ) : (
            <button className="btn btnPrimary" disabled>No phone number</button>
          )}
        </div>
        <div className="muted" style={{ fontSize: 12 }}>
          The template is summoned into this box first, so staff can edit before opening WhatsApp. Opening WhatsApp alone does not mark the lead confirmed.
        </div>
      </div>
    </div>
  );
}
