"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { CustomerOut, InboxCustomerOut, TemplateOut } from "@/lib/types";
import { buildWhatsAppLink, defaultWhatsAppMessage, renderTemplate, whatsappTemplates } from "@/lib/whatsapp";

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
  const renderedMessage = selectedTemplate ? renderTemplate(selectedTemplate.body, customer) : defaultWhatsAppMessage(customer);
  const [message, setMessage] = useState(renderedMessage);

  useEffect(() => {
    setMessage(renderedMessage);
  }, [renderedMessage]);

  const href = buildWhatsAppLink(customer, message);

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
      <a className="btn" href={href} target="_blank" rel="noreferrer">WhatsApp</a>
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
        <div style={{ display: "grid", gap: 6 }}>
          <div className="muted" style={{ fontSize: 12 }}>Editable message</div>
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5} />
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button className="btn" onClick={() => navigator.clipboard?.writeText(message)}>Copy message</button>
          {markConfirmation && <button className="btn" type="button" onClick={() => void markAsConfirmation()}>Mark confirmed</button>}
          {href ? (
            <a className="btn btnPrimary" href={href} target="_blank" rel="noreferrer">
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
