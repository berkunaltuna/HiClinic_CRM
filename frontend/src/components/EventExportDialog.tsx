"use client";

import { useState } from "react";
import { apiDownloadFile } from "@/lib/api";
import type { EventOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

export function EventExportDialog({ event, onClose }: { event: EventOut; onClose: () => void }) {
  const toast = useToast();
  const [day, setDay] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function doExport() {
    setBusy(true);
    try {
      const params = new URLSearchParams();
      if (day) params.set("day", day);
      if (status) params.set("status", status);
      const qs = params.toString();
      const filename = `${event.name.replace(/\s+/g, "_")}-bookings.xlsx`;
      await apiDownloadFile(`/events/${event.id}/export.xlsx${qs ? `?${qs}` : ""}`, filename);
      onClose();
    } catch (err: any) {
      toast.push(err?.message || "Failed to export bookings", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modalOverlay" onClick={onClose}>
      <div className="modal" style={{ width: "min(480px, 96vw)" }} onClick={(e) => e.stopPropagation()}>
        <div className="modalHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 900 }}>Export bookings</div>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        <div className="modalBody stack">
          <label className="stack" style={{ gap: 6 }}>
            <span className="muted" style={{ fontSize: 12 }}>Day</span>
            <select className="formField" value={day} onChange={(e) => setDay(e.target.value)}>
              <option value="">All days</option>
              {event.days.map((d) => <option key={d.id} value={d.day}>{d.label || d.day}</option>)}
            </select>
          </label>
          <label className="stack" style={{ gap: 6 }}>
            <span className="muted" style={{ fontSize: 12 }}>Status</span>
            <select className="formField" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              <option value="booked">Booked</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>
          <div>
            <button className="btn btnPrimary" disabled={busy} onClick={doExport}>{busy ? "Exporting…" : "Export"}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
