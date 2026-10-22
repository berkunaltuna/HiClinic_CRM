"use client";

import { useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { UserOut } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { fmtDateTime } from "@/lib/dates";

const ROLES = ["admin", "manager", "coordinator", "doctor", "viewer", "user"];

export default function UsersPage() {
  const toast = useToast();
  const [items, setItems] = useState<UserOut[]>([]);
  const [busy, setBusy] = useState(true);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("coordinator");
  const [creating, setCreating] = useState(false);

  async function createUser(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await apiFetch<UserOut>("/users", { method: "POST", body: JSON.stringify({ email: newEmail.trim(), password: newPassword, role: newRole }) });
      toast.push("User created. Share the temporary password privately and ask them to change it.");
      setNewEmail("");
      setNewPassword("");
      await load();
    } catch (err: any) {
      let msg = err?.message || "Failed to create user";
      try {
        const detail = JSON.parse(err?.bodyText || "").detail;
        msg = typeof detail === "string" ? detail : "Check the email and use a password of at least 8 characters";
      } catch {
        // keep msg
      }
      toast.push(msg, "error");
    } finally {
      setCreating(false);
    }
  }

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
      <section className="card" aria-labelledby="add-user-h">
        <div className="cardHeader" id="add-user-h" style={{ fontWeight: 900 }}>Add user</div>
        <form className="cardBody" onSubmit={createUser} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ display: "grid", gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>Email</span>
            <input type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} required />
          </label>
          <label style={{ display: "grid", gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>Temporary password (min 8)</span>
            <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={8} required autoComplete="new-password" />
          </label>
          <label style={{ display: "grid", gap: 4 }}>
            <span className="muted" style={{ fontSize: 12 }}>Role</span>
            <select value={newRole} onChange={(e) => setNewRole(e.target.value)}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <button className="btn btnPrimary" type="submit" disabled={creating}>{creating ? "Creating…" : "Create user"}</button>
        </form>
      </section>
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
