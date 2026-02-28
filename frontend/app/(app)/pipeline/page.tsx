"use client";

import { useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { InboxCustomerOut } from "@/lib/types";
import { PIPELINE_STAGES, SERVICE_TAGS, stageLabel } from "@/lib/constants";
import { fmtDateTime } from "@/lib/dates";
import { LeadDrawer } from "@/components/LeadDrawer";
import { useToast } from "@/components/Toast";

export default function PipelinePage() {
  const toast = useToast();
  const [leads, setLeads] = useState<InboxCustomerOut[]>([]);
  const [busy, setBusy] = useState(true);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [selected, setSelected] = useState<InboxCustomerOut | null>(null);

  async function load(): Promise<InboxCustomerOut[]> {
    setBusy(true);
    try {
      const qs = new URLSearchParams();
      qs.set("limit", "200");
      if (q.trim()) qs.set("q", q.trim());
      if (tag) qs.set("tag", tag);
      const data = await apiFetch<InboxCustomerOut[]>(`/inbox/customers?${qs.toString()}`);
      setLeads(data);
      return data;
    } catch (err: any) {
      toast.push(err?.message || "Failed to load pipeline", "error");
      return [];
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const grouped = useMemo(() => {
    const map: Record<string, InboxCustomerOut[]> = {};
    for (const s of PIPELINE_STAGES) map[s] = [];
    for (const l of leads) {
      const key = PIPELINE_STAGES.includes(l.stage) ? l.stage : "new";
      map[key].push(l);
    }
    return map;
  }, [leads]);

  return (
    <div className="stack">
      <Topbar
        title="Pipeline"
        right={
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input
              placeholder="Search name / phone / email / company"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ width: 320 }}
            />
            <select value={tag} onChange={(e) => setTag(e.target.value)}>
              <option value="">All patients</option>
              {SERVICE_TAGS.map((t) => (
                <option key={t} value={t}>{t.replace("service:", "")}</option>
              ))}
            </select>
            <button className="btn" onClick={load} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>
          </div>
        }
      />

      <div className="kanban">
        {PIPELINE_STAGES.map((stage) => (
          <section key={stage} className="kanbanCol">
            <div className="kanbanColHeader">
              <div style={{ fontWeight: 900 }}>{stageLabel(stage)}</div>
              <span className="chip"><b>{(grouped[stage] || []).length}</b> leads</span>
            </div>
            <div className="kanbanCards">
              {(grouped[stage] || []).map((l) => (
                <div key={l.id} className="cardMini" onClick={() => setSelected(l)}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <div style={{ fontWeight: 900 }}>{l.name}</div>
                    <span className="badge">{l.bucket}</span>
                  </div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{l.company || "—"}</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                    {(l.tags || []).slice(0, 3).map((t) => (
                      <span key={t} className="chip">{t}</span>
                    ))}
                    {(l.tags || []).length > 3 && <span className="chip">+{(l.tags || []).length - 3}</span>}
                  </div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                    Last: {fmtDateTime(l.last_activity_at)}
                  </div>
                </div>
              ))}
              {!busy && !(grouped[stage] || []).length && (
                <div className="muted" style={{ padding: 10 }}>No leads.</div>
              )}
            </div>
          </section>
        ))}
      </div>

      {selected && (
        <LeadDrawer
          lead={selected}
          onClose={() => setSelected(null)}
          onUpdated={async () => {
            const data = await load();
            const updated = data.find((x) => x.id === selected.id);
            setSelected(updated || null);
          }}
        />
      )}
    </div>
  );
}
