"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe } from "@/lib/useMe";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/contacts", label: "Contacts" },
  { href: "/tasks", label: "Tasks" },
  { href: "/events", label: "Events" },
  { href: "/photo-reviews", label: "Photo reviews" },
  { href: "/inbox", label: "Inbox" },
  { href: "/analytics", label: "Analytics" },
  { href: "/templates", label: "Templates" },
  { href: "/tags", label: "Tags" },
  { href: "/workflows", label: "Automations" },
  { href: "/outbox", label: "Outbox" },
  { href: "/activity", label: "Activity" },
  { href: "/users", label: "Users" },
  { href: "/care-team", label: "Care team" },
];

// Pages the API only serves to admins; hidden from everyone else.
const ADMIN_ONLY = new Set(["/users", "/care-team"]);

type SidebarProps = {
  collapsed: boolean;
  onToggle: () => void;
};

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  const { me } = useMe();
  const nav = NAV.filter((n) => !ADMIN_ONLY.has(n.href) || me?.role === "admin");

  return (
    <aside className={`sidebar ${collapsed ? "sidebarCollapsed" : ""}`.trim()}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <div className="logoWrap" aria-hidden>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="" className="logoImg" />
          </div>

          {!collapsed && (
            <div style={{ lineHeight: 1.1, minWidth: 0 }}>
              <div style={{ fontWeight: 800, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                HiClinic CRM
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                Sales workspace
              </div>
            </div>
          )}
        </div>

        <button
          type="button"
          className="btn"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand" : "Collapse"}
          style={{ padding: "8px 10px", borderRadius: 12 }}
        >
          {collapsed ? ">" : "<"}
        </button>
      </div>

      <nav className="sidebarNav" aria-label="Sidebar navigation">
        {nav.map((n) => {
          const active = pathname === n.href || pathname?.startsWith(n.href + "/");
          return (
            <Link
              key={n.href}
              href={n.href}
              className="navItem"
              title={collapsed ? n.label : undefined}
              style={{
                background: active ? "rgba(30, 103, 150, 0.10)" : undefined,
                border: active ? "1px solid rgba(30, 103, 150, 0.20)" : "1px solid transparent",
                justifyContent: collapsed ? "center" : undefined,
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: 99, background: active ? "var(--primary)" : "var(--border)" }} />
              {!collapsed && <span style={{ fontWeight: 600 }}>{n.label}</span>}
            </Link>
          );
        })}
      </nav>

      {!collapsed && (
      <div style={{ marginTop: 16 }} className="muted">
        <div style={{ fontSize: 12, lineHeight: 1.35 }}>
          Tip: classify leads with tags like <b>service:TMJ</b>.
        </div>
      </div>
      )}
    </aside>
  );
}
