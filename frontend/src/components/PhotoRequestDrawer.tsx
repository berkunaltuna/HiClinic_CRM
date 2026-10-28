"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { fmtDateTime } from "@/lib/dates";
import { useToast } from "@/components/Toast";
import {
  type EntryOut,
  type IssuedLinkOut,
  type PatientPhotoOut,
  type PhotoRequestDetailOut,
  EMAIL_STATUS_LABELS,
  dealSelectionFrom,
  errorDetail,
  fetchStaffPhotoUrl,
  fmtBytes,
  photoStatusLabel,
} from "@/lib/photoRequests";

const can = (d: PhotoRequestDetailOut | null, p: string) => !!d?.permissions.includes(p);

/** Staff view of one photo request. Every action is also enforced by the API. */
export function PhotoRequestDrawer({
  requestId,
  onClose,
  onChanged,
}: {
  requestId: string;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const toast = useToast();
  const [d, setD] = useState<PhotoRequestDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [issuedUrl, setIssuedUrl] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  async function load() {
    try {
      setD(await apiFetch<PhotoRequestDetailOut>(`/photo-requests/${requestId}`));
      setError(null);
    } catch (err: any) {
      setError(err?.status === 404 ? "This photo request was not found or you do not have access." : err?.message || "Failed to load");
    }
  }

  useEffect(() => {
    void load();
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestId]);

  async function act<T>(fn: () => Promise<T>, success: string): Promise<T | undefined> {
    setBusy(true);
    try {
      const out = await fn();
      toast.push(success);
      onChanged?.();
      return out;
    } catch (err: any) {
      let msg = err?.message || "Action failed";
      try {
        msg = JSON.parse(err?.bodyText || "").detail || msg;
      } catch {
        // keep msg
      }
      toast.push(msg, "error");
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(status: string) {
    let patient_message: string | undefined;
    let reason: string | undefined;
    if (status === "more_photos_needed") {
      const m = window.prompt("Message to the patient: which photos are needed? (The patient will see this.)");
      if (!m?.trim()) return;
      patient_message = m.trim();
    } else if (status === "closed" || status === "withdrawn") {
      const r = window.prompt(`Internal reason for ${status === "closed" ? "closing" : "withdrawing"} (staff only, optional):`);
      if (r === null) return;
      reason = r.trim() || undefined;
    }
    const out = await act(
      () => apiFetch<PhotoRequestDetailOut>(`/photo-requests/${requestId}/status`, { method: "POST", body: JSON.stringify({ status, patient_message, reason }) }),
      `Status: ${photoStatusLabel(status)}`,
    );
    if (out) setD(out);
  }

  async function issueLink() {
    const out = await act(() => apiFetch<IssuedLinkOut>(`/photo-requests/${requestId}/links`, { method: "POST" }), "New patient link created");
    if (out) {
      setIssuedUrl(out.portal_url);
      await load();
    }
  }

  async function emailLink(resend = false, dealId?: string) {
    setBusy(true);
    try {
      const out = await apiFetch<IssuedLinkOut>(`/photo-requests/${requestId}/send-email`, {
        method: "POST",
        body: JSON.stringify({ resend, deal_id: dealId || null }),
      });
      if (out.duplicate) {
        toast.push(`An email with a valid link is already ${EMAIL_STATUS_LABELS[out.email?.status || ""]?.toLowerCase() || "on its way"}. Nothing new was sent.`);
      } else {
        toast.push(`Link emailed to ${out.email?.to_email}${out.pipeline?.changed ? " · pipeline moved to Photos Requested" : ""}`);
      }
      onChanged?.();
      await load();
    } catch (err: any) {
      const sel = dealSelectionFrom(err);
      if (sel) {
        const choice = window.prompt(
          `${sel.message}\n\n${sel.deals.map((d, i) => `${i + 1}. ${d.label}`).join("\n")}\n\nType the number of the enquiry:`,
        );
        const picked = choice ? sel.deals[Number(choice) - 1] : undefined;
        setBusy(false);
        if (picked) await emailLink(resend, picked.id);
        return;
      }
      toast.push(errorDetail(err, "The email was not sent"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function revokeLink(linkId: string) {
    if (!confirm("Revoke this link? The patient will no longer be able to use it.")) return;
    await act(() => apiFetch(`/photo-requests/${requestId}/links/${linkId}/revoke`, { method: "POST", body: JSON.stringify({}) }), "Link revoked");
    await load();
  }

  const status = d?.request.status;
  const terminal = status === "closed" || status === "withdrawn";

  return (
    <>
      <div className="drawerOverlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="photo-request-title" style={{ width: "min(760px, 100vw)" }}>
        <div className="drawerHeader">
          <div style={{ minWidth: 0 }}>
            <div id="photo-request-title" style={{ fontWeight: 900 }}>{d?.request.title || "Photo request"}</div>
            {d && <div className="muted" style={{ fontSize: 12 }}>{d.customer_name} · created {fmtDateTime(d.request.created_at)}{d.request.created_by_email ? ` by ${d.request.created_by_email}` : ""}</div>}
          </div>
          <button ref={closeRef} className="btn" onClick={onClose} aria-label="Close photo request">Close</button>
        </div>
        <div className="drawerBody stack" style={{ gap: 14 }}>
          {error ? (
            <div role="alert" className="card" style={{ padding: 12 }}>{error}</div>
          ) : !d ? (
            <div className="muted" aria-live="polite">Loading…</div>
          ) : (
            <>
              <section aria-label="Status" style={{ display: "grid", gap: 8 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span className="badge" style={{ fontWeight: 800 }}>{photoStatusLabel(d.request.status)}</span>
                  <span className="muted" style={{ fontSize: 12 }}>
                    Consent: {d.request.consent_status === "accepted" ? `accepted ${fmtDateTime(d.request.consent_accepted_at)} (v${d.request.consent_version})` : "not yet given"}
                  </span>
                  {d.request.submitted_at && <span className="muted" style={{ fontSize: 12 }}>· submitted {fmtDateTime(d.request.submitted_at)}</span>}
                </div>
                {d.request.instructions && <div className="muted" style={{ whiteSpace: "pre-wrap" }}><b>Patient instructions:</b> {d.request.instructions}</div>}
                {d.request.patient_message && <div className="muted" style={{ whiteSpace: "pre-wrap" }}><b>Last message to patient:</b> {d.request.patient_message}</div>}
                <div className="muted" style={{ fontSize: 12 }}>
                  Doctor: {d.assigned_doctor ? (d.assigned_doctor.display_name || d.assigned_doctor.email) : "not assigned"}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {can(d, "photo_request.manage_status") && (status === "uploaded" || status === "reviewed") && (
                    <button className="btn" disabled={busy} onClick={() => changeStatus("in_review")}>{status === "reviewed" ? "Reopen review" : "Start review"}</button>
                  )}
                  {can(d, "photo_request.request_more") && (status === "uploaded" || status === "in_review" || status === "reviewed") && (
                    <button className="btn" disabled={busy} onClick={() => changeStatus("more_photos_needed")}>Request more photos</button>
                  )}
                  {can(d, "photo_request.mark_reviewed") && (status === "uploaded" || status === "in_review") && (
                    <button className="btn btnPrimary" disabled={busy || !d.assessments?.length} title={!d.assessments?.length ? "Add a clinical assessment first" : undefined} onClick={() => changeStatus("reviewed")}>Mark reviewed</button>
                  )}
                  {can(d, "photo_request.manage_status") && !terminal && (
                    <button className="btn" disabled={busy} onClick={() => changeStatus("closed")}>Close</button>
                  )}
                  {can(d, "photo_request.manage_status") && !terminal && status !== "reviewed" && (
                    <button className="btn btnDanger" disabled={busy} onClick={() => changeStatus("withdrawn")}>Withdraw</button>
                  )}
                </div>
              </section>

              <PhotosSection detail={d} onChanged={load} />

              {d.assessments !== null && (
                <EntriesSection
                  title="Clinical assessments"
                  hint="Written by doctors only. Not visible to the patient."
                  entries={d.assessments}
                  canWrite={can(d, "assessment.write") && status !== "requested" && status !== "withdrawn"}
                  path={`/photo-requests/${requestId}/assessments`}
                  onSaved={(x) => { setD(x); onChanged?.(); }}
                />
              )}

              {d.notes !== null && (
                <EntriesSection
                  title="Internal notes"
                  hint="Administrative notes for staff. Never shown to the patient."
                  entries={d.notes}
                  canWrite={can(d, "note.write")}
                  path={`/photo-requests/${requestId}/notes`}
                  onSaved={(x) => { setD(x); onChanged?.(); }}
                />
              )}

              <section aria-labelledby="links-h" className="card">
                <div className="cardHeader" id="links-h" style={{ fontWeight: 900, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  Patient portal links
                  {can(d, "photo_request.manage_links") && (status === "requested" || status === "more_photos_needed") && (
                    <span style={{ display: "flex", gap: 6 }}>
                      <button className="btn btnPrimary" disabled={busy} onClick={() => emailLink(false)}>Email link to patient</button>
                      {d.emails.length > 0 && <button className="btn" disabled={busy} onClick={() => confirm("Send a new link? The previous link stops working.") && emailLink(true)}>Resend</button>}
                      <button className="btn" disabled={busy} onClick={issueLink}>Copy new link</button>
                    </span>
                  )}
                </div>
                <div className="cardBody" style={{ display: "grid", gap: 8 }}>
                  {d.emails.length > 0 && (
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }} aria-label="Emails sent">
                      {d.emails.map((e) => (
                        <li key={e.id}>
                          <b>{EMAIL_STATUS_LABELS[e.status || ""] || e.status || "Email"}</b>{" "}
                          <span className="muted">to {e.to_email} · {fmtDateTime(e.created_at)}{e.sent_by_email ? ` by ${e.sent_by_email}` : ""}</span>
                          {e.status === "failed" && e.last_error && <div style={{ color: "var(--danger)", fontSize: 12 }}>{e.last_error}</div>}
                        </li>
                      ))}
                    </ul>
                  )}
                  {issuedUrl && <IssuedLink url={issuedUrl} />}
                  {d.links.map((l) => (
                    <div key={l.id} style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", fontSize: 13 }}>
                      <span>
                        <span className="badge">{l.active ? "Active" : l.revoked_at ? "Revoked" : "Inactive"}</span>{" "}
                        <span className="muted">created {fmtDateTime(l.created_at)} · expires {fmtDateTime(l.expires_at)} · opened {l.use_count}/{l.max_uses}{l.revoke_reason ? ` · ${l.revoke_reason}` : ""}</span>
                      </span>
                      {l.active && can(d, "photo_request.manage_links") && (
                        <button className="btn" onClick={() => revokeLink(l.id)} aria-label={`Revoke link created ${fmtDateTime(l.created_at)}`}>Revoke</button>
                      )}
                    </div>
                  ))}
                  {!d.links.length && <div className="muted">No links.</div>}
                </div>
              </section>

              <section aria-labelledby="history-h" className="card">
                <div className="cardHeader" id="history-h" style={{ fontWeight: 900 }}>History</div>
                <div className="cardBody">
                  <ol style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
                    {d.history.map((h, i) => (
                      <li key={i} style={{ fontSize: 13 }}>
                        <b>{photoStatusLabel(h.to_status)}</b>{" "}
                        <span className="muted">
                          {fmtDateTime(h.created_at)} · {h.actor_type === "patient" ? "patient" : `${h.actor_email || "staff"} (${h.actor_role})`}
                          {h.reason ? ` · ${h.reason}` : ""}
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

export function IssuedLink({ url }: { url: string }) {
  const toast = useToast();
  return (
    <div style={{ display: "grid", gap: 6, padding: 10, border: "1px solid var(--border)", borderRadius: 12, background: "rgba(30,103,150,0.05)" }}>
      <label htmlFor="issued-link" style={{ fontSize: 12, fontWeight: 800 }}>Patient link (shown once — copy it now)</label>
      <div style={{ display: "flex", gap: 8 }}>
        <input id="issued-link" className="formField" readOnly value={url} onFocus={(e) => e.currentTarget.select()} />
        <button
          className="btn btnPrimary"
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(url);
              toast.push("Link copied");
            } catch {
              toast.push("Copy failed — select the link and copy it manually", "error");
            }
          }}
        >
          Copy
        </button>
      </div>
      <div className="muted" style={{ fontSize: 12 }}>
        Send only this link to the patient. Never ask for or send photos by WhatsApp or email.
      </div>
    </div>
  );
}

function PhotosSection({ detail, onChanged }: { detail: PhotoRequestDetailOut; onChanged: () => void }) {
  if (detail.photos === null) {
    return <div className="muted">Your role cannot view patient photos.</div>;
  }
  const visible = detail.photos.filter((p) => !p.deleted_at);
  const rounds = Array.from(new Set(visible.map((p) => p.upload_round))).sort((a, b) => b - a);
  return (
    <section aria-labelledby="photos-h" className="card">
      <div className="cardHeader" id="photos-h" style={{ fontWeight: 900 }}>Photos ({visible.length})</div>
      <div className="cardBody" style={{ display: "grid", gap: 12 }}>
        {!visible.length && <div className="muted">No photos submitted yet.</div>}
        {rounds.map((round) => (
          <div key={round} style={{ display: "grid", gap: 8 }}>
            {rounds.length > 1 && <div className="muted" style={{ fontSize: 12, fontWeight: 800 }}>Upload round {round}</div>}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 10 }}>
              {visible.filter((p) => p.upload_round === round).map((p) => (
                <PhotoTile key={p.id} requestId={detail.request.id} photo={p} canHide={detail.permissions.includes("photo.hide")} onChanged={onChanged} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function PhotoTile({ requestId, photo, canHide, onChanged }: { requestId: string; photo: PatientPhotoOut; canHide: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const previewable = photo.content_type !== "image/heic";

  // Photos are only fetched (and the view audited) when staff choose to open them.
  async function show() {
    setState("loading");
    try {
      setUrl(await fetchStaffPhotoUrl(requestId, photo.id));
      setState("idle");
    } catch {
      setState("error");
    }
  }

  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  async function download() {
    try {
      const u = await fetchStaffPhotoUrl(requestId, photo.id, true);
      const a = document.createElement("a");
      a.href = u;
      a.download = `photo-${photo.id}.${photo.content_type.split("/")[1] || "img"}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(u), 1000);
    } catch {
      toast.push("Download failed", "error");
    }
  }

  async function hide() {
    const reason = window.prompt("Reason for hiding this photo (it is kept in the record):");
    if (!reason?.trim()) return;
    try {
      await apiFetch(`/photo-requests/${requestId}/photos/${photo.id}/hide`, { method: "POST", body: JSON.stringify({ reason: reason.trim() }) });
      toast.push("Photo hidden");
      onChanged();
    } catch (err: any) {
      toast.push(err?.message || "Failed to hide photo", "error");
    }
  }

  return (
    <figure style={{ margin: 0, border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden", display: "grid" }}>
      <div style={{ aspectRatio: "1 / 1", background: "#f3f6f8", display: "flex", alignItems: "center", justifyContent: "center" }}>
        {url && previewable ? (
          <a href={url} target="_blank" rel="noopener noreferrer" aria-label="Open photo full size">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt={`Patient photo uploaded ${fmtDateTime(photo.uploaded_at)}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          </a>
        ) : state === "loading" ? (
          <span className="muted" aria-live="polite">Loading…</span>
        ) : state === "error" ? (
          <span role="alert" className="muted">Could not load</span>
        ) : previewable ? (
          <button className="btn" onClick={show}>View photo</button>
        ) : (
          <span className="muted" style={{ fontSize: 12, padding: 8, textAlign: "center" }}>HEIC — download to view</span>
        )}
      </div>
      <figcaption style={{ padding: 8, fontSize: 12, display: "grid", gap: 4 }}>
        <span className="muted">{fmtBytes(photo.size_bytes)} · {fmtDateTime(photo.uploaded_at)}</span>
        <span style={{ display: "flex", gap: 6 }}>
          <button className="btn" style={{ padding: "4px 8px", fontSize: 12 }} onClick={download}>Download</button>
          {canHide && <button className="btn" style={{ padding: "4px 8px", fontSize: 12 }} onClick={hide}>Hide</button>}
        </span>
      </figcaption>
    </figure>
  );
}

function EntriesSection({
  title,
  hint,
  entries,
  canWrite,
  path,
  onSaved,
}: {
  title: string;
  hint: string;
  entries: EntryOut[];
  canWrite: boolean;
  path: string;
  onSaved: (d: PhotoRequestDetailOut) => void;
}) {
  const toast = useToast();
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [me, setMe] = useState<string | null>(null);
  const id = title.toLowerCase().replace(/\s+/g, "-");

  useEffect(() => {
    apiFetch<{ id: string }>("/auth/me").then((m) => setMe(m.id)).catch(() => setMe(null));
  }, []);

  async function save(url: string, method: "POST" | "PATCH", body: string) {
    setSaving(true);
    try {
      onSaved(await apiFetch<PhotoRequestDetailOut>(url, { method, body: JSON.stringify({ body }) }));
      toast.push("Saved");
      return true;
    } catch (err: any) {
      toast.push(err?.status === 403 ? "Your role cannot do this" : err?.message || "Failed to save", "error");
      return false;
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby={`${id}-h`} className="card">
      <div className="cardHeader" id={`${id}-h`} style={{ fontWeight: 900 }}>
        {title}
        <div className="muted" style={{ fontSize: 12, fontWeight: 400 }}>{hint}</div>
      </div>
      <div className="cardBody" style={{ display: "grid", gap: 10 }}>
        {!entries.length && <div className="muted">None yet.</div>}
        {entries.map((e) => (
          <article key={e.id} style={{ padding: 10, border: "1px solid var(--border)", borderRadius: 12, display: "grid", gap: 6 }}>
            <div className="muted" style={{ fontSize: 12 }}>
              {e.author_email || "staff"} ({e.author_role}) · {fmtDateTime(e.created_at)}
              {e.version > 1 ? ` · edited ${fmtDateTime(e.updated_at)} (v${e.version})` : ""}
            </div>
            {editing === e.id ? (
              <form onSubmit={async (ev) => { ev.preventDefault(); if (await save(`${path}/${e.id}`, "PATCH", editDraft.trim())) setEditing(null); }} style={{ display: "grid", gap: 6 }}>
                <label htmlFor={`edit-${e.id}`} className="muted" style={{ fontSize: 12 }}>Edit {title.toLowerCase().replace(/s$/, "")}</label>
                <textarea id={`edit-${e.id}`} rows={4} value={editDraft} onChange={(ev) => setEditDraft(ev.target.value)} />
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="btn btnPrimary" type="submit" disabled={saving || !editDraft.trim()}>Save</button>
                  <button className="btn" type="button" onClick={() => setEditing(null)}>Cancel</button>
                </div>
              </form>
            ) : (
              <div style={{ whiteSpace: "pre-wrap" }}>{e.body}</div>
            )}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {canWrite && me === e.author_user_id && editing !== e.id && (
                <button className="btn" style={{ padding: "4px 8px", fontSize: 12 }} onClick={() => { setEditing(e.id); setEditDraft(e.body); }}>Edit</button>
              )}
              {e.revisions.length > 1 && (
                <details>
                  <summary className="muted" style={{ fontSize: 12, cursor: "pointer" }}>Edit history ({e.revisions.length} versions)</summary>
                  <ol style={{ paddingLeft: 18, fontSize: 12 }}>
                    {e.revisions.map((r) => (
                      <li key={r.version}>
                        <span className="muted">v{r.version} · {r.editor_email} ({r.editor_role}) · {fmtDateTime(r.created_at)}</span>
                        <div style={{ whiteSpace: "pre-wrap" }}>{r.body}</div>
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </div>
          </article>
        ))}
        {canWrite && (
          <form onSubmit={async (ev) => { ev.preventDefault(); if (await save(path, "POST", draft.trim())) setDraft(""); }} style={{ display: "grid", gap: 6 }}>
            <label htmlFor={`${id}-new`} className="muted" style={{ fontSize: 12 }}>Add {title.toLowerCase().replace(/s$/, "")}</label>
            <textarea id={`${id}-new`} rows={3} value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={10000} />
            <button className="btn btnPrimary" type="submit" disabled={saving || !draft.trim()}>{saving ? "Saving…" : "Add"}</button>
          </form>
        )}
      </div>
    </section>
  );
}
