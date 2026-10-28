"use client";

import { PhotoQueue } from "@/components/PhotoQueue";

export default function DoctorPhotosPage() {
  return (
    <>
      <h1 style={{ fontSize: 20, margin: 0 }}>Photos</h1>
      <PhotoQueue patientHref={(id) => `/doctor/patients/${id}`} />
    </>
  );
}
