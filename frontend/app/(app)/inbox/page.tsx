"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { InboxCustomerOut, ThreadItem, TemplateOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";

export default function InboxPage() {
  const toast = useToast();
  const [customers, setCustomers] = useState<InboxCustomerOut[]>([]);
  const [selected, setSelected] = useState<InboxCustomerOut | null>(null);
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [templates, setTemplates] = useState<TemplateOut[]>([]);

  const [busy, setBusy] = useState(true);
  const [bucket, setBucket] = useState("");
  const [q, setQ] = useState("");

  const [msg, setMsg] = useState("");
  const [templateId, setTemplateId] = useState("");

  const selectedName = useMemo(() => selected?.name || "Select a lead", [selected]);

  async function loadList() {
    setBusy(true);
    try {
      const qs = new URLSearchParams();
      qs.set("limit", "80");
      if (bucket) qs.set("bucket", bucket);
      if (q.trim()) qs.set("q", q.trim());
      const data = await apiFetch<InboxCustomerOut[]>(`/inbox/customers?${qs.toString()}`);
      setCustomers(data);
      if (selected) {
        const still = data.find((x) => x.id === selected.id);
        setSelected(still || null);
      }
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
    } catch (err: any) {
      // not critical
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

  async function sendText() {
    if (!selected) return;
    const body = msg.trim();
    if (!body) return;
    try {
      await apiFetch<{ id: string; status: string }>(`/inbox/customers/${selected.id}/send-text`, {
        method: "POST",
        body: JSON.stringify({ body, channel: "whatsapp" }),
      });
      setMsg("");
      toast.push("Queued message");
      await loadThread(selected.id);
      await loadList();
    } catch (err: any) {
      toast.push(err?.message || "Failed to send", "error");
    }
  }

  async function sendTemplate() {
    if (!selected) return;
    if (!templateId) return;
    try {
      await apiFetch<{ id: string; status: string }>(`/inbox/customers/${selected.id}/send-template`, {
        method: "POST",
        body: JSON.stringify({ template_id: templateId, channel: "whatsapp" }),
      });
      toast.push("Queued template");
      await loadThread(selected.id);
      await loadList();
    } catch (err: any) {
      toast.push(err?.message || "Failed to send template", "error");
    }
  }

  return (
    <div className="stack">
      <Topbar
        title="Inbox"
        right={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <select value={bucket} onChange={(e) => setBucket(e.target.value)}>
              <option value="">All</option>
              <option value="followup_due">Follow-up due</option>
              <option value="open">Open</option>
              <option value="waiting">Waiting</option>
              <option value="closed">Closed</option>
            </select>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" />
            <button className="btn" onClick={loadList} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>
          </div>
        }
      />

      <div className="grid" style={{ gridTemplateColumns: "360px 1fr", alignItems: "start" }}>
        <section className="card" style={{ overflow: "hidden" }}>
          <div className="cardHeader" style={{ fontWeight: 900 }}>Leads</div>
          <div className="cardBody" style={{ padding: 0 }}>
            <div style={{ maxHeight: "70vh", overflow: "auto" }}>
              {customers.map((c) => {
                const active = selected?.id === c.id;
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
                      <div style={{ fontWeight: 900 }}>{c.name}</div>
                      <span className="badge">{c.bucket}</span>
                    </div>
                    <div className="muted" style={{ fontSize: 12 }}>{c.company || "—"}</div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Last: {fmtDateTime(c.last_activity_at)}</div>
                  </div>
                );
              })}
              {!busy && !customers.length && <div className="muted" style={{ padding: 12 }}>No results.</div>}
            </div>
          </div>
        </section>

        <section className="stack">
          <div className="card">
            <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontWeight: 900 }}>{selectedName}</div>
              {selected ? <Link className="btn" href={`/contacts/${selected.id}`}>Open contact</Link> : <span />}
            </div>
            <div className="cardBody" style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "grid", gap: 6 }}>
                <div className="muted" style={{ fontSize: 12 }}>Quick message (WhatsApp)</div>
                <textarea rows={3} value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Type a message…" />
                <button className="btn btnPrimary" onClick={sendText} disabled={!selected || !msg.trim()}>Send</button>
              </div>

              <div style={{ display: "grid", gap: 6 }}>
                <div className="muted" style={{ fontSize: 12 }}>Send template</div>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} style={{ flex: 1 }}>
                    <option value="">Select template…</option>
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>{t.name} ({t.channel})</option>
                    ))}
                  </select>
                  <button className="btn" onClick={sendTemplate} disabled={!selected || !templateId}>Queue</button>
                </div>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="cardHeader" style={{ fontWeight: 900 }}>Thread</div>
            <div className="cardBody" style={{ maxHeight: "62vh", overflow: "auto", display: "grid", gap: 10 }}>
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
                <div className="muted">Select a lead to view messages.</div>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
