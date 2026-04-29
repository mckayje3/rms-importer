# Landing Page — Copy Draft

Markdown copy for the RMS Importer marketing page. Hand to a designer (Webflow, Framer, plain HTML — pick anything) and wire up the CTAs.

> **Voice notes:** confident but not slick; engineer-to-engineer; concrete numbers over adjectives. Audience = government construction project managers and QC leads. They've been retyping submittals for years and they're skeptical of fluff.

---

## Above-the-fold (hero)

### **Stop retyping every submittal.**

Push your RMS exports straight into Procore. Submittals, RFIs, daily logs, and QA deficiencies — kept in sync, with attachments, in a single click.

[Install from Procore Marketplace] [Watch 90-second demo]

> *(small, under the buttons)* Built for USACE construction contractors. Free during beta.

**Hero visual:** screenshot of the Sync Review screen with 3 new submittals + 8 QA updates + a File Plan card showing "12 to upload, 4 to new submittals."

---

## The problem (one short paragraph)

You log everything in RMS because the government requires it. You also log everything in Procore because that's where the project actually runs. So your team types the same submittal twice — once in RMS, once in Procore — including the QA codes, the dates, the responsible contractor, and the transmittal PDFs.

A 2,000-submittal job means **roughly 100+ hours of pure data re-entry** before anyone has touched Procore for collaboration.

---

## How it works (3 steps)

### 1. Export from RMS
Two CSVs (Submittal Register, Transmittal Report) and your folder of transmittal PDFs. Standard exports — no special configuration.

### 2. Review the diff
The app compares your export against what's already in Procore and shows you exactly what will change: new submittals, QA code updates, date corrections, files to attach. Nothing has been touched yet.

### 3. Apply
One button. The app creates new submittals, attaches your PDFs, updates fields, and saves a baseline so the next sync only shows what changed since.

**Visual:** 3-column layout, one screenshot per step.

---

## What it imports

- **Submittals** — section, item, revision, type, paragraph, QA/QC codes, dates, responsible contractor, status (mapped from QA code)
- **Transmittal PDFs** — uploaded to Procore Documents and attached to the right submittal automatically
- **RFIs** — questions, official responses, file attachments
- **Daily Logs** — QC equipment, labor, narrative entries
- **Observations** — QAQC deficiency items mapped to Procore Observations with location matching

---

## Why it's different

**Built for the way RMS actually works.** Naming conventions, transmittal numbering with revisions (`01 50 00-1.2`), QC vs QA distinction, government-vs-contractor date fields — everything is mapped without configuration.

**Idempotent by design.** Run it weekly. The app stores a per-project baseline of what's already in Procore and only pushes what's changed since. No duplicates.

**Embeddable.** Install once and access from inside Procore as a Full Screen App — no separate login, project context auto-detected.

**Transparent.** Every sync shows you exactly what will change before you commit. Cancel at any point. Reset the stored baseline anytime.

---

## Built on Dobbins

> *(case-study card with photo / project name)*

**Dobbins Air Reserve Base — Security Forces Facility**
2,280 submittals · 1,166 transmittal PDFs · 8 custom fields migrated · USACE Savannah District

[Read the full case study]

---

## Pricing

> **TBD — pick one before publishing:**
> - Free during beta (simplest)
> - $X/month per active project
> - $Y per project (one-time setup fee)
> - Custom — Contact us

---

## FAQ (collapse-style)

**Does it work with non-USACE projects?**
The app is currently optimized for RMS exports (the USACE format). If you're using a different submittal system, contact us — we'd like to know.

**What happens if RMS and Procore disagree on a record?**
RMS is treated as the source of truth. The app shows you the diff before applying anything; you can deselect any row you don't want overwritten.

**Will it delete submittals I've removed from RMS?**
No. The app *flags* removed items for review but never auto-deletes from Procore.

**What about my data?**
We keep a baseline of the records we've synced so we can detect changes on the next run. The fields stored are the ones we compare against — nothing more. Full policy: [link to /privacy].

**Can I uninstall and remove all my data?**
Yes. There's a "Reset Stored Data" button inside the app (per-project), or email support and we'll purge everything.

---

## Footer

- About GlobalGo
- Privacy Policy → `/privacy`
- Terms of Service → `/terms`
- Status → `status.<domain>`
- Support → `support@<domain>`
- © GlobalGo, LLC

---

## Notes for the designer

- Hero CTA — primary button goes to the Procore Marketplace listing once it's live; demo button opens a Loom in a modal.
- Screenshots should use a real (or convincing) Procore project — not Lorem ipsum.
- "Built on Dobbins" card — use a stock construction photo or, ideally, a permitted photo from the actual site.
- Status page link is fine to leave dead until UptimeRobot is set up.
- Brand colors: pick something neutral; the app uses orange (`#F97316` Tailwind orange-500) for primary actions and purple (`#9333EA`) for file-related affordances. The site doesn't need to match exactly but matching helps recognition.
