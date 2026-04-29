"use client";

import { Topbar } from "@/components/Topbar";

export default function WorkflowsPage() {
  return (
    <div className="stack">
      <Topbar title="Workflows" />
      <div className="card" style={{ padding: 16 }}>
        <div style={{ fontWeight: 900 }}>Automation (coming next)</div>
        <div className="muted" style={{ marginTop: 6 }}>
          Ideas to add:
          <ul>
            <li>Auto-tag leads by source (UTM, form, referral)</li>
            <li>Auto-create follow-up task after inbound</li>
            <li>Auto-queue a template 30 minutes after no reply</li>
            <li>Escalation rules for high-value deals</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
