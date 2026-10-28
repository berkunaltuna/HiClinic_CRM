"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function DoctorHome() {
  const router = useRouter();
  useEffect(() => router.replace("/doctor/patients"), [router]);
  return null;
}
