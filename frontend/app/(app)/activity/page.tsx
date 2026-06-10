"use client";

import { useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { AuditLogOut } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { fmtDateTime } from "@/lib/dates";

export default function ActivityPage() {
  const toast = useToast();
  const [items, setItems] = useState<AuditLogOut[]>([]);
  const [busy, setBusy] = useState(true);

  async function load() {
    setBusy(true);
    try {
      setItems(await apiFetch<AuditLogOut[]>("/audit-logs?limit=200"));
    } catch (err: any) {
      toast.push(err?.message || "Failed to load activity. Admin permission may be required.", "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="stack">
      <Topbar title="Activity log" right={<button className="btn" onClick={() => void load()}>{busy ? "Loading…" : "Refresh"}</button>} />
      <section className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>Who did what</div>
        <div className="cardBody">
          <table className="table">
            <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Entity</th><th>Change</th></tr></thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td>{fmtDateTime(a.created_at)}</td>
                  <td>{a.actor_email || "System"}</td>
                  <td><span className="chip">{a.action}</span></td>
                  <td>{a.entity_type}{a.entity_id ? <div className="muted" style={{ fontSize: 12 }}>{a.entity_id}</div> : null}</td>
                  <td><pre style={{ whiteSpace: "pre-wrap", margin: 0, maxWidth: 420 }}>{JSON.stringify(a.after || a.before || a.meta || {}, null, 2)}</pre></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
