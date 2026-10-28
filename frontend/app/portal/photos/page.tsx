"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, ApiError } from "@/lib/api";
import {
  type PortalPhotoOut,
  type PortalRequestOut,
  fmtBytes,
  portalFetch,
  portalUpload,
} from "@/lib/photoRequests";

const SESSION_KEY = "hiclinic_photo_portal_session";

type Phase =
  | { kind: "loading" }
  | { kind: "no_link" }
  | { kind: "expired" }
  | { kind: "rate_limited" }
  | { kind: "error"; message: string }
  | { kind: "ready" };

type Pending = { id: string; file: File; preview: string | null; progress: number; error: string | null; done: boolean };

function readSession(): string | null {
  try {
    return window.sessionStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function writeSession(token: string | null) {
  try {
    if (token) window.sessionStorage.setItem(SESSION_KEY, token);
    else window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // storage unavailable: the session lives in memory only
  }
}

export default function PatientPhotoPortalPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [session, setSession] = useState<string | null>(null);
  const [req, setReq] = useState<PortalRequestOut | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [message, setMessage] = useState<{ text: string; kind: "info" | "error" } | null>(null);
  const [consentTicked, setConsentTicked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploading = useRef(false);
  const started = useRef(false);
  const exchanged = useRef(new Set<string>());

  const handleAuthError = useCallback((err: unknown) => {
    const status = err instanceof ApiError ? err.status : 0;
    if (status === 401) {
      writeSession(null);
      setSession(null);
      setPhase({ kind: "expired" });
      return true;
    }
    if (status === 429) {
      setPhase({ kind: "rate_limited" });
      return true;
    }
    return false;
  }, []);

  const load = useCallback(
    async (token: string) => {
      try {
        setReq(await portalFetch<PortalRequestOut>("", token));
        setPhase({ kind: "ready" });
      } catch (err) {
        if (!handleAuthError(err)) setPhase({ kind: "error", message: (err as Error).message || "Something went wrong." });
      }
    },
    [handleAuthError],
  );

  // Open the session: the link token arrives in the URL fragment (never sent to servers)
  // and is exchanged once, then removed from the address bar and history. A link opened
  // while this page is already showing only changes the fragment, so listen for that too.
  useEffect(() => {
    const exchange = async (linkToken: string) => {
      setPhase({ kind: "loading" });
      try {
        const out = await portalFetch<{ session_token: string }>("/session", null, { method: "POST", body: JSON.stringify({ token: linkToken }) });
        writeSession(out.session_token);
        setSession(out.session_token);
        await load(out.session_token);
      } catch (err) {
        if (!handleAuthError(err)) setPhase({ kind: "error", message: (err as Error).message || "Something went wrong." });
      }
    };

    // Returns the fragment's token (if any) after stripping it from the URL.
    const takeToken = (): string | null => {
      const linkToken = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");
      if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
      // Each exchange spends one of the link's limited uses: never exchange the same token twice
      // (React strict mode runs this effect twice in development).
      if (!linkToken || exchanged.current.has(linkToken)) return null;
      exchanged.current.add(linkToken);
      return linkToken;
    };

    const onHashChange = () => {
      const linkToken = takeToken();
      if (linkToken) void exchange(linkToken);
    };
    window.addEventListener("hashchange", onHashChange);

    if (!started.current) {
      started.current = true;
      const linkToken = takeToken();
      if (linkToken) {
        void exchange(linkToken);
      } else {
        const existing = readSession();
        if (existing) {
          setSession(existing);
          void load(existing);
        } else {
          setPhase({ kind: "no_link" });
        }
      }
    }
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [load, handleAuthError]);

  useEffect(() => () => pending.forEach((p) => p.preview && URL.revokeObjectURL(p.preview)), []); // eslint-disable-line react-hooks/exhaustive-deps

  async function acceptConsent() {
    if (!session || !req) return;
    setBusy(true);
    try {
      await portalFetch<void>("/consent", session, { method: "POST", body: JSON.stringify({ version: req.consent.version, accepted: true }) });
      await load(session);
      setMessage({ text: "Thank you. You can now add your photos.", kind: "info" });
    } catch (err) {
      if (!handleAuthError(err)) setMessage({ text: (err as Error).message, kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  function validate(file: File, alreadyCount: number): string | null {
    if (!req) return "Not ready";
    const ext = file.name.split(".").pop()?.toLowerCase() || "";
    if (!req.limits.allowed_extensions.includes(ext)) return `${file.name}: please choose a JPEG, PNG, WebP or HEIC photo.`;
    if (file.size > req.limits.max_file_size_bytes) return `${file.name} is larger than ${fmtBytes(req.limits.max_file_size_bytes)}.`;
    if (file.size === 0) return `${file.name} is empty.`;
    if (alreadyCount >= req.limits.max_files) return `You can upload up to ${req.limits.max_files} photos.`;
    return null;
  }

  function addFiles(list: FileList | File[]) {
    if (!req) return;
    setMessage(null);
    const queued = pending.filter((p) => !p.done && !p.error).length;
    let count = req.photos.length + queued;
    const next: Pending[] = [];
    const errors: string[] = [];
    for (const file of Array.from(list)) {
      const problem = validate(file, count);
      if (problem) {
        errors.push(problem);
        continue;
      }
      count += 1;
      const previewable = file.type.startsWith("image/") && !/hei[cf]/i.test(file.type);
      next.push({ id: `${Date.now()}-${Math.random()}`, file, preview: previewable ? URL.createObjectURL(file) : null, progress: 0, error: null, done: false });
    }
    if (errors.length) setMessage({ text: errors.join(" "), kind: "error" });
    if (next.length) {
      setPending((prev) => [...prev, ...next]);
      void uploadQueue(next);
    }
  }

  // One file at a time keeps memory and bandwidth low on both ends.
  async function uploadQueue(items: Pending[]) {
    if (!session) return;
    while (uploading.current) await new Promise((r) => setTimeout(r, 150));
    uploading.current = true;
    try {
      for (const item of items) {
        try {
          const { promise } = portalUpload(item.file, session, (f) =>
            setPending((prev) => prev.map((p) => (p.id === item.id ? { ...p, progress: f } : p))),
          );
          const photo = await promise;
          setPending((prev) => prev.map((p) => (p.id === item.id ? { ...p, progress: 1, done: true } : p)));
          setReq((r) => (r ? { ...r, photos: [...r.photos, photo] } : r));
          setPreviewFor(photo.id, item.preview);
        } catch (err) {
          if (handleAuthError(err)) return;
          setPending((prev) => prev.map((p) => (p.id === item.id ? { ...p, error: (err as Error).message } : p)));
        }
      }
    } finally {
      uploading.current = false;
    }
  }

  const [previews, setPreviews] = useState<Record<string, string | null>>({});
  function setPreviewFor(photoId: string, url: string | null) {
    setPreviews((p) => ({ ...p, [photoId]: url }));
  }

  async function removePhoto(photo: PortalPhotoOut) {
    if (!session) return;
    if (!confirm(`Remove ${photo.original_filename || "this photo"}?`)) return;
    try {
      await portalFetch<void>(`/photos/${photo.id}`, session, { method: "DELETE" });
      setReq((r) => (r ? { ...r, photos: r.photos.filter((p) => p.id !== photo.id) } : r));
      setMessage({ text: "Photo removed.", kind: "info" });
    } catch (err) {
      if (!handleAuthError(err)) setMessage({ text: (err as Error).message, kind: "error" });
    }
  }

  // The proforma opens through a short-lived, single-document link (never a public file URL).
  async function openProforma() {
    if (!session) return;
    // Open the tab now (inside the click) so pop-up blockers allow it; point it at the file once ready.
    const win = window.open("about:blank", "_blank");
    try {
      const out = await portalFetch<{ url: string }>("/proforma/link", session, { method: "POST" });
      if (win) {
        win.opener = null;
        win.location.href = `${API_URL}${out.url}`;
      } else {
        window.location.href = `${API_URL}${out.url}`;
      }
    } catch (err) {
      win?.close();
      if (!handleAuthError(err)) setMessage({ text: (err as Error).message || "The proforma could not be opened.", kind: "error" });
    }
  }

  async function submit() {
    if (!session) return;
    setBusy(true);
    try {
      const out = await portalFetch<PortalRequestOut>("/submit", session, { method: "POST" });
      setReq(out);
      setPending([]);
      setMessage(null);
      window.scrollTo({ top: 0 });
    } catch (err) {
      if (!handleAuthError(err)) setMessage({ text: (err as Error).message, kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  const activeUploads = pending.filter((p) => !p.done && !p.error);

  return (
    <div className="portalShell">
      <header style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo.png" alt="" width={40} height={40} style={{ borderRadius: 10 }} />
        <div>
          <h1 style={{ fontSize: 20, margin: 0 }}>Secure photo upload</h1>
          <div className="muted" style={{ fontSize: 13 }}>Private and encrypted in transit. Only authorised clinic staff can see your photos.</div>
        </div>
      </header>

      {phase.kind === "loading" && <div className="card" style={{ padding: 16 }} aria-live="polite">Opening your secure link…</div>}

      {phase.kind === "no_link" && (
        <div className="card" style={{ padding: 16 }} role="alert">
          <h2 style={{ fontSize: 16, marginTop: 0 }}>Link missing</h2>
          <p className="muted" style={{ marginBottom: 0 }}>Please open this page using the full link the clinic sent you.</p>
        </div>
      )}

      {phase.kind === "expired" && (
        <div className="card" style={{ padding: 16 }} role="alert">
          <h2 style={{ fontSize: 16, marginTop: 0 }}>This link has expired or is no longer valid</h2>
          <p className="muted" style={{ marginBottom: 0 }}>
            For your privacy, photo links stop working after a while or once they are replaced. Please open the latest link from the clinic again,
            or contact the clinic and ask for a new one.
          </p>
        </div>
      )}

      {phase.kind === "rate_limited" && (
        <div className="card" style={{ padding: 16 }} role="alert">
          <h2 style={{ fontSize: 16, marginTop: 0 }}>Too many attempts</h2>
          <p className="muted" style={{ marginBottom: 0 }}>Please wait 15 minutes and then open your link again.</p>
        </div>
      )}

      {phase.kind === "error" && (
        <div className="card" style={{ padding: 16 }} role="alert">
          <h2 style={{ fontSize: 16, marginTop: 0 }}>Something went wrong</h2>
          <p className="muted">{phase.message}</p>
          <button className="btn" onClick={() => window.location.reload()}>Try again</button>
        </div>
      )}

      {phase.kind === "ready" && req && (
        <>
          <section className="card" aria-labelledby="req-title">
            <div className="cardBody" style={{ display: "grid", gap: 8 }}>
              {req.patient_first_name && <div className="muted">Hello {req.patient_first_name},</div>}
              <h2 id="req-title" style={{ fontSize: 18, margin: 0 }}>{req.title}</h2>
              <div className="muted" style={{ fontSize: 13 }}>Requested {new Date(req.created_at).toLocaleDateString()}</div>
              {req.patient_message && (
                <div role="note" style={{ padding: 10, borderRadius: 10, background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.4)" }}>
                  <b>The clinic has asked for more photos:</b>
                  <div style={{ whiteSpace: "pre-wrap" }}>{req.patient_message}</div>
                </div>
              )}
              {req.instructions && (
                <div>
                  <b>Photos needed</b>
                  <div style={{ whiteSpace: "pre-wrap" }}>{req.instructions}</div>
                </div>
              )}
              <div className="muted" style={{ fontSize: 13 }}>Your photos will be reviewed by {req.reviewer}.</div>
            </div>
          </section>

          {!req.can_upload ? (
            <section className="card" aria-live="polite">
              <div className="cardBody" style={{ display: "grid", gap: 6 }}>
                <h2 style={{ fontSize: 16, margin: 0 }}>✓ Thank you — your photos have been received</h2>
                {req.submitted_at && <div className="muted">Submitted {new Date(req.submitted_at).toLocaleString()}.</div>}
                <div className="muted">
                  {req.status === "reviewed"
                    ? "Your photos have been reviewed. The clinic will contact you with next steps."
                    : "The clinic will review them and contact you. You can close this page."}
                </div>
              </div>
            </section>
          ) : !req.consent.accepted ? (
            <section className="card" aria-labelledby="consent-h">
              <div className="cardBody" style={{ display: "grid", gap: 10 }}>
                <h2 id="consent-h" style={{ fontSize: 16, margin: 0 }}>Before you upload</h2>
                <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
                  {req.consent.text.split("\n").filter(Boolean).map((line, i) => <li key={i}>{line}</li>)}
                </ul>
                <label style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                  <input type="checkbox" checked={consentTicked} onChange={(e) => setConsentTicked(e.target.checked)} />
                  <span>I have read the above and agree to share my photos with the clinic for this purpose.</span>
                </label>
                <div className="muted" style={{ fontSize: 12 }}>Consent version {req.consent.version}</div>
                <button className="btn btnPrimary" disabled={!consentTicked || busy} onClick={acceptConsent}>Continue</button>
              </div>
            </section>
          ) : (
            <section className="card" aria-labelledby="upload-h">
              <div className="cardBody" style={{ display: "grid", gap: 12 }}>
                <h2 id="upload-h" style={{ fontSize: 16, margin: 0 }}>Add your photos</h2>
                <div
                  className={`portalDrop ${dragging ? "portalDropActive" : ""}`.trim()}
                  onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
                >
                  <label htmlFor="photo-input" style={{ display: "grid", gap: 6, cursor: "pointer" }}>
                    <b>Choose photos</b>
                    <span className="muted" style={{ fontSize: 13 }}>
                      or drag them here. JPEG, PNG, WebP or HEIC · up to {fmtBytes(req.limits.max_file_size_bytes)} each · up to {req.limits.max_files} photos
                    </span>
                  </label>
                  <input
                    ref={fileInput}
                    id="photo-input"
                    type="file"
                    multiple
                    accept={[...req.limits.allowed_mime_types, ...req.limits.allowed_extensions.map((e) => `.${e}`)].join(",")}
                    onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
                    style={{ marginTop: 10 }}
                  />
                </div>

                {message && (
                  <div role={message.kind === "error" ? "alert" : "status"} style={{ color: message.kind === "error" ? "var(--danger)" : "inherit" }}>
                    {message.text}
                  </div>
                )}

                {(req.photos.length > 0 || pending.some((p) => !p.done)) && (
                  <ul className="portalGrid" style={{ listStyle: "none", padding: 0, margin: 0 }} aria-label="Your photos">
                    {req.photos.map((p) => (
                      <PhotoCard key={p.id} photo={p} session={session} preview={previews[p.id]} onRemove={() => removePhoto(p)} />
                    ))}
                    {pending.filter((p) => !p.done).map((p) => (
                      <li key={p.id} className="portalTile">
                        <div className="portalThumb">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          {p.preview && !p.error ? <img src={p.preview} alt={`Preview of ${p.file.name}`} onError={(e) => { e.currentTarget.style.display = "none"; }} /> : <span className="muted" style={{ fontSize: 12, padding: 8, overflowWrap: "anywhere" }}>{p.file.name}</span>}
                        </div>
                        <div style={{ padding: 8, display: "grid", gap: 6, fontSize: 12 }}>
                          {p.error ? (
                            <span role="alert" style={{ color: "var(--danger)" }}>{p.error}</span>
                          ) : (
                            <>
                              <span>Uploading… {Math.round(p.progress * 100)}%</span>
                              <div className="progress" role="progressbar" aria-label={`Uploading ${p.file.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(p.progress * 100)}>
                                <div style={{ width: `${Math.round(p.progress * 100)}%` }} />
                              </div>
                            </>
                          )}
                          {p.error && (
                            <button className="btn" onClick={() => setPending((prev) => prev.filter((x) => x.id !== p.id))}>Dismiss</button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}

                <div style={{ display: "grid", gap: 6 }}>
                  <button className="btn btnPrimary" onClick={submit} disabled={busy || activeUploads.length > 0 || req.photos.length === 0}>
                    {busy ? "Sending…" : activeUploads.length ? "Waiting for uploads…" : `Send ${req.photos.length} photo${req.photos.length === 1 ? "" : "s"} to the clinic`}
                  </button>
                  <div className="muted" style={{ fontSize: 12 }}>You can remove a photo before sending. After sending, the clinic will review them.</div>
                </div>
              </div>
            </section>
          )}

          <section className="card" aria-labelledby="doctor-h">
            <div className="cardBody" style={{ display: "grid", gap: 6 }}>
              <h2 id="doctor-h" style={{ fontSize: 16, margin: 0 }}>Your doctor</h2>
              {req.doctor ? (
                <>
                  <div style={{ fontWeight: 700 }}>{req.doctor.display_name}</div>
                  {(req.doctor.title || req.doctor.specialty) && (
                    <div className="muted" style={{ fontSize: 13 }}>{[req.doctor.title, req.doctor.specialty].filter(Boolean).join(" · ")}</div>
                  )}
                  {req.doctor.bio && <div style={{ whiteSpace: "pre-wrap", fontSize: 14 }}>{req.doctor.bio}</div>}
                </>
              ) : (
                <div className="muted">Your doctor&apos;s details will appear here once the clinic has added them.</div>
              )}
            </div>
          </section>

          <section className="card" aria-labelledby="proforma-h">
            <div className="cardBody" style={{ display: "grid", gap: 6 }}>
              <h2 id="proforma-h" style={{ fontSize: 16, margin: 0 }}>Your proforma invoice</h2>
              {req.proforma.available ? (
                <>
                  <div className="muted" style={{ fontSize: 13 }}>
                    {req.proforma.filename || "Proforma invoice"}
                    {req.proforma.uploaded_at ? ` · added ${new Date(req.proforma.uploaded_at).toLocaleDateString()}` : ""}
                  </div>
                  <button className="btn" onClick={openProforma} disabled={busy} style={{ justifySelf: "start" }}>Open proforma (PDF)</button>
                  <div className="muted" style={{ fontSize: 12 }}>Opens a private copy for a couple of minutes. Please don&apos;t share the address.</div>
                </>
              ) : (
                <div className="muted">There is no proforma invoice yet. The clinic will add it here when it&apos;s ready.</div>
              )}
              {message?.kind === "error" && !req.can_upload && <div role="alert" style={{ color: "var(--danger)" }}>{message.text}</div>}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function PhotoCard({ photo, session, preview, onRemove }: { photo: PortalPhotoOut; session: string | null; preview: string | null | undefined; onRemove: () => void }) {
  const [url, setUrl] = useState<string | null>(preview || null);
  const heic = /hei[cf]/.test(photo.content_type);

  // After a reload the local preview is gone; fetch the patient's own photo with their session.
  useEffect(() => {
    if (url || heic || !session) return;
    let revoked: string | null = null;
    fetch(`${API_URL}/portal/photo-request/photos/${photo.id}/content`, { headers: { Authorization: `Bearer ${session}` }, cache: "no-store" })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (b) {
          revoked = URL.createObjectURL(b);
          setUrl(revoked);
        }
      })
      .catch(() => undefined);
    return () => { if (revoked) URL.revokeObjectURL(revoked); };
  }, [photo.id, session]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <li className="portalTile">
      <div className="portalThumb">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {url ? <img src={url} alt={`Your photo ${photo.original_filename || ""}`.trim()} /> : <span className="muted" style={{ fontSize: 12, padding: 8, textAlign: "center" }}>{heic ? "HEIC photo (no preview)" : "Loading preview…"}</span>}
      </div>
      <div style={{ padding: 8, display: "grid", gap: 6, fontSize: 12 }}>
        <span>✓ Uploaded · {fmtBytes(photo.size_bytes)}</span>
        <button className="btn" onClick={onRemove} aria-label={`Remove ${photo.original_filename || "photo"}`}>Remove</button>
      </div>
    </li>
  );
}
