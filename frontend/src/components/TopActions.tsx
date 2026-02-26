"use client";

import React, { useMemo, useState } from "react";
import { getToken, setToken } from "@/lib/api";

export default function TopActions() {
  const authed = useMemo(() => !!getToken(), []);
  const [q, setQ] = useState("");

  function logout() {
    setToken("");
    if (typeof window !== "undefined") window.localStorage.removeItem("hiclinic_token");
    window.location.href = "/";
  }

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    // Lightweight global search via inbox q filter (name/phone/email)
    window.location.href = `/inbox?${new URLSearchParams({ q: q.trim() }).toString()}`;
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <form onSubmit={submitSearch} style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name / phone / email"
          style={{ width: 280 }}
        />
        <button className="btn" type="submit">
          Search
        </button>
      </form>

      {authed && (
        <button className="btn" onClick={logout} title="Sign out">
          Logout
        </button>
      )}
    </div>
  );
}
