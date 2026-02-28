"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { CustomerOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";

export default function TasksPage() {
  const toast = useToast();
  const [items, setItems] = useState<CustomerOut[]>([]);
  const [busy, setBusy] = useState(true);

  async function load() {
    setBusy(true);
    try {
      const data = await apiFetch<CustomerOut[]>("/followups");
      setItems(data);
    } catch (err: any) {
      toast.push(err?.message || "Failed to load follow-ups", "error");
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
      <Topbar title="Tasks (Follow-ups)" right={<button className="btn" onClick={load} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>} />

      <div className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>Due / overdue</div>
        <div className="cardBody">
          <table className="table">
            <thead>
              <tr>
                <th>Lead</th>
                <th>Stage</th>
                <th>Due at</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link href={`/contacts/${c.id}`} style={{ fontWeight: 800 }}>{c.name}</Link>
                    <div className="muted" style={{ fontSize: 12 }}>{c.company || "—"}</div>
                  </td>
                  <td><span className="badge">{c.stage}</span></td>
                  <td className="muted">{fmtDateTime(c.next_follow_up_at)}</td>
                </tr>
              ))}
              {!busy && !items.length && (
                <tr>
                  <td colSpan={3} className="muted">No follow-ups due.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
