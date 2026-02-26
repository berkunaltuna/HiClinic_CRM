"use client";

import React, { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";

type Summary = {
  start: string;
  end: string;
  leads_created: number;
  outbound_sent: number;
  inbound_received: number;
  median_first_response_seconds?: number | null;
  outcomes: Record<string, number>;
  conversion_rates: Record<string, number>;
};

type LeadsPoint = { date: string; leads: number };
type TemplateRow = {
  template_id: string;
  template_name: string;
  sent: number;
  replied_within_7d: number;
  reply_rate_7d: number;
};

export default function AnalyticsPage() {
  useRequireAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [leads, setLeads] = useState<LeadsPoint[]>([]);
  const [templates, setTemplates] = useState<TemplateRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    Promise.all([
      apiFetch<Summary>("/analytics/summary"),
      apiFetch<LeadsPoint[]>("/analytics/leads-by-day"),
      apiFetch<TemplateRow[]>("/analytics/templates"),
    ])
      .then(([s, l, t]) => {
        if (!alive) return;
        setSummary(s);
        setLeads(l);
        setTemplates(t);
      })
      .catch((e: any) => alive && setError(e?.message || "Failed"));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="grid">
      <div>
        <h2 style={{ margin: 0 }}>Analytics</h2>
        <div className="muted" style={{ marginTop: 4 }}>
          Outcome events, funnel conversion and messaging performance.
        </div>
      </div>
      {error && <div style={{ color: "var(--danger)" }}>{error}</div>}

      {summary && (
        <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <div className="card">
            <div className="cardBody">
              <strong>Leads</strong>
              <div style={{ fontSize: 28, marginTop: 6 }}>{summary.leads_created}</div>
            </div>
          </div>
          <div className="card">
            <div className="cardBody">
              <strong>Inbound</strong>
              <div style={{ fontSize: 28, marginTop: 6 }}>{summary.inbound_received}</div>
            </div>
          </div>
          <div className="card">
            <div className="cardBody">
              <strong>Outbound sent</strong>
              <div style={{ fontSize: 28, marginTop: 6 }}>{summary.outbound_sent}</div>
            </div>
          </div>
          <div className="card">
            <div className="cardBody">
              <strong>Median first response</strong>
              <div style={{ fontSize: 28, marginTop: 6 }}>
                {summary.median_first_response_seconds ? Math.round(summary.median_first_response_seconds / 60) + "m" : "—"}
              </div>
            </div>
          </div>
        </div>
      )}

      {summary && (
        <div className="card">
          <div className="cardHeader">
            <strong>Outcomes</strong>
          </div>
          <div className="cardBody" style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {Object.entries(summary.outcomes || {}).map(([k, v]) => (
              <div key={k}>
                <div className="muted">{k}</div>
                <div style={{ fontSize: 22, fontWeight: 800 }}>{v}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  rate: {((summary.conversion_rates?.[k] || 0) * 100).toFixed(1)}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <div className="cardHeader">
          <strong>Leads by day</strong>
        </div>
        <div className="cardBody" style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace", fontSize: 12, color: "#333" }}>
          {leads.map((p) => (
            <div key={p.date}>
              {p.date}  {"|"}  {"#".repeat(Math.min(p.leads, 50))} ({p.leads})
            </div>
          ))}
          {!leads.length && <div style={{ color: "#666" }}>No data yet.</div>}
        </div>
      </div>

      <div className="card">
        <div className="cardHeader">
          <strong>Template effectiveness (reply within 7 days)</strong>
        </div>
        <div className="cardBody" style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr style={{ textAlign: "left" }}>
                <th>Template</th>
                <th>Sent</th>
                <th>Replied</th>
                <th>Rate</th>
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => (
                <tr key={t.template_id}>
                  <td>{t.template_name}</td>
                  <td>{t.sent}</td>
                  <td>{t.replied_within_7d}</td>
                  <td>{(t.reply_rate_7d * 100).toFixed(1)}%</td>
                </tr>
              ))}
              {!templates.length && (
                <tr>
                  <td colSpan={4} className="muted">
                    No template data yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
