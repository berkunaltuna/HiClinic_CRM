export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TOKEN_KEY = "hiclinic_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (!token) {
    window.localStorage.removeItem(TOKEN_KEY);
    return;
  }
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  setToken(null);
}

export class ApiError extends Error {
  status: number;
  bodyText?: string;

  constructor(message: string, status: number, bodyText?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.bodyText = bodyText;
  }
}

async function rawFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers || {});
  // Never set Content-Type for FormData -- the browser must set it (with the multipart
  // boundary) itself, or the upload body becomes unparsable on the server.
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.replace(`/login?next=${next}`);
    }
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(text || `HTTP ${res.status}`, res.status, text);
  }
  return res;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await rawFetch(path, init);
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

/** POST/PUT a FormData body (e.g. a file upload) without corrupting the multipart boundary. */
export async function apiUpload<T>(path: string, formData: FormData, init: RequestInit = {}): Promise<T> {
  const res = await rawFetch(path, { method: "POST", ...init, body: formData });
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

/** GET a binary response (e.g. an .xlsx export) and trigger a browser save. */
export async function apiDownloadFile(path: string, filename: string): Promise<void> {
  const res = await rawFetch(path);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
