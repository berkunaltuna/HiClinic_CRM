"use client";

import { CarePatientList } from "@/components/CarePatientList";

export default function DoctorPatientsPage() {
  return (
    <>
      <h1 style={{ fontSize: 20, margin: 0 }}>My patients</h1>
      <CarePatientList patientHref={(id) => `/doctor/patients/${id}`} />
    </>
  );
}
