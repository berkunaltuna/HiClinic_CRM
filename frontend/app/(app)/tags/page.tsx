"use client";

import { FormEvent, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { TagOut } from "@/lib/types";
import { SERVICE_TAGS } from "@/lib/constants";
import { useToast } from "@/components/Toast";

export default function TagsPage() {
  const toast = useToast();
  const [tags, setTags] = useState<TagOut[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(true);

  async function load() {
    setBusy(true);
    try {
      const data = await apiFetch<TagOut[]>("/tags");
      setTags(data);
    } catch (err: any) {
      toast.push(err?.message || "Failed to load tags", "error");
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
    const n = name.trim();
    if (!n) return;
    try {
      await apiFetch<TagOut>("/tags", { method: "POST", body: JSON.stringify({ name: n }) });
      toast.push("Tag created");
      setName("");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to create", "error");
    }
  }

  async function seedServiceTags() {
    try {
      for (const t of SERVICE_TAGS) {
        await apiFetch<TagOut>("/tags", { method: "POST", body: JSON.stringify({ name: t }) });
      }
      toast.push("Service tags created");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to seed tags", "error");
    }
  }

  return (
    <div className="stack">
      <Topbar
        title="Tags"
        right={<button className="btn" onClick={seedServiceTags} disabled={busy}>Seed service tags</button>}
      />

      <div className="split">
        <section className="card">
          <div className="cardHeader" style={{ fontWeight: 900 }}>All tags</div>
          <div className="cardBody">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {tags.map((t) => (
                <span key={t.id} className="chip">{t.name}</span>
              ))}
              {!busy && !tags.length && <span className="muted">No tags yet.</span>}
            </div>
          </div>
        </section>

        <section className="card">
          <div className="cardHeader" style={{ fontWeight: 900 }}>Create tag</div>
          <div className="cardBody">
            <form onSubmit={onCreate} className="stack">
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. service:TMJ, source:Instagram" />
              <button className="btn btnPrimary" type="submit">Create</button>
              <div className="muted" style={{ fontSize: 12 }}>
                Recommended pattern: <b>service:*</b>, <b>source:*</b>, <b>priority:*</b>.
              </div>
            </form>
          </div>
        </section>
      </div>
    </div>
  );
}
