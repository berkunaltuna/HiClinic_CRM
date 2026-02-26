"use client";

import { useEffect } from "react";
import { getToken } from "./api";

/**
 * Client-side guard: redirects to / if there is no JWT in localStorage.
 * We keep it minimal to match the backend's JWT scheme.
 */
export function useRequireAuth() {
  useEffect(() => {
    const token = getToken();
    if (!token) {
      window.location.href = "/";
    }
  }, []);
}
