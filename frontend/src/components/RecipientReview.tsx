"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { AutomationKey, AutomationRecipient, RecipientPreview } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import { escapeHtml } from "@/lib/messageFormat";

const AUTOMATION_LABEL: Record<string, string> = {
  appointment_confirmation: "Event confirmation",
  lead_followup: "Lead follow-up",
};

const STATE_STYLE: Record<string, { label: string; color: string }> = {
  scheduled: { label: "Scheduled", color: "#1e6796" },
  existing: { label: "Existing record", color: "#64748b" },
  awaiting_approval: { label: "Awaiting approval", color: "#b45309" },
  needs_reapproval: { label: "Changed: re-approve", color: "#dc2626" },
  waiting: { label: "Waiting", color: "#64748b" },
  held: { label: "On hold", color: "#64748b" },
  queued: { label: "Sending", color: "#15803d" },
  needs_review: { label: "Needs fixing", color: "#dc2626" },
};

const CHANNEL_LABEL: Record<string, string> = { email: "Email", whatsapp: "WhatsApp" };

function kindLabel(r: { automation_key: string; kind: string }) {
  if (r.kind === "update") return "Updated event confirmation";
  return AUTOMATION_LABEL[r.automation_key] || r.automation_key;
}

function plannedText(r: AutomationRecipient) {
  if (!r.automation_enabled) return "Automation paused";
  if (r.state === "existing") return "Only if you include and approve it";
  if (r.state === "awaiting_approval") return "When approved";
  if (r.state === "needs_reapproval") return "After a new preview and approval";
  if (r.state === "held") return "On hold";
  if (r.state === "needs_review") return "Blocked until fixed";
  if (r.state === "waiting") return r.reason || "Waiting";
  if (r.state === "queued") return "Being sent now";
  if (!r.planned_at) return "—";
  const due = new Date(r.planned_at);
  const soon = due.getTime() - Date.now() < 90_000;
  const when = soon ? "Next check (within a minute)" : fmtDateTime(r.planned_at);
  return r.requires_approval ? `${when}, then needs approval` : when;
}

function keyOf(r: { automation_key: string; customer_id: string; appointment_id: string | null }) {
  return `${r.automation_key}:${r.customer_id}:${r.appointment_id || ""}`;
}

function StatePill({ state }: { state: string }) {
  const s = STATE_STYLE[state] || { label: state, color: "#64748b" };
  return <span className="badge" style={{ borderColor: s.color, color: s.color, whiteSpace: "nowrap" }}>{s.label}</span>;
}

