"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { InboxCustomerOut, ThreadItem, TemplateOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import { WhatsAppQuickAction } from "@/components/WhatsAppQuickAction";

export default function InboxPage() {
  const toast = useToast();
  const [customers, setCustomers] = useState<InboxCustomerOut[]>([]);
  const [selected, setSelected] = useState<InboxCustomerOut | null>(null);
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [templates, setTemplates] = useState<TemplateOut[]>([]);
  const [busy, setBusy] = useState(true);
  const [bucket, setBucket] = useState("");
  const [q, setQ] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [channel, setChannel] = useState<"email" | "whatsapp">("email");
  const [composerMode, setComposerMode] = useState<"send" | "queue">("send");
  const [body, setBody] = useState("");
  const [subject, setSubject] = useState("Hi {{customer_name}}");
  const [templateId, setTemplateId] = useState("");
  const [delayMinutes, setDelayMinutes] = useState("");
  const [cancelOnInbound, setCancelOnInbound] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);

  async function loadList() {
    setBusy(true);
    try {
      const qs = new URLSearchParams();
      qs.set("limit", "200");
      if (bucket) qs.set("bucket", bucket);
      if (q.trim()) qs.set("q", q.trim());
      const data = await apiFetch<InboxCustomerOut[]>(`/inbox/customers?${qs.toString()}`);
      setCustomers(data);
      setSelected((prev) => {
        if (!prev) return data[0] || null;
        return data.find((x) => x.id === prev.id) || data[0] || null;
      });
    } catch (err: any) {
      toast.push(err?.message || "Failed to load inbox", "error");
    } finally {
      setBusy(false);
    }
  }

  async function loadThread(id: string) {
    try {
      const items = await apiFetch<ThreadItem[]>(`/inbox/customers/${id}/thread`);
      setThread(items);
    } catch (err: any) {
      toast.push(err?.message || "Failed to load thread", "error");
    }
  }

  async function loadTemplates() {
    try {
      const t = await apiFetch<TemplateOut[]>("/templates");
      setTemplates(t);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    loadList();
    loadTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selected) loadThread(selected.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id]);

  const channelTemplates = useMemo(() => templates.filter((t) => (t.channel || "").toLowerCase() === channel), [templates, channel]);
  const recipients = useMemo(() => {
    const ids = Array.from(selectedIds);
    if (ids.length) return ids;
    return selected ? [selected.id] : [];
  }, [selectedIds, selected]);

  function toggleSelected(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function clearSelected() {
    setSelectedIds(new Set());
  }

  async function sendNow() {
    if (!recipients.length) return toast.push("Select at least one lead", "error");
    const trimmedBody = body.trim();
    if (!trimmedBody) return toast.push("Message body is required", "error");

    setActionBusy(true);
    try {
      if (channel === "email") {
        const trimmedSubject = subject.trim();
        if (!trimmedSubject) return toast.push("Email subject is required", "error");
        await Promise.all(recipients.map((id) => apiFetch(`/customers/${id}/email/send`, {
          method: "POST",
          body: JSON.stringify({ subject: trimmedSubject, body: trimmedBody }),
        })));
        toast.push(recipients.length > 1 ? "Bulk email sent" : "Email sent");
      } else {
        await Promise.all(recipients.map((id) => apiFetch(`/inbox/customers/${id}/send-text`, {
          method: "POST",
          body: JSON.stringify({ body: trimmedBody, channel: "whatsapp" }),
        })));
        toast.push(recipients.length > 1 ? "Bulk WhatsApp queued" : "WhatsApp queued");
      }
      setBody("");
      if (selected) await loadThread(selected.id);
      await loadList();
    } catch (err: any) {
      toast.push(err?.message || "Failed to send", "error");
    } finally {
      setActionBusy(false);
    }
  }

  async function queueTemplate() {
    if (!recipients.length) return toast.push("Select at least one lead", "error");
    if (!templateId) return toast.push("Select a template", "error");
    setActionBusy(true);
    try {
      await Promise.all(recipients.map((id) => apiFetch(`/inbox/customers/${id}/send-template`, {
        method: "POST",
        body: JSON.stringify({
          template_id: templateId,
          channel,
          delay_minutes: delayMinutes ? Number(delayMinutes) : null,
          cancel_on_inbound: cancelOnInbound,
        }),
      })));
      toast.push(recipients.length > 1 ? "Templates queued" : "Template queued");
      setTemplateId("");
      setDelayMinutes("");
      setCancelOnInbound(false);
      if (selected) await loadThread(selected.id);
      await loadList();
    } catch (err: any) {
      toast.push(err?.message || "Failed to queue template", "error");
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <div className="stack">
      <Topbar
        title="Inbox"
        right={
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <select value={bucket} onChange={(e) => setBucket(e.target.value)}>
              <option value="">All buckets</option>
              <option value="followup_due">Follow-up due</option>
              <option value="open">Open</option>
              <option value="waiting">Waiting</option>
              <option value="closed">Closed</option>
            </select>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search leads…" />
            <button className="btn" onClick={loadList} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>
          </div>
        }
      />

      <div className="card">
        <div className="cardBody" style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <span className="chip"><b>{recipients.length}</b> selected recipient{recipients.length === 1 ? "" : "s"}</span>
              <button className={`btn ${channel === "email" ? "btnPrimary" : ""}`} onClick={() => setChannel("email")}>Email</button>
              <button className={`btn ${channel === "whatsapp" ? "btnPrimary" : ""}`} onClick={() => setChannel("whatsapp")}>WhatsApp</button>
              <button className={`btn ${composerMode === "send" ? "btnPrimary" : ""}`} onClick={() => setComposerMode("send")}>Send now</button>
              <button className={`btn ${composerMode === "queue" ? "btnPrimary" : ""}`} onClick={() => setComposerMode("queue")}>Queue template</button>
              <button className="btn" disabled={!selectedIds.size} onClick={clearSelected}>Clear selection</button>
            </div>
            <div className="muted" style={{ fontSize: 12 }}>Use checkboxes for bulk actions; otherwise actions apply to the open conversation.</div>
          </div>

          {composerMode === "send" && (
            <div style={{ display: "grid", gap: 10 }}>
              {channel === "email" && (
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Subject</div>
                  <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Email subject" />
                </div>
              )}
              <div>
                <div className="muted" style={{ fontSize: 12 }}>{channel === "email" ? "Message" : "WhatsApp message"}</div>
                <textarea rows={5} value={body} onChange={(e) => setBody(e.target.value)} placeholder={channel === "email" ? "Write the email body…" : "Write the WhatsApp message…"} />
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button className="btn btnPrimary" onClick={sendNow} disabled={actionBusy || !recipients.length}>Send</button>
              </div>
            </div>
          )}

          {composerMode === "queue" && (
            <div style={{ display: "grid", gap: 10 }}>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Template</div>
                <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                  <option value="">Select a {channel} template…</option>
                  {channelTemplates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </div>
              <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Delay (minutes)</div>
                  <input value={delayMinutes} onChange={(e) => setDelayMinutes(e.target.value)} placeholder="0" inputMode="numeric" />
                </div>
                <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 20 }}>
                  <input type="checkbox" checked={cancelOnInbound} onChange={(e) => setCancelOnInbound(e.target.checked)} />
                  <span className="muted">Cancel on inbound reply</span>
                </label>
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button className="btn btnPrimary" onClick={queueTemplate} disabled={actionBusy || !recipients.length}>Queue template</button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "360px 1fr", alignItems: "start" }}>
        <section className="card" style={{ overflow: "hidden" }}>
          <div className="cardHeader" style={{ fontWeight: 900 }}>Conversations</div>
          <div className="cardBody" style={{ padding: 0 }}>
            <div style={{ maxHeight: "72vh", overflow: "auto" }}>
              {customers.map((c) => {
                const active = selected?.id === c.id;
                const checked = selectedIds.has(c.id);
                return (
                  <div
                    key={c.id}
                    onClick={() => setSelected(c)}
                    style={{
                      padding: 12,
                      borderBottom: "1px solid var(--border)",
                      cursor: "pointer",
                      background: active ? "rgba(30, 103, 150, 0.08)" : undefined,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                      <label style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 900 }} onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={checked} onChange={() => toggleSelected(c.id)} />
                        <span>{c.name}</span>
                      </label>
                      <span className="badge">{c.bucket}</span>
                    </div>
                    <div className="muted" style={{ fontSize: 12 }}>{c.company || c.email || c.phone || "—"}</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                      {c.latest_deal?.treatment_interest && <span className="chip">{c.latest_deal.treatment_interest}</span>}
                      {c.latest_deal?.preferred_consultation_day && <span className="chip">{c.latest_deal.preferred_consultation_day}</span>}
                      {c.latest_deal?.seminar_preference && <span className="chip">{c.latest_deal.seminar_preference}</span>}
                    </div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Last: {fmtDateTime(c.last_activity_at)}</div>
                  </div>
                );
              })}
              {!busy && !customers.length && <div className="muted" style={{ padding: 12 }}>No conversations.</div>}
            </div>
          </div>
        </section>

        <section className="stack">
          <div className="card">
            <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 900 }}>{selected?.name || "Select a lead"}</div>
                {selected && <div className="muted" style={{ fontSize: 12 }}>{selected.email || "—"} · {selected.phone || "—"}</div>}
              </div>
              {selected ? (
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <WhatsAppQuickAction customer={selected} compact />
                  <Link className="btn" href={`/contacts/${selected.id}`}>Open contact</Link>
                </div>
              ) : <span />}
            </div>
            <div className="cardBody" style={{ maxHeight: "58vh", overflow: "auto", display: "grid", gap: 10 }}>
              {selected && (
                <div style={{ padding: 12, border: "1px solid var(--border)", borderRadius: 14 }}>
                  <div style={{ fontWeight: 900, marginBottom: 6 }}>Lead form details</div>
                  <div className="muted" style={{ fontSize: 12 }}>Treatment: <b>{selected.latest_deal?.treatment_interest || "—"}</b></div>
                  <div className="muted" style={{ fontSize: 12 }}>Preferred day: <b>{selected.latest_deal?.preferred_consultation_day || "—"}</b></div>
                  <div className="muted" style={{ fontSize: 12 }}>Seminar: <b>{selected.latest_deal?.seminar_preference || "—"}</b></div>
                </div>
              )}
              {selected ? thread.slice().reverse().map((t) => (
                <div key={t.id} style={{ padding: 12, border: "1px solid var(--border)", borderRadius: 14, background: t.direction === "outbound" ? "rgba(30, 103, 150, 0.05)" : "white" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <div style={{ fontWeight: 800, fontSize: 12 }}>{t.direction} · {t.channel}</div>
                    <div className="muted" style={{ fontSize: 12 }}>{fmtDateTime(t.occurred_at)}</div>
                  </div>
                  {t.subject && <div style={{ fontWeight: 800, marginTop: 4 }}>{t.subject}</div>}
                  <div className="muted" style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{t.content || "—"}</div>
                  {t.status && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Status: {t.status}</div>}
                </div>
              )) : <div className="muted">Select a lead to view the conversation.</div>}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
