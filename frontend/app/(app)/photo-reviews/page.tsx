"use client";

import { Topbar } from "@/components/Topbar";
import { PhotoQueue } from "@/components/PhotoQueue";

export default function PhotoReviewsPage() {
  return (
    <div className="stack">
      <Topbar title="Photo reviews" subtitle="Patient photo requests across your patients" />
      <PhotoQueue patientHref={(id) => `/contacts/${id}`} />
    </div>
  );
}
