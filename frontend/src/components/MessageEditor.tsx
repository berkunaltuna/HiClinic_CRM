"use client";

import { useRef } from "react";
import { fillFields, htmlToText, looksLikeHtml, textToHtml, whatsappToHtml } from "@/lib/messageFormat";

const FIELD_LABELS: Record<string, string> = {
  first_name: "First name",
  customer_name: "Full name",
  name: "Full name",
  appointment_date: "Appointment date",
  appointment_time: "Start time",
  appointment_end_time: "End time",
  appointment_timezone: "Timezone",
  appointment_location: "Location",
  event_name: "Event name",
  event_location: "Event location",
  location: "Location",
  doctor_name: "Doctor",
  clinic_name: "Clinic name",
  clinic_phone: "Clinic phone",
  clinic_email: "Clinic email",
  company: "Company",
};

export const EXAMPLE_VALUES: Record<string, string> = {
  first_name: "Sarah",
  customer_name: "Sarah Thompson",
  name: "Sarah Thompson",
  appointment_date: "Wednesday 4 November 2026",
  appointment_time: "10:00",
  appointment_end_time: "10:30",
  appointment_timezone: "UK time, GMT",
  appointment_location: "Health Clinic, 1 Harley Street, London",
  event_name: "London consultation day",
  event_location: "Health Clinic, 1 Harley Street, London",
  location: "Health Clinic, 1 Harley Street, London",
  doctor_name: "Dr Example",
  clinic_name: "Health Clinic",
  clinic_phone: "+44 20 7946 0000",
  clinic_email: "hello@healthclinic.example",
  company: "",
};

/**
 * Plain-text message editor: write normally, blank line = new paragraph,
 * *text* = bold. Formatting into an email happens automatically when it's sent.
 */
export function MessageEditor({
  value,
  onChange,
  channel,
  fields,
  examples = {},
  disabled = false,
  rows = 8,
  id,
}: {
  value: string;
  onChange: (v: string) => void;
  channel: "email" | "whatsapp" | string;
  fields: string[];
  examples?: Record<string, string>;
  disabled?: boolean;
  rows?: number;
  id?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const isHtml = channel === "email" && looksLikeHtml(value);
  const sample = { ...EXAMPLE_VALUES, ...Object.fromEntries(Object.entries(examples).filter(([, v]) => v)) };

  function edit(transform: (before: string, selected: string, after: string) => { text: string; cursor: number }) {
    const el = ref.current;
    if (!el) return;
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const { text, cursor } = transform(value.slice(0, start), value.slice(start, end), value.slice(end));
    onChange(text);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(cursor, cursor);
    });
  }

  const bold = () =>
    edit((before, selected, after) => {
      const inner = selected || "bold text";
      return { text: `${before}*${inner}*${after}`, cursor: before.length + inner.length + 2 };
    });

  const insertField = (field: string) =>
    edit((before, _selected, after) => {
      const token = `{{${field}}}`;
      return { text: before + token + after, cursor: before.length + token.length };
    });

  const filled = fillFields(value, sample);
  const previewHtml = channel === "email" ? (isHtml ? filled : textToHtml(filled)) : "";

  return (
    <div style={{ display: "grid", gap: 6 }}>
      {!disabled && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <button className="btn" type="button" onClick={bold} title="Make the selected text bold" style={{ padding: "4px 10px", fontWeight: 800 }}>
            B
          </button>
          <select
            value=""
            onChange={(e) => { if (e.target.value) insertField(e.target.value); }}
            style={{ width: "auto", padding: "4px 8px" }}
            aria-label="Insert a field"
          >
            <option value="">Insert field…</option>
            {fields.map((f) => (
              <option key={f} value={f}>{FIELD_LABELS[f] || f}</option>
            ))}
          </select>
          <span className="muted" style={{ fontSize: 12 }}>Blank line = new paragraph · *text* = bold</span>
        </div>
      )}

      {isHtml && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", padding: 8, borderRadius: 10, background: "rgba(245,158,11,0.10)", border: "1px solid rgba(245,158,11,0.35)", fontSize: 12 }}>
          <span>This message is written in HTML.</span>
          {!disabled && (
            <button className="btn" type="button" style={{ padding: "4px 10px" }} onClick={() => onChange(htmlToText(value))}>
              Convert to plain text
            </button>
          )}
        </div>
      )}

      <textarea
        ref={ref}
        id={id}
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        style={{ width: "100%", boxSizing: "border-box", fontFamily: "inherit" }}
      />

      <div style={{ display: "grid", gap: 4 }}>
        <span className="muted" style={{ fontSize: 12 }}>Preview with example details</span>
        {channel === "email" ? (
          <iframe
            title="Email preview"
            sandbox=""
            srcDoc={`<!doctype html><meta charset="utf-8"><body style="margin:12px;background:#fff">${previewHtml}</body>`}
            style={{ width: "100%", height: 220, border: "1px solid var(--border)", borderRadius: 10, background: "#fff" }}
          />
        ) : (
          <div style={{ background: "rgba(136,194,199,0.15)", borderRadius: 10, padding: 10 }}>
            <div
              style={{ background: "#dcf8c6", color: "#102a12", padding: "8px 10px", borderRadius: "10px 10px 2px 10px", maxWidth: "90%", marginLeft: "auto", fontSize: 13 }}
              dangerouslySetInnerHTML={{ __html: whatsappToHtml(filled) }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
