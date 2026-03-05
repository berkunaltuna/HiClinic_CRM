"use client";

import { useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { TemplateOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

type MeOut = { id: string; email: string; role: string };

export default function TemplatesPage() {
  const toast = useToast();
  const [items, setItems] = useState<TemplateOut[]>([]);
  const [busy, setBusy] = useState(true);
  const [q, setQ] = useState("");

  const [me, setMe] = useState<MeOut | null>(null);
  const isAdmin = (me?.role || "").toLowerCase() === "admin";

  const [showNew, setShowNew] = useState(false);
  const [newChannel, setNewChannel] = useState<"email" | "whatsapp">("email");
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState<"transactional" | "marketing">("transactional");
  const [newLang, setNewLang] = useState("en");
  const [newSubject, setNewSubject] = useState("Hi {{customer_name}}");
  const [newBody, setNewBody] = useState(
    "Hello {{customer_name}},\n\nThanks for reaching out.\n\nKind regards,\nHiClinic"
  );

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
    // Best-effort: only used to hide admin-only actions.
    apiFetch<MeOut>("/auth/me").then(setMe).catch(() => setMe(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createTemplate() {
    if (!newName.trim()) return toast.push("Template name is required", "error");
    if (!newBody.trim()) return toast.push("Body is required", "error");
    if (newChannel === "email" && !newSubject.trim()) return toast.push("Subject is required for email", "error");

    try {
      await apiFetch<TemplateOut>("/templates", {
        method: "POST",
        body: JSON.stringify({
          channel: newChannel,
          name: newName.trim(),
          category: newCategory,
          language: newLang.trim() || null,
          subject: newChannel === "email" ? newSubject.trim() : null,
          body: newBody,
        }),
      });
      toast.push("Template created");
      setShowNew(false);
      setNewName("");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to create template", "error");
    }
  }

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
            {isAdmin && (
              <button className="btn" onClick={() => setShowNew(true)}>
                New
              </button>
            )}
            <button className="btn" onClick={load} disabled={busy}>{busy ? "Loading…" : "Refresh"}</button>
          </div>
        }
      />

      {showNew && (
        <div className="modalOverlay" onClick={() => setShowNew(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontWeight: 900 }}>New template</div>
              <button className="btn" onClick={() => setShowNew(false)}>Close</button>
            </div>
            <div className="modalBody" style={{ display: "grid", gap: 10 }}>
              <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Channel</div>
                  <select value={newChannel} onChange={(e) => setNewChannel(e.target.value as any)}>
                    <option value="email">Email</option>
                    <option value="whatsapp">WhatsApp</option>
                  </select>
                </div>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Category</div>
                  <select value={newCategory} onChange={(e) => setNewCategory(e.target.value as any)}>
                    <option value="transactional">Transactional</option>
                    <option value="marketing">Marketing</option>
                  </select>
                </div>
              </div>

              <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Name</div>
                  <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. TMJ - First reply" />
                </div>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Language</div>
                  <input value={newLang} onChange={(e) => setNewLang(e.target.value)} placeholder="en" />
                </div>
              </div>

              {newChannel === "email" && (
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Subject</div>
                  <input value={newSubject} onChange={(e) => setNewSubject(e.target.value)} />
                </div>
              )}

              <div>
                <div className="muted" style={{ fontSize: 12 }}>Body</div>
                <textarea rows={8} value={newBody} onChange={(e) => setNewBody(e.target.value)} />
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  Tip: use merge fields like <b>{"{{customer_name}}"}</b> and <b>{"{{company}}"}</b>
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button className="btn" onClick={() => setShowNew(false)}>Cancel</button>
                <button className="btn btnPrimary" onClick={createTemplate}>Create</button>
              </div>
            </div>
          </div>
        </div>
      )}

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
