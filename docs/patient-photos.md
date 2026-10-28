# Patient photo requests

Staff ask a patient for photos, the patient uploads them through a private portal
link, a doctor reviews them, and the whole history stays on the patient's CRM record.

## Workflow and statuses

| Status | Meaning | Set by |
| --- | --- | --- |
| `requested` | Request created, link issued, waiting for the patient | staff (create) |
| `uploaded` | Patient pressed "Send" | patient |
| `in_review` | Someone is working on it | staff |
| `more_photos_needed` | Doctor asked for more; patient sees the doctor's message and can upload a new round | doctor |
| `reviewed` | Doctor finished (needs at least one clinical assessment) | doctor |
| `closed` | Done; links revoked | staff |
| `withdrawn` | Cancelled before review finished; links revoked | staff |

Allowed transitions: `uploaded/reviewed → in_review`; `uploaded/in_review/reviewed → more_photos_needed`;
`uploaded/in_review → reviewed`; any non-final → `closed`; `requested/uploaded/in_review/more_photos_needed → withdrawn`.
`more_photos_needed → uploaded` happens when the patient sends the new round.

Where to find it: CRM staff use the **Photo requests** and **Care team** cards on a contact and **Photo reviews** in the sidebar. Doctors use `/doctor` (Patients, Photos), assistants use `/assistant`, and admins use **Care team** in the sidebar.

## Roles

Enforced in `api/app/services/photo_permissions.py` on every request; the UI only mirrors it.

| Action | admin | manager | coordinator | doctor | doctor_assistant | user | viewer |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| See request list, status, history, upload status | ✓ all | ✓ | ✓ | assigned | their doctors' patients | ✓ | ✓ |
| Create request, email/copy link, revoke links | ✓ | ✓ | ✓ | assigned | | | |
| View / download photos | ✓ | ✓ | ✓ | assigned | | | |
| Read & write internal notes | ✓ | ✓ | ✓ | assigned | | | |
| Read clinical assessments | ✓ | ✓ | ✓ | assigned | | | |
| **Write assessments, mark reviewed, request more photos** | | | | assigned | | | |
| Start review, close, withdraw | ✓ | ✓ | ✓ | assigned | | | |
| Hide a photo (soft delete) | ✓ | ✓ | | | | | |
| View / upload / replace proforma | ✓ | ✓ | ✓ | | their doctors' patients | | |
| Assign doctors and assistants, edit doctor profiles | ✓ | | | | | | |
| General CRM (contacts, deals, events, inbox, settings…) | ✓ | ✓ | ✓ | **no** | **no** | ✓ | ✓ |

- **Which patients:** admins see every patient. Doctors see only patients assigned to them
  (`doctor_patient_assignments`, one active doctor per patient). Assistants see only patients
  whose doctor they are assigned to (`assistant_doctor_assignments`). Other CRM roles follow
  `SHARE_CUSTOMERS_ACROSS_USERS`. Assignments are explicit rows set by an admin, never
  guessed from names or emails, and ending one keeps its history.
- **Doctors and assistants never reach the CRM:** every existing CRM route uses
  `get_current_user`, which refuses these two roles (403). Only `/auth/me`, `/care/*`,
  `/photo-requests/*`, `/customers/{id}/photo-requests*` and `/customers/{id}/proforma*` use
  `get_authenticated_user`, and those check role and assignment themselves. A test walks every
  authenticated GET route and checks that both roles get 403.
- Doctors land on `/doctor/patients` (sections: Patients, Photos), assistants on `/assistant`.
  The CRM layout redirects them away, and the CRM sidebar hides admin-only pages from non-admins.
- `user` is the role every new account starts with, so it gets no clinical access. Give
  assistants who work in the CRM the `coordinator` role, and assistants who work for a doctor
  the `doctor_assistant` role.
- Notes and assessments can only be edited by their author. Every version is kept
  (`photo_entry_revisions`) and shown as edit history.

## Emailing the upload link

