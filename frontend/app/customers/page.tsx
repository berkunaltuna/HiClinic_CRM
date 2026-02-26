"use client";

import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";

type Customer = {
  id: string;
  name: string;
  email?: string | null;
  phone?: string | null;
  company?: string | null;
  next_follow_up_at?: string | null;
  can_contact?: boolean;
  language?: string | null;
  created_at?: string;
  updated_at?: string;
  tags?: { name: string; color?: string | null }[];
};

export default function CustomersPage() {
  useRequireAuth();

  const [rows, setRows] = useState<Customer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [company, setCompany] = useState("");

  async function load() {
    setError(null);
    try {
      const data = await apiFetch<Customer[]>("/customers");
      setRows(data);
    } catch (e: any) {
      setError(e?.message || "Failed to load customers");
    }
  }

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return rows;
    return rows.filter((c) => {
      return (
        c.name?.toLowerCase().includes(s) ||
        (c.email || "").toLowerCase().includes(s) ||
        (c.phone || "").toLowerCase().includes(s) ||
        (c.company || "").toLowerCase().includes(s)
      );
    });
  }, [rows, q]);

  async function createCustomer(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await apiFetch<Customer>("/customers", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim() || null,
          phone: phone.trim() || null,
          company: company.trim() || null,
        }),
      });
      setName("");
      setEmail("");
      setPhone("");
      setCompany("");
      await load();
    } catch (e: any) {
      setError(e?.message || "Failed to create customer");
    }
  }

  return (
    <div className="grid">
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0 }}>Customers</h2>
          <div className="muted" style={{ marginTop: 4 }}>
            Create and manage leads/customers in your workspace.
          </div>
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by name / phone / email"
          style={{ width: 340 }}
        />
      </div>

      {error && <div style={{ color: "var(--danger)" }}>{error}</div>}

      <div className="split">
        <div className="card">
          <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>Customer list</strong>
            <span className="muted" style={{ fontSize: 12 }}>
              {filtered.length} shown
            </span>
          </div>
          <div className="cardBody" style={{ overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Contact</th>
                  <th>Company</th>
                  <th>Next follow-up</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <a href={`/customers/${c.id}`} style={{ fontWeight: 700 }}>
                        {c.name}
                      </a>
                      <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {(c.tags || []).slice(0, 6).map((t) => (
                          <span key={t.name} className="chip">
                            <span
                              aria-hidden
                              style={{ width: 8, height: 8, borderRadius: 999, background: t.color || "var(--teal)" }}
                            />
                            {t.name}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <div>{c.phone || "—"}</div>
                      <div className="muted" style={{ fontSize: 13 }}>
                        {c.email || ""}
                      </div>
                    </td>
                    <td>{c.company || "—"}</td>
                    <td>
                      {c.next_follow_up_at ? new Date(c.next_follow_up_at).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
                {!filtered.length && (
                  <tr>
                    <td colSpan={4} className="muted">
                      No customers found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="cardHeader">
            <strong>Create customer</strong>
          </div>
          <div className="cardBody">
            <form onSubmit={createCustomer} className="stack">
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Name
                </div>
                <input value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Email
                </div>
                <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="optional" />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Phone
                </div>
                <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="optional" />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Company
                </div>
                <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="optional" />
              </div>
              <button className="btn btnPrimary" type="submit">
                Create
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
