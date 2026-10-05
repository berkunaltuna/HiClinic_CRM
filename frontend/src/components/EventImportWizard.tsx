"use client";

import { useEffect, useMemo, useState } from "react";
import { apiDownloadFile, apiFetch, apiUpload } from "@/lib/api";
import type { EventOut, ImportFieldMapping, ImportResultOut, ImportUploadOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

type Step = "upload" | "map" | "preview" | "results";

const TARGET_FIELDS: { key: string; label: string; required?: boolean }[] = [
  { key: "name", label: "Name", required: true },
  { key: "phone", label: "Phone" },
  { key: "email", label: "Email" },
  { key: "date", label: "Date", required: true },
  { key: "appointment_time", label: "Appointment Time", required: true },
  { key: "booking_status", label: "Booking Status" },
  { key: "treatment_interest", label: "Treatment Interest" },
  { key: "notes", label: "Notes" },
  { key: "customer_id", label: "Customer ID" },
  { key: "booking_id", label: "Booking ID" },
  { key: "event", label: "Event (checked against the selected event)" },
];

const STATUS_LABEL: Record<string, string> = {
  created: "Will create",
  updated: "Will update",
  unchanged: "Already up to date",
  flagged: "Needs review",
  error: "Error",
  pending: "Pending",
};

const STATUS_COLOR: Record<string, string> = {
  created: "#10b981",
  updated: "#3b82f6",
  unchanged: "#94a3b8",
  flagged: "#f59e0b",
  error: "#ef4444",
  pending: "#94a3b8",
};

export function EventImportWizard({
  eventId,
  onClose,
  onImported,
}: {
  eventId?: string;
  onClose: () => void;
  onImported: () => void;
}) {
  const toast = useToast();
  const [step, setStep] = useState<Step>("upload");
  const [events, setEvents] = useState<EventOut[]>([]);
  const [selectedEventId, setSelectedEventId] = useState(eventId || "");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  const [upload, setUpload] = useState<ImportUploadOut | null>(null);
  const [mapping, setMapping] = useState<ImportFieldMapping>({});
  const [preview, setPreview] = useState<ImportResultOut | null>(null);
  const [result, setResult] = useState<ImportResultOut | null>(null);

  useEffect(() => {
    if (!eventId) {
      apiFetch<EventOut[]>("/events").then(setEvents).catch((err: any) => toast.push(err?.message || "Failed to load events", "error"));
    }
  }, [eventId]); // eslint-disable-line react-hooks/exhaustive-deps

  const targetEventId = eventId || selectedEventId;

  async function doUpload() {
    if (!targetEventId || !file) return;
    setBusy(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await apiUpload<ImportUploadOut>(`/events/${targetEventId}/imports/upload`, formData);
      setUpload(res);
      setMapping(res.suggested_mapping);
      setStep("map");
    } catch (err: any) {
      toast.push(err?.message || "Failed to upload file", "error");
    } finally {
      setBusy(false);
    }
  }

  async function doPreview() {
    if (!upload) return;
    setBusy(true);
    try {
      const res = await apiFetch<ImportResultOut>(`/events/${targetEventId}/imports/${upload.batch_id}/preview`, {
        method: "POST",
        body: JSON.stringify({ mapping }),
      });
      setPreview(res);
      setStep("preview");
    } catch (err: any) {
      toast.push(err?.message || "Failed to preview import", "error");
    } finally {
      setBusy(false);
    }
  }

  async function doCommit() {
    if (!upload) return;
    setBusy(true);
    try {
      const res = await apiFetch<ImportResultOut>(`/events/${targetEventId}/imports/${upload.batch_id}/commit`, {
        method: "POST",
      });
      setResult(res);
      setStep("results");
      onImported();
    } catch (err: any) {
      toast.push(err?.message || "Failed to commit import", "error");
    } finally {
      setBusy(false);
    }
  }

  async function downloadErrors() {
    if (!upload) return;
    try {
      await apiDownloadFile(`/events/${targetEventId}/imports/${upload.batch_id}/errors.xlsx`, "import-errors.xlsx");
    } catch (err: any) {
      toast.push(err?.message || "Failed to download error report", "error");
    }
  }

  const counts = (preview || result)?.batch;
  const committable = preview ? preview.batch.row_count - preview.batch.rows_flagged > 0 : false;
  const canCommit = preview?.batch.status === "previewed" && committable;

  const groupedReasons = useMemo(() => {
    if (!preview) return [];
    return preview.rows.filter((r) => r.status === "flagged" || r.status === "error");
  }, [preview]);

  return (
    <div className="modalOverlay" onClick={onClose}>
      <div className="modal" style={{ width: "min(960px, 96vw)" }} onClick={(e) => e.stopPropagation()}>
        <div className="modalHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 900 }}>Import bookings {step !== "upload" ? `— ${step}` : ""}</div>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        <div className="modalBody stack">
          {step === "upload" && (
            <div className="stack">
              {!eventId && (
                <label className="stack" style={{ gap: 6 }}>
                  <span className="muted" style={{ fontSize: 12 }}>Event</span>
                  <select className="formField" value={selectedEventId} onChange={(e) => setSelectedEventId(e.target.value)}>
                    <option value="">Select event…</option>
                    {events.map((ev) => (
                      <option key={ev.id} value={ev.id}>{ev.name} ({ev.starts_on})</option>
                    ))}
                  </select>
                </label>
              )}
              <label className="stack" style={{ gap: 6 }}>
                <span className="muted" style={{ fontSize: 12 }}>File (.xlsx or .csv)</span>
                <input
                  type="file"
                  accept=".xlsx,.csv"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
              </label>
              <div>
                <button className="btn btnPrimary" disabled={!targetEventId || !file || busy} onClick={doUpload}>
                  {busy ? "Uploading…" : "Upload"}
                </button>
              </div>
            </div>
          )}

          {step === "map" && upload && (
            <div className="stack">
              <div className="muted">{upload.row_count} rows detected. Map each field to a column from your file.</div>
              <table className="table">
                <thead><tr><th>Field</th><th>Column</th></tr></thead>
                <tbody>
                  {TARGET_FIELDS.map((f) => (
                    <tr key={f.key}>
                      <td>{f.label}{f.required ? " *" : ""}</td>
                      <td>
                        <select
                          className="formField"
                          value={mapping[f.key] || ""}
                          onChange={(e) => setMapping((m) => ({ ...m, [f.key]: e.target.value }))}
                        >
                          <option value="">— not mapped —</option>
                          {upload.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn" onClick={() => setStep("upload")}>Back</button>
                <button className="btn btnPrimary" disabled={busy} onClick={doPreview}>{busy ? "Checking…" : "Preview"}</button>
              </div>
            </div>
          )}

          {step === "preview" && preview && counts && (
            <div className="stack">
              <div className="grid" style={{ gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
                <StatTile label="New customers" value={counts.customers_created} />
                <StatTile label="Customers updated" value={counts.customers_updated} />
                <StatTile label="Duplicates merged" value={counts.duplicates_merged} />
                <StatTile label="Bookings created/updated" value={counts.bookings_created + counts.bookings_updated} />
                <StatTile label="Needs review" value={counts.rows_flagged} color={counts.rows_flagged ? "#f59e0b" : undefined} />
              </div>
              <div style={{ maxHeight: 360, overflowY: "auto" }}>
                <table className="table">
                  <thead><tr><th>#</th><th>Name</th><th>Status</th><th>Reasons</th></tr></thead>
                  <tbody>
                    {preview.rows.map((r) => (
                      <tr key={r.id}>
                        <td>{r.row_number}</td>
                        <td>{(r.mapped_data?.customer_name as string) || r.raw_data[mapping.name || ""] || "—"}</td>
                        <td><span className="chip" style={{ background: STATUS_COLOR[r.status], color: "#fff" }}>{STATUS_LABEL[r.status] || r.status}</span></td>
                        <td className="muted">{(r.reasons || []).join("; ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ display: "flex", gap: 8, justifyContent: "space-between" }}>
                <button className="btn" onClick={() => setStep("map")}>Back to mapping</button>
                <button className="btn btnPrimary" disabled={!canCommit || busy} onClick={doCommit}>
                  {busy ? "Importing…" : "Confirm import"}
                </button>
              </div>
            </div>
          )}

          {step === "results" && result && counts && (
            <div className="stack">
              <div className="grid" style={{ gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
                <StatTile label="Customers created" value={counts.customers_created} />
                <StatTile label="Customers updated" value={counts.customers_updated} />
                <StatTile label="Already up to date" value={counts.rows_unchanged} />
                <StatTile label="Bookings created" value={counts.bookings_created} />
                <StatTile label="Bookings updated" value={counts.bookings_updated} />
              </div>
              {counts.rows_flagged > 0 && (
                <div className="card" style={{ boxShadow: "none" }}>
                  <div className="cardHeader">
                    <b>{counts.rows_flagged} row(s) need review</b>
                  </div>
                  <div className="cardBody">
                    <button className="btn" onClick={downloadErrors}>Download error report</button>
                    <ul style={{ marginTop: 10 }}>
                      {groupedReasons.slice(0, 10).map((r) => (
                        <li key={r.id} className="muted">Row {r.row_number}: {(r.reasons || []).join("; ")}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              <div>
                <button className="btn btnPrimary" onClick={onClose}>Done</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatTile({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="card" style={{ boxShadow: "none", textAlign: "center" }}>
      <div className="cardBody">
        <div style={{ fontSize: 24, fontWeight: 900, color }}>{value}</div>
        <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      </div>
    </div>
  );
}
