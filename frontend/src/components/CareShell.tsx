"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearToken, getToken } from "@/lib/api";
import { fetchMe, homeFor, type Me } from "@/lib/useMe";

/**
 * Layout for the doctor and assistant interfaces: only their own sections, no CRM chrome.
 * Anyone else is sent to their home (the API enforces the same rules).
 */
export function CareShell({
  role,
  title,
  nav,
  children,
}: {
  role: "doctor" | "doctor_assistant";
  title: string;
  nav: { href: string; label: string }[];
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace(`/login?next=${encodeURIComponent(pathname || "/")}`);
      return;
    }
    fetchMe()
      .then((m) => {
        if (m.role !== role) router.replace(homeFor(m.role));
        else setMe(m);
      })
      .catch(() => router.replace("/login"));
  }, [role, router, pathname]);

  if (!me) {
    return (
      <div style={{ padding: 24 }} aria-live="polite">
        <div className="card" style={{ padding: 16, maxWidth: 520 }}>Checking session…</div>
      </div>
    );
  }

  return (
    <div className="careShell">
      <header className="careHeader">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.png" alt="" width={32} height={32} style={{ borderRadius: 8 }} />
          <div>
            <div style={{ fontWeight: 900 }}>{title}</div>
            <div className="muted" style={{ fontSize: 12 }}>{me.email}</div>
          </div>
        </div>
        <nav aria-label={`${title} navigation`} className="careNav">
          {nav.map((n) => {
            const active = pathname === n.href || pathname?.startsWith(n.href + "/");
            return (
              <Link key={n.href} href={n.href} className={`btn ${active ? "btnPrimary" : ""}`.trim()} aria-current={active ? "page" : undefined}>
                {n.label}
              </Link>
            );
          })}
        </nav>
        <button
          className="btn"
          onClick={() => {
            clearToken();
            router.replace("/login");
          }}
        >
          Logout
        </button>
      </header>
      <main className="careMain">{children}</main>
    </div>
  );
}