"Email link to patient" (contact page, doctor interface, or "Email the secure upload link" when
creating a request) queues an email through the existing outbox (`outbound_messages`, sent by
the worker) using the `photo_request_link` template. Migration 0025 seeds this template, and it
can be edited on the Templates page; sending refuses if it no longer contains `{{portal_link}}`.

- The email contains only the personal link and its expiry date: no photos, attachments or
  clinical details.
- **No duplicates:** each link has at most one email (`photo_request_emails.link_id` is
  unique), and the request row is locked while sending. If the current link's email is queued,
  sending or sent, a repeated send returns it with `duplicate: true` and queues nothing.
  "Resend" deliberately sends a new link and revokes the old one.
- **Failures change nothing:** if the patient has no valid email, has opted out
  (`can_contact = false`), or the message cannot be queued, the API returns a clear error
  (422/503). No link, email record or pipeline change is kept, and the attempt is audited as
  `photo_request.email_not_sent`. The CRM shows the outbox status (queued / sent / failed),
  so a later worker failure is visible and the link can be resent.
- **The link is not kept in CRM data:** it only lives in the queued message's variables. The
  outbox API shows it as `[hidden]`. The worker sends the real link, writes a redacted copy to
  the contact thread, and wipes the link from the queue row once the message is sent or fails
  (`worker/app/redaction.py`).

### Pipeline

The CRM pipeline stage lives on the patient (`customers.stage`; deals have no stage). When a link
email is queued, the patient's card moves to the new **Photos Requested** stage (between
Interested and Appointment Booked), **forward only**. A patient at or past that stage, `lost`,
or an unknown stage is left alone. Stages are plain strings, so no migration was needed; the
frontend stage list gained `photos_requested`. The request is also linked to the enquiry
(deal) it is about. If the patient has several open enquiries and none was chosen, sending is
refused with `deal_selection_required` and staff pick one; deal records themselves are never
changed. A patient uploading photos never changes the pipeline.

## Proforma invoices

