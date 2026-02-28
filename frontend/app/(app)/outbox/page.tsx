"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { OutboundMessageOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";

export default function OutboxPage() {
  const toast = useToast();
  const [items, setItems] = useState<OutboundMessageOut[]>([]);
  const [busy, setBusy] = useState(true);

  async function load() {
    setBusy(true);
    try {
      const data = await apiFetch<OutboundMessageOut[]>("/outbound-messages");
      setItems(data);
    } catch (err: any) {
      toast.push(err?.message || "Failed to load outbox", "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="stack">
      <Topbar title="Outbox" right={<button className="btn" onClick={load} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>} />

      <div className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>Queued / sent messages</div>
        <div className="cardBody">
          <table className="table">
            <thead>
              <tr>
                <th>Customer</th>
                <th>Channel</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id}>
                  <td>
                    <Link href={`/contacts/${m.customer_id}`} style={{ fontWeight: 800 }}>{m.customer_id}</Link>
                    <div className="muted" style={{ fontSize: 12 }}>{m.template_id ? `Template: ${m.template_id}` : (m.body ? m.body.slice(0, 60) : "—")}</div>
                  </td>
                  <td className="muted">{m.channel}</td>
                  <td><span className="badge">{m.status}</span></td>
                  <td className="muted">{fmtDateTime(m.created_at)}</td>
                </tr>
              ))}
              {!busy && !items.length && (
                <tr>
                  <td colSpan={4} className="muted">No outbound messages.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
