"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { AutomationKey, AutomationSendOut, AutomationsOverview, MessagingAutomationOut, TemplateOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import { AutomationSendStatus, automationLabel, slotText } from "@/components/AutomationSendStatus";
import { MessageEditor } from "@/components/MessageEditor";

const AUTOMATION_COPY: Record<AutomationKey, { title: string; description: string }> = {
  appointment_confirmation: {
    title: "Appointment confirmation",
    description:
      "Sends a confirmation when a booking is created in the Events tab (status booked/confirmed). The date, time and location come from the booked slot, shown in UK time. Bookings with missing or unclear slot details are held for review instead of being sent.",
  },
  lead_followup: {
    title: "Follow up with leads who haven't booked",
    description:
      "Sends one follow-up after the delay to leads still at stage New with no appointment and no logged outbound call, message or WhatsApp chat. Eligibility is checked again at send time, so booking or contacting the lead first stops it.",
  },
};

const FIELD = { display: "grid", gap: 4 } as const;
const FULL = { width: "100%", boxSizing: "border-box" } as const;

function TemplateEditor({ template, canEdit, onSaved, fields, examples }: { template: TemplateOut; canEdit: boolean; onSaved: () => Promise<void>; fields: string[]; examples: Record<string, string> }) {
  const toast = useToast();
  const [subject, setSubject] = useState(template.subject || "");
  const [body, setBody] = useState(template.body);
  const [sid, setSid] = useState(template.provider_template_id || "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setSubject(template.subject || "");
    setBody(template.body);
    setSid(template.provider_template_id || "");
  }, [template]);

  const dirty = subject !== (template.subject || "") || body !== template.body || sid !== (template.provider_template_id || "");

  async function save() {
    setSaving(true);
    try {
      const payload: Record<string, string> = { body };
      if (template.channel === "email") payload.subject = subject;
      else payload.provider_template_id = sid;
      await apiFetch<TemplateOut>(`/templates/${template.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      toast.push(`Template '${template.name}' saved`);
      await onSaved();
    } catch (err: any) {
      toast.push(err?.message || "Failed to save template", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 6, padding: 10, border: "1px solid var(--border)", borderRadius: 12 }}>
      {template.channel === "email" ? (
        <div style={FIELD}>
          <span className="muted" style={{ fontSize: 12 }}>Subject (no clinical details)</span>
          <input className="formField" value={subject} onChange={(e) => setSubject(e.target.value)} disabled={!canEdit} style={FULL} />
        </div>
      ) : (
        <div style={FIELD}>
          <span className="muted" style={{ fontSize: 12 }}>Twilio Content SID of the approved WhatsApp template</span>
          <input className="formField" value={sid} onChange={(e) => setSid(e.target.value)} placeholder="HX…" disabled={!canEdit} style={FULL} />
        </div>
      )}
      <div style={FIELD}>
        <span className="muted" style={{ fontSize: 12 }}>Message</span>
        <MessageEditor value={body} onChange={setBody} channel={template.channel} fields={fields} examples={examples} disabled={!canEdit} rows={template.channel === "email" ? 9 : 5} />
      </div>
      {canEdit && (
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          {dirty && <button className="btn" type="button" onClick={() => { setSubject(template.subject || ""); setBody(template.body); setSid(template.provider_template_id || ""); }}>Reset</button>}
          <button className="btn btnPrimary" type="button" disabled={!dirty || saving || !body.trim()} onClick={() => void save()}>{saving ? "Saving…" : "Save template"}</button>
        </div>
      )}
    </div>
  );
}

function TemplatePicker({
  label,
  channel,
  value,
  templates,
  canEdit,
  fields,
  examples,
  onChange,
  onTemplateSaved,
}: {
  label: string;
  channel: "email" | "whatsapp";
  value: string | null;
  templates: TemplateOut[];
  canEdit: boolean;
  fields: string[];
  examples: Record<string, string>;
  onChange: (id: string | null) => void;
  onTemplateSaved: () => Promise<void>;
}) {
  const options = templates.filter((t) => t.channel === channel);
  const selected = options.find((t) => t.id === value) || null;
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div style={FIELD}>
        <span className="muted" style={{ fontSize: 12 }}>{label}</span>
        <select value={value || ""} onChange={(e) => onChange(e.target.value || null)} disabled={!canEdit} style={FULL}>
          <option value="">Select template…</option>
          {options.map((t) => (
            <option key={t.id} value={t.id}>{t.name}{t.language && t.language !== "und" ? ` (${t.language})` : ""}</option>
          ))}
        </select>
      </div>
      {selected && <TemplateEditor template={selected} canEdit={canEdit} onSaved={onTemplateSaved} fields={fields} examples={examples} />}
    </div>
  );
}

function AutomationCard({
  automation,
  templates,
  canEdit,
  examples,
  onSaved,
}: {
  automation: MessagingAutomationOut;
  templates: TemplateOut[];
  canEdit: boolean;
  examples: Record<string, string>;
  onSaved: () => Promise<void>;
}) {
  const toast = useToast();
  const [draft, setDraft] = useState(automation);
  const [saving, setSaving] = useState(false);
  useEffect(() => setDraft(automation), [automation]);

  const copy = AUTOMATION_COPY[automation.key];
  const isConfirmation = automation.key === "appointment_confirmation";
  const dirty = JSON.stringify(draft) !== JSON.stringify(automation);

  function patch(p: Partial<MessagingAutomationOut>) {
    setDraft((d) => ({ ...d, ...p }));
  }

  async function save(overrides: Partial<MessagingAutomationOut> = {}) {
    const next = { ...draft, ...overrides };
    setSaving(true);
    try {
      await apiFetch<AutomationsOverview>(`/automations/${automation.key}`, {
        method: "PATCH",
        body: JSON.stringify({
          is_enabled: next.is_enabled,
          email_enabled: next.email_enabled,
          whatsapp_enabled: next.whatsapp_enabled,
          email_template_id: next.email_template_id,
          whatsapp_template_id: next.whatsapp_template_id,
          send_updates: next.send_updates,
          update_email_template_id: next.update_email_template_id,
          update_whatsapp_template_id: next.update_whatsapp_template_id,
          delay_minutes: next.delay_minutes,
          max_per_run: next.max_per_run,
        }),
      });
      toast.push(`${copy.title} ${overrides.is_enabled === undefined ? "saved" : overrides.is_enabled ? "switched on" : "paused"}`);
      await onSaved();
    } catch (err: any) {
      toast.push(err?.message || "Failed to save automation", "error");
    } finally {
      setSaving(false);
    }
  }

  const delayHours = Math.round((draft.delay_minutes / 60) * 100) / 100;

  return (
    <section className="card">
      <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div>
          <div style={{ fontWeight: 900 }}>{copy.title}</div>
          <div className="muted" style={{ fontSize: 12 }}>
            {automation.is_enabled ? `On since ${fmtDateTime(automation.active_since)}` : "Paused"}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="badge" style={{ background: automation.is_enabled ? "rgba(16,185,129,0.15)" : undefined }}>{automation.is_enabled ? "On" : "Paused"}</span>
          {canEdit && (
            <button className={`btn ${automation.is_enabled ? "" : "btnPrimary"}`} type="button" disabled={saving} onClick={() => void save({ is_enabled: !automation.is_enabled })}>
              {automation.is_enabled ? "Pause" : "Switch on"}
            </button>
          )}
        </div>
      </div>
      <div className="cardBody" style={{ display: "grid", gap: 12 }}>
        <div className="muted" style={{ fontSize: 13 }}>{copy.description}</div>

        {!!automation.warnings.length && (
          <div style={{ display: "grid", gap: 4, padding: 10, borderRadius: 12, background: "rgba(245,158,11,0.10)", border: "1px solid rgba(245,158,11,0.35)" }}>
            {automation.warnings.map((w) => (
              <div key={w} style={{ fontSize: 13 }}>⚠ {w}</div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={draft.email_enabled} onChange={(e) => patch({ email_enabled: e.target.checked })} disabled={!canEdit} /> Email
          </label>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={draft.whatsapp_enabled} onChange={(e) => patch({ whatsapp_enabled: e.target.checked })} disabled={!canEdit} /> WhatsApp
          </label>
          {!isConfirmation && (
            <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
              Send after
              <input
                className="formField"
                type="number"
                min={0.25}
                max={720}
                step={0.25}
                value={delayHours}
                onChange={(e) => patch({ delay_minutes: Math.round(Number(e.target.value) * 60) })}
                disabled={!canEdit}
                style={{ width: 90 }}
              />
              hours after the lead is created
            </label>
          )}
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            Send to
            <select
              value={draft.max_per_run ?? ""}
              onChange={(e) => patch({ max_per_run: e.target.value ? Number(e.target.value) : null })}
              disabled={!canEdit}
              style={{ width: "auto" }}
            >
              {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              <option value="">all</option>
            </select>
            {draft.max_per_run ? `patient${draft.max_per_run === 1 ? "" : "s"} per check (about once a minute); the rest wait in line` : "patients due at once"}
          </label>
          {isConfirmation && (
            <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={draft.send_updates} onChange={(e) => patch({ send_updates: e.target.checked })} disabled={!canEdit} />
              Send an updated confirmation when a confirmed booking is moved to another slot
            </label>
          )}
        </div>

        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {draft.email_enabled && (
            <TemplatePicker label="Email template" channel="email" value={draft.email_template_id} templates={templates} canEdit={canEdit} fields={automation.supported_fields} examples={examples}
              onChange={(id) => patch({ email_template_id: id })} onTemplateSaved={onSaved} />
          )}
          {draft.whatsapp_enabled && (
            <TemplatePicker label="WhatsApp template" channel="whatsapp" value={draft.whatsapp_template_id} templates={templates} canEdit={canEdit} fields={automation.supported_fields} examples={examples}
              onChange={(id) => patch({ whatsapp_template_id: id })} onTemplateSaved={onSaved} />
          )}
          {isConfirmation && draft.send_updates && draft.email_enabled && (
            <TemplatePicker label="Rescheduled: email template" channel="email" value={draft.update_email_template_id} templates={templates} canEdit={canEdit} fields={automation.supported_fields} examples={examples}
              onChange={(id) => patch({ update_email_template_id: id })} onTemplateSaved={onSaved} />
          )}
          {isConfirmation && draft.send_updates && draft.whatsapp_enabled && (
            <TemplatePicker label="Rescheduled: WhatsApp template" channel="whatsapp" value={draft.update_whatsapp_template_id} templates={templates} canEdit={canEdit} fields={automation.supported_fields} examples={examples}
              onChange={(id) => patch({ update_whatsapp_template_id: id })} onTemplateSaved={onSaved} />
          )}
        </div>

        <div className="muted" style={{ fontSize: 12 }}>
          Fields you can use: {automation.supported_fields.map((f) => <code key={f} style={{ marginRight: 6 }}>{`{{${f}}}`}</code>)}
          <br />
          Write messages as normal text: emails are laid out automatically when sent. For WhatsApp, enter the approved template&apos;s Twilio Content SID. Its numbered placeholders are filled in the order the fields appear in the message above.
        </div>

        {canEdit && (
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            {dirty && <button className="btn" type="button" onClick={() => setDraft(automation)}>Reset</button>}
            <button className="btn btnPrimary" type="button" disabled={!dirty || saving} onClick={() => void save()}>{saving ? "Saving…" : "Save settings"}</button>
          </div>
        )}
      </div>
    </section>
  );
}

function SendsTable({ items, onDismiss, emptyText }: { items: AutomationSendOut[]; onDismiss?: (s: AutomationSendOut) => void; emptyText: string }) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Patient</th>
          <th>Automation</th>
          <th>Channel</th>
          <th>Outcome</th>
          <th>When</th>
          {onDismiss && <th />}
        </tr>
      </thead>
      <tbody>
        {items.map((s) => (
          <tr key={s.id}>
            <td>
              <Link href={`/contacts/${s.customer_id}`} style={{ fontWeight: 800 }}>{s.customer_name || "Unknown"}</Link>
              {s.slot_starts_at && <div className="muted" style={{ fontSize: 12 }}>Slot: {slotText(s.slot_starts_at, s.slot_ends_at)}</div>}
            </td>
            <td className="muted">{automationLabel(s)}</td>
            <td className="muted">{s.channel || "—"}</td>
            <td><AutomationSendStatus send={s} /></td>
            <td className="muted" style={{ whiteSpace: "nowrap" }}>
              {fmtDateTime(s.sent_at || s.attempted_at || s.created_at)}
            </td>
            {onDismiss && (
              <td><button className="btn" type="button" onClick={() => onDismiss(s)}>Dismiss</button></td>
            )}
          </tr>
        ))}
        {!items.length && (
          <tr><td colSpan={onDismiss ? 6 : 5} className="muted">{emptyText}</td></tr>
        )}
      </tbody>
    </table>
  );
}

export default function WorkflowsPage() {
  const toast = useToast();
  const [overview, setOverview] = useState<AutomationsOverview | null>(null);
  const [templates, setTemplates] = useState<TemplateOut[]>([]);
  const [attention, setAttention] = useState<AutomationSendOut[]>([]);
  const [recent, setRecent] = useState<AutomationSendOut[]>([]);
  const [role, setRole] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [running, setRunning] = useState(false);
  const [clinic, setClinic] = useState({ clinic_name: "", contact_phone: "", contact_email: "" });
  const [savingClinic, setSavingClinic] = useState(false);
  const canEdit = role === "admin";

  async function load() {
    setBusy(true);
    try {
      const [ov, tpl, att, rec, me] = await Promise.all([
        apiFetch<AutomationsOverview>("/automations"),
        apiFetch<TemplateOut[]>("/templates"),
        apiFetch<AutomationSendOut[]>("/automations/sends?attention=true&limit=100"),
        apiFetch<AutomationSendOut[]>("/automations/sends?limit=100"),
        apiFetch<{ role: string }>("/auth/me").catch(() => null),
      ]);
      setOverview(ov);
      setTemplates(tpl);
      setAttention(att);
      setRecent(rec);
      setRole(me?.role || null);
      setClinic({ clinic_name: ov.clinic.clinic_name, contact_phone: ov.clinic.contact_phone || "", contact_email: ov.clinic.contact_email || "" });
    } catch (err: any) {
      toast.push(err?.message || "Failed to load automations", "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function saveClinic() {
    setSavingClinic(true);
    try {
      await apiFetch<AutomationsOverview>("/automations/clinic", {
        method: "PUT",
        body: JSON.stringify({ clinic_name: clinic.clinic_name, contact_phone: clinic.contact_phone || null, contact_email: clinic.contact_email || null }),
      });
      toast.push("Clinic contact details saved");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to save clinic details", "error");
    } finally {
      setSavingClinic(false);
    }
  }

  async function runNow() {
    setRunning(true);
    try {
      await apiFetch("/automations/run", { method: "POST" });
      toast.push("Automations checked");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to run automations", "error");
    } finally {
      setRunning(false);
    }
  }

  async function dismiss(s: AutomationSendOut) {
    try {
      await apiFetch(`/automations/sends/${s.id}/dismiss`, { method: "POST" });
      toast.push("Dismissed");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to dismiss", "error");
    }
  }

  const clinicDirty = useMemo(() => {
    if (!overview) return false;
    const c = overview.clinic;
    return clinic.clinic_name !== c.clinic_name || clinic.contact_phone !== (c.contact_phone || "") || clinic.contact_email !== (c.contact_email || "");
  }, [clinic, overview]);

  return (
    <div className="stack">
      <Topbar
        title="Automations"
        subtitle="Appointment confirmations and lead follow-ups"
        right={
          <div style={{ display: "flex", gap: 8 }}>
            {canEdit && <button className="btn" onClick={() => void runNow()} disabled={running}>{running ? "Checking…" : "Run check now"}</button>}
            <button className="btn" onClick={() => void load()} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>
          </div>
        }
      />

      {overview && !canEdit && (
        <div className="card" style={{ padding: 12 }}>
          <span className="muted">Only administrators can change automation settings and templates.</span>
        </div>
      )}

      {!!overview?.warnings.length && (
        <div className="card" style={{ padding: 12, borderLeft: "4px solid #f59e0b", display: "grid", gap: 4 }}>
          {overview.warnings.map((w) => <div key={w} style={{ fontSize: 13 }}>⚠ {w}</div>)}
        </div>
      )}

      <section className="card">
        <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
          <b>Needs attention</b>
          <span className="muted">Failed sends, messages held for review and bookings where the patient got no confirmation on any channel. Failed sends are never retried automatically.</span>
        </div>
        <div className="cardBody" style={{ overflowX: "auto" }}>
          <SendsTable items={attention} onDismiss={(s) => void dismiss(s)} emptyText="Nothing needs attention." />
        </div>
      </section>

      <section className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>Clinic contact details</div>
        <div className="cardBody grid" style={{ gap: 10 }}>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
            <label>Clinic name<input className="formField" value={clinic.clinic_name} onChange={(e) => setClinic({ ...clinic, clinic_name: e.target.value })} disabled={!canEdit} /></label>
            <label>Phone<input className="formField" value={clinic.contact_phone} onChange={(e) => setClinic({ ...clinic, contact_phone: e.target.value })} placeholder="+44…" disabled={!canEdit} /></label>
            <label>Email<input className="formField" type="email" value={clinic.contact_email} onChange={(e) => setClinic({ ...clinic, contact_email: e.target.value })} disabled={!canEdit} /></label>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <span className="muted">Used as {"{{clinic_name}}"}, {"{{clinic_phone}}"} and {"{{clinic_email}}"} so patients have a way to reach the clinic.</span>
            {canEdit && <button className="btn btnPrimary" type="button" disabled={!clinicDirty || savingClinic} onClick={() => void saveClinic()}>{savingClinic ? "Saving…" : "Save"}</button>}
          </div>
        </div>
      </section>

      {overview?.automations.map((a) => (
        <AutomationCard
          key={a.key}
          automation={a}
          templates={templates}
          canEdit={canEdit}
          examples={{ clinic_name: overview.clinic.clinic_name, clinic_phone: overview.clinic.contact_phone || "", clinic_email: overview.clinic.contact_email || "" }}
          onSaved={load}
        />
      ))}

      <section className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>Recent automation activity</div>
        <div className="cardBody" style={{ overflowX: "auto" }}>
          <SendsTable items={recent} emptyText="No automated messages yet." />
        </div>
      </section>
    </div>
  );
}
