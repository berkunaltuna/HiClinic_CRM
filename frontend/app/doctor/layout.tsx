"use client";

import { CareShell } from "@/components/CareShell";

export default function DoctorLayout({ children }: { children: React.ReactNode }) {
  return (
    <CareShell
      role="doctor"
      title="Doctor"
      nav={[
        { href: "/doctor/patients", label: "Patients" },
        { href: "/doctor/photos", label: "Photos" },
      ]}
    >
      {children}
    </CareShell>
  );
}
