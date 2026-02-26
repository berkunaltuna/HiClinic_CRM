"use client";

import React, { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";

type Tag = {
  id: string;
  name: string;
  color?: string | null;
};

export default function TagsPage() {
  useRequireAuth();

  const [rows, setRows] = useState<Tag[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [color, setColor] = useState("#88c2c7");

  async function load() {
    setError(null);
    try {
      const t = await apiFetch<Tag[]>("/tags");
      setRows(t);
    } catch (e: any) {
      setError(e?.message || "Failed to load tags");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await apiFetch<Tag>("/tags", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), color: color || null }),
      });
      setName("");
      await load();
    } catch (e: any) {
      setError(e?.message || "Failed to create tag");
    }
  }

  return (
    <div className="grid">
      <div>
        <h2 style={{ margin: 0 }}>Tags</h2>
        <div className="muted" style={{ marginTop: 4 }}>
          Create reusable labels for customers.
        </div>
      </div>

      {error && <div style={{ color: "var(--danger)" }}>{error}</div>}

      <div className="split">
        <div className="card">
          <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between" }}>
            <strong>All tags</strong>
            <span className="muted" style={{ fontSize: 12 }}>
              {rows.length} total
            </span>
          </div>
          <div className="cardBody" style={{ overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Tag</th>
                  <th>Colour</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id}>
                    <td style={{ fontWeight: 700 }}>{t.name}</td>
                    <td>
                      <span className="chip">
                        <span aria-hidden style={{ width: 10, height: 10, borderRadius: 999, background: t.color || "var(--teal)" }} />
                        {t.color || "(default)"}
                      </span>
                    </td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td colSpan={2} className="muted">
                      No tags yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="cardHeader">
            <strong>Create tag</strong>
          </div>
          <div className="cardBody">
            <form onSubmit={create} className="stack">
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Name
                </div>
                <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="e.g., TMJ" />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Colour
                </div>
                <input type="color" value={color} onChange={(e) => setColor(e.target.value)} />
              </div>
              <button className="btn btnPrimary" type="submit">
                Create
              </button>
              <div className="muted" style={{ fontSize: 12 }}>
                Tip: you can also create tags directly on a customer page.
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
