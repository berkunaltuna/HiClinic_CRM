"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { CarePatientList } from "@/components/CarePatientList";
import type { PersonOut } from "@/lib/photoRequests";

export default function AssistantPage() {
  const [doctors, setDoctors] = useState<PersonOut[] | null>(null);
  useEffect(() => {
    apiFetch<{ doctors: PersonOut[] }>("/care/me").then((m) => setDoctors(m.doctors)).catch(() => setDoctors([]));
  }, []);
  return (
    <>
      <div>
        <h1 style={{ fontSize: 20, margin: 0 }}>Patients</h1>
        <div className="muted" style={{ fontSize: 13 }}>
          {doctors === null
            ? "Loading…"
            : doctors.length
              ? `Patients of ${doctors.map((d) => d.display_name || d.email).join(", ")}`
              : "You are not assigned to a doctor yet. Ask an administrator."}
        </div>
      </div>
      <CarePatientList showDoctor={(doctors?.length || 0) > 1} proformas />
    </>
  );
}
