"use client";

import { useRouter } from "next/navigation";
import { clearToken } from "@/lib/api";

export function Topbar({ title, right }: { title: string; right?: React.ReactNode }) {
  const router = useRouter();

  return (
    <div className="topbar">
      <div>
        <div style={{ fontSize: 18, fontWeight: 800 }}>{title}</div>
        <div className="muted" style={{ fontSize: 12 }}>HiClinic CRM</div>
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
