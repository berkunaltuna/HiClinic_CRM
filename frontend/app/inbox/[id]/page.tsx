"use client";

import React, { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type ThreadItem = {
  kind: string;
  id: string;
  direction: string;
  channel: string;
  occurred_at: string;
  content?: string | null;
  status?: string | null;
};

export default function CustomerThread({ params }: { params: { id: string } }) {
  const customerId = params.id;
  const [items, setItems] = useState<ThreadItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [body, setBody] = useState<string>("");

  async function load() {
    setError(null);
    try {
      const d = await apiFetch<ThreadItem[]>(`/inbox/customers/${customerId}/thread`);
      setItems(d);
    } catch (e: any) {
      setError(e?.message || "Failed");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  async function sendText() {
    if (!body.trim()) return;
    try {
      await apiFetch(`/inbox/customers/${customerId}/send-text`, {
        method: "POST",
        body: JSON.stringify({ body, channel: "whatsapp" }),
      });
      setBody("");
      await load();
    } catch (e: any) {
      setError(e?.message || "Failed");
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Conversation</h2>
        <a href="/inbox">← Back</a>
      </div>

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12, marginTop: 12 }}>
        <div style={{ display: "grid", gap: 8 }}>
          {items.map((it) => (
            <div key={it.id} style={{ display: "flex", justifyContent: it.direction === "outbound" ? "flex-end" : "flex-start" }}>
              <div
                style={{
                  maxWidth: 720,
                  border: "1px solid #ddd",
                  borderRadius: 10,
                  padding: 10,
                  background: it.direction === "outbound" ? "#fafafa" : "white",
                }}
              >
                <div style={{ fontSize: 12, color: "#666", marginBottom: 6 }}>
                  {it.direction} · {it.channel} · {new Date(it.occurred_at).toLocaleString()} {it.status ? `· ${it.status}` : ""}
                </div>
                <div style={{ whiteSpace: "pre-wrap" }}>{it.content || ""}</div>
              </div>
            </div>
          ))}
          {!items.length && <p style={{ color: "#666" }}>No messages yet.</p>}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Type a WhatsApp message..."
          style={{ flex: 1, padding: 10 }}
        />
        <button onClick={sendText} style={{ padding: "10px 14px" }}>
          Send
        </button>
      </div>
    </div>
  );
}
