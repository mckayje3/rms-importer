# Case Study — Dobbins Security Forces Facility

> **Status:** draft. Numbers are confirmed; quote from the project team is still needed before publishing. Replace bracketed placeholders before going live.

---

## At a glance

- **Project:** Dobbins Security Forces Facility, Dobbins ARB, Georgia
- **Owner:** USACE Savannah District (Atlanta Resident Office)
- **Prime contractor:** GlobalGo, LLC (Fort Lauderdale, FL)
- **Contract:** W912QR24C0035
- **Records migrated to Procore:** 2,280 submittals, 1,166 transmittal attachments, 8 custom fields
- **Migration timeline:** March 2026
- **Time recovered:** ~120 hours of double-entry, conservatively

---

## The problem

USACE construction contracts require everything to be logged in **RMS** — submittals, RFIs, daily QC logs, deficiency reports. The government doesn't accept Procore records as a substitute. But Procore is where the project team actually runs the job: design coordination, day-to-day comms, document control, schedule integration.

So the team was running both systems. Every submittal logged in RMS got re-typed in Procore by hand. Every QA code update meant updating two fields in two places. Every transmittal PDF got downloaded from RMS and re-uploaded to Procore.

The Dobbins project's submittal register had **2,280 records** by mid-contract. At ~3 minutes each for re-entry — typing the basics, mapping QA codes, attaching the PDF — that's well over **100 hours of pure data entry** before anyone could use Procore for what it's actually for.

## The approach

Two phases.

**Phase 1 (early 2026): PowerShell scripts as a stopgap.** GlobalGo's project team had a deadline. The first version of the importer was a set of PowerShell scripts that read RMS exports, called the Procore REST API, and pushed submittals through. Crude but it cleared the backlog: 1,933 base submittals + 35 recreations, 1,090 file uploads, 277 revisions linked to their parents.

**Phase 2 (March-April 2026): web app for ongoing sync.** Once the initial migration cleared, the requirement shifted. The team needed something the field staff could run weekly — not a developer console. The PowerShell scripts were retired in favor of a web app:

- Embedded inside Procore (Full Screen App) — no separate login, project context auto-detected
- Three-step wizard: Upload → Review → Apply
- Diff-based — every run shows what's changed against the stored baseline before any writes happen
- All four record types: submittals, RFIs, daily logs, observations
- File handling — transmittal PDFs deduplicate against the Procore Documents folder; revisions link to their parent submittals automatically
- Background processing — long syncs run server-side; the user can navigate away

## Outcomes

| Before | After |
|--------|-------|
| Manual re-entry of every submittal, QA code, date | Push from RMS export in one click |
| ~3 min per submittal | ~3 sec per submittal of user attention |
| Files uploaded one at a time via the Procore UI | 1,166 transmittal PDFs uploaded and attached automatically, with revision linking |
| QA code drift between RMS and Procore | Diff-based sync surfaces every drift before applying |
| Procore was the second source of truth | RMS remains source of truth; Procore stays current automatically |

**Estimated time recovered:** ~120 hours over the lifetime of the migration phase, plus ~4-6 hours per weekly sync going forward.

## What the team said

> *(placeholder — Brian Murray, PE, Resident Engineer; or whoever on the GlobalGo PM side is willing to be quoted. 1-2 sentences. Examples below.)*

> *"The web app turned a 100-hour data entry problem into a 90-second click."*
> *— [Name, Title, GlobalGo]*

> *"We submit RMS exports weekly now and the diff makes it obvious what's changed since the last sync. Nothing surprises us."*
> *— [Name, Title]*

## Technical notes

- All Procore writes go through one orchestrated background job (creates → file uploads → updates → baseline save) so files for newly-created submittals attach correctly without race conditions.
- The Procore Documents folder for the Dobbins project ("03 Submittals") holds 1,166 files. The app paginates the entire folder when building its dedupe cache so re-running a sync never produces duplicates.
- OAuth tokens are refreshed at the start of every background job so long-running syncs don't 401 mid-flow.
- The whole stack: Next.js on Vercel, FastAPI on Railway with a SQLite volume, embedded into Procore via the Developer Console.

## What's next

The same code path now handles:

- **RFIs** — questions, official responses, file attachments
- **Daily Logs** — QC equipment, labor (with vendor matching), narratives
- **Observations** — QAQC deficiency items with location matching and auto-create

Inspections (QC tests as Procore Inspections) is the next module on deck.

---

*The RMS Importer was built to solve a dual-system problem on the Dobbins ARB project, where GlobalGo, LLC is the prime contractor. It is now operated and distributed as a SaaS by **The Test Experts, LLC** (Suwanee, GA) and available to other USACE construction contractors via the Procore Marketplace.*

[Install from Procore Marketplace] [Contact us]