function RecipientDrawer({ recipient, onClose, onChanged }: { recipient: AutomationRecipient; onClose: () => void; onChanged: () => Promise<void> }) {
  const toast = useToast();
  const [preview, setPreview] = useState<RecipientPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmExclude, setConfirmExclude] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams({ automation_key: recipient.automation_key, customer_id: recipient.customer_id });
    if (recipient.appointment_id) params.set("appointment_id", recipient.appointment_id);
    apiFetch<RecipientPreview>(`/automations/recipients/preview?${params}`)
      .then(setPreview)
      .catch((err: any) => setError(detailOf(err)));
  }, [recipient]);

  async function act(action: "include" | "approve" | "hold" | "release" | "exclude") {
    setBusy(action);
    try {
      await apiFetch(`/automations/recipients/${action}`, {
        method: "POST",
        body: JSON.stringify({
          automation_key: recipient.automation_key,
          customer_id: recipient.customer_id,
          appointment_id: recipient.appointment_id,
          note: note.trim() || null,
          preview_token: action === "approve" ? preview?.preview_token : null,
        }),
      });
      toast.push({
        include: "Included: preview and approve it to send",
        approve: "Approved and sent to the queue",
        hold: "On hold until you release it",
        release: "Hold released",
        exclude: "Removed from this automation",
      }[action]);
      await onChanged();
      onClose();
    } catch (err: any) {
      toast.push(detailOf(err), "error");
    } finally {
      setBusy(null);
    }
  }

  const booking = preview?.booking || recipient.booking;
  return (
    <div className="modalOverlay" onClick={onClose}>
      <div className="modal" style={{ width: "min(860px, 96vw)", maxHeight: "92vh", display: "flex", flexDirection: "column" }} onClick={(e) => e.stopPropagation()}>
        <div className="modalHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
          <div>
            <div style={{ fontWeight: 900 }}>{recipient.customer_name || "Unknown"} · {kindLabel(recipient)}</div>
            <div className="muted" style={{ fontSize: 12 }}>Preview only. Nothing is sent from this window unless you approve it.</div>
          </div>
          <button className="btn" type="button" onClick={onClose}>Close</button>
        </div>
        <div className="modalBody" style={{ display: "grid", gap: 12, overflowY: "auto" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <StatePill state={recipient.state} />
            <span className="muted" style={{ fontSize: 13 }}>{plannedText(recipient)}</span>
            <Link href={`/contacts/${recipient.customer_id}`} className="muted" style={{ fontSize: 13, textDecoration: "underline" }}>Open contact</Link>
          </div>

          {booking && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8, padding: 10, borderRadius: 10, background: "rgba(30,103,150,0.06)" }}>
              <div><div className="muted" style={{ fontSize: 12 }}>Event</div><b>{booking.event_name || "—"}</b></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Date</div><b>{booking.event_date || "—"}</b></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Time slot</div><b>{booking.slot || "—"}</b></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Venue</div><b>{booking.event_venue || "—"}</b></div>
            </div>
          )}

          {(recipient.reason || preview?.problem || booking?.problem) && (
            <div style={{ padding: 10, borderRadius: 10, fontSize: 13, background: "rgba(245,158,11,0.10)", border: "1px solid rgba(245,158,11,0.35)" }}>
              {preview?.problem || booking?.problem || recipient.reason}
            </div>
          )}
          {error && <div style={{ color: "var(--danger)" }}>{error}</div>}
          {!preview && !error && <div className="muted">Loading preview…</div>}

          {preview?.channels.map((c) => (
            <div key={c.channel} style={{ display: "grid", gap: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <b>{CHANNEL_LABEL[c.channel]} to {c.address || "no address"}</b>
                {c.status !== "ok" && <span className="muted" style={{ fontSize: 12 }}>{c.status.replace("_", " ")}</span>}
              </div>
              {c.body ? (
                c.channel === "email" ? (
                  <div style={{ border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
                    <div style={{ padding: "8px 10px", background: "rgba(0,0,0,0.03)", fontSize: 13 }}><span className="muted">Subject:</span> <b>{c.subject}</b></div>
                    <iframe title={`Email to ${recipient.customer_name}`} sandbox="" srcDoc={`<!doctype html><meta charset="utf-8"><body style="margin:12px;background:#fff">${c.body}</body>`} style={{ width: "100%", height: 260, border: 0, background: "#fff" }} />
                  </div>
                ) : (
                  <div style={{ background: "rgba(136,194,199,0.15)", borderRadius: 10, padding: 10 }}>
                    <div style={{ background: "#dcf8c6", color: "#102a12", padding: "8px 10px", borderRadius: "10px 10px 2px 10px", maxWidth: "90%", marginLeft: "auto", fontSize: 13, whiteSpace: "pre-wrap" }}
                      dangerouslySetInnerHTML={{ __html: escapeHtml(c.body) }} />
                  </div>
                )
              ) : (
                <div className="muted" style={{ fontSize: 13 }}>Won&apos;t be sent on {CHANNEL_LABEL[c.channel]}: {c.reason}</div>
              )}
            </div>
          ))}

          {recipient.state === "needs_reapproval" && (
            <div style={{ fontSize: 13 }}>The booking changed after this message was approved, so it was stopped. The preview above shows the message with the booking as it is now. Approve it again to send.</div>
          )}
          {(recipient.can_hold || recipient.can_exclude || recipient.can_approve || recipient.can_release || recipient.can_include) && (
            <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              {(recipient.can_hold || recipient.can_exclude) && (
                <input className="formField" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason (optional, saved in the activity log)" maxLength={300} />
              )}
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
                {recipient.can_exclude && (confirmExclude ? (
                  <button className="btn" type="button" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} disabled={!!busy} onClick={() => void act("exclude")}>
                    {busy === "exclude" ? "Removing…" : "Confirm: remove from this automation"}
                  </button>
                ) : (
                  <button className="btn" type="button" disabled={!!busy} onClick={() => setConfirmExclude(true)} title="Never send this automated message to them">Exclude from automation</button>
                ))}
                {recipient.can_hold && <button className="btn" type="button" disabled={!!busy} onClick={() => void act("hold")} title="Pause until you release it">{busy === "hold" ? "Holding…" : "Hold (pause)"}</button>}
                {recipient.can_release && <button className="btn" type="button" disabled={!!busy} onClick={() => void act("release")}>{busy === "release" ? "Releasing…" : "Release hold"}</button>}
                {recipient.can_include && (
                  <button className="btn btnPrimary" type="button" disabled={!!busy} onClick={() => void act("include")}>
                    {busy === "include" ? "Including…" : "Include for approval"}
                  </button>
                )}
                {recipient.can_approve && (
                  <button className="btn btnPrimary" type="button" disabled={!!busy || !preview?.preview_token} title={!preview?.preview_token ? (preview?.problem || "Wait for the preview to load") : undefined} onClick={() => void act("approve")}>
                    {busy === "approve" ? "Approving…" : recipient.state === "needs_reapproval" ? "Approve again and send" : "Approve and send"}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function detailOf(err: any): string {
  try {
    const parsed = JSON.parse(err?.bodyText || err?.message || "");
    if (typeof parsed?.detail === "string") return parsed.detail;
  } catch {
    // not JSON
  }
  return err?.message || "Something went wrong";
}

/** Who is due to receive each automated message, with preview and staff controls. */
export function RecipientReview({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => Promise<void> }) {
  const toast = useToast();
  const [items, setItems] = useState<AutomationRecipient[]>([]);
  const [busy, setBusy] = useState(true);
  const [filter, setFilter] = useState<"" | AutomationKey>("");
  const [open, setOpen] = useState<AutomationRecipient | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [including, setIncluding] = useState(false);

  async function load() {
    setBusy(true);
    try {
      setItems(await apiFetch<AutomationRecipient[]>("/automations/recipients"));
    } catch (err: any) {
      toast.push(detailOf(err), "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  const shown = useMemo(() => items.filter((i) => !filter || i.automation_key === filter), [items, filter]);
  const awaiting = items.filter((i) => i.state === "awaiting_approval" || i.state === "needs_reapproval").length;
  const includable = shown.filter((i) => i.can_include);
  const chosen = includable.filter((i) => selected.has(keyOf(i)));

  function toggle(r: AutomationRecipient) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(keyOf(r))) next.delete(keyOf(r));
      else next.add(keyOf(r));
      return next;
    });
  }

  async function includeSelected() {
    setIncluding(true);
    const failed: string[] = [];
    for (const r of chosen) {
      try {
        await apiFetch(`/automations/recipients/include`, {
          method: "POST",
          body: JSON.stringify({ automation_key: r.automation_key, customer_id: r.customer_id, appointment_id: r.appointment_id }),
        });
      } catch (err: any) {
        failed.push(`${r.customer_name || "Unknown"}: ${detailOf(err)}`);
      }
    }
    setIncluding(false);
    setSelected(new Set());
    const ok = chosen.length - failed.length;
    if (ok) toast.push(`${ok} included. Preview and approve each one to send it.`);
    if (failed.length) toast.push(failed.join(" · "), "error");
    await load();
    await onChanged();
  }

  return (
    <section className="card">
      <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <div>
          <b>Upcoming recipients</b>
          <div className="muted" style={{ fontSize: 12 }}>
            Who is due to get an automated message. Open one to preview the exact message. Hold pauses it until you release it; Exclude removes them from the automation.
            Existing records from before the automation was switched on are only sent if you include and approve them.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {awaiting > 0 && <span className="badge" style={{ borderColor: "#b45309", color: "#b45309" }}>{awaiting} awaiting approval</span>}
          {includable.length > 0 && (
            <button className="btn btnPrimary" type="button" disabled={!chosen.length || including} onClick={() => void includeSelected()}
              title="Prepares the messages for approval. Nothing is sent until each one is previewed and approved.">
              {including ? "Including…" : `Include selected for approval (${chosen.length})`}
            </button>
          )}
          <select value={filter} onChange={(e) => setFilter(e.target.value as "" | AutomationKey)} style={{ width: "auto" }} aria-label="Filter by automation">
            <option value="">All automations</option>
            <option value="appointment_confirmation">Event confirmations</option>
            <option value="lead_followup">Lead follow-ups</option>
          </select>
          <button className="btn" type="button" onClick={() => void load()} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>
        </div>
      </div>
      <div className="cardBody" style={{ overflowX: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 28 }}>
                {includable.length > 0 && (
                  <input type="checkbox" aria-label="Select all existing records" checked={chosen.length === includable.length}
                    onChange={(e) => setSelected(e.target.checked ? new Set(includable.map(keyOf)) : new Set())} />
                )}
              </th>
              <th>Recipient</th>
              <th>Automation</th>
              <th>Planned</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={keyOf(r)}>
                <td>
                  {r.can_include && <input type="checkbox" aria-label={`Select ${r.customer_name}`} checked={selected.has(keyOf(r))} onChange={() => toggle(r)} />}
                </td>
                <td>
                  <div style={{ fontWeight: 800 }}>{r.customer_name || "Unknown"}</div>
                  {r.channels.map((c) => (
                    <div key={c.channel} className="muted" style={{ fontSize: 12 }}>
                      {CHANNEL_LABEL[c.channel]}: {c.address || "—"}{c.status === "skipped" || c.status === "needs_review" ? " (won't send)" : ""}
                    </div>
                  ))}
                </td>
                <td>
                  <div>{kindLabel(r)}</div>
                  {r.booking && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      {r.booking.event_name}<br />
                      {r.booking.event_date ? `${r.booking.event_date}, ${r.booking.slot}` : "Slot details missing"}<br />
                      {r.booking.event_venue || "No venue"}
                    </div>
                  )}
                </td>
                <td className="muted" style={{ fontSize: 13 }}>{plannedText(r)}</td>
                <td>
                  <StatePill state={r.state} />
                  {r.reason && r.state !== "waiting" && <div className="muted" style={{ fontSize: 12, marginTop: 4, maxWidth: 320 }}>{r.reason}</div>}
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className={`btn ${r.can_approve ? "btnPrimary" : ""}`} type="button" onClick={() => setOpen(r)}>
                    {r.can_approve ? (r.state === "needs_reapproval" ? "Review again" : "Review & approve") : "Preview"}
                  </button>
                </td>
              </tr>
            ))}
            {!busy && !shown.length && (
              <tr><td colSpan={6} className="muted">No one is due to receive an automated message right now.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {open && (
        <RecipientDrawer
          recipient={open}
          onClose={() => setOpen(null)}
          onChanged={async () => { await load(); await onChanged(); }}
        />
      )}
    </section>
  );
}
