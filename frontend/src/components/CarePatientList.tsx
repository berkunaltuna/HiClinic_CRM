"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { fmtDateTime } from "@/lib/dates";
import { ProformaPanel } from "@/components/ProformaPanel";
import { type CarePatientOut, EMAIL_STATUS_LABELS, photoStatusLabel } from "@/lib/photoRequests";

const FILTERS = [
  { label: "All", value: "" },
  { label: "Awaiting photos", value: "requested,more_photos_needed" },
  { label: "Photos uploaded", value: "uploaded,in_review" },
  { label: "Reviewed", value: "reviewed" },
];

/** Assigned patients with their latest photo-request status (scoped by the API). */
export function CarePatientList({
  patientHref,
  showDoctor = false,
  proformas = false,
}: {
  patientHref?: (id: string) => string;
  showDoctor?: boolean;
  proformas?: boolean;
}) {
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<CarePatientOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openProforma, setOpenProforma] = useState<string | null>(null);

  async function load() {
    setItems(null);
    try {
      setItems(await apiFetch<CarePatientOut[]>(`/care/patients${filter ? `?status=${encodeURIComponent(filter)}` : ""}`));
      setError(null);
    } catch (err: any) {
      setError(err?.status === 403 ? "Your role cannot view this list." : "Could not load patients.");
      setItems([]);
    }
  }

  useEffect(() => { void load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = (items || []).filter((p) => !query.trim() || p.name.toLowerCase().includes(query.trim().toLowerCase()));

  return (
    <section className="card">
      <div className="cardHeader" style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }} role="group" aria-label="Filter by photo status">
          {FILTERS.map((f) => (
            <button key={f.label} className={`btn ${filter === f.value ? "btnPrimary" : ""}`.trim()} aria-pressed={filter === f.value} onClick={() => setFilter(f.value)}>
              {f.label}
            </button>
          ))}
        </div>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span className="sr-only">Search patients</span>
          <input type="search" placeholder="Search by name" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
      </div>
      <div className="cardBody">
        {error && <div role="alert" className="muted">{error}</div>}
        {items === null ? (
          <div className="muted" aria-live="polite">Loading…</div>
        ) : !shown.length && !error ? (
          <div className="muted">{items.length ? "No patients match." : "No patients are assigned yet. An administrator assigns patients."}</div>
        ) : (
          <div className="tableWrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Patient</th>
                  {showDoctor && <th>Doctor</th>}
                  <th>Photo request</th>
                  <th>Photos</th>
                  {proformas && <th>Proforma</th>}
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((p) => {
                  const r = p.latest_request;
                  return (
                    <tr key={p.id}>
                      <td>
                        {patientHref ? <Link href={patientHref(p.id)} style={{ fontWeight: 700 }}>{p.name}</Link> : <b>{p.name}</b>}
                        {p.treatment_interest && <div className="muted" style={{ fontSize: 12 }}>{p.treatment_interest}</div>}
                      </td>
                      {showDoctor && <td className="muted">{p.doctor ? p.doctor.display_name || p.doctor.email : "—"}</td>}
                      <td>
                        {r ? (
                          <>
                            <span className="badge">{photoStatusLabel(r.status)}</span>
                            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                              {r.title}
                              {r.email_status ? ` · ${EMAIL_STATUS_LABELS[r.email_status] || r.email_status}` : ""}
                            </div>
                          </>
                        ) : (
                          <span className="muted">No requests</span>
                        )}
                      </td>
                      <td>
                        {r ? (
                          r.photos_uploaded ? <span className="badge" style={{ borderColor: "var(--success)" }}>✓ Uploaded ({r.photo_count})</span> : <span className="muted">Not yet</span>
                        ) : "—"}
                      </td>
                      {proformas && (
                        <td>
                          <span className="muted" style={{ fontSize: 12 }}>{p.proforma?.available ? "✓ Available" : "None"}</span>{" "}
                          <button className="btn" style={{ padding: "4px 10px", fontSize: 12 }} onClick={() => setOpenProforma(openProforma === p.id ? null : p.id)} aria-expanded={openProforma === p.id}>
                            {openProforma === p.id ? "Close" : "Manage"}
                          </button>
                        </td>
                      )}
                      <td className="muted">{r ? fmtDateTime(r.updated_at) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {openProforma && (
          <div className="card" style={{ padding: 12, marginTop: 12 }} aria-label="Proforma">
            <div style={{ fontWeight: 800, marginBottom: 8 }}>Proforma · {items?.find((p) => p.id === openProforma)?.name}</div>
            <ProformaPanel customerId={openProforma} canUpload />
          </div>
        )}
      </div>
    </section>
  );
}
