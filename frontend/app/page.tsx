"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";
import { fetchMe, homeFor } from "@/lib/useMe";

export default function IndexPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    fetchMe()
      .then((me) => router.replace(homeFor(me.role)))
      .catch(() => router.replace("/login"));
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