Admins, managers, coordinators and assistants (for their doctors' patients) can upload or
replace a patient's proforma on the contact page or in the assistant interface. It's a PDF,
validated by extension, MIME type and `%PDF-` signature, up to `PROFORMA_MAX_FILE_SIZE_MB`. It is
streamed into the same private storage as photos and stored as `patient_documents`
(category `proforma`). Replacing one supersedes the old file instead of deleting it. Every
upload, replacement, view and download is audited.

The patient portal shows only the request instructions and upload controls, their current
proforma (if any), and their assigned doctor's profile, but only if an admin filled it in and
ticked "show to patients". Otherwise it shows clear empty states. Patients open the proforma
through `POST /portal/photo-request/proforma/link`, which returns a link to that one document
valid for `PORTAL_DOCUMENT_LINK_SECONDS` (default 120 s). The link is signed with the portal
key and its own audience, and stops working if the portal link is revoked or the document is
replaced.

## Doctors and staff logins

Doctors and assistants are ordinary staff accounts (`users` table). An admin creates them on
the Users page with the `doctor` or `doctor_assistant` role, and they sign in at `/login`.
They are then sent to their own interface. Roles are read from the database on every
request, not stored in the JWT, so a role change takes effect immediately.

## Future patient accounts (not built yet)

The guest link is one way into the portal, and the design leaves room for others:

- Requests belong to the CRM customer (`photo_requests.customer_id`, `ON DELETE RESTRICT`;
  merges move them). A future verified patient account should be its own table (e.g.
  `patient_accounts` with a unique, verified link to `customers.id`), **not** a row in `users`.
  Every existing staff route treats any `users` row as staff.
- Portal sessions already use their own signing key and audience, separate from staff
  JWTs. A patient-login session should get its own token type in the same way and resolve to
  the set of requests for its customer. Portal routes for several requests would be
  new routes (`/portal/photo-requests/{id}`) that check the request belongs to that customer.
  `PortalContext` is the place to add this.
- Patient actions are recorded as `actor_type: "patient"` with the `link_id`
  (audit metadata, status events, `uploaded_via_link_id`, `consent_link_id`). Account-based
  actions can add nullable `patient_account_id` columns next to these without changing existing rows.
- Guest links can stay alongside accounts (e.g. for patients who never register).

## Patient access (assumption: the CRM has no patient login)

There was no patient authentication, so the portal uses per-request links:

- Link token = 256 random bits (`pr_…`). Only its SHA-256 is stored. The token is shown to
  staff once, when issued.
- The link is `FRONTEND_BASE_URL/portal/photos#token=…`. The token is in the URL fragment,
  so it is never sent to a server, logged by proxies, or leaked via `Referer`; the page removes
  it from the address bar after use.
- Opening the link exchanges it (`POST /portal/photo-request/session`) for a 30-minute session
  JWT signed with a portal-only key and audience. It cannot be used on staff routes, and staff
  tokens do not work on the portal. Each portal route works out the request from the session,
  never from an ID in the URL, so changing IDs cannot reach another patient.
- Links expire (`PHOTO_LINK_TTL_HOURS`), are limited to `PHOTO_LINK_MAX_USES` opens, are revoked
  when a new link is issued or the request is closed/withdrawn, and can be revoked by staff.
  Revocation also kills sessions already opened from that link.
- Failed link exchanges are rate-limited per client IP (`PHOTO_PORTAL_MAX_FAILED_ATTEMPTS` per
  `PHOTO_PORTAL_LOCKOUT_MINUTES`). The limiter is in memory, which is correct for the single
  uvicorn process this project runs; with several workers each keeps its own count.
- The patient must accept the consent statement (version `PHOTO_CONSENT_VERSION`) before
  uploading. The version, time and link used are stored on the request and shown to staff.
  Bumping the version requires fresh consent.
- Staff send the link through their usual channel. **Only the link** is sent; photos and
  assessments are never attached to WhatsApp, email or CRM notifications.

## Storage (assumption: no object storage was configured)

- `PHOTO_STORAGE_BACKEND=local` stores files in `PHOTO_STORAGE_DIR` (docker volume
  `photo_data` → `/data/patient_photos`). Directories are `0700`, files `0600`. Nothing is
  mounted as static files. Photos are served only by authenticated, audited endpoints with
  `Cache-Control: no-store`, `nosniff` and a sandbox CSP.
- Storage keys are random (`ab/<32 hex>.jpg`). Patient names, emails and original filenames
  are never used in paths; a cleaned-up original filename is kept as display metadata only.
- The database stores only metadata (size, SHA-256, type, round, key). No image bytes.
- The storage interface (`PhotoStorage` in `api/app/services/photo_storage.py`) can be backed by
  a private S3-compatible bucket later without changing the API.

### Uploads on a 2 GB server

- The portal uploads **one file per request as the raw body** (`PUT /portal/photo-request/photos`),
  one file at a time. The API reads it with `request.stream()` in ~64 KB chunks and writes each
  chunk straight to a temp file, so memory use stays at one chunk per upload, whatever the file size.
  No multipart parsing and no full-body buffering.
- Limits are checked while streaming: `Content-Length` is required and checked first, and the
  upload stops the moment it goes over `PHOTO_MAX_FILE_SIZE_MB`.
- The first 16 bytes must match a real JPEG/PNG/WebP/HEIC signature, **and** the extension and
  declared MIME type must agree with it. Everything else is rejected with 415 and the temp
  file is deleted.
- `PHOTO_MAX_FILES_PER_REQUEST` applies to each upload round and is re-checked under a row
  lock so parallel uploads cannot get past it.
- No thumbnails or conversion on the server. Browsers preview photos locally; staff fetch the
  original photo only when they click "View photo". HEIC is stored as-is (download to view).

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `PHOTO_STORAGE_BACKEND` | `local` | Only `local` is implemented |
| `PHOTO_STORAGE_DIR` | `/data/patient_photos` | Must be private and persistent; **back it up** with the database |
| `PHOTO_MAX_FILE_SIZE_MB` | `15` | Per photo |
| `PHOTO_MAX_FILES_PER_REQUEST` | `10` | Per upload round |
| `PHOTO_ALLOWED_FORMATS` | `jpeg,png,webp,heic` | Subset of these four |
| `PHOTO_LINK_TTL_HOURS` | `72` | |
| `PHOTO_LINK_MAX_USES` | `10` | Link opens (each opens a 30-min session) |
| `PHOTO_PORTAL_SESSION_MINUTES` | `30` | |
| `PHOTO_PORTAL_MAX_FAILED_ATTEMPTS` / `PHOTO_PORTAL_LOCKOUT_MINUTES` | `10` / `15` | Brute-force limit |
| `PHOTO_PORTAL_TRUST_PROXY_HEADERS` | `false` | Set `true` only behind a proxy that overwrites `X-Forwarded-For` |
| `PHOTO_CONSENT_VERSION` | `2026-10-v1` | Change when the consent wording changes |
| `PHOTO_REVIEWER_DESCRIPTION` | "a doctor from the Health Clinic Türkiye medical team" | Shown to patients |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Used to build portal links; **set to the public frontend URL** |
| `PROFORMA_ALLOWED_FORMATS` | `pdf` | Proforma file types |
| `PROFORMA_MAX_FILE_SIZE_MB` | `10` | Per proforma |
| `PORTAL_DOCUMENT_LINK_SECONDS` | `120` | Lifetime of a patient's proforma link |

### Deployment checklist

1. `alembic upgrade head` (runs automatically in `entrypoint.sh`). Migration `0024` adds the
   `doctor` role and the photo tables.
2. Mount a persistent, private volume at `PHOTO_STORAGE_DIR` and include it in backups.
3. Set `FRONTEND_BASE_URL` to the public HTTPS frontend URL. Serve the portal over HTTPS only.
4. Reverse proxy (e.g. nginx) in front of the API: `client_max_body_size` at least
   `PHOTO_MAX_FILE_SIZE_MB` + 1m, and preferably `proxy_request_buffering off;` for
   `/portal/photo-request/photos` so the body streams through. Make sure `/data` or the volume
   path is never exposed as a static location.
5. Give clinicians the `doctor` role and their assistants `doctor_assistant` on the Users page,
   then link assistants to doctors and fill in doctor profiles on **Care team**, and assign
   patients to doctors on each contact page.
6. Rebuild and restart the **worker** too (`docker compose up -d --build worker`): it gained
   the link redaction. Email sending needs the existing SMTP settings.

## Audit

Care team and documents: `care_team.doctor_assigned/unassigned` (customer),
`care_team.assistant_doctors_set` and `care_team.doctor_profile_updated` (user),
`patient_document.uploaded/replaced/viewed/downloaded/link_issued_to_patient/viewed_by_patient`
(document), `pipeline.stage_changed` with `source: photo_request_email` (customer).

Photo requests are written to `audit_logs` with `entity_type="photo_request"` and the request id
(including `photo_request.email_queued` and `.email_not_sent`):
`photo_request.created`, `.link_issued`, `.link_revoked`, `.status_changed` (staff and patient),
`.consent_recorded`, `.note_created/updated`, `.assessment_created/updated`,
`photo_portal.session_opened`, `photo_portal.access_denied`, `patient_photo.uploaded`,
`.viewed`, `.downloaded`, `.viewed_by_patient`, `.removed_by_patient`, `.hidden`.
Audit rows record versions and lengths, never note or assessment text (that stays in the
access-controlled revisions table).

Nothing is hard-deleted: requests are closed/withdrawn, links revoked, photos soft-deleted
(a photo the patient removes *before sending* has its file erased but keeps its metadata row).
Deleting a contact with photo requests is blocked (409); merging contacts moves the requests
to the surviving contact.

## Tests

`api/tests/test_patient_photos.py` and `api/tests/test_care_team.py` (run with the rest of the suite, see `api/tests/README.md`).
