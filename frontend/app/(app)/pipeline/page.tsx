"use client";

import { useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { EventOut, InboxCustomerOut } from "@/lib/types";
import { LOST_REASONS, PIPELINE_STAGES, SERVICE_TAGS, stageLabel, sourceMeta, stageAccent, ownerInitials, countryFromPhone } from "@/lib/constants";
import { LeadDrawer } from "@/components/LeadDrawer";
import { useToast } from "@/components/Toast";

function daysSince(date?: string | null): number | null {
  if (!date) return null;
  const t = new Date(date).getTime();
  if (!Number.isFinite(t)) return null;
  return Math.floor((Date.now() - t) / (1000 * 60 * 60 * 24));
}

function followupBadge(date?: string | null): string | null {
  if (!date) return null;
  const t = new Date(date).getTime();
  if (!Number.isFinite(t)) return null;
  const diffDays = Math.floor((t - Date.now()) / (1000 * 60 * 60 * 24));
  if (diffDays < 0) return `Overdue ${Math.abs(diffDays)}d`;
  if (diffDays === 0) return "Follow-up today";
  return null;
}

function relLabel(days: number | null): string {
  if (days == null) return "—";
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return `${days}d ago`;
}

function depositValue(amount?: string | null): number | null {
  if (!amount) return null;
  const n = parseFloat(amount);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export default function PipelinePage() {
  const toast = useToast();
  const [leads, setLeads] = useState<InboxCustomerOut[]>([]);
  const [events, setEvents] = useState<EventOut[]>([]);
  const [busy, setBusy] = useState(true);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [eventId, setEventId] = useState("");
  const [selected, setSelected] = useState<InboxCustomerOut | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [bulkStage, setBulkStage] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [viewMode, setViewMode] = useState<"fit" | "comfortable">("fit");
  const [dateDir, setDateDir] = useState<"oldest" | "newest">("oldest");
  const [alphabetical, setAlphabetical] = useState(false);
  const [cardStyle, setCardStyle] = useState<"minimal" | "detailed" | "accent">("detailed");
  const [source, setSource] = useState("");
  const [collapsedStages, setCollapsedStages] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const saved = window.localStorage.getItem("pipeline_view_mode");
    if (saved === "fit" || saved === "comfortable") setViewMode(saved);
    const savedCardStyle = window.localStorage.getItem("pipeline_card_style");
    if (savedCardStyle === "minimal" || savedCardStyle === "detailed" || savedCardStyle === "accent") setCardStyle(savedCardStyle);
  }, []);

  function changeViewMode(mode: "fit" | "comfortable") {
    setViewMode(mode);
    window.localStorage.setItem("pipeline_view_mode", mode);
  }

  function changeCardStyle(style: "minimal" | "detailed" | "accent") {
    setCardStyle(style);
    window.localStorage.setItem("pipeline_card_style", style);
  }

  function toggleStageCollapsed(stage: string, currentlyCollapsed: boolean) {
    setCollapsedStages((prev) => ({ ...prev, [stage]: !currentlyCollapsed }));
  }

  function toggleCollapseAll(allCollapsed: boolean) {
    const next: Record<string, boolean> = {};
    for (const s of PIPELINE_STAGES) next[s] = !allCollapsed;
    setCollapsedStages(next);
  }

  async function load(): Promise<InboxCustomerOut[]> {
    setBusy(true);
    try {
      const qs = new URLSearchParams();
      qs.set("limit", "200");
      if (tag) qs.set("tag", tag);
      if (eventId) qs.set("event_id", eventId);
      const [data, evs] = await Promise.all([
        apiFetch<InboxCustomerOut[]>(`/inbox/customers?${qs.toString()}`),
        apiFetch<EventOut[]>(`/events`).catch(() => [] as EventOut[]),
      ]);
      setLeads(data);
      setEvents(evs);
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
  }, [eventId, tag]);

  const sourceOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const l of leads) {
      if (!l.lead_source || !l.lead_source.trim()) continue;
      const key = l.lead_source.trim().toLowerCase();
      if (!seen.has(key)) seen.set(key, sourceMeta(l.lead_source).label);
    }
    return Array.from(seen.entries()).map(([value, label]) => ({ value, label }));
  }, [leads]);

  const grouped = useMemo(() => {
    const map: Record<string, InboxCustomerOut[]> = {};
    for (const s of PIPELINE_STAGES) map[s] = [];
    const query = q.trim().toLowerCase();
    for (const l of leads) {
      if (source && (l.lead_source || "").trim().toLowerCase() !== source) continue;
      if (query) {
        const haystack = [
          l.name,
          l.company,
          l.phone,
          l.email,
          sourceMeta(l.lead_source).label,
          countryFromPhone(l.phone),
          l.latest_deal?.treatment_interest,
          ...(l.tags || []),
        ].filter(Boolean).join(" ").toLowerCase();
        if (!haystack.includes(query)) continue;
      }
      const key = PIPELINE_STAGES.includes(l.stage) ? l.stage : "new";
      map[key].push(l);
    }
    const sorter = alphabetical
      ? (a: InboxCustomerOut, b: InboxCustomerOut) => a.name.localeCompare(b.name)
      : dateDir === "oldest"
        ? (a: InboxCustomerOut, b: InboxCustomerOut) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        : (a: InboxCustomerOut, b: InboxCustomerOut) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    for (const s of PIPELINE_STAGES) map[s].sort(sorter);
    return map;
  }, [leads, dateDir, alphabetical, source, q]);

  const allCollapsed = PIPELINE_STAGES.every((s) => {
    const stageLeads = grouped[s] || [];
    return collapsedStages[s] ?? (leads.length > 0 && stageLeads.length === 0);
  });

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
    let lost_reason: string | undefined;
    if (stage === "lost") {
      const selectedReason = prompt(`Lost reason:\n${LOST_REASONS.join("\n")}`, "No response") || "Other";
      lost_reason = selectedReason.trim() || "Other";
    }
    await apiFetch(`/inbox/customers/${leadId}/stage`, {
      method: "POST",
      body: JSON.stringify({ stage, lost_reason }),
    });
    setLeads((prev) => prev.map((l) => (l.id === leadId ? { ...l, stage, latest_deal: l.latest_deal ? { ...l.latest_deal, lost_reason: lost_reason || l.latest_deal.lost_reason } : l.latest_deal } : l)));
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
        subtitle={`${leads.length} active lead${leads.length === 1 ? "" : "s"}`}
        right={
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <input
              placeholder="Search name, service or source…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ width: 260 }}
            />
            <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Filter by lead source">
              <option value="">All sources</option>
              {sourceOptions.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
            <button
              type="button"
              className="btn"
              style={alphabetical ? { opacity: 0.55 } : undefined}
              title="Toggle sort direction"
              onClick={() => { setAlphabetical(false); setDateDir((d) => (d === "oldest" ? "newest" : "oldest")); }}
            >
              {dateDir === "oldest" ? "↑ Oldest first" : "↓ Newest first"}
            </button>
            <button
              type="button"
              className="btn"
              style={alphabetical ? { background: "var(--primary)", color: "#fff", borderColor: "var(--primary)" } : undefined}
              title="Toggle alphabetical sort"
              onClick={() => setAlphabetical((a) => !a)}
            >
              A–Z
            </button>
            <div className="pipelineViewToggle" aria-label="Pipeline view mode">
              <button type="button" className={viewMode === "fit" ? "active" : ""} onClick={() => changeViewMode("fit")}>Fit</button>
              <button type="button" className={viewMode === "comfortable" ? "active" : ""} onClick={() => changeViewMode("comfortable")}>Comfort</button>
            </div>
          </div>
        }
      />

      <div className="card">
        <div className="cardBody" style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span className="muted" style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.03em", textTransform: "uppercase" }}>Card</span>
            <div className="pipelineViewToggle" aria-label="Card style">
              <button type="button" className={cardStyle === "minimal" ? "active" : ""} onClick={() => changeCardStyle("minimal")}>Minimal</button>
              <button type="button" className={cardStyle === "detailed" ? "active" : ""} onClick={() => changeCardStyle("detailed")}>Detailed</button>
              <button type="button" className={cardStyle === "accent" ? "active" : ""} onClick={() => changeCardStyle("accent")}>Accent</button>
            </div>
            <select value={eventId} onChange={(e) => setEventId(e.target.value)} aria-label="Filter by event">
              <option value="">All events</option>
              {events.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
            <select value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Filter by patient classification">
              <option value="">All patients</option>
              {SERVICE_TAGS.map((t) => <option key={t} value={t}>{t.replace("service:", "")}</option>)}
            </select>
            <button type="button" className="btn" onClick={() => toggleCollapseAll(allCollapsed)}>
              {allCollapsed ? "Expand all" : "Collapse all"}
            </button>
          </div>
          {totalSelected > 0 ? (
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <span className="chip"><span className="selCountBadge">{totalSelected}</span> selected</span>
              <select value={bulkStage} onChange={(e) => setBulkStage(e.target.value)}>
                <option value="">Move selected to…</option>
                {PIPELINE_STAGES.map((s) => <option key={s} value={s}>{stageLabel(s)}</option>)}
              </select>
              <button className="btn" disabled={!bulkStage || bulkBusy} onClick={() => bulkMove(Array.from(selectedIds), bulkStage)}>Move</button>
              <button className="btn" disabled={bulkBusy} onClick={() => deleteCustomers(Array.from(selectedIds))}>Delete</button>
              <button className="btn" onClick={clearSelected}>Clear</button>
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 12 }}>Drag cards between stages · open a card to send WhatsApp &amp; email</div>
          )}
        </div>
      </div>

      <div className={`kanban kanban-${viewMode}`}>
        {PIPELINE_STAGES.map((stage) => {
          const stageLeads = grouped[stage] || [];
          const accent = stageAccent(stage);
          const collapsed = collapsedStages[stage] ?? (leads.length > 0 && stageLeads.length === 0);

          if (collapsed) {
            return (
              <section key={stage} className="kanbanCol kanbanColCollapsed">
                <div
                  className="kanbanRail"
                  onClick={() => toggleStageCollapsed(stage, true)}
                  title={`Expand ${stageLabel(stage)}`}
                >
                  <span
                    className="kanbanRailCount"
                    style={{
                      color: stageLeads.length > 0 ? "var(--primary)" : "#c2cad4",
                      background: stageLeads.length > 0 ? "rgba(30,103,150,0.10)" : "#f1f5f9",
                    }}
                  >
                    {stageLeads.length}
                  </span>
                  <span className="kanbanRailLabel">{stageLabel(stage)}</span>
                </div>
              </section>
            );
          }

          return (
            <section key={stage} className="kanbanCol">
              <div className="kanbanColHeader">
                <span className="stageAccentBar" style={{ background: accent }} />
                <div style={{ fontWeight: 900, flex: 1, minWidth: 0 }}>{stageLabel(stage)}</div>
                <span className="chip"><b>{stageLeads.length}</b> leads</span>
                <button
                  type="button"
                  className="kanbanCollapseBtn"
                  title="Collapse"
                  onClick={() => toggleStageCollapsed(stage, false)}
                >
                  ‹
                </button>
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
                {stageLeads.map((l) => {
                  const age = daysSince(l.last_activity_at);
                  const fu = followupBadge(l.next_follow_up_at);
                  const confirmed = Boolean(l.latest_deal?.confirmation_sent_at);
                  const src = sourceMeta(l.lead_source);
                  const country = countryFromPhone(l.phone);
                  const value = depositValue(l.latest_deal?.amount);
                  const quote = l.latest_deal?.quote_amount != null && l.latest_deal.quote_amount > 0 ? l.latest_deal.quote_amount : null;
                  const serviceTag = (l.tags || []).find((t) => t.startsWith("service:"));
                  const serviceLabel = l.latest_deal?.treatment_interest || serviceTag?.replace("service:", "") || l.company || l.ad_name || l.campaign_name || null;
                  const extraTags = (l.tags || []).filter((t) => t !== serviceTag);
                  const showAvatar = cardStyle !== "minimal";
                  const showValue = cardStyle !== "minimal" && value != null;
                  const showQuote = cardStyle !== "minimal" && quote != null;
                  const showExtras = cardStyle !== "minimal";
                  return (
                    <div
                      key={l.id}
                      className={`cardMini cardStyle-${cardStyle} ${draggingId === l.id ? "cardMiniDragging" : ""}`}
                      data-density={cardStyle}
                      draggable
                      onDragStart={(e) => { e.dataTransfer.setData("text/plain", l.id); e.dataTransfer.effectAllowed = "move"; setDraggingId(l.id); }}
                      onDragEnd={() => setDraggingId(null)}
                      onClick={() => setSelected(l)}
                    >
                      {cardStyle === "accent" && <span className="cardAccentBar" style={{ background: src.color }} />}
                      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                        <label style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer", minWidth: 0, flex: 1 }} onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" checked={selectedIds.has(l.id)} onChange={() => toggleSelected(l.id)} onClick={(e) => e.stopPropagation()} style={{ marginTop: 2, accentColor: "var(--primary)" }} />
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                              <span style={{ fontWeight: 700, fontSize: 13, minWidth: 0, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.name}</span>
                              {country && <span className="countryBadge">{country}</span>}
                            </div>
                            {serviceLabel && <div className="serviceBadge">{serviceLabel}</div>}
                          </div>
                        </label>
                        {showAvatar && (
                          <span
                            className="ownerAvatar"
                            title={l.owner_email || undefined}
                            style={{ background: "rgba(30,103,150,0.10)", color: "var(--primary)" }}
                          >
                            {ownerInitials(l.owner_email)}
                          </span>
                        )}
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
                        <span className={`sourceBadge${cardStyle === "minimal" ? " sourceBadge-minimal" : ""}`} style={cardStyle === "minimal" ? undefined : { background: `${src.color}1f`, color: src.color }}>
                          <span className="sourceDot" style={{ background: src.color }} />
                          {src.label}
                        </span>
                        <span style={{ flex: 1 }} />
                        <span className="muted" style={{ fontSize: 11, whiteSpace: "nowrap" }}>{relLabel(age)}</span>
                      </div>

                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                        {fu && <span className="chipWarn">{fu}</span>}
                        {showQuote && <span className="chipQuote">Quote €{quote!.toLocaleString("en-US")}</span>}
                        {showValue && <span className="chipValue">Deposit €{value!.toLocaleString("en-US")}</span>}
                        {showExtras && confirmed && <span className="chip">✓ Confirmed</span>}
                        {showExtras && !confirmed && stage === "appointment_booked" && <span className="chip">⚠ Not confirmed</span>}
                        {showExtras && age != null && age >= 7 && <span className="chip">Last contact {age}d ago</span>}
                        {showExtras && l.latest_deal?.event_id && <span className="chip">Event assigned</span>}
                        {showExtras && !fu && l.bucket === "followup_due" && <span className="chip">Follow-up due</span>}
                      </div>
                      {showExtras && extraTags.length > 0 && (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                          {extraTags.slice(0, 3).map((t) => <span key={t} className="chip">{t}</span>)}
                          {extraTags.length > 3 && <span className="chip">+{extraTags.length - 3}</span>}
                        </div>
                      )}
                    </div>
                  );
                })}
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
