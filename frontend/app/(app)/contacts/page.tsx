"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { CustomerOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import { WhatsAppQuickAction } from "@/components/WhatsAppQuickAction";

export default function ContactsPage() {
  const toast = useToast();
  const [items, setItems] = useState<CustomerOut[]>([]);
  const [busy, setBusy] = useState(true);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [company, setCompany] = useState("");

  const [q, setQ] = useState("");
  const [dateDir, setDateDir] = useState<"oldest" | "newest">("newest");
  const [alphabetical, setAlphabetical] = useState(false);

  async function load() {
    setBusy(true);
    try {
      const data = await apiFetch<CustomerOut[]>("/customers");
      setItems(data);
    } catch (err: any) {
      toast.push(err?.message || "Failed to load contacts", "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    try {
      await apiFetch<CustomerOut>("/customers", {
        method: "POST",
        body: JSON.stringify({
          name,
          email: email || null,
          phone: phone || null,
          company: company || null,
        }),
      });
      toast.push("Contact created");
      setName("");
      setEmail("");
      setPhone("");
      setCompany("");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to create", "error");
    }
  }

  const visibleItems = useMemo(() => {
    const query = q.trim().toLowerCase();
    let list = items;
    if (query) {
      list = list.filter((c) => {
        const haystack = [c.name, c.email, c.phone, c.company, c.stage, c.latest_deal?.treatment_interest, ...(c.tag_names || [])]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(query);
      });
    }
    const sorter = alphabetical
      ? (a: CustomerOut, b: CustomerOut) => a.name.localeCompare(b.name)
      : dateDir === "oldest"
        ? (a: CustomerOut, b: CustomerOut) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        : (a: CustomerOut, b: CustomerOut) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    return list.slice().sort(sorter);
  }, [items, q, dateDir, alphabetical]);

  async function deleteContact(id: string, label: string) {
    if (!confirm(`Delete ${label}? This cannot be undone.`)) return;
    try {
      await apiFetch(`/customers/${id}`, { method: "DELETE" });
      toast.push("Contact deleted");
      setItems((prev) => prev.filter((x) => x.id !== id));
    } catch (err: any) {
      toast.push(err?.message || "Failed to delete contact", "error");
    }
  }

  return (
    <div className="stack">
      <Topbar title="Contacts" />

      <div className="split">
        <section className="card">
          <div className="cardHeader" style={{ fontWeight: 900 }}>All contacts</div>
          <div className="cardBody">
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
              <input
                placeholder="Search name, email, phone, company…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                style={{ flex: 1, minWidth: 200 }}
              />
              <button
                type="button"
                className="btn"
                style={alphabetical ? { opacity: 0.55 } : undefined}
                title="Toggle sort direction"
                onClick={() => { setAlphabetical(false); setDateDir((d) => (d === "oldest" ? "newest" : "oldest")); }}
              >
                {dateDir === "oldest" ? "↑ Oldest first" : "↓ Newest first"}
              </button>
              <button
                type="button"
                className="btn"
                style={alphabetical ? { background: "var(--primary)", color: "#fff", borderColor: "var(--primary)" } : undefined}
                title="Toggle alphabetical sort"
                onClick={() => setAlphabetical((a) => !a)}
              >
                A–Z
              </button>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Company</th>
                  <th>Stage</th>
                  <th>Follow-up</th>
                  <th>Lead form</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link href={`/contacts/${c.id}`} style={{ fontWeight: 800 }}>{c.name}</Link>
                      <div className="muted" style={{ fontSize: 12 }}>{c.email || c.phone || "—"}</div>
                    </td>
                    <td className="muted">{c.company || "—"}</td>
                    <td><span className="badge">{c.stage}</span></td>
                    <td className="muted">{fmtDateTime(c.next_follow_up_at)}</td>
                    <td>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {c.latest_deal?.treatment_interest && <span className="chip">{c.latest_deal.treatment_interest}</span>}
                        {c.latest_deal?.preferred_consultation_day && <span className="chip">{c.latest_deal.preferred_consultation_day}</span>}
                        {c.latest_deal?.seminar_preference && <span className="chip">{c.latest_deal.seminar_preference}</span>}
                        {!c.latest_deal?.treatment_interest && !c.latest_deal?.preferred_consultation_day && !c.latest_deal?.seminar_preference && <span className="muted">—</span>}
                      </div>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                        <WhatsAppQuickAction customer={c} compact />
                        <button className="btn" onClick={() => deleteContact(c.id, c.name)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!busy && !items.length && (
                  <tr>
                    <td colSpan={6} className="muted">No contacts yet.</td>
                  </tr>
                )}
                {!busy && items.length > 0 && !visibleItems.length && (
                  <tr>
                    <td colSpan={6} className="muted">No contacts match your search.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card">
          <div className="cardHeader" style={{ fontWeight: 900 }}>Create contact</div>
          <div className="cardBody">
            <form onSubmit={onCreate} className="stack">
              <label className="stack" style={{ gap: 6 }}>
                <span className="muted" style={{ fontSize: 12 }}>Name</span>
                <input value={name} onChange={(e) => setName(e.target.value)} required />
              </label>
              <label className="stack" style={{ gap: 6 }}>
                <span className="muted" style={{ fontSize: 12 }}>Email</span>
                <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" />
              </label>
              <label className="stack" style={{ gap: 6 }}>
                <span className="muted" style={{ fontSize: 12 }}>Phone</span>
                <input value={phone} onChange={(e) => setPhone(e.target.value)} />
              </label>
              <label className="stack" style={{ gap: 6 }}>
                <span className="muted" style={{ fontSize: 12 }}>Company / Source</span>
                <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="e.g. London event, Instagram, referral…" />
              </label>

              <button className="btn btnPrimary" type="submit">Create</button>
              <div className="muted" style={{ fontSize: 12 }}>
                Using <b>Option A</b>: classification/source is stored in <b>company</b>.
              </div>
            </form>
          </div>
        </section>
      </div>
    </div>
  );
}
