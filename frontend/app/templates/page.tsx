"use client";

import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";

type Template = {
  id: string;
  channel: string;
  name: string;
  subject?: string | null;
  body: string;
  category?: string | null;
  language: string;
};

type Customer = { id: string; name: string };

type PreviewOut = { subject: string; body: string };

export default function TemplatesPage() {
  useRequireAuth();

  const [templates, setTemplates] = useState<Template[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selected, setSelected] = useState<Template | null>(null);
  const [customerId, setCustomerId] = useState<string>("");
  const [preview, setPreview] = useState<PreviewOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    let alive = true;
    setError(null);
    Promise.all([apiFetch<Template[]>("/templates"), apiFetch<Customer[]>("/customers")])
      .then(([t, c]) => {
        if (!alive) return;
        setTemplates(t);
        setCustomers(c);
        if (c.length) setCustomerId(c[0].id);
      })
      .catch((e: any) => alive && setError(e?.message || "Failed to load"));
    return () => {
      alive = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return templates;
    return templates.filter((t) => {
      return (
        t.name.toLowerCase().includes(s) ||
        t.channel.toLowerCase().includes(s) ||
        (t.category || "").toLowerCase().includes(s) ||
        (t.language || "").toLowerCase().includes(s)
      );
    });
  }, [templates, q]);

  async function runPreview() {
    if (!selected || !customerId) return;
    setError(null);
    setPreview(null);
    try {
      const out = await apiFetch<PreviewOut>(`/templates/${selected.id}/preview`, {
        method: "POST",
        body: JSON.stringify({ customer_id: customerId }),
      });
      setPreview(out);
    } catch (e: any) {
      setError(e?.message || "Failed to preview");
    }
  }

  return (
    <div className="grid">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0 }}>Templates</h2>
          <div className="muted" style={{ marginTop: 4 }}>
            View message templates and preview with customer variables.
          </div>
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter templates" style={{ width: 320 }} />
      </div>

      {error && <div style={{ color: "var(--danger)" }}>{error}</div>}

      <div className="split">
        <div className="card">
          <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between" }}>
            <strong>All templates</strong>
            <span className="muted" style={{ fontSize: 12 }}>
              {filtered.length} shown
            </span>
          </div>
          <div className="cardBody" style={{ overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Channel</th>
                  <th>Language</th>
                  <th>Category</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <button
                        className="btn"
                        style={{ padding: "6px 10px" }}
                        onClick={() => {
                          setSelected(t);
                          setPreview(null);
                        }}
                      >
                        {t.name}
                      </button>
                    </td>
                    <td>{t.channel}</td>
                    <td>{t.language}</td>
                    <td>{t.category || "—"}</td>
                  </tr>
                ))}
                {!filtered.length && (
                  <tr>
                    <td colSpan={4} className="muted">
                      No templates found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="cardHeader">
            <strong>Preview</strong>
          </div>
          <div className="cardBody" className="stack">
            {!selected ? (
              <div className="muted">Select a template to preview.</div>
            ) : (
              <>
                <div>
                  <div style={{ fontWeight: 700 }}>{selected.name}</div>
                  <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                    {selected.channel} · {selected.language} {selected.category ? `· ${selected.category}` : ""}
                  </div>
                </div>

                <div>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                    Preview with customer
                  </div>
                  <select value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                    {customers.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                    {!customers.length && <option value="">No customers yet</option>}
                  </select>
                </div>

                <button className="btn btnPrimary" onClick={runPreview} disabled={!customerId}>
                  Generate preview
                </button>

                {preview && (
                  <div className="card" style={{ boxShadow: "none" }}>
                    <div className="cardHeader">
                      <strong>Rendered</strong>
                    </div>
                    <div className="cardBody" style={{ display: "grid", gap: 10 }}>
                      <div>
                        <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                          Subject
                        </div>
                        <div style={{ fontWeight: 700 }}>{preview.subject}</div>
                      </div>
                      <div>
                        <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                          Body
                        </div>
                        <pre
                          style={{
                            margin: 0,
                            whiteSpace: "pre-wrap",
                            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                            fontSize: 13,
                            border: "1px solid var(--border)",
                            borderRadius: 12,
                            padding: 12,
                            background: "rgba(136, 194, 199, 0.12)",
                          }}
                        >
                          {preview.body}
                        </pre>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
