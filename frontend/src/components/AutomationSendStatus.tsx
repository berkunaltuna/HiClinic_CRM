"use client";

import type { AutomationSendOut } from "@/lib/types";

const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  queued: { label: "Queued", color: "#3b82f6" },
  sent: { label: "Sent", color: "#10b981" },
  failed: { label: "Failed", color: "#ef4444" },
  needs_review: { label: "Needs review", color: "#f59e0b" },
  skipped: { label: "Not sent", color: "#94a3b8" },
  cancelled: { label: "Cancelled", color: "#94a3b8" },
  resolved: { label: "Resolved", color: "#94a3b8" },
  dismissed: { label: "Dismissed", color: "#94a3b8" },
};

export function automationLabel(s: AutomationSendOut): string {
  if (s.kind === "followup") return "Lead follow-up";
  if (s.kind === "update") return "Updated confirmation";
  return "Appointment confirmation";
}

/** Slot times are stored as the Events tab's UK wall-clock time, so show them without timezone conversion. */
export function slotText(starts: string | null, ends: string | null): string {
  if (!starts) return "—";
  return `${starts.slice(0, 10)} ${starts.slice(11, 16)}${ends ? `–${ends.slice(11, 16)}` : ""} UK`;
}

export function AutomationSendStatus({ send }: { send: AutomationSendOut }) {
  const style = STATUS_STYLE[send.status] || { label: send.status, color: "#64748b" };
  return (
    <div>
      <span className="badge" style={{ borderColor: style.color, color: style.color }}>{style.label}</span>
      {send.reason && <div className="muted" style={{ fontSize: 12, marginTop: 4, maxWidth: 420 }}>{send.reason}</div>}
    </div>
  );
}
