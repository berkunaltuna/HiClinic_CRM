"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

export type Me = { id: string; email: string; role: string };

/** Roles that use their own interface instead of the CRM. */
export const CARE_HOME: Record<string, string> = {
  doctor: "/doctor/patients",
  doctor_assistant: "/assistant",
};

export function homeFor(role: string | null | undefined, fallback = "/dashboard"): string {
  return (role && CARE_HOME[role]) || fallback;
}

let cached: Promise<Me> | null = null;

/** The signed-in staff member (cached for the page's lifetime). */
export function fetchMe(force = false): Promise<Me> {
  if (!cached || force) {
    cached = apiFetch<Me>("/auth/me");
    cached.catch(() => {
      cached = null;
    });
  }
  return cached;
}

export function useMe(): { me: Me | null; error: boolean } {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    fetchMe().then(setMe).catch(() => setError(true));
  }, []);
  return { me, error };
}
