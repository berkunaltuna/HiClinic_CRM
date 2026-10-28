"use client";

import { CareShell } from "@/components/CareShell";

export default function AssistantLayout({ children }: { children: React.ReactNode }) {
  return (
    <CareShell role="doctor_assistant" title="Doctor's assistant" nav={[{ href: "/assistant", label: "Patients" }]}>
      {children}
    </CareShell>
  );
}
