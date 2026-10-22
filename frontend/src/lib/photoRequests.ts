import { API_URL, ApiError, getToken } from "@/lib/api";
import type { UUID } from "@/lib/types";

// --- Staff types -----------------------------------------------------------------

export type PhotoRequestStatus =
  | "requested"
  | "uploaded"
  | "in_review"
  | "more_photos_needed"
  | "reviewed"
  | "closed"
  | "withdrawn";

export type PhotoRequestOut = {
  id: UUID;
  customer_id: UUID;
  appointment_id: UUID | null;
  deal_id: UUID | null;
  title: string;
  instructions: string | null;
  patient_message: string | null;
  status: PhotoRequestStatus;
  upload_round: number;
  consent_version: string | null;
  consent_accepted_at: string | null;
  consent_status: "pending" | "accepted";
  submitted_at: string | null;
  closed_at: string | null;
  created_by_email: string | null;
  photo_count: number;
  created_at: string;
  updated_at: string;
};

export type PhotoRequestQueueItem = PhotoRequestOut & { customer_name: string };

export type PhotoAccessLinkOut = {
  id: UUID;
  created_at: string;
  expires_at: string;
  max_uses: number;
  use_count: number;
  last_used_at: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
  active: boolean;
};

export type IssuedLinkOut = { request: PhotoRequestOut; link: PhotoAccessLinkOut; portal_url: string };

export type PatientPhotoOut = {
  id: UUID;
  original_filename: string | null;
  content_type: string;
  size_bytes: number;
  upload_round: number;
  uploaded_at: string;
  deleted_at: string | null;
  delete_reason: string | null;
};

export type EntryRevisionOut = { version: number; body: string; editor_email: string | null; editor_role: string; created_at: string };

export type EntryOut = {
  id: UUID;
  author_user_id: UUID | null;
  author_email: string | null;
  author_role: string;
  body: string;
  version: number;
  created_at: string;
  updated_at: string;
  revisions: EntryRevisionOut[];
};

export type StatusEventOut = {
  from_status: string | null;
  to_status: string;
  actor_type: "staff" | "patient";
  actor_email: string | null;
  actor_role: string | null;
  reason: string | null;
  created_at: string;
};

export type PhotoRequestDetailOut = {
  request: PhotoRequestOut;
  customer_name: string;
  permissions: string[];
  photos: PatientPhotoOut[] | null;
  notes: EntryOut[] | null;
  assessments: EntryOut[] | null;
  links: PhotoAccessLinkOut[];
  history: StatusEventOut[];
};

export type LinkOption = { id: UUID; label: string };
export type PhotoLinkOptionsOut = { appointments: LinkOption[]; deals: LinkOption[] };

export const PHOTO_STATUS_LABELS: Record<PhotoRequestStatus, string> = {
  requested: "Requested",
  uploaded: "Photos uploaded",
  in_review: "In review",
  more_photos_needed: "More photos needed",
  reviewed: "Reviewed",
  closed: "Closed",
  withdrawn: "Withdrawn",
};

export function photoStatusLabel(s: string): string {
  return PHOTO_STATUS_LABELS[s as PhotoRequestStatus] || s;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Fetch a staff-only photo with the CRM token and return an object URL (photos have no public URL). */
export async function fetchStaffPhotoUrl(requestId: UUID, photoId: UUID, download = false): Promise<string> {
  const token = getToken();
  const res = await fetch(`${API_URL}/photo-requests/${requestId}/photos/${photoId}/content${download ? "?download=true" : ""}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status, await res.text().catch(() => ""));
  return URL.createObjectURL(await res.blob());
}

// --- Patient portal --------------------------------------------------------------

export type PortalPhotoOut = { id: UUID; original_filename: string | null; content_type: string; size_bytes: number; uploaded_at: string };

export type PortalRequestOut = {
  title: string;
  instructions: string | null;
  patient_message: string | null;
  status: PhotoRequestStatus;
  patient_first_name: string;
  reviewer: string;
  can_upload: boolean;
  consent: { version: string; text: string; accepted: boolean; accepted_at: string | null };
  limits: { max_file_size_bytes: number; max_files: number; allowed_extensions: string[]; allowed_mime_types: string[] };
  photos: PortalPhotoOut[];
  submitted_at: string | null;
  created_at: string;
};

/** The portal never touches the staff token; it uses its own short-lived session token. */
export async function portalFetch<T>(path: string, session: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (session) headers.set("Authorization", `Bearer ${session}`);
  const res = await fetch(`${API_URL}/portal/photo-request${path}`, { ...init, headers, cache: "no-store", referrerPolicy: "no-referrer" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {
      // not JSON
    }
    throw new ApiError(typeof detail === "string" ? detail : `HTTP ${res.status}`, res.status, text);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

const EXT_MIME: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  heic: "image/heic",
  heif: "image/heif",
};

export function mimeFor(file: File): string {
  if (file.type) return file.type;
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  return EXT_MIME[ext] || "application/octet-stream";
}

/** Upload one file as a raw body with progress (the API streams it straight to private storage). */
export function portalUpload(
  file: File,
  session: string,
  onProgress: (fraction: number) => void,
): { promise: Promise<PortalPhotoOut>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<PortalPhotoOut>((resolve, reject) => {
    xhr.open("PUT", `${API_URL}/portal/photo-request/photos?filename=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Authorization", `Bearer ${session}`);
    xhr.setRequestHeader("Content-Type", mimeFor(file));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
        return;
      }
      let detail = `Upload failed (HTTP ${xhr.status})`;
      try {
        detail = JSON.parse(xhr.responseText).detail || detail;
      } catch {
        // keep default
      }
      reject(new ApiError(detail, xhr.status, xhr.responseText));
    };
    xhr.onerror = () => reject(new ApiError("Network error during upload. Please check your connection and try again.", 0));
    xhr.onabort = () => reject(new ApiError("Upload cancelled", 0));
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}
