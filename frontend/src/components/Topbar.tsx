"use client";

import { useRouter } from "next/navigation";
import { clearToken } from "@/lib/api";

export function Topbar({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  const router = useRouter();

  return (
    <div className="topbar">
      <div>
        <div style={{ fontSize: 18, fontWeight: 800 }}>{title}</div>
        <div className="muted" style={{ fontSize: 12 }}>{subtitle || "HiClinic CRM"}</div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {right}
        <button
          className="btn"
          onClick={() => {
            clearToken();
            router.replace("/login");
          }}
          title="Logout"
        >
          Logout
        </button>
      </div>
    </div>
  );
}
