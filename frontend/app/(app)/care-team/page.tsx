"use client";

import { useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { type DoctorProfileOut, type PersonOut, errorDetail } from "@/lib/photoRequests";

type DoctorSummary = PersonOut & { patient_count: number; assistants: PersonOut[]; profile: DoctorProfileOut | null };
type AssistantSummary = PersonOut & { doctors: PersonOut[] };

/** Admin: doctor profiles shown to patients, and which doctors each assistant works for. */
export default function CareTeamPage() {
  const toast = useToast();
  const [doctors, setDoctors] = useState<DoctorSummary[] | null>(null);
  const [assistants, setAssistants] = useState<AssistantSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  async function load() {
    try {
      const [d, a] = await Promise.all([apiFetch<DoctorSummary[]>("/care/doctors"), apiFetch<AssistantSummary[]>("/care/assistants")]);
      setDoctors(d);
      setAssistants(a);
      setError(null);
    } catch (err: any) {
      setError(err?.status === 403 ? "Only administrators can manage the care team." : "Could not load the care team.");
      setDoctors([]);
    }
  }

  useEffect(() => { void load(); }, []);

  async function setAssistantDoctors(a: AssistantSummary, doctorIds: string[]) {
    try {
      await apiFetch(`/care/assistants/${a.id}/doctors`, { method: "PUT", body: JSON.stringify({ doctor_user_ids: doctorIds }) });
      toast.push("Assistant updated");
      await load();
    } catch (err: any) {
      toast.push(errorDetail(err, "Could not update the assistant"), "error");
    }
  }

  return (
    <div className="stack">
      <Topbar title="Care team" subtitle="Doctors, their patient-facing profiles and assistants" />
      {error && <div className="card" style={{ padding: 16 }} role="alert">{error}</div>}
      <div className="muted" style={{ fontSize: 13 }}>
        Create doctor and assistant accounts on the Users page (roles <b>doctor</b> and <b>doctor_assistant</b>). Assign patients to a doctor from the patient&apos;s contact page.
      </div>

      <section className="card" aria-labelledby="doctors-h">
        <div className="cardHeader" id="doctors-h" style={{ fontWeight: 900 }}>Doctors</div>
        <div className="cardBody" style={{ display: "grid", gap: 10 }}>
          {doctors === null ? <div className="muted">Loading…</div> : !doctors.length ? <div className="muted">No doctor accounts yet.</div> : doctors.map((d) => (
            <div key={d.id} style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 10, display: "grid", gap: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <div>
                  <b>{d.profile?.display_name || d.email}</b> <span className="muted" style={{ fontSize: 12 }}>{d.email}</span>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {d.patient_count} patient{d.patient_count === 1 ? "" : "s"} · assistants: {d.assistants.length ? d.assistants.map((a) => a.email).join(", ") : "none"} ·
                    profile {d.profile?.visible_to_patients && d.profile.display_name ? "shown to patients" : "not shown to patients"}
                  </div>
                </div>
                <button className="btn" onClick={() => setEditing(editing === d.id ? null : d.id)} aria-expanded={editing === d.id}>
                  {editing === d.id ? "Close" : "Edit patient-facing profile"}
                </button>
              </div>
              {editing === d.id && <ProfileForm doctor={d} onSaved={() => { setEditing(null); void load(); }} />}
            </div>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="assistants-h">
        <div className="cardHeader" id="assistants-h" style={{ fontWeight: 900 }}>Assistants</div>
        <div className="cardBody" style={{ display: "grid", gap: 10 }}>
          {!assistants.length ? <div className="muted">No assistant accounts yet.</div> : assistants.map((a) => (
            <fieldset key={a.id} style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 10 }}>
              <legend style={{ fontWeight: 700 }}>{a.email}</legend>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Works for:</div>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                {(doctors || []).map((d) => {
                  const on = a.doctors.some((x) => x.id === d.id);
                  return (
                    <label key={d.id} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => setAssistantDoctors(a, on ? a.doctors.filter((x) => x.id !== d.id).map((x) => x.id) : [...a.doctors.map((x) => x.id), d.id])}
                      />
                      {d.profile?.display_name || d.email}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          ))}
        </div>
      </section>
    </div>
  );
}

function ProfileForm({ doctor, onSaved }: { doctor: DoctorSummary; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({
    display_name: doctor.profile?.display_name || "",
    title: doctor.profile?.title || "",
    specialty: doctor.profile?.specialty || "",
    bio: doctor.profile?.bio || "",
    visible_to_patients: doctor.profile?.visible_to_patients || false,
  });
  const [saving, setSaving] = useState(false);
  const id = (k: string) => `${doctor.id}-${k}`;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await apiFetch(`/care/doctors/${doctor.id}/profile`, { method: "PUT", body: JSON.stringify(f) });
      toast.push("Profile saved");
      onSaved();
    } catch (err: any) {
      toast.push(errorDetail(err, "Could not save"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} style={{ display: "grid", gap: 6 }}>
      <div className="muted" style={{ fontSize: 12 }}>Patients see only what you enter here. Leave a field empty to hide it. Don&apos;t enter qualifications you haven&apos;t verified.</div>
      {(["display_name", "title", "specialty"] as const).map((k) => (
        <div key={k} style={{ display: "grid", gap: 2 }}>
          <label htmlFor={id(k)} style={{ fontSize: 12, fontWeight: 700 }}>{k === "display_name" ? "Name shown to patients" : k === "title" ? "Title (e.g. Consultant)" : "Specialty"}</label>
          <input id={id(k)} className="formField" value={f[k]} maxLength={200} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
        </div>
      ))}
      <label htmlFor={id("bio")} style={{ fontSize: 12, fontWeight: 700 }}>Short introduction</label>
      <textarea id={id("bio")} rows={3} maxLength={4000} value={f.bio} onChange={(e) => setF({ ...f, bio: e.target.value })} />
      <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input type="checkbox" checked={f.visible_to_patients} onChange={(e) => setF({ ...f, visible_to_patients: e.target.checked })} />
        Show this profile to the doctor&apos;s patients in their photo portal (needs a name)
      </label>
      <button className="btn btnPrimary" type="submit" disabled={saving} style={{ justifySelf: "start" }}>{saving ? "Saving…" : "Save profile"}</button>
    </form>
  );
}
