"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import { IssuedLink, onPhotoRequestChanged, openPhotoRequestWindow } from "@/components/PhotoRequestView";
import { NewPhotoRequestForm } from "@/components/NewPhotoRequestForm";
import { type CarePatientDetailOut, EMAIL_STATUS_LABELS, photoStatusLabel } from "@/lib/photoRequests";

export default function DoctorPatientPage() {
  const toast = useToast();
  const id = String(useParams().id);
  const [p, setP] = useState<CarePatientDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<string | null>(null);

  async function load() {
    try {
      setP(await apiFetch<CarePatientDetailOut>(`/care/patients/${id}`));
      setError(null);
    } catch (err: any) {
      setError(err?.status === 404 ? "This patient is not assigned to you." : "Could not load the patient.");
    }
  }

  useEffect(() => { void load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  // Refresh when the request is changed in its own window.
  useEffect(() => onPhotoRequestChanged(() => void load()), [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) {
    return (
      <div className="card" style={{ padding: 16 }} role="alert">
        {error} <Link href="/doctor/patients">Back to my patients</Link>
      </div>
    );
  }
  if (!p) return <div className="muted" aria-live="polite">Loading…</div>;

  return (
    <>
      <div>
        <Link href="/doctor/patients" className="muted" style={{ fontSize: 13 }}>← My patients</Link>
        <h1 style={{ fontSize: 20, margin: "6px 0 0" }}>{p.name}</h1>
        {p.treatment_interest && <div className="muted">{p.treatment_interest}</div>}
      </div>
      <section className="card" aria-labelledby="req-h">
        <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div id="req-h" style={{ fontWeight: 900 }}>Photo requests</div>
          {!creating && <button className="btn btnPrimary" onClick={() => { setCreating(true); setIssued(null); }}>Request photos</button>}
        </div>
        <div className="cardBody" style={{ display: "grid", gap: 10 }}>
          {issued && <IssuedLink url={issued} />}
          {creating && (
            <NewPhotoRequestForm
              customerId={id}
              showAppointment={false}
              onCancel={() => setCreating(false)}
              onCreated={(out) => {
                setCreating(false);
                setIssued(out.portal_url);
                toast.push(out.email ? `Photo request emailed to the patient` : "Photo request created");
                void load();
              }}
            />
          )}
          {!p.requests.length ? (
            <div className="muted">No photo requests yet.</div>
          ) : (
            <div className="tableWrap">
              <table className="table">
                <thead><tr><th>Request</th><th>Status</th><th>Photos</th><th>Updated</th><th><span className="sr-only">Open</span></th></tr></thead>
                <tbody>
                  {p.requests.map((r) => (
                    <tr key={r.id}>
                      <td style={{ fontWeight: 700 }}>{r.title}</td>
                      <td>
                        <span className="badge">{photoStatusLabel(r.status)}</span>
                        {r.email_status && <div className="muted" style={{ fontSize: 11 }}>{EMAIL_STATUS_LABELS[r.email_status] || r.email_status}</div>}
                      </td>
                      <td className="muted">{r.photo_count}</td>
                      <td className="muted">{fmtDateTime(r.updated_at)}</td>
                      <td><button className="btn" onClick={() => openPhotoRequestWindow(r.id)} aria-label={`Open ${r.title} in a new window`}>Open</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
