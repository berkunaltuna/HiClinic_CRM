"use client";

import React, { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

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
    <div>
      <h2>Analytics</h2>
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      {summary && (
        <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12 }}>
            <strong>Leads</strong>
            <div style={{ fontSize: 28 }}>{summary.leads_created}</div>
          </div>
          <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12 }}>
            <strong>Inbound</strong>
            <div style={{ fontSize: 28 }}>{summary.inbound_received}</div>
          </div>
          <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12 }}>
            <strong>Outbound Sent</strong>
            <div style={{ fontSize: 28 }}>{summary.outbound_sent}</div>
          </div>
          <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12 }}>
            <strong>Median First Response</strong>
            <div style={{ fontSize: 28 }}>
              {summary.median_first_response_seconds ? Math.round(summary.median_first_response_seconds / 60) + "m" : "—"}
            </div>
          </div>
        </div>
      )}

      {summary && (
        <div style={{ marginTop: 16, border: "1px solid #eee", borderRadius: 8, padding: 12 }}>
          <strong>Outcomes</strong>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 8 }}>
            {Object.entries(summary.outcomes || {}).map(([k, v]) => (
              <div key={k}>
                <div style={{ color: "#666" }}>{k}</div>
                <div style={{ fontSize: 22 }}>{v}</div>
                <div style={{ color: "#666", fontSize: 12 }}>
                  rate: {((summary.conversion_rates?.[k] || 0) * 100).toFixed(1)}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 16, border: "1px solid #eee", borderRadius: 8, padding: 12 }}>
        <strong>Leads by day</strong>
        <div style={{ marginTop: 8, fontFamily: "monospace", fontSize: 12, color: "#333" }}>
          {leads.map((p) => (
            <div key={p.date}>
              {p.date}  {"|"}  {"#".repeat(Math.min(p.leads, 50))} ({p.leads})
            </div>
          ))}
          {!leads.length && <div style={{ color: "#666" }}>No data yet.</div>}
        </div>
      </div>

      <div style={{ marginTop: 16, border: "1px solid #eee", borderRadius: 8, padding: 12 }}>
        <strong>Template effectiveness (reply within 7 days)</strong>
        <div style={{ overflowX: "auto", marginTop: 8 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left" }}>
                <th style={{ borderBottom: "1px solid #eee", padding: 8 }}>Template</th>
                <th style={{ borderBottom: "1px solid #eee", padding: 8 }}>Sent</th>
                <th style={{ borderBottom: "1px solid #eee", padding: 8 }}>Replied</th>
                <th style={{ borderBottom: "1px solid #eee", padding: 8 }}>Rate</th>
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => (
                <tr key={t.template_id}>
                  <td style={{ borderBottom: "1px solid #f3f3f3", padding: 8 }}>{t.template_name}</td>
                  <td style={{ borderBottom: "1px solid #f3f3f3", padding: 8 }}>{t.sent}</td>
                  <td style={{ borderBottom: "1px solid #f3f3f3", padding: 8 }}>{t.replied_within_7d}</td>
                  <td style={{ borderBottom: "1px solid #f3f3f3", padding: 8 }}>{(t.reply_rate_7d * 100).toFixed(1)}%</td>
                </tr>
              ))}
              {!templates.length && (
                <tr>
                  <td colSpan={4} style={{ padding: 8, color: "#666" }}>
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
