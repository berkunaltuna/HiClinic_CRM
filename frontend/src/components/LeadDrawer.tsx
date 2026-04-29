"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { InboxCustomerOut, ThreadItem } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { PIPELINE_STAGES, SERVICE_TAGS, stageLabel } from "@/lib/constants";
import { useToast } from "@/components/Toast";

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
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const selectedService = useMemo(() => {
    return SERVICE_TAGS.find((t) => (lead.tags || []).includes(t)) || "";
  }, [lead.tags]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const items = await apiFetch<ThreadItem[]>(`/inbox/customers/${lead.id}/thread`);
        if (!mounted) return;
        setThread(items);
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
          channel: "whatsapp",
          direction: "outbound",
          occurred_at: new Date().toISOString(),
          content: body,
          subject: null,
        }),
      });
      setNote("");
      toast.push("Note added");
      const items = await apiFetch<ThreadItem[]>(`/inbox/customers/${lead.id}/thread`);
      setThread(items);
      onUpdated();
    } catch (err: any) {
      toast.push(err?.message || "Failed to add note", "error");
    } finally {
      setBusy(false);
    }
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

          <div className="card" style={{ boxShadow: "none" }}>
            <div className="cardHeader" style={{ fontWeight: 800 }}>Quick note</div>
            <div className="cardBody" style={{ display: "grid", gap: 8 }}>
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Add a note (saved as outbound interaction)…" />
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
        </div>
      </aside>
    </>
  );
}
