"use client";

import { useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { AttributionRow, KPIResponse, LostReasonRow } from "@/lib/types";
import { useToast } from "@/components/Toast";


type LeadsByDayPoint = { date: string; leads: number };
type TemplateEff = { template_id: string; template_name: string; sent: number; replied_within_7d: number; reply_rate_7d: number };

export default function AnalyticsPage() {
  const toast = useToast();
  const [kpi, setKpi] = useState<KPIResponse | null>(null);
  const [leadsByDay, setLeadsByDay] = useState<LeadsByDayPoint[]>([]);
  const [tpl, setTpl] = useState<TemplateEff[]>([]);
  const [lost, setLost] = useState<LostReasonRow[]>([]);
  const [ads, setAds] = useState<AttributionRow[]>([]);
  const [campaigns, setCampaigns] = useState<AttributionRow[]>([]);
  const [forms, setForms] = useState<AttributionRow[]>([]);
  const [busy, setBusy] = useState(true);

  const outcomes = useMemo(() => {
    if (!kpi) return [] as Array<{ k: string; v: number }>;
    return Object.entries(kpi.outcomes || {}).sort((a, b) => Number(b[1]) - Number(a[1])).map(([k, v]) => ({ k, v: Number(v) }));
  }, [kpi]);

  async function load() {
    setBusy(true);
    try {
      const [a, b, c, d, e, f, g] = await Promise.all([
        apiFetch<KPIResponse>("/analytics/summary"),
        apiFetch<LeadsByDayPoint[]>("/analytics/leads-by-day"),
        apiFetch<TemplateEff[]>("/analytics/templates"),
        apiFetch<LostReasonRow[]>("/analytics/lost-reasons"),
        apiFetch<AttributionRow[]>("/analytics/lead-attribution?field=ad_name"),
        apiFetch<AttributionRow[]>("/analytics/lead-attribution?field=campaign_name"),
        apiFetch<AttributionRow[]>("/analytics/lead-attribution?field=form_name"),
      ]);
      setKpi(a); setLeadsByDay(b); setTpl(c); setLost(d); setAds(e); setCampaigns(f); setForms(g);
    } catch (err: any) {
      toast.push(err?.message || "Failed to load analytics", "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  function miniTable(rows: AttributionRow[] | LostReasonRow[], nameKey: "name" | "reason") {
    return (
      <table className="table">
        <tbody>
          {rows.map((r: any) => (
            <tr key={r[nameKey]}><td style={{ fontWeight: 800 }}>{r[nameKey]}</td><td className="muted" style={{ textAlign: "right" }}>{r.count}</td></tr>
          ))}
          {!busy && !rows.length && <tr><td className="muted">No data.</td><td /></tr>}
        </tbody>
      </table>
    );
  }

  return (
    <div className="stack">
      <Topbar title="Analytics" right={<button className="btn" onClick={load} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>} />

      <div className="grid" style={{ gridTemplateColumns: "repeat(3, minmax(220px, 1fr))" }}>
        <div className="card kpi"><div className="kpiLabel">Leads created (30d)</div><div className="kpiValue">{kpi?.leads_created ?? 0}</div></div>
        <div className="card kpi"><div className="kpiLabel">Inbound received (30d)</div><div className="kpiValue">{kpi?.inbound_received ?? 0}</div></div>
        <div className="card kpi"><div className="kpiLabel">Outbound sent (30d)</div><div className="kpiValue">{kpi?.outbound_sent ?? 0}</div></div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "repeat(3, minmax(220px, 1fr))" }}>
        <section className="card"><div className="cardHeader" style={{ fontWeight: 900 }}>Leads by advert</div><div className="cardBody">{miniTable(ads, "name")}</div></section>
        <section className="card"><div className="cardHeader" style={{ fontWeight: 900 }}>Leads by campaign</div><div className="cardBody">{miniTable(campaigns, "name")}</div></section>
        <section className="card"><div className="cardHeader" style={{ fontWeight: 900 }}>Leads by form</div><div className="cardBody">{miniTable(forms, "name")}</div></section>
      </div>

      <div className="split">
        <section className="card">
          <div className="cardHeader" style={{ fontWeight: 900 }}>Leads by day</div>
          <div className="cardBody">
            <table className="table"><thead><tr><th>Date</th><th>Leads</th></tr></thead><tbody>
              {leadsByDay.map((p) => <tr key={p.date}><td className="muted">{p.date}</td><td style={{ fontWeight: 800 }}>{p.leads}</td></tr>)}
              {!busy && !leadsByDay.length && <tr><td colSpan={2} className="muted">No data.</td></tr>}
            </tbody></table>
          </div>
        </section>

        <section className="stack">
          <div className="card"><div className="cardHeader" style={{ fontWeight: 900 }}>Lost reasons</div><div className="cardBody">{miniTable(lost, "reason")}</div></div>
          <div className="card">
            <div className="cardHeader" style={{ fontWeight: 900 }}>Outcome events</div>
            <div className="cardBody" style={{ display: "grid", gap: 8 }}>
              {outcomes.map((o) => <div key={o.k} style={{ display: "flex", justifyContent: "space-between" }}><div className="muted">{o.k}</div><div style={{ fontWeight: 900 }}>{o.v}</div></div>)}
              {!outcomes.length && <div className="muted">—</div>}
            </div>
          </div>
          <div className="card">
            <div className="cardHeader" style={{ fontWeight: 900 }}>Template effectiveness (7d reply)</div>
            <div className="cardBody"><table className="table"><thead><tr><th>Template</th><th>Sent</th><th>Replied</th><th>Rate</th></tr></thead><tbody>
              {tpl.map((r) => <tr key={r.template_id}><td style={{ fontWeight: 800 }}>{r.template_name}</td><td className="muted">{r.sent}</td><td className="muted">{r.replied_within_7d}</td><td style={{ fontWeight: 800 }}>{Math.round(r.reply_rate_7d * 1000) / 10}%</td></tr>)}
              {!busy && !tpl.length && <tr><td colSpan={4} className="muted">No data.</td></tr>}
            </tbody></table></div>
          </div>
        </section>
      </div>
    </div>
  );
}
