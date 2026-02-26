"use client";

import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";

type Tag = { name: string; color?: string | null };

type Customer = {
  id: string;
  name: string;
  email?: string | null;
  phone?: string | null;
  company?: string | null;
  next_follow_up_at?: string | null;
  can_contact?: boolean;
  language?: string | null;
  tags?: Tag[];
  created_at?: string;
  updated_at?: string;
};

type Deal = {
  id: string;
  customer_id: string;
  amount: number;
  status: string;
  created_at?: string;
};

export default function CustomerDetail({ params }: { params: { id: string } }) {
  useRequireAuth();
  const customerId = params.id;

  const [customer, setCustomer] = useState<Customer | null>(null);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [addTagName, setAddTagName] = useState("");
  const [addTagColor, setAddTagColor] = useState("#88c2c7");

  const [dealAmount, setDealAmount] = useState("1000");
  const [dealStatus, setDealStatus] = useState("open");

  async function load() {
    setError(null);
    try {
      const [c, d, t] = await Promise.all([
        apiFetch<Customer>(`/customers/${customerId}`),
        apiFetch<Deal[]>(`/customers/${customerId}/deals`),
        apiFetch<Tag[]>(`/tags`),
      ]);
      setCustomer(c);
      setDeals(d);
      setTags(t);
    } catch (e: any) {
      setError(e?.message || "Failed to load customer");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const tagNames = useMemo(() => new Set((customer?.tags || []).map((t) => t.name)), [customer]);

  async function savePatch(patch: Record<string, any>) {
    if (!customer) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await apiFetch<Customer>(`/customers/${customerId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setCustomer(updated);
    } catch (e: any) {
      setError(e?.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function addTag(e: React.FormEvent) {
    e.preventDefault();
    if (!addTagName.trim()) return;
    setError(null);
    try {
      await apiFetch(`/tags/customers/${customerId}`, {
        method: "POST",
        body: JSON.stringify({ name: addTagName.trim(), color: addTagColor || null }),
      });
      setAddTagName("");
      await load();
    } catch (e: any) {
      setError(e?.message || "Failed to add tag");
    }
  }

  async function removeTag(tagName: string) {
    setError(null);
    try {
      await apiFetch(`/tags/customers/${customerId}/${encodeURIComponent(tagName)}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      setError(e?.message || "Failed to remove tag");
    }
  }

  async function createDeal(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const amt = Number(dealAmount);
      if (!Number.isFinite(amt)) throw new Error("Amount must be a number");
      await apiFetch(`/customers/${customerId}/deals`, {
        method: "POST",
        body: JSON.stringify({ amount: amt, status: dealStatus }),
      });
      await load();
    } catch (e: any) {
      setError(e?.message || "Failed to create deal");
    }
  }

  if (!customer) {
    return (
      <div>
        <a href="/customers">← Customers</a>
        <div style={{ marginTop: 12 }} className="muted">
          Loading…
        </div>
        {error && <div style={{ marginTop: 10, color: "var(--danger)" }}>{error}</div>}
      </div>
    );
  }

  return (
    <div className="grid">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
        <div>
          <a href="/customers">← Customers</a>
          <h2 style={{ margin: "6px 0 0" }}>{customer.name}</h2>
          <div className="muted" style={{ marginTop: 4 }}>
            {customer.phone || ""} {customer.email ? `· ${customer.email}` : ""}
          </div>
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <a className="btn" href={`/inbox/${customer.id}`}>
            Open conversation
          </a>
          <span className="muted" style={{ fontSize: 12 }}>
            {saving ? "Saving…" : ""}
          </span>
        </div>
      </div>

      {error && <div style={{ color: "var(--danger)" }}>{error}</div>}

      <div className="split">
        <div className="card">
          <div className="cardHeader">
            <strong>Details</strong>
          </div>
          <div className="cardBody grid">
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Name
                </div>
                <input
                  value={customer.name}
                  onChange={(e) => setCustomer({ ...customer, name: e.target.value })}
                  onBlur={() => savePatch({ name: customer.name })}
                />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Email
                </div>
                <input
                  value={customer.email || ""}
                  onChange={(e) => setCustomer({ ...customer, email: e.target.value || null })}
                  onBlur={() => savePatch({ email: customer.email || null })}
                  placeholder="—"
                />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Phone
                </div>
                <input
                  value={customer.phone || ""}
                  onChange={(e) => setCustomer({ ...customer, phone: e.target.value || null })}
                  onBlur={() => savePatch({ phone: customer.phone || null })}
                  placeholder="—"
                />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Company
                </div>
                <input
                  value={customer.company || ""}
                  onChange={(e) => setCustomer({ ...customer, company: e.target.value || null })}
                  onBlur={() => savePatch({ company: customer.company || null })}
                  placeholder="—"
                />
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Language
                </div>
                <select
                  value={customer.language || ""}
                  onChange={(e) => {
                    const v = e.target.value || null;
                    setCustomer({ ...customer, language: v });
                    savePatch({ language: v });
                  }}
                >
                  <option value="">(auto)</option>
                  <option value="en">en</option>
                  <option value="tr">tr</option>
                  <option value="de">de</option>
                </select>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Can contact
                </div>
                <select
                  value={String(customer.can_contact ?? true)}
                  onChange={(e) => {
                    const v = e.target.value === "true";
                    setCustomer({ ...customer, can_contact: v });
                    savePatch({ can_contact: v });
                  }}
                >
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Next follow-up
                </div>
                <input
                  type="datetime-local"
                  value={customer.next_follow_up_at ? customer.next_follow_up_at.slice(0, 16) : ""}
                  onChange={(e) => {
                    const v = e.target.value ? new Date(e.target.value).toISOString() : null;
                    setCustomer({ ...customer, next_follow_up_at: v });
                  }}
                  onBlur={() => savePatch({ next_follow_up_at: customer.next_follow_up_at || null })}
                />
              </div>
            </div>

            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong>Tags</strong>
                <span className="muted" style={{ fontSize: 12 }}>
                  click to remove
                </span>
              </div>

              <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {(customer.tags || []).map((t) => (
                  <button
                    key={t.name}
                    className="chip"
                    onClick={() => removeTag(t.name)}
                    style={{ cursor: "pointer" }}
                    title="Remove tag"
                  >
                    <span aria-hidden style={{ width: 8, height: 8, borderRadius: 999, background: t.color || "var(--teal)" }} />
                    {t.name}
                    <span className="muted" aria-hidden>
                      ×
                    </span>
                  </button>
                ))}
                {!customer.tags?.length && <div className="muted">No tags yet.</div>}
              </div>

              <form onSubmit={addTag} style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
                <select
                  value={addTagName}
                  onChange={(e) => setAddTagName(e.target.value)}
                  style={{ minWidth: 220 }}
                >
                  <option value="">Add existing tag…</option>
                  {tags
                    .filter((t) => !tagNames.has(t.name))
                    .map((t) => (
                      <option key={t.name} value={t.name}>
                        {t.name}
                      </option>
                    ))}
                </select>
                <input
                  value={addTagName}
                  onChange={(e) => setAddTagName(e.target.value)}
                  placeholder="or type a new tag name"
                  style={{ minWidth: 240 }}
                />
                <input type="color" value={addTagColor} onChange={(e) => setAddTagColor(e.target.value)} />
                <button className="btn" type="submit">
                  Add tag
                </button>
              </form>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="cardHeader">
            <strong>Deals</strong>
          </div>
          <div className="cardBody stack">
            <form onSubmit={createDeal} style={{ display: "grid", gap: 8 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <div>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                    Amount
                  </div>
                  <input value={dealAmount} onChange={(e) => setDealAmount(e.target.value)} />
                </div>
                <div>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                    Status
                  </div>
                  <select value={dealStatus} onChange={(e) => setDealStatus(e.target.value)}>
                    <option value="open">open</option>
                    <option value="won">won</option>
                    <option value="lost">lost</option>
                  </select>
                </div>
              </div>
              <button className="btn btnPrimary" type="submit">
                Add deal
              </button>
            </form>

            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                Existing deals
              </div>
              <div style={{ overflowX: "auto" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deals.map((d) => (
                      <tr key={d.id}>
                        <td>£{Number(d.amount).toLocaleString()}</td>
                        <td>
                          <span className="badge">{d.status}</span>
                        </td>
                        <td className="muted" style={{ fontSize: 13 }}>
                          {d.created_at ? new Date(d.created_at).toLocaleString() : "—"}
                        </td>
                      </tr>
                    ))}
                    {!deals.length && (
                      <tr>
                        <td colSpan={3} className="muted">
                          No deals yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
