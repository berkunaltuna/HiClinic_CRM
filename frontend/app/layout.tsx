import React from "react";

export const metadata = {
  title: "HiClinic CRM",
  description: "Lightweight CRM UI for HiClinic backend",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", margin: 0 }}>
        <div style={{ padding: 16, borderBottom: "1px solid #eee", display: "flex", gap: 12 }}>
          <a href="/" style={{ textDecoration: "none" }}>
            <strong>HiClinic CRM</strong>
          </a>
          <a href="/inbox">Inbox</a>
          <a href="/analytics">Analytics</a>
        </div>
        <div style={{ padding: 16 }}>{children}</div>
      </body>
    </html>
  );
}
