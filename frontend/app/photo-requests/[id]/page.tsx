"use client";

import { useParams } from "next/navigation";
import { PhotoRequestView } from "@/components/PhotoRequestView";
import { useRequireAuth } from "@/lib/useRequireAuth";

// Opened in its own window from the CRM, the doctor interface or the review queue. No CRM
// navigation here, so it suits every staff role; the API decides what each role may see.
export default function PhotoRequestWindowPage() {
  const { isReady } = useRequireAuth();
  const id = String(useParams().id);
  if (!isReady) {
    return (
      <div style={{ padding: 24 }} aria-live="polite">
        <div className="card" style={{ padding: 16, maxWidth: 520 }}>Checking session…</div>
      </div>
    );
  }
  return <PhotoRequestView requestId={id} />;
}
