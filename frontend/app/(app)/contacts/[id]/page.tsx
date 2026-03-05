"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { CustomerOut, DealOut, ThreadItem, TemplateOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { PIPELINE_STAGES, SERVICE_TAGS, stageLabel } from "@/lib/constants";
import { useToast } from "@/components/Toast";

export default function ContactDetailPage() {
  const toast = useToast();
  const params = useParams();
  const id = String(params.id);

  const [c, setC] = useState<CustomerOut | null>(null);
  const [deals, setDeals] = useState<DealOut[]>([]);
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [templates, setTemplates] = useState<TemplateOut[]>([]);
  const [busy, setBusy] = useState(true);
  const [note, setNote] = useState("");

  const [emailSubject, setEmailSubject] = useState("Hi {{customer_name}}");
  const [emailBody, setEmailBody] = useState("");
  const [emailTemplateId, setEmailTemplateId] = useState("");

  const service = useMemo(() => {
    if (!c) return "";
    return SERVICE_TAGS.find((t) => (c.tag_names || []).includes(t)) || "";
  }, [c]);

  async function load() {
    setBusy(true);
    try {
      const [cc, dd, tt, tpl] = await Promise.all([
        apiFetch<CustomerOut>(`/customers/${id}`),
        apiFetch<DealOut[]>(`/customers/${id}/deals`),
        apiFetch<ThreadItem[]>(`/inbox/customers/${id}/thread`),
        apiFetch<TemplateOut[]>(`/templates`).catch(() => [] as TemplateOut[]),
      ]);
      setC(cc);
      setDeals(dd);
      setThread(tt);
      setTemplates(tpl);
    } catch (err: any) {
      toast.push(err?.message || "Failed to load contact", "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function setStage(stage: string) {
    try {
      await apiFetch<void>(`/inbox/customers/${id}/stage`, { method: "POST", body: JSON.stringify({ stage }) });
      toast.push("Stage updated");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to update stage", "error");
    }
  }

  async function setServiceTag(next: string) {
    if (!c) return;
    try {
      for (const t of SERVICE_TAGS) {
        if ((c.tag_names || []).includes(t)) {
          await apiFetch<void>(`/inbox/customers/${id}/tags/remove`, { method: "POST", body: JSON.stringify({ tag: t }) });
        }
      }
      if (next) {
        await apiFetch<void>(`/inbox/customers/${id}/tags/add`, { method: "POST", body: JSON.stringify({ tag: next }) });
      }
      toast.push("Classification updated");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to update tags", "error");
    }
  }

  async function addNote() {
    const body = note.trim();
    if (!body) return;
    try {
      await apiFetch<void>(`/customers/${id}/interactions`, {
        method: "POST",
        body: JSON.stringify({
          channel: "whatsapp",
          direction: "outbound",
          occurred_at: new Date().toISOString(),
          content: body,
          subject: null,
        }),
      });
      setNote("");
      toast.push("Note added");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to add note", "error");
    }
  }

  async function sendEmailNow() {
    if (!c) return;
    const subject = emailSubject.trim();
    const body = emailBody.trim();
    if (!subject || !body) return;
    try {
      await apiFetch<{ provider_message_id: string; interaction_id: string }>(`/customers/${id}/email/send`, {
        method: "POST",
        body: JSON.stringify({ subject, body }),
      });
      setEmailBody("");
      toast.push("Email sent");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to send email", "error");
    }
  }

  async function queueEmailTemplate() {
    if (!emailTemplateId) return;
    try {
      await apiFetch<{ id: string; status: string }>(`/inbox/customers/${id}/send-template`, {
        method: "POST",
        body: JSON.stringify({ template_id: emailTemplateId, channel: "email" }),
      });
      toast.push("Queued email template");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to queue template", "error");
    }
  }

  const emailTemplates = useMemo(() => templates.filter((t) => (t.channel || "").toLowerCase() === "email"), [templates]);

  return (
    <div className="stack">
      <Topbar title="Contact" />

      {busy && !c ? (
        <div className="card" style={{ padding: 16 }}>Loading…</div>
      ) : !c ? (
        <div className="card" style={{ padding: 16 }}>Not found.</div>
      ) : (
        <div className="split">
          <section className="stack">
            <div className="card">
              <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontWeight: 900, fontSize: 16 }}>{c.name}</div>
                  <div className="muted" style={{ fontSize: 12 }}>{c.company || "—"}</div>
                </div>
                <span className="badge">{c.stage}</span>
              </div>
              <div className="cardBody" style={{ display: "grid", gap: 10 }}>
                <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <div>
                    <div className="muted" style={{ fontSize: 12 }}>Email</div>
                    <div style={{ fontWeight: 700 }}>{c.email || "—"}</div>
                  </div>
                  <div>
                    <div className="muted" style={{ fontSize: 12 }}>Phone</div>
                    <div style={{ fontWeight: 700 }}>{c.phone || "—"}</div>
                  </div>
                </div>

                <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <div>
                    <div className="muted" style={{ fontSize: 12 }}>Follow-up</div>
                    <div style={{ fontWeight: 700 }}>{fmtDateTime(c.next_follow_up_at)}</div>
                  </div>
                  <div>
                    <div className="muted" style={{ fontSize: 12 }}>Patient classification</div>
                    <select value={service} onChange={(e) => setServiceTag(e.target.value)}>
                      <option value="">—</option>
                      {SERVICE_TAGS.map((t) => (
                        <option key={t} value={t}>{t.replace("service:", "")}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Stage</div>
                  <select value={c.stage} onChange={(e) => setStage(e.target.value)}>
                    {PIPELINE_STAGES.map((s) => (
                      <option key={s} value={s}>{stageLabel(s)}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Tags</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                    {(c.tag_names || []).map((t) => (
                      <span key={t} className="chip">{t}</span>
                    ))}
                    {!(c.tag_names || []).length && <span className="muted">—</span>}
                  </div>
                </div>
              </div>
            </div>

            <div className="card">
              <div className="cardHeader" style={{ fontWeight: 900 }}>Deals</div>
              <div className="cardBody">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deals.map((d) => (
                      <tr key={d.id}>
                        <td style={{ fontWeight: 800 }}>{d.amount}</td>
                        <td className="muted">{d.status}</td>
                        <td className="muted">{fmtDateTime(d.updated_at)}</td>
                      </tr>
                    ))}
                    {!deals.length && (
                      <tr>
                        <td colSpan={3} className="muted">No deals yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section className="stack">
            <div className="card">
              <div className="cardHeader" style={{ fontWeight: 900 }}>Add note</div>
              <div className="cardBody" style={{ display: "grid", gap: 8 }}>
                <textarea rows={4} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note (saved as outbound interaction)…" />
                <button className="btn btnPrimary" onClick={addNote} disabled={!note.trim()}>Add note</button>
              </div>
            </div>

            <div className="card">
              <div className="cardHeader" style={{ fontWeight: 900 }}>Send email</div>
              <div className="cardBody" style={{ display: "grid", gap: 10 }}>
                <div style={{ display: "grid", gap: 6 }}>
                  <div className="muted" style={{ fontSize: 12 }}>From template</div>
                  <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <select value={emailTemplateId} onChange={(e) => setEmailTemplateId(e.target.value)} style={{ flex: 1 }}>
                      <option value="">Select email template…</option>
                      {emailTemplates.map((t) => (
                        <option key={t.id} value={t.id}>{t.name}</option>
                      ))}
                    </select>
                    <button className="btn" onClick={queueEmailTemplate} disabled={!emailTemplateId}>Queue</button>
                  </div>
                </div>

                <div style={{ borderTop: "1px solid var(--border)", margin: "6px 0" }} />

                <div style={{ display: "grid", gap: 6 }}>
                  <div className="muted" style={{ fontSize: 12 }}>Manual email</div>
                  <input value={emailSubject} onChange={(e) => setEmailSubject(e.target.value)} placeholder="Subject…" />
                  <textarea rows={6} value={emailBody} onChange={(e) => setEmailBody(e.target.value)} placeholder="Write your email…" />
                  <button className="btn btnPrimary" onClick={sendEmailNow} disabled={!emailSubject.trim() || !emailBody.trim()}>Send email</button>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Tip: merge fields supported, e.g. <b>{"{{customer_name}}"}</b>
                  </div>
                </div>
              </div>
            </div>

            <div className="card">
              <div className="cardHeader" style={{ fontWeight: 900 }}>Thread</div>
              <div className="cardBody" style={{ display: "grid", gap: 10, maxHeight: 520, overflow: "auto" }}>
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
          </section>
        </div>
      )}
    </div>
  );
}
