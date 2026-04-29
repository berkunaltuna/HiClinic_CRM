"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch, ApiError } from "@/lib/api";
import type { TemplateOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

type MeOut = {
  id: string;
  email: string;
  role: string;
};

type TemplateChannel = "email" | "whatsapp";
type TemplateCategory = "transactional" | "marketing";

const DEFAULT_CHANNEL: TemplateChannel = "email";
const DEFAULT_CATEGORY: TemplateCategory = "transactional";
const DEFAULT_LANGUAGE = "en";
const DEFAULT_SUBJECT = "Hi {{customer_name}}";
const DEFAULT_BODY =
  "Hello {{customer_name}},\n\nThanks for reaching out.\n\nKind regards,\nHiClinic";

export default function TemplatesPage() {
  const toast = useToast();

  const [items, setItems] = useState<TemplateOut[]>([]);
  const [busy, setBusy] = useState<boolean>(true);
  const [q, setQ] = useState<string>("");
  const [me, setMe] = useState<MeOut | null>(null);

  const [showNew, setShowNew] = useState<boolean>(false);
  const [newChannel, setNewChannel] = useState<TemplateChannel>(DEFAULT_CHANNEL);
  const [newName, setNewName] = useState<string>("");
  const [newCategory, setNewCategory] = useState<TemplateCategory>(DEFAULT_CATEGORY);
  const [newLang, setNewLang] = useState<string>(DEFAULT_LANGUAGE);
  const [newSubject, setNewSubject] = useState<string>(DEFAULT_SUBJECT);
  const [newBody, setNewBody] = useState<string>(DEFAULT_BODY);
  const [creating, setCreating] = useState<boolean>(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const isAdmin = (me?.role ?? "").toLowerCase().includes("admin");

  const resetNewForm = useCallback(() => {
    setNewChannel(DEFAULT_CHANNEL);
    setNewName("");
    setNewCategory(DEFAULT_CATEGORY);
    setNewLang(DEFAULT_LANGUAGE);
    setNewSubject(DEFAULT_SUBJECT);
    setNewBody(DEFAULT_BODY);
  }, []);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const data = await apiFetch<TemplateOut[]>("/templates");
      setItems(Array.isArray(data) ? data : []);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to load templates";
      toast.push(message, "error");
    } finally {
      setBusy(false);
    }
  }, [toast]);

  const loadMe = useCallback(async () => {
    try {
      const data = await apiFetch<MeOut>("/auth/me");
      setMe(data);
    } catch {
      setMe(null);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadMe();
  }, [load, loadMe]);

  async function createTemplate() {
    if (!newName.trim()) {
      toast.push("Template name is required", "error");
      return;
    }

    if (!newBody.trim()) {
      toast.push("Body is required", "error");
      return;
    }

    if (newChannel === "email" && !newSubject.trim()) {
      toast.push("Subject is required for email", "error");
      return;
    }

    setCreating(true);
    try {
      await apiFetch<TemplateOut>("/templates", {
        method: "POST",
        body: JSON.stringify({
          channel: newChannel,
          name: newName.trim(),
          category: newCategory,
          language: newLang.trim() || null,
          subject: newChannel === "email" ? newSubject.trim() : null,
          body: newBody.trim(),
        }),
      });

      toast.push("Template created");
      setShowNew(false);
      resetNewForm();
      await load();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 403) {
        toast.push(
          "Admin only: you don't have permission to create templates",
          "error"
        );
        return;
      }

      const message =
        err instanceof Error ? err.message : "Failed to create template";
      toast.push(message, "error");
    } finally {
      setCreating(false);
    }
  }

  async function deleteTemplate(t: TemplateOut) {
    if (!confirm(`Delete template "${t.name}"?`)) return;

    setDeletingId(t.id);
    try {
      await apiFetch<void>(`/templates/${t.id}`, { method: "DELETE" });
      toast.push("Template deleted");
      await load();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to delete template";
      toast.push(message, "error");
    } finally {
      setDeletingId(null);
    }
  }

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return items;

    return items.filter((t) =>
      [
        t.name,
        t.channel,
        t.category,
        t.language ?? "",
        t.subject ?? "",
        t.body ?? "",
      ].some((x) => String(x).toLowerCase().includes(s))
    );
  }, [items, q]);

  return (
    <div className="stack">
      <Topbar
        title="Templates"
        right={
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search templates…"
            />
            {isAdmin && (
              <button
                className="btn"
                onClick={() => {
                  resetNewForm();
                  setShowNew(true);
                }}
              >
                New
              </button>
            )}
            <button className="btn" onClick={() => void load()} disabled={busy}>
              {busy ? "Loading…" : "Refresh"}
            </button>
          </div>
        }
      />

      {showNew && (
        <div className="modalOverlay" onClick={() => setShowNew(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div
              className="modalHeader"
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div style={{ fontWeight: 900 }}>New template</div>
              <button className="btn" onClick={() => setShowNew(false)}>
                Close
              </button>
            </div>

            <div className="modalBody" style={{ display: "grid", gap: 10 }}>
              <div
                className="grid"
                style={{ gridTemplateColumns: "1fr 1fr", gap: 10 }}
              >
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Channel
                  </div>
                  <select
                    value={newChannel}
                    onChange={(e) =>
                      setNewChannel(e.target.value as TemplateChannel)
                    }
                  >
                    <option value="email">Email</option>
                    <option value="whatsapp">WhatsApp</option>
                  </select>
                </div>

                <div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Category
                  </div>
                  <select
                    value={newCategory}
                    onChange={(e) =>
                      setNewCategory(e.target.value as TemplateCategory)
                    }
                  >
                    <option value="transactional">Transactional</option>
                    <option value="marketing">Marketing</option>
                  </select>
                </div>
              </div>

              <div
                className="grid"
                style={{ gridTemplateColumns: "2fr 1fr", gap: 10 }}
              >
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Name
                  </div>
                  <input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="e.g. TMJ - First reply"
                  />
                </div>

                <div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Language
                  </div>
                  <input
                    value={newLang}
                    onChange={(e) => setNewLang(e.target.value)}
                    placeholder="en"
                  />
                </div>
              </div>

              {newChannel === "email" && (
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Subject
                  </div>
                  <input
                    value={newSubject}
                    onChange={(e) => setNewSubject(e.target.value)}
                    placeholder="Hi {{customer_name}}"
                  />
                </div>
              )}

              <div>
                <div className="muted" style={{ fontSize: 12 }}>
                  Body
                </div>
                <textarea
                  rows={8}
                  value={newBody}
                  onChange={(e) => setNewBody(e.target.value)}
                />
                <div
                  className="muted"
                  style={{ fontSize: 12, marginTop: 6 }}
                >
                  Tip: use merge fields like <b>{"{{customer_name}}"}</b> and{" "}
                  <b>{"{{company}}"}</b>
                </div>
              </div>

              <div
                style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}
              >
                <button className="btn" onClick={() => setShowNew(false)}>
                  Cancel
                </button>
                <button
                  className="btn btnPrimary"
                  onClick={createTemplate}
                  disabled={creating}
                >
                  {creating ? "Creating…" : "Create"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>
          All templates
        </div>

        <div className="cardBody">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Channel</th>
                <th>Category</th>
                <th>Language</th>
                <th></th>
              </tr>
            </thead>

            <tbody>
              {filtered.map((t) => (
                <tr key={t.id}>
                  <td style={{ fontWeight: 800 }}>{t.name}</td>
                  <td className="muted">{t.channel}</td>
                  <td className="muted">{t.category}</td>
                  <td className="muted">{t.language || "-"}</td>
                  <td style={{ textAlign: "right" }}>
                    {isAdmin && (
                      <button
                        className="btn"
                        onClick={() => void deleteTemplate(t)}
                        disabled={deletingId === t.id}
                      >
                        {deletingId === t.id ? "Deleting…" : "Delete"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}

              {!busy && !filtered.length && (
                <tr>
                  <td colSpan={5} className="muted">
                    No templates.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}