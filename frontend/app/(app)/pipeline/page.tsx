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
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [bulkStage, setBulkStage] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);

  async function load(): Promise<InboxCustomerOut[]> {
    setBusy(true);
    try {
      const qs = new URLSearchParams();
      qs.set("limit", "200");
      if (q.trim()) qs.set("q", q.trim());
      if (tag) qs.set("tag", tag);
      const data = await apiFetch<InboxCustomerOut[]>(`/inbox/customers?${qs.toString()}`);
      setLeads(data);
      setSelected((prev) => (prev ? data.find((x) => x.id === prev.id) || null : prev));
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

  const totalSelected = selectedIds.size;

  function toggleSelected(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function clearSelected() {
    setSelectedIds(new Set());
    setBulkStage("");
  }

  async function moveLeadToStage(leadId: string, stage: string) {
    await apiFetch(`/inbox/customers/${leadId}/stage`, {
      method: "POST",
      body: JSON.stringify({ stage }),
    });
    setLeads((prev) => prev.map((l) => (l.id === leadId ? { ...l, stage } : l)));
    if (selected?.id === leadId) setSelected((prev) => (prev ? { ...prev, stage } : prev));
  }

  async function bulkMove(ids: string[], stage: string) {
    if (!ids.length || !stage) return;
    setBulkBusy(true);
    try {
      await Promise.all(ids.map((id) => moveLeadToStage(id, stage)));
      toast.push("Bulk moved");
      clearSelected();
    } catch (err: any) {
      toast.push(err?.message || "Bulk move failed", "error");
    } finally {
      setBulkBusy(false);
    }
  }

  async function deleteCustomers(ids: string[]) {
    if (!ids.length) return;
    if (!confirm(`Delete ${ids.length} selected contact${ids.length > 1 ? "s" : ""}? This cannot be undone.`)) return;
    setBulkBusy(true);
    try {
      await Promise.all(ids.map((id) => apiFetch(`/customers/${id}`, { method: "DELETE" })));
      toast.push(ids.length > 1 ? "Contacts deleted" : "Contact deleted");
      setLeads((prev) => prev.filter((l) => !ids.includes(l.id)));
      if (selected && ids.includes(selected.id)) setSelected(null);
      clearSelected();
    } catch (err: any) {
      toast.push(err?.message || "Delete failed", "error");
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <div className="stack">
      <Topbar
        title="Pipeline"
        right={
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <input placeholder="Search name / phone / email / company" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 320 }} />
            <select value={tag} onChange={(e) => setTag(e.target.value)}>
              <option value="">All patients</option>
              {SERVICE_TAGS.map((t) => <option key={t} value={t}>{t.replace("service:", "")}</option>)}
            </select>
            <button className="btn" onClick={load} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>
          </div>
        }
      />

      <div className="card">
        <div className="cardBody" style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span className="chip"><b>{totalSelected}</b> selected</span>
            <select value={bulkStage} onChange={(e) => setBulkStage(e.target.value)}>
              <option value="">Move selected to…</option>
              {PIPELINE_STAGES.map((s) => <option key={s} value={s}>{stageLabel(s)}</option>)}
            </select>
            <button className="btn" disabled={!totalSelected || !bulkStage || bulkBusy} onClick={() => bulkMove(Array.from(selectedIds), bulkStage)}>Move</button>
            <button className="btn" disabled={!totalSelected || bulkBusy} onClick={() => deleteCustomers(Array.from(selectedIds))}>Delete</button>
            <button className="btn" disabled={!totalSelected} onClick={clearSelected}>Clear</button>
          </div>
          <div className="muted" style={{ fontSize: 12 }}>Tip: drag cards between stages, or bulk move/delete selected leads.</div>
        </div>
      </div>

      <div className="kanban">
        {PIPELINE_STAGES.map((stage) => {
          const stageLeads = grouped[stage] || [];
          return (
            <section key={stage} className="kanbanCol">
              <div className="kanbanColHeader">
                <div style={{ fontWeight: 900 }}>{stageLabel(stage)}</div>
                <span className="chip"><b>{stageLeads.length}</b> leads</span>
              </div>

              <div
                className={`kanbanCards${draggingId ? " kanbanDropActive" : ""}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={async (e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const id = e.dataTransfer.getData("text/plain");
                  setDraggingId(null);
                  if (!id) return;
                  try {
                    await moveLeadToStage(id, stage);
                    toast.push("Moved");
                  } catch (err: any) {
                    toast.push(err?.message || "Failed to move lead", "error");
                  }
                }}
              >
                {stageLeads.map((l) => (
                  <div
                    key={l.id}
                    className={`cardMini ${draggingId === l.id ? "cardMiniDragging" : ""}`}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/plain", l.id);
                      e.dataTransfer.effectAllowed = "move";
                      setDraggingId(l.id);
                    }}
                    onDragEnd={() => setDraggingId(null)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={async (e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      const id = e.dataTransfer.getData("text/plain");
                      setDraggingId(null);
                      if (!id) return;
                      try {
                        await moveLeadToStage(id, stage);
                        toast.push("Moved");
                      } catch (err: any) {
                        toast.push(err?.message || "Failed to move lead", "error");
                      }
                    }}
                    onClick={() => setSelected(l)}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                      <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }} onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedIds.has(l.id)}
                          onChange={() => toggleSelected(l.id)}
                          onClick={(e) => e.stopPropagation()}
                        />
                        <span style={{ fontWeight: 900 }}>{l.name}</span>
                      </label>
                      <span className="badge">{l.bucket}</span>
                    </div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{l.company || "—"}</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                      {(l.tags || []).slice(0, 3).map((t) => <span key={t} className="chip">{t}</span>)}
                      {(l.tags || []).length > 3 && <span className="chip">+{(l.tags || []).length - 3}</span>}
                    </div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>Last: {fmtDateTime(l.last_activity_at)}</div>
                  </div>
                ))}
                {!busy && !stageLeads.length && <div className="muted" style={{ padding: 10 }}>No leads.</div>}
              </div>
            </section>
          );
        })}
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
