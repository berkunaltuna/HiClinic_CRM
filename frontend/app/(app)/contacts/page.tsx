"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { CustomerOut } from "@/lib/types";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";

export default function ContactsPage() {
  const toast = useToast();
  const [items, setItems] = useState<CustomerOut[]>([]);
  const [busy, setBusy] = useState(true);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [company, setCompany] = useState("");

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

  return (
    <div className="stack">
      <Topbar title="Contacts" />

      <div className="split">
        <section className="card">
          <div className="cardHeader" style={{ fontWeight: 900 }}>All contacts</div>
          <div className="cardBody">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Company</th>
                  <th>Stage</th>
                  <th>Follow-up</th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link href={`/contacts/${c.id}`} style={{ fontWeight: 800 }}>{c.name}</Link>
                      <div className="muted" style={{ fontSize: 12 }}>{c.email || c.phone || "—"}</div>
                    </td>
                    <td className="muted">{c.company || "—"}</td>
                    <td><span className="badge">{c.stage}</span></td>
                    <td className="muted">{fmtDateTime(c.next_follow_up_at)}</td>
                  </tr>
                ))}
                {!busy && !items.length && (
                  <tr>
                    <td colSpan={4} className="muted">No contacts yet.</td>
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
