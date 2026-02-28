"use client";

import { useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { TemplateOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

export default function TemplatesPage() {
  const toast = useToast();
  const [items, setItems] = useState<TemplateOut[]>([]);
  const [busy, setBusy] = useState(true);
  const [q, setQ] = useState("");

  async function load() {
    setBusy(true);
    try {
      const data = await apiFetch<TemplateOut[]>("/templates");
      setItems(data);
    } catch (err: any) {
      toast.push(err?.message || "Failed to load templates", "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return items;
    return items.filter((t) =>
      [t.name, t.channel, t.category, t.language, t.subject || "", t.body].some((x) => (x || "").toLowerCase().includes(s))
    );
  }, [items, q]);

  return (
    <div className="stack">
      <Topbar
        title="Templates"
        right={
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search templates…" />
            <button className="btn" onClick={load} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>
          </div>
        }
      />

      <div className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>All templates</div>
        <div className="cardBody">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Channel</th>
                <th>Category</th>
                <th>Language</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.id}>
                  <td style={{ fontWeight: 800 }}>{t.name}</td>
                  <td className="muted">{t.channel}</td>
                  <td className="muted">{t.category}</td>
                  <td className="muted">{t.language}</td>
                </tr>
              ))}
              {!busy && !filtered.length && (
                <tr>
                  <td colSpan={4} className="muted">No templates.</td>
                </tr>
              )}
            </tbody>
          </table>

          <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
            Note: creating/updating templates requires an <b>admin</b> user on the backend.
          </div>
        </div>
      </div>
    </div>
  );
}
