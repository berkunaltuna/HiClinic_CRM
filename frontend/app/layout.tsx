import React from "react";
import "./globals.css";
import TopActions from "@/components/TopActions";

export const metadata = {
  title: "HiClinic CRM",
  description: "Lightweight CRM UI for HiClinic backend",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="layout">
          <aside className="sidebar">
            <a href="/" style={{ display: "block" }}>
              <img
                src="/logo.png"
                alt="HealthClinicTurkiye"
                style={{ width: 210, height: "auto" }}
              />
            </a>

            <div className="sidebarNav">
              <a className="navItem" href="/inbox">
                Inbox
              </a>
              <a className="navItem" href="/customers">
                Customers
              </a>
              <a className="navItem" href="/tags">
                Tags
              </a>
              <a className="navItem" href="/templates">
                Templates
              </a>
              <a className="navItem" href="/analytics">
                Analytics
              </a>
            </div>

            <div style={{ marginTop: 18 }}>
              <div className="chip" style={{ borderColor: "rgba(136, 194, 199, 0.65)" }}>
                <span
                  aria-hidden
                  style={{ width: 10, height: 10, borderRadius: 999, background: "var(--teal)" }}
                />
                Clinical CRM
              </div>
            </div>
          </aside>

          <main className="content">
            <div className="topbar">
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <strong>HiClinic CRM</strong>
                <span className="muted" style={{ fontSize: 13 }}>
                  Internal workspace
                </span>
              </div>
              <TopActions />
            </div>
            <div style={{ marginTop: 14 }}>{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
