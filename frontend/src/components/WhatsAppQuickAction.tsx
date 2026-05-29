"use client";

import { useMemo, useState } from "react";
import type { CustomerOut, InboxCustomerOut, TemplateOut } from "@/lib/types";
import { buildWhatsAppLink, defaultWhatsAppMessage, renderTemplate, whatsappTemplates } from "@/lib/whatsapp";

export function WhatsAppQuickAction({
  customer,
  templates = [],
  compact = false,
}: {
  customer: CustomerOut | InboxCustomerOut;
  templates?: TemplateOut[];
  compact?: boolean;
}) {
  const waTemplates = useMemo(() => whatsappTemplates(templates), [templates]);
  const [templateId, setTemplateId] = useState("");
  const selectedTemplate = waTemplates.find((t) => t.id === templateId) || null;
  const message = selectedTemplate ? renderTemplate(selectedTemplate.body, customer) : defaultWhatsAppMessage(customer);
  const href = buildWhatsAppLink(customer, message);

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
          <div className="muted" style={{ fontSize: 12 }}>Preview</div>
          <textarea value={message} readOnly rows={5} />
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button className="btn" onClick={() => navigator.clipboard?.writeText(message)}>Copy message</button>
          {href ? (
            <a className="btn btnPrimary" href={href} target="_blank" rel="noreferrer">Open WhatsApp</a>
          ) : (
            <button className="btn btnPrimary" disabled>No phone number</button>
          )}
        </div>
        <div className="muted" style={{ fontSize: 12 }}>
          Opens WhatsApp with the selected message pre-filled. You can still edit it before sending.
        </div>
      </div>
    </div>
  );
}
