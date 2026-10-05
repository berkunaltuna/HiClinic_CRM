"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { CustomerOut, MergeAnalysisOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

export function MergeCustomerDialog({
  survivor,
  onClose,
  onMerged,
}: {
  survivor: CustomerOut;
  onClose: () => void;
  onMerged: () => void;
}) {
  const toast = useToast();
  const [customers, setCustomers] = useState<CustomerOut[]>([]);
  const [query, setQuery] = useState("");
  const [loser, setLoser] = useState<CustomerOut | null>(null);
  const [analysis, setAnalysis] = useState<MergeAnalysisOut | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch<CustomerOut[]>("/customers").then(setCustomers).catch((err: any) => toast.push(err?.message || "Failed to load customers", "error"));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return customers
      .filter((c) => c.id !== survivor.id)
      .filter((c) => !q || [c.name, c.email, c.phone].filter(Boolean).join(" ").toLowerCase().includes(q))
      .slice(0, 30);
  }, [customers, query, survivor.id]);

  async function selectLoser(c: CustomerOut) {
    setLoser(c);
    setAnalysis(null);
    setBusy(true);
    try {
      const res = await apiFetch<MergeAnalysisOut>(`/customers/${survivor.id}/merge/preview`, {
        method: "POST",
        body: JSON.stringify({ loser_customer_id: c.id }),
      });
      setAnalysis(res);
    } catch (err: any) {
      toast.push(err?.message || "Failed to compare customers", "error");
      setLoser(null);
    } finally {
      setBusy(false);
    }
  }

  async function doCommit() {
    if (!loser || !analysis) return;
    setBusy(true);
    try {
      const res = await apiFetch<import("@/lib/types").MergeCommitOut>(`/customers/${survivor.id}/merge/commit`, {
        method: "POST",
        body: JSON.stringify({ loser_customer_id: loser.id, confirmed_fingerprint: analysis.fingerprint }),
      });
      const cancelledCount = res.cancelled_duplicate_appointment_ids.length;
      toast.push(
        cancelledCount > 0
          ? `Customers merged — ${cancelledCount} duplicate booking(s) in the same slot were cancelled to avoid double-booking.`
          : "Customers merged",
      );
      onMerged();
      onClose();
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 409) {
        try {
          const detail = JSON.parse(err.bodyText || "{}").detail;
          if (detail?.analysis) {
            setAnalysis(detail.analysis);
            toast.push(
              detail.requires_manual_resolution
                ? "These customers have different active bookings in the same event and time slot — cancel one of them before merging."
                : "This customer changed since you compared them — review the updated details and confirm again.",
              "error",
            );
            return;
          }
        } catch {
          // fall through to generic error
        }
      }
      toast.push(err?.message || "Failed to merge customers", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modalOverlay" onClick={onClose}>
      <div className="modal" style={{ width: "min(640px, 96vw)" }} onClick={(e) => e.stopPropagation()}>
        <div className="modalHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 900 }}>Merge duplicate into {survivor.name}</div>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        <div className="modalBody stack">
          {!loser && (
            <>
              <input
                className="formField"
                placeholder="Search customers by name, email or phone…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
              />
              <div style={{ maxHeight: 320, overflowY: "auto" }}>
                {matches.map((c) => (
                  <div
                    key={c.id}
                    className="card"
                    style={{ boxShadow: "none", cursor: "pointer", marginBottom: 6 }}
                    onClick={() => selectLoser(c)}
                  >
                    <div className="cardBody" style={{ padding: "8px 12px" }}>
                      <div style={{ fontWeight: 700 }}>{c.name}</div>
                      <div className="muted" style={{ fontSize: 12 }}>{[c.email, c.phone].filter(Boolean).join(" · ") || "No contact info"}</div>
                    </div>
                  </div>
                ))}
                {!matches.length && <div className="muted">No customers found</div>}
              </div>
            </>
          )}

          {loser && busy && !analysis && <div className="muted">Comparing…</div>}

          {loser && analysis && (
            <div className="stack">
              <div className="muted">Merging <b>{loser.name}</b> into <b>{survivor.name}</b>. {survivor.name} is kept; {loser.name} will be deleted after its history is moved over.</div>

              {analysis.conflicts.length > 0 && (
                <div className="card" style={{ boxShadow: "none" }}>
                  <div className="cardHeader"><b>Conflicting fields</b> <span className="muted">({survivor.name}&apos;s value is kept)</span></div>
                  <div className="cardBody">
                    <table className="table">
                      <thead><tr><th>Field</th><th>{survivor.name} (kept)</th><th>{loser.name}</th></tr></thead>
                      <tbody>
                        {analysis.conflicts.map((c) => (
                          <tr key={c.field}><td>{c.field}</td><td>{c.survivor_value}</td><td className="muted">{c.loser_value}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {analysis.capacity_conflicts.length > 0 && (
                <div className="card" style={{ boxShadow: "none", borderColor: "#ef4444" }}>
                  <div className="cardHeader"><b>Cannot merge yet</b></div>
                  <div className="cardBody">
                    <div className="muted" style={{ marginBottom: 8 }}>
                      Both customers have a different active booking at the same event and exact time slot. Merging them would double-book that slot, so this has to be resolved by hand first — cancel or reschedule one of the two bookings below, then try the merge again.
                    </div>
                    {analysis.capacity_conflicts.map((b) => (
                      <div key={b.loser_appointment_id} className="muted" style={{ fontSize: 12 }}>
                        {b.event_name || "Event"} · {b.starts_at} — {survivor.name}: {String(b.detail.survivor_status)} vs {loser.name}: {String(b.detail.loser_status)}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {analysis.divergent_bookings.filter((b) => !b.both_active).length > 0 && (
                <div className="muted">
                  {analysis.divergent_bookings.filter((b) => !b.both_active).length} booking(s) at the same event/time with different details (one already cancelled) will both be kept — review them after merging.
                </div>
              )}

              {analysis.identical_bookings.filter((b) => b.both_active).length > 0 && (
                <div className="muted">
                  {analysis.identical_bookings.filter((b) => b.both_active).length} duplicate active booking(s) in the same slot will be consolidated — one copy is kept booked, the redundant one is cancelled (not deleted) so the slot isn&apos;t double-booked.
                </div>
              )}
              {analysis.identical_bookings.filter((b) => !b.both_active).length > 0 && (
                <div className="muted">{analysis.identical_bookings.filter((b) => !b.both_active).length} identical booking(s) will be preserved and reassigned.</div>
              )}

              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn" onClick={() => { setLoser(null); setAnalysis(null); }}>Back</button>
                <button className="btn btnPrimary" disabled={busy || analysis.capacity_conflicts.length > 0} onClick={doCommit}>
                  {busy ? "Merging…" : "Confirm merge"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
