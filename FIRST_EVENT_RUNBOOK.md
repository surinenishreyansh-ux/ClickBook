# ClickBook: first in-person event readiness and security

**Scope:** An organizer hosts an in-person event. Approved photographers upload
JPEGs using the web camera, phone, or DSLR folder uploader. Guests scan one
QR code to view the gallery. **No payments, checkout, invoicing, or billing
feature is required in this release.**

A successful automated photo smoke test does **not** guarantee availability,
face-match accuracy, or security under a real crowd. This is the pre-event
release checklist for a first limited pilot.

## Release gates — complete before inviting real guests

- [ ] Use **non-sensitive test photos** for a complete rehearsal: organizer
  signs in, creates event, invites separate photographer, photographer signs
  in and uploads, guest sees image via QR, organizer deletes image.
- [ ] Confirm at least two phones (Android/iOS if available) work over
  **mobile data**, not just venue Wi-Fi, including camera permission over HTTPS.
- [ ] Rehearse DSLRs and backup uploader with the real tethering workflow.
  Carry sufficient storage cards and keep original files locally.
- [ ] With **20+ consented testers**, simulate multiple concurrent uploads
  and guest gallery refreshes. Inspect Render memory, HTTP error rate,
  Cloudinary credit usage, and Neon database connection count. Scale up only
  after passing the rehearsal.
- [ ] Measure first-request latency after idle. Free Render sleeps after
  inactivity and can restart. **Not approved for a time-critical live
  event without a documented and tested fallback.** A paid always-on
  service may help, but requires separate explicit approval.
- [ ] Prepare an offline contingency: save original photos locally, reserve a
  personal hotspot, print the QR plus short URL, and arrange a way to
  deliver images later if cloud hosting goes down.
- [ ] Check Cloudinary Free storage/credit limits and the configured 10 MiB
  asset cap. Keep photographer input images <=25 MiB and <=36 megapixels,
  or resize oversized files before upload.
- [ ] Rotate the previously exposed Neon password if it has ever been in
  Git history. Confirm strong unique secrets, enable 2FA in GitHub,
  Neon, Cloudinary and Render, and limit collaborator permissions.
- [ ] Export/verify Neon backups and confirm the ability to restore.
  Photos must have an independent backup (original camera cards).
- [ ] Test QR reset and revocation; it invalidates the URL but **cannot
  retract photos already downloaded or screenshotted**.
- [ ] Check the current pilot limits: 2,000 photos per event, 10 events
  per organizer. Increase only after capacity and quota validation.
- [ ] After organizer and photographer accounts are set up, optionally set
  `ALLOW_PUBLIC_REGISTRATION=0` in Render to close new signups during
  the event. Guests don't need an account to scan the QR code.
- [ ] Understand access model: the guest QR is a **bearer link**. Anyone
  with the link may view all gallery photos. Do not share private photos
  until attendees consent and this exposure is acceptable.
- [ ] Keep **face search disabled by default**. Face embeddings and
  per-person search should be enabled only if the event has a lawful,
  documented consent process and participants understand the risks.
  For events involving children, seek appropriate guardian consent;
  otherwise keep it off. Review local biometric/privacy requirements.
- [ ] If face search is used, test performance, false matches and
  false negatives across several real participants before relying on it.
  A screenshot of a face-match result is **not identity verification**.
- [ ] Confirm event owner can disable original downloads, close uploads,
  remove photographers and delete images/data.
- [ ] Decide and disclose a retention period for guest photos and face
  embeddings; remove them promptly after the event.
- [ ] Conduct independent security review, dependency scanning, and
  controlled penetration testing before offering this service to
  paying clients or marketing it as secure for sensitive events.

## Security measures in this release

- Credential-backed organizer and approved photographer uploads, event
  isolation, hashed session tokens and passwords.
- Rate limits for account registration, password guessing, event creation,
  invites and uploads, plus event-level face-search limits.
- Security response headers, same-origin CSP, no-referrer protection for
  QR links, no-store caching of private responses, and disabled production
  API documentation.
- Image validation / EXIF removal / JPEG reconstruction and maximum
  decoded resolution checks; private Cloudinary authenticated variants.
- An async/nonblocking upload image processing path so uploading photos
  doesn't stall the live SSE event loop.
- Shared, short-lived in-process live-gallery counters reduce Neon load.

**Limitations:** This is not "unhackable". In-process rate limiting resets
on instance restart; a durable shared limiter and perimeter WAF/Turnstile
are needed before large-scale use. A single 512 MiB sleeping Render Free
worker is a pilot environment, not an SLA-backed production system.
Guests can forward QR links and download/screenshot photos. Uploaded
photos are held by Cloudinary; use event-specific, documented consent.
No payment flow was implemented.

## On-site drill (10–30 minutes before doors open)

1. Open the organizer dashboard; check Render health.
2. Create or select the intended event. Confirm date, title, and QR.
3. Have a photographer upload a fresh consented test photo while the
   organizer checks the gallery from a second phone.
4. Have one guest scan the QR, load the thumbnail/full image
   (depending on downloads setting), and refresh.
5. Confirm at least one photographer can continue using a mobile
   hotspot if venue Wi-Fi is lost.
6. Keep face search off unless a consented, tested workflow is ready.
7. Keep originals safe on cameras/computers; never delete cards because
   the cloud gallery appears to be working.

## On-site incident response

- **Backend unavailable:** Check Render deployments/logs. Use local
  camera storage, post updates via the organizer, and keep shooting.
  Never discard local originals. Note Free instances may cold-start.
- **Photos slow:** Stop automated face/Gemini analysis if it competes
  for resources; reduce upload batches, measure memory and errors.
- **Suspected QR leak:** Rotate the guest QR code; tell guests the old
  link no longer works. Understand prior downloads can't be revoked.
- **Unauthorized uploads:** Remove the photographer in event controls,
  revoke compromised sessions where possible, and rotate credentials.
- **Unexpected storage costs or quota:** Stop uploads, preserve originals,
  review Cloudinary usage and only resume with adequate verified quota.
- **Possible breach:** Disable access immediately, preserve relevant
  incident logs, rotate affected secrets, follow applicable breach
  notification rules, and engage a qualified security professional.
