"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";

export default function IndexPage() {
  const router = useRouter();

  useEffect(() => {
    const token = getToken();
    router.replace(token ? "/dashboard" : "/login");
  }, [router]);

  return (
    <main style={{ padding: 24 }}>
      <div className="card" style={{ padding: 16, maxWidth: 520 }}>
        <div style={{ fontWeight: 800 }}>Loading…</div>
        <div className="muted">Redirecting…</div>
      </div>
    </main>
  );
}
