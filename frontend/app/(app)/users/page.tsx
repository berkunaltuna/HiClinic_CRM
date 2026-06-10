"use client";

import { useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { UserOut } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { fmtDateTime } from "@/lib/dates";

const ROLES = ["admin", "manager", "coordinator", "viewer", "user"];

export default function UsersPage() {
  const toast = useToast();
  const [items, setItems] = useState<UserOut[]>([]);
  const [busy, setBusy] = useState(true);

  async function load() {
    setBusy(true);
    try {
      setItems(await apiFetch<UserOut[]>("/users"));
    } catch (err: any) {
      toast.push(err?.message || "Failed to load users. Admin permission may be required.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function updateRole(user: UserOut, role: string) {
    try {
      await apiFetch<UserOut>(`/users/${user.id}`, { method: "PATCH", body: JSON.stringify({ role }) });
      toast.push("Role updated");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to update role", "error");
    }
  }

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="stack">
      <Topbar title="Users" right={<button className="btn" onClick={() => void load()}>{busy ? "Loading…" : "Refresh"}</button>} />
      <section className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>CRM users and roles</div>
        <div className="cardBody">
          <table className="table">
            <thead><tr><th>Email</th><th>Role</th><th>Created</th></tr></thead>
            <tbody>
              {items.map((u) => (
                <tr key={u.id}>
                  <td><b>{u.email}</b><div className="muted" style={{ fontSize: 12 }}>{u.id}</div></td>
                  <td>
                    <select value={u.role} onChange={(e) => void updateRole(u, e.target.value)}>
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>{fmtDateTime(u.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
