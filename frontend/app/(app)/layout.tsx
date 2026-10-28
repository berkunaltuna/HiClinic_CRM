"use client";

import { Sidebar } from "@/components/Sidebar";
import { useRequireAuth } from "@/lib/useRequireAuth";
import { CARE_HOME, fetchMe } from "@/lib/useMe";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { isReady } = useRequireAuth();
  const router = useRouter();
  // The CRM is not for doctors/assistants (the API refuses them too): send them to their own area.
  const [roleOk, setRoleOk] = useState(false);
  useEffect(() => {
    if (!isReady) return;
    fetchMe()
      .then((me) => {
        if (CARE_HOME[me.role]) router.replace(CARE_HOME[me.role]);
        else setRoleOk(true);
      })
      .catch(() => router.replace("/login"));
  }, [isReady, router]);

  const storageKey = "hiclinic.sidebarCollapsed";
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      const v = window.localStorage.getItem(storageKey);
      if (v === "1") setCollapsed(true);
    } catch {
      // ignore
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onToggle = useMemo(
    () =>
      () => {
        setCollapsed((prev) => {
          const next = !prev;
          try {
            window.localStorage.setItem(storageKey, next ? "1" : "0");
          } catch {
            // ignore
          }
          return next;
        });
      },
    []
  );

  if (!isReady || !roleOk) {
    return (
      <div style={{ padding: 24 }}>
        <div className="card" style={{ padding: 16, maxWidth: 520 }}>
          <div style={{ fontWeight: 800 }}>Checking session…</div>
          <div className="muted">Please sign in</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`layout ${collapsed ? "layoutCollapsed" : ""}`.trim()}>
      <Sidebar collapsed={collapsed} onToggle={onToggle} />
      <div className="content">{children}</div>
    </div>
  );
}
