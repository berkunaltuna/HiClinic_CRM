"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL, getToken } from "@/lib/api";
import { apiFetch } from "@/lib/api";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import { type ProformaOut, errorDetail, fetchStaffFileUrl, fmtBytes, xhrUpload } from "@/lib/photoRequests";

/** A patient's proforma invoice: current file, history, upload/replace and open. */
export function ProformaPanel({ customerId, canUpload, compact = false }: { customerId: string; canUpload: boolean; compact?: boolean }) {
  const toast = useToast();
  const [info, setInfo] = useState<ProformaOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const inputId = `proforma-file-${customerId}`;

  async function load() {
    try {
      setInfo(await apiFetch<ProformaOut>(`/customers/${customerId}/proforma`));
      setError(null);
    } catch (err: any) {
      setError(err?.status === 403 ? "Your role cannot view proformas." : err?.status === 404 ? "Patient not found." : "Could not load the proforma.");
    }
  }

  useEffect(() => {
    void load();
  }, [customerId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function upload(file: File) {
    if (!info) return;
    const ext = file.name.split(".").pop()?.toLowerCase() || "";
    if (!info.allowed_extensions.includes(ext)) {
      toast.push("Proforma invoices must be PDF files", "error");
      return;
    }
    if (file.size > info.max_file_size_bytes) {
      toast.push(`The file is larger than ${fmtBytes(info.max_file_size_bytes)}`, "error");
      return;
    }
    if (info.current && !confirm("Replace the current proforma? The old one is kept in the history but patients will only see the new one.")) return;
    setProgress(0);
    try {
      await xhrUpload(
        `${API_URL}/customers/${customerId}/proforma?filename=${encodeURIComponent(file.name)}`,
        file,
        getToken() || "",
        file.type || "application/pdf",
        setProgress,
      ).promise;
      toast.push(info.current ? "Proforma replaced" : "Proforma uploaded");
      await load();
    } catch (err: any) {
      toast.push(errorDetail(err, "Upload failed"), "error");
    } finally {
      setProgress(null);
    }
  }

  async function open(docId: string, download = false) {
    try {
      const url = await fetchStaffFileUrl(`/customers/${customerId}/proforma/${docId}/content${download ? "?download=true" : ""}`);
      if (download) {
        const a = document.createElement("a");
        a.href = url;
        a.download = `proforma-${docId}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      } else {
        window.open(url, "_blank", "noopener,noreferrer");
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      toast.push("Could not open the document", "error");
    }
  }

  if (error) return <div className="muted" role="alert">{error}</div>;
  if (!info) return <div className="muted" aria-live="polite">Loading…</div>;

  return (
    <div style={{ display: "grid", gap: 8 }}>
      {info.current ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span className="badge">Proforma available</span>
          <span className="muted" style={{ fontSize: 12 }}>
            {info.current.original_filename} · {fmtBytes(info.current.size_bytes)} · {fmtDateTime(info.current.uploaded_at)}
            {info.current.uploaded_by_email ? ` · ${info.current.uploaded_by_email}` : ""}
          </span>
          <button className="btn" style={{ padding: "4px 10px", fontSize: 12 }} onClick={() => open(info.current!.id)}>Open</button>
        </div>
      ) : (
        <div className="muted">No proforma uploaded yet.</div>
      )}
      {canUpload && (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label htmlFor={inputId} className="btn" style={{ cursor: "pointer", padding: "4px 10px", fontSize: 12 }}>
            {info.current ? "Replace proforma (PDF)" : "Upload proforma (PDF)"}
          </label>
          <input
            ref={input}
            id={inputId}
            type="file"
            accept=".pdf,application/pdf"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void upload(f);
            }}
          />
          {progress !== null && (
            <div className="progress" style={{ width: 120 }} role="progressbar" aria-label="Uploading proforma" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
              <div style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
          )}
        </div>
      )}
      {!compact && info.history.length > 1 && (
        <details>
          <summary className="muted" style={{ fontSize: 12, cursor: "pointer" }}>Previous versions ({info.history.length - 1})</summary>
          <ul style={{ fontSize: 12, paddingLeft: 18 }}>
            {info.history.filter((d) => d.superseded_at).map((d) => (
              <li key={d.id}>
                {d.original_filename} · {fmtDateTime(d.uploaded_at)} · replaced {fmtDateTime(d.superseded_at)}{" "}
                <button className="btn" style={{ padding: "2px 8px", fontSize: 11 }} onClick={() => open(d.id, true)}>Download</button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
