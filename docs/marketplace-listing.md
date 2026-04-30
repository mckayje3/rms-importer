# Procore Marketplace Listing — Copy

Copy for the actual Procore Marketplace listing. Procore typically asks for:

- **Tagline** (≤ 80 chars)
- **Short description** (≤ 200 chars, shown in search results)
- **Long description** (~250-500 words, shown on the listing page)
- **Feature bullets** (5-10)
- **Categories / use cases**
- **Screenshots** (separate from copy — see launch checklist)

---

## Tagline (80 chars max)

**Eliminate double-entry between USACE RMS and Procore.**

*(74 chars)*

---

## Short description (200 chars max)

Push submittals, RFIs, daily logs, and QAQC deficiencies from RMS into Procore in one click. Diff-based sync, automatic file attachments, no double-entry.

*(165 chars)*

---

## Long description (~300 words)

**Built for USACE construction contractors who maintain records in both RMS and Procore.**

If your project requires the government's RMS (Resident Management System) and your team runs Procore for day-to-day collaboration, you've been paying the double-entry tax: every submittal, every QA code, every transmittal PDF logged twice. On a typical 2,000-submittal job, that's 100+ hours of pure re-typing before anyone touches Procore for actual coordination.

The RMS Importer eliminates that. Export your standard RMS reports (Submittal Register, Transmittal Report, RFI Report, QC daily logs, QAQC Deficiencies — whichever ones apply), drop them into the app, review a diff against what's already in Procore, and apply.

### What it imports

- **Submittals** with section, item number, revision, paragraph, QA code, QC code, info classification, government received/returned dates, responsible contractor, and Procore status mapped from the QA code
- **Transmittal PDFs** — uploaded to Procore Documents and attached to the matching submittal automatically (revisions linked to their parents)
- **RFIs** with official responses and file attachments
- **Daily Logs** — QC equipment, labor, and narrative entries (with vendor matching for labor)
- **Observations** — QAQC deficiency items as Procore Observations with location matching and auto-create

### How it works

The app stores a per-project baseline of what it's already pushed to Procore. On every subsequent sync, it shows you exactly what's changed since — new records, field updates, files to upload, items removed from RMS — before you commit anything. Idempotent by design, so you can run it weekly without creating duplicates.

### Embedded

Install once, then open the importer as a **Full Screen App** inside Procore. The active project is detected automatically — no second login, no project picker.

### Battle-tested

Built and used at the USACE Dobbins Security Forces Facility project — 2,280 submittals and 1,166 attachments migrated in March 2026.

---

## Feature bullets

- One-click sync of submittals, RFIs, daily logs, and observations from RMS to Procore
- Automatic transmittal PDF upload and attachment, including revision linking
- Diff-based: only pushes what's changed since the last sync
- File deduplication against the Procore Documents folder
- Embedded Full Screen App — works from inside Procore with no extra login
- Per-project field mapping with a guided setup wizard
- Background processing with live progress; navigate away anytime
- Resilient to token expiry, network blips, and rate limits (auto-refresh, exponential backoff, 30s/60s/120s retry)
- Per-project baseline reset for full data control
- Detailed sync history and audit trail

---

## Categories

Primary: **Document Management** or **Workflow Automation**
Secondary: **Government / Federal Construction**

*(Verify available categories in Procore's listing flow — these are common picks for sync-style apps.)*

---

## Use cases

- USACE prime contractors and design-build teams
- Government QC managers maintaining dual records
- Project teams onboarding to Procore mid-project who need to backfill RMS history
- Contractors managing multiple Procore projects who want to standardize the RMS handoff

---

## Required permissions / OAuth scopes

The app requests the standard Procore OAuth scopes for read/write on:

- Submittals (create, update, attach files)
- RFIs (create, update, replies, attach files)
- Daily Logs (equipment, manpower, notes)
- Observations and Locations
- Documents (read folder contents, create files)
- Project metadata (companies, projects, custom fields, statuses, vendors, spec sections)

No company-admin permissions required. No financial data accessed.

---

## Pricing

**$1,500 per active Procore project per year.** Annual subscription, billed by invoice (manual ACH/check for v1; Stripe Checkout to be added once self-serve volume justifies it). Includes unlimited submittal/RFI/daily log/observation imports, unlimited file attachments, all future updates, and email support.

Volume discount for 5+ active projects — contact sales.

Free during beta for early adopters who provide a short feedback call.

Billing model field on the marketplace listing form: **Subscription** (or "Contact for quote" if Procore's form requires it).

---

## Support

- **Email:** `rms-support@thetestexperts.com`
- **Documentation:** linked from the landing page
- **Status page:** `status.<domain>` *(once UptimeRobot is set up)*
- **Response SLA:** within 1 business day for support email *(adjust to a number you can actually hit)*

---

## Open items before submitting this listing

- Pricing decision
- Support email and SLA promise
- Final domain
- Categories — verify Procore's exact options
- Scopes list — confirm against the app's actual OAuth scope string in `routers/auth.py` once that's reviewed
