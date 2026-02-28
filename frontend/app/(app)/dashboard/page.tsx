"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { InboxCustomerOut, KPIResponse, CustomerOut } from "@/lib/types";
import { Topbar } from "@/components/Topbar";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";

function toMins(sec: number | null): string {
  if (sec == null) return "—";
  const mins = Math.round(sec / 60);
  return `${mins} min`;
}

export default function DashboardPage() {
  const toast = useToast();
  const [kpi, setKpi] = useState<KPIResponse | null>(null);
  const [recent, setRecent] = useState<InboxCustomerOut[]>([]);
  const [followups, setFollowups] = useState<CustomerOut[]>([]);
  const [busy, setBusy] = useState(true);

  const conversion = useMemo(() => {
    if (!kpi) return [] as Array<{ k: string; v: number }>;
    const keys = ["consult_booked", "deposit_paid", "treatment_done", "lost"];
    return keys.map((k) => ({ k, v: Math.round((kpi.conversion_rates?.[k] || 0) * 1000) / 10 }));
  }, [kpi]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setBusy(true);
      try {
        const [k, r, f] = await Promise.all([
          apiFetch<KPIResponse>("/analytics/summary"),
          apiFetch<InboxCustomerOut[]>("/inbox/customers?limit=12"),
          apiFetch<CustomerOut[]>("/followups"),
        ]);
        if (!mounted) return;
        setKpi(k);
        setRecent(r);
        setFollowups(f.slice(0, 10));
      } catch (err: any) {
        toast.push(err?.message || "Failed to load dashboard", "error");
      } finally {
        if (mounted) setBusy(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [toast]);

  return (
    <div className="stack">
      <Topbar
        title="Sales Overview"
        right={
          <Link className="btn btnPrimary" href="/pipeline">
            Go to Pipeline
          </Link>
        }
      />

      {busy && !kpi ? (
        <div className="card" style={{ padding: 16 }}>Loading…</div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "repeat(4, minmax(180px, 1fr))" }}>
          <div className="card kpi">
            <div className="kpiLabel">Leads created (30d)</div>
            <div className="kpiValue">{kpi?.leads_created ?? 0}</div>
          </div>
          <div className="card kpi">
            <div className="kpiLabel">Inbound received (30d)</div>
            <div className="kpiValue">{kpi?.inbound_received ?? 0}</div>
          </div>
          <div className="card kpi">
            <div className="kpiLabel">Outbound sent (30d)</div>
            <div className="kpiValue">{kpi?.outbound_sent ?? 0}</div>
          </div>
          <div className="card kpi">
            <div className="kpiLabel">Median first response</div>
            <div className="kpiValue">{toMins(kpi?.median_first_response_seconds ?? null)}</div>
          </div>
        </div>
      )}

      <div className="split">
        <section className="card">
          <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontWeight: 800 }}>Recent leads</div>
            <Link href="/inbox" className="muted" style={{ fontSize: 13 }}>Open Inbox</Link>
          </div>
          <div className="cardBody">
            <table className="table">
              <thead>
                <tr>
                  <th>Lead</th>
                  <th>Stage</th>
                  <th>Bucket</th>
                  <th>Last activity</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link href={`/contacts/${c.id}`} style={{ fontWeight: 700 }}>{c.name}</Link>
                      <div className="muted" style={{ fontSize: 12 }}>{c.company || "—"}</div>
                    </td>
                    <td><span className="badge">{c.stage}</span></td>
                    <td className="muted">{c.bucket}</td>
                    <td className="muted">{fmtDateTime(c.last_activity_at)}</td>
                  </tr>
                ))}
                {!recent.length && (
                  <tr>
                    <td colSpan={4} className="muted">No leads yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="stack">
          <div className="card">
            <div className="cardHeader" style={{ fontWeight: 800 }}>Conversion (30d)</div>
            <div className="cardBody" style={{ display: "grid", gap: 8 }}>
              {conversion.map((x) => (
                <div key={x.k} style={{ display: "flex", justifyContent: "space-between" }}>
                  <div className="muted">{x.k.replaceAll("_", " ")}</div>
                  <div style={{ fontWeight: 800 }}>{x.v}%</div>
                </div>
              ))}
              {!conversion.length && <div className="muted">—</div>}
            </div>
          </div>

          <div className="card">
            <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontWeight: 800 }}>Follow-ups due</div>
              <Link href="/tasks" className="muted" style={{ fontSize: 13 }}>View Tasks</Link>
            </div>
            <div className="cardBody">
              <div className="stack">
                {followups.map((c) => (
                  <div key={c.id} style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <div>
                      <Link href={`/contacts/${c.id}`} style={{ fontWeight: 700 }}>{c.name}</Link>
                      <div className="muted" style={{ fontSize: 12 }}>{fmtDateTime(c.next_follow_up_at)}</div>
                    </div>
                    <span className="badge">{c.stage}</span>
                  </div>
                ))}
                {!followups.length && <div className="muted">Nothing due right now.</div>}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
