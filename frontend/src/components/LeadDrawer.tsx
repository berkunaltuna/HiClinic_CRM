"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { AuditLogOut, InboxCustomerOut, ThreadItem, TemplateOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { PIPELINE_STAGES, SERVICE_TAGS, stageLabel } from "@/lib/constants";
import { useToast } from "@/components/Toast";
import { WhatsAppQuickAction } from "@/components/WhatsAppQuickAction";

export function LeadDrawer({
  lead,
  onClose,
  onUpdated,
}: {
  lead: InboxCustomerOut;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const toast = useToast();
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [activity, setActivity] = useState<AuditLogOut[]>([]);
  const [templates, setTemplates] = useState<TemplateOut[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [emailTemplateId, setEmailTemplateId] = useState("");
  const [emailSubject, setEmailSubject] = useState("Appointment Confirmation");
  const [emailBody, setEmailBody] = useState("Hi {{customer_name}},\n\nThis is to confirm your appointment on {{appointment_date}} at {{appointment_time}}.\n\nLocation: {{event_location}}\n\nKind regards,\nHealth Clinic Turkiye");
  const [emailPreviewBusy, setEmailPreviewBusy] = useState(false);
  const [attribution, setAttribution] = useState({
    lead_source: lead.lead_source || "",
    form_name: lead.form_name || "",
    campaign_name: lead.campaign_name || "",
    adset_name: lead.adset_name || "",
    ad_name: lead.ad_name || "",
  });

  const selectedService = useMemo(() => {
    return SERVICE_TAGS.find((t) => (lead.tags || []).includes(t)) || "";
  }, [lead.tags]);

  useEffect(() => {
    setAttribution({
      lead_source: lead.lead_source || "",
      form_name: lead.form_name || "",
      campaign_name: lead.campaign_name || "",
      adset_name: lead.adset_name || "",
      ad_name: lead.ad_name || "",
    });
    let mounted = true;
    (async () => {
      try {
        const [items, activityItems, tpls] = await Promise.all([
          apiFetch<ThreadItem[]>(`/inbox/customers/${lead.id}/thread`),
          apiFetch<AuditLogOut[]>(`/inbox/customers/${lead.id}/activity`).catch(() => [] as AuditLogOut[]),
          apiFetch<TemplateOut[]>(`/templates`).catch(() => [] as TemplateOut[]),
        ]);
        if (!mounted) return;
        setThread(items);
        setActivity(activityItems);
        setTemplates(tpls);
      } catch (err: any) {
        toast.push(err?.message || "Failed to load thread", "error");
      }
    })();
    return () => {
      mounted = false;
    };
  }, [lead.id, toast]);

  async function setStage(stage: string) {
    setBusy(true);
    try {
      await apiFetch<void>(`/inbox/customers/${lead.id}/stage`, {
        method: "POST",
        body: JSON.stringify({ stage }),
      });
      toast.push("Stage updated");
      onUpdated();
    } catch (err: any) {
      toast.push(err?.message || "Failed to update stage", "error");
    } finally {
      setBusy(false);
    }
  }

  async function setFollowupMinutes(minutes: number | null) {
    setBusy(true);
    try {
      await apiFetch<void>(`/inbox/customers/${lead.id}/followup`, {
        method: "POST",
        body: JSON.stringify(minutes ? { minutes_from_now: minutes } : { next_follow_up_at: null }),
      });
      toast.push(minutes ? "Follow-up set" : "Follow-up cleared");
      onUpdated();
    } catch (err: any) {
      toast.push(err?.message || "Failed to set follow-up", "error");
    } finally {
      setBusy(false);
    }
  }

  async function toggleServiceTag(next: string) {
    setBusy(true);
    try {
      // remove all existing service:* tags, then add the selected one (if any)
      for (const t of SERVICE_TAGS) {
        if ((lead.tags || []).includes(t)) {
          await apiFetch<void>(`/inbox/customers/${lead.id}/tags/remove`, {
            method: "POST",
            body: JSON.stringify({ tag: t }),
          });
        }
      }
      if (next) {
        await apiFetch<void>(`/inbox/customers/${lead.id}/tags/add`, {
          method: "POST",
          body: JSON.stringify({ tag: next }),
        });
      }
      toast.push("Patient classification updated");
      onUpdated();
    } catch (err: any) {
      toast.push(err?.message || "Failed to update tag", "error");
    } finally {
      setBusy(false);
    }
  }

  async function addNote() {
    const body = note.trim();
    if (!body) return;
    setBusy(true);
    try {
      await apiFetch<void>(`/customers/${lead.id}/interactions`, {
        method: "POST",
        body: JSON.stringify({
          channel: "meeting",
          direction: "outbound",
          occurred_at: new Date().toISOString(),
          content: body,
          subject: "Internal note",
        }),
      });
      setNote("");
      toast.push("Note added");
      const [items, activityItems] = await Promise.all([
        apiFetch<ThreadItem[]>(`/inbox/customers/${lead.id}/thread`),
        apiFetch<AuditLogOut[]>(`/inbox/customers/${lead.id}/activity`).catch(() => [] as AuditLogOut[]),
      ]);
      setThread(items);
      setActivity(activityItems);
      onUpdated();
    } catch (err: any) {
      toast.push(err?.message || "Failed to add note", "error");
    } finally {
      setBusy(false);
    }
  }


  async function previewConfirmationEmail(templateId?: string) {
    setEmailPreviewBusy(true);
    try {
      const payload: any = templateId
        ? { template_id: templateId }
        : { subject: emailSubject, body: emailBody };
      const preview = await apiFetch<{ subject: string | null; body: string }>(`/customers/${lead.id}/email/confirmation/preview`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setEmailSubject(preview.subject || "Appointment Confirmation");
      setEmailBody(preview.body || "");
    } catch (err: any) {
      toast.push(err?.message || "Failed to preview confirmation email", "error");
    } finally {
      setEmailPreviewBusy(false);
    }
  }

  async function sendConfirmationEmail() {
    if (!emailSubject.trim() || !emailBody.trim()) return;
    setBusy(true);
    try {
      await apiFetch(`/customers/${lead.id}/email/confirmation/send`, {
        method: "POST",
        body: JSON.stringify({ subject: emailSubject, body: emailBody }),
      });
      toast.push("Confirmation email sent");
      onUpdated();
    } catch (err: any) {
      toast.push(err?.message || "Failed to send confirmation email", "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveAttribution() {
    setBusy(true);
    try {
      await apiFetch(`/customers/${lead.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          lead_source: attribution.lead_source.trim() || null,
          form_name: attribution.form_name.trim() || null,
          campaign_name: attribution.campaign_name.trim() || null,
          adset_name: attribution.adset_name.trim() || null,
          ad_name: attribution.ad_name.trim() || null,
        }),
      });
      toast.push("Attribution updated");
      onUpdated();
    } catch (err: any) {
      toast.push(err?.message || "Failed to update attribution", "error");
    } finally {
      setBusy(false);
    }
  }

  function updateAttribution(key: keyof typeof attribution, value: string) {
    setAttribution((prev) => ({ ...prev, [key]: value }));
  }


  return (
    <>
      <div className="drawerOverlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        <div className="drawerHeader">
          <div>
            <div style={{ fontWeight: 900, fontSize: 16 }}>{lead.name}</div>
            <div className="muted" style={{ fontSize: 12 }}>{lead.company || "—"}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Link className="btn" href={`/contacts/${lead.id}`}>Open</Link>
            <button className="btn" onClick={onClose}>Close</button>
          </div>
        </div>

        <div className="drawerBody" style={{ display: "grid", gap: 14 }}>
          <div className="card" style={{ boxShadow: "none" }}>
            <div className="cardBody" style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "grid", gap: 6 }}>
                <div className="muted" style={{ fontSize: 12 }}>Stage</div>
                <select value={lead.stage} onChange={(e) => setStage(e.target.value)} disabled={busy}>
                  {PIPELINE_STAGES.map((s) => (
                    <option key={s} value={s}>{stageLabel(s)}</option>
                  ))}
                </select>
              </div>

              <div style={{ display: "grid", gap: 6 }}>
                <div className="muted" style={{ fontSize: 12 }}>Patient classification</div>
                <select value={selectedService} onChange={(e) => toggleServiceTag(e.target.value)} disabled={busy}>
                  <option value="">—</option>
                  {SERVICE_TAGS.map((t) => (
                    <option key={t} value={t}>{t.replace("service:", "")}</option>
                  ))}
                </select>
              </div>

              <div style={{ display: "grid", gap: 6 }}>
                <div className="muted" style={{ fontSize: 12 }}>Follow-up</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  <button className="btn" disabled={busy} onClick={() => setFollowupMinutes(60)}>+1h</button>
                  <button className="btn" disabled={busy} onClick={() => setFollowupMinutes(60 * 24)}>Tomorrow</button>
                  <button className="btn" disabled={busy} onClick={() => setFollowupMinutes(60 * 24 * 3)}>+3d</button>
                  <button className="btn" disabled={busy} onClick={() => setFollowupMinutes(null)}>Clear</button>
                </div>
                <div className="muted" style={{ fontSize: 12 }}>Current: {fmtDateTime(lead.next_follow_up_at)}</div>
              </div>
            </div>
          </div>

          <div style={{ boxShadow: "none" }}>
            <WhatsAppQuickAction customer={lead} templates={templates} />
          </div>

          <div className="card" style={{ boxShadow: "none" }}>
            <div className="cardHeader" style={{ fontWeight: 800 }}>Confirmation email</div>
            <div className="cardBody" style={{ display: "grid", gap: 8 }}>
              <div style={{ display: "grid", gap: 6 }}>
                <div className="muted" style={{ fontSize: 12 }}>Template</div>
                <select
                  value={emailTemplateId}
                  onChange={(e) => {
                    setEmailTemplateId(e.target.value);
                    if (e.target.value) previewConfirmationEmail(e.target.value);
                  }}
                >
                  <option value="">Custom / manual</option>
                  {templates.filter((t) => (t.channel || "").toLowerCase() === "email").map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </div>
              <input value={emailSubject} onChange={(e) => setEmailSubject(e.target.value)} placeholder="Subject" />
              <textarea value={emailBody} onChange={(e) => setEmailBody(e.target.value)} rows={7} placeholder="Confirmation email body" />
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
                <button className="btn" onClick={() => previewConfirmationEmail()} disabled={emailPreviewBusy}>{emailPreviewBusy ? "Rendering…" : "Render variables"}</button>
                <button className="btn btnPrimary" onClick={sendConfirmationEmail} disabled={busy || !emailSubject.trim() || !emailBody.trim()}>Send confirmation email</button>
              </div>
              <div className="muted" style={{ fontSize: 12 }}>{"Uses variables such as {{customer_name}}, {{appointment_date}}, {{appointment_time}}, {{event_name}}, {{event_location}}, {{doctor_name}}. Event location/address comes from the Event location field."}</div>
            </div>
          </div>

          <div className="card" style={{ boxShadow: "none" }}>
            <div className="cardHeader" style={{ fontWeight: 800 }}>Lead form details</div>
            <div className="cardBody" style={{ display: "grid", gap: 8 }}>
              <div><span className="muted">Treatment: </span><b>{lead.latest_deal?.treatment_interest || "—"}</b></div>
              <div><span className="muted">Preferred day: </span><b>{lead.latest_deal?.preferred_consultation_day || "—"}</b></div>
              <div><span className="muted">Seminar: </span><b>{lead.latest_deal?.seminar_preference || "—"}</b></div>
              <div><span className="muted">Confirmation: </span><b>{lead.latest_deal?.confirmation_sent_at ? `Sent via ${lead.latest_deal.confirmation_channel || "CRM"}` : "Not confirmed"}</b></div>
              <div><span className="muted">Ad: </span><b>{lead.ad_name || "—"}</b></div>
              <div><span className="muted">Campaign: </span><b>{lead.campaign_name || "—"}</b></div>
            </div>
          </div>

          <div className="card" style={{ boxShadow: "none" }}>
            <div className="cardHeader" style={{ fontWeight: 800 }}>Lead attribution</div>
            <div className="cardBody" style={{ display: "grid", gap: 8 }}>
              <input value={attribution.lead_source} onChange={(e) => updateAttribution("lead_source", e.target.value)} placeholder="Lead source, e.g. Facebook" />
              <input value={attribution.form_name} onChange={(e) => updateAttribution("form_name", e.target.value)} placeholder="Form name" />
              <input value={attribution.campaign_name} onChange={(e) => updateAttribution("campaign_name", e.target.value)} placeholder="Campaign name" />
              <input value={attribution.adset_name} onChange={(e) => updateAttribution("adset_name", e.target.value)} placeholder="Ad set name" />
              <input value={attribution.ad_name} onChange={(e) => updateAttribution("ad_name", e.target.value)} placeholder="Ad name" />
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button className="btn" onClick={saveAttribution} disabled={busy}>Save attribution</button>
              </div>
              <div className="muted" style={{ fontSize: 12 }}>Use this when a lead source was entered manually or Make did not send the form/ad/campaign names.</div>
            </div>
          </div>

          <div className="card" style={{ boxShadow: "none" }}>
            <div className="cardHeader" style={{ fontWeight: 800 }}>Quick note</div>
            <div className="cardBody" style={{ display: "grid", gap: 8 }}>
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Add an internal note…" />
              <button className="btn btnPrimary" onClick={addNote} disabled={busy || !note.trim()}>
                Add note
              </button>
            </div>
          </div>

          <div className="card" style={{ boxShadow: "none" }}>
            <div className="cardHeader" style={{ fontWeight: 800 }}>Thread</div>
            <div className="cardBody" style={{ display: "grid", gap: 10 }}>
              {thread.length ? (
                thread.slice().reverse().map((t) => (
                  <div key={t.id} style={{ padding: 10, border: "1px solid var(--border)", borderRadius: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                      <div style={{ fontWeight: 800, fontSize: 12 }}>{t.direction} · {t.channel}</div>
                      <div className="muted" style={{ fontSize: 12 }}>{fmtDateTime(t.occurred_at)}</div>
                    </div>
                    {t.subject && <div style={{ fontWeight: 700, marginTop: 4 }}>{t.subject}</div>}
                    <div className="muted" style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>{t.content || "—"}</div>
                  </div>
                ))
              ) : (
                <div className="muted">No messages yet.</div>
              )}
            </div>
          </div>


          <div className="card" style={{ boxShadow: "none" }}>
            <div className="cardHeader" style={{ fontWeight: 800 }}>Activity</div>
            <div className="cardBody" style={{ display: "grid", gap: 10 }}>
              {activity.length ? (
                activity.map((a) => (
                  <div key={a.id} style={{ padding: 10, border: "1px solid var(--border)", borderRadius: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                      <div style={{ fontWeight: 800, fontSize: 12 }}>{a.action.replaceAll("_", ".")}</div>
                      <div className="muted" style={{ fontSize: 12 }}>{fmtDateTime(a.created_at)}</div>
                    </div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>By {a.actor_email || "system"}</div>
                    {a.after?.content && <div className="muted" style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>{String(a.after.content)}</div>}
                    {a.after?.stage && <div className="muted" style={{ marginTop: 4 }}>Stage: {stageLabel(String(a.before?.stage || "—"))} → {stageLabel(String(a.after.stage))}</div>}
                    {a.after?.tag && <div className="muted" style={{ marginTop: 4 }}>Tag added: {String(a.after.tag)}</div>}
                    {a.before?.tag && <div className="muted" style={{ marginTop: 4 }}>Tag removed: {String(a.before.tag)}</div>}
                  </div>
                ))
              ) : (
                <div className="muted">No activity yet.</div>
              )}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
