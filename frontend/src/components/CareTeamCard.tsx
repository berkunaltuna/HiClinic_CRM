"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ProformaPanel } from "@/components/ProformaPanel";
import { useMe } from "@/lib/useMe";
import { type PersonOut, errorDetail } from "@/lib/photoRequests";

const PROFORMA_ROLES = ["admin", "manager", "coordinator"];

/** Contact page: the patient's assigned doctor (admin can change it) and proforma invoice. */
export function CareTeamCard({ customerId }: { customerId: string }) {
  const toast = useToast();
  const { me } = useMe();
  const [doctor, setDoctor] = useState<PersonOut | null | undefined>(undefined);
  const [doctors, setDoctors] = useState<PersonOut[]>([]);
  const [saving, setSaving] = useState(false);
  const isAdmin = me?.role === "admin";

  useEffect(() => {
    apiFetch<PersonOut | null>(`/care/patients/${customerId}/doctor`).then(setDoctor).catch(() => setDoctor(null));
  }, [customerId]);
  useEffect(() => {
    if (isAdmin) apiFetch<PersonOut[]>("/care/doctors").then(setDoctors).catch(() => setDoctors([]));
  }, [isAdmin]);

  async function change(doctorId: string) {
    setSaving(true);
    try {
      setDoctor(await apiFetch<PersonOut | null>(`/care/patients/${customerId}/doctor`, { method: "PUT", body: JSON.stringify({ doctor_user_id: doctorId || null }) }));
      toast.push(doctorId ? "Doctor assigned" : "Doctor unassigned");
    } catch (err: any) {
      toast.push(errorDetail(err, "Could not change the doctor"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card" aria-labelledby="care-team-h">
      <div className="cardHeader" id="care-team-h" style={{ fontWeight: 900 }}>Care team</div>
      <div className="cardBody" style={{ display: "grid", gap: 12 }}>
        <div style={{ display: "grid", gap: 4 }}>
          <label htmlFor="assigned-doctor" className="muted" style={{ fontSize: 12 }}>Assigned doctor</label>
          {isAdmin ? (
            <select id="assigned-doctor" value={doctor?.id || ""} disabled={saving || doctor === undefined} onChange={(e) => void change(e.target.value)}>
              <option value="">Not assigned</option>
              {doctors.map((d) => <option key={d.id} value={d.id}>{d.display_name ? `${d.display_name} (${d.email})` : d.email}</option>)}
            </select>
          ) : (
            <div id="assigned-doctor" style={{ fontWeight: 700 }}>
              {doctor === undefined ? "…" : doctor ? doctor.display_name || doctor.email : "Not assigned"}
            </div>
          )}
          <div className="muted" style={{ fontSize: 12 }}>The doctor and their assistants see this patient in their own interface.</div>
        </div>
        {me && PROFORMA_ROLES.includes(me.role) && (
          <div style={{ display: "grid", gap: 4 }}>
            <div className="muted" style={{ fontSize: 12 }}>Proforma invoice (shown to the patient in their portal)</div>
            <ProformaPanel customerId={customerId} canUpload />
          </div>
        )}
      </div>
    </section>
  );
}
