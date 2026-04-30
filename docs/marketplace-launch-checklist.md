# Procore Marketplace Launch Checklist

Working document for shipping RMS Importer to the Procore Marketplace. Status updated as items move.

**Legend:** ☐ pending — ◐ in progress — ☑ done — ⊘ blocked

---

## Phase 1 — Required to submit application

### Branding & site

- ☐ **Pick a domain.** `globalgo.io/rms-importer` (subpath) or `rms-importer.com` (dedicated)? Affects landing-page URL throughout the listing.
- ☐ **Logo / app icon** — Procore requires a square (≥512×512) icon. Banner image (~1280×320) for the listing helps.
- ☐ **Landing page** — copy drafted in `docs/marketplace-landing-page.md`. Needs design + hosting.
- ☐ **Demo video** — 60-90s walkthrough of the wizard (Loom is fine for v1). Embed on landing page; link from listing.
- ☐ **Screenshots** — at least 4: tool selector, Upload step, Review step, Apply progress. PNG/WebP, ~1200px wide.

### Legal

- ☑ **Privacy policy** — generated via iubenda (doc 91796741), hosted at `rms-importer.vercel.app/privacy` (iframes the iubenda full-legal page). Override URL via `NEXT_PUBLIC_PRIVACY_URL` env var if you regenerate or migrate domains.
- ☑ **Cookie policy** — generated via iubenda (same doc), hosted at `rms-importer.vercel.app/cookies`. Override URL via `NEXT_PUBLIC_COOKIE_URL`.
- ☑ **iubenda Privacy Controls + Cookie Solution widget** — wired into `app/layout.tsx` with `beforeInteractive` strategy so the cookie banner and consent management load on every page. Override URL via `NEXT_PUBLIC_IUBENDA_WIDGET_URL`.
- ◐ **iubenda scan: Google Fonts service** — flagged Apr 30, 2026. Either declare Google Fonts in iubenda's dashboard *or* drop `next/font/google` Geist imports from `app/layout.tsx` for system fonts. Pending decision.
- ☐ **Terms of Service** — generate via iubenda the same way; route already pre-wired pattern (add `app/terms/page.tsx` mirroring `privacy/page.tsx`). Host at `<domain>/terms`.
- ☐ **Sub-processor list** — short page listing Vercel, Railway, Procore. (Required if you sign any DPA.)

### Support & contact

- ◐ **Support email** — chosen: `rms-support@thetestexperts.com` (decided 2026-04-30). **Pending:** create the inbox in The Test Experts cPanel; verify forwarding/ticketing if desired. Until it's live, links to it will bounce.
- ☑ **In-app help link** — `<HelpFooter />` mounts on every authenticated screen; reads `NEXT_PUBLIC_SUPPORT_EMAIL` and `NEXT_PUBLIC_HELP_URL` from Vercel env. After the cPanel inbox is live, set `NEXT_PUBLIC_SUPPORT_EMAIL=rms-support@thetestexperts.com` in Vercel — no code change needed. (Default fallback in code is intentionally `support@example.com` so users don't get bouncebacks before the inbox exists.)
- ☑ **Replace `[Your support contact here]`** in `RMS_Importer_User_Guide.md` — done.

### Procore-side paperwork

- ☐ **Procore Developer Network membership** — confirm enrollment in the formal partner program (separate from having an OAuth app registered).
- ☐ **Production app credentials** — verify `PROCORE_CLIENT_ID` / `PROCORE_CLIENT_SECRET` on Railway are the production set, not dev/sandbox.
- ☐ **App listing copy** — drafted in `docs/marketplace-listing.md`. Needs your review + screenshots inserted.
- ☐ **Security questionnaire** — Procore typically sends this with the application. Be ready to answer auth flow, data residency, encryption-in-transit, retention, deletion. Most answers are already in `docs/data-retention.md` and `docs/marketplace-overview.md`.
- ☐ **Pricing decision** — pick one before submitting:
  - Free during beta (simplest)
  - Per-project monthly subscription (~$X/mo per active project)
  - One-time per-project setup fee
  - Custom (contact for quote)

---

## Phase 2 — Improves submission, can ship in parallel with review

- ☐ **Case study** — drafted in `docs/marketplace-case-study-dobbins.md`. Needs Brian Murray quote (or similar) for credibility.
- ☐ **Status page** — UptimeRobot (free) pinging Railway `/health`. Public page at `status.<domain>`. Link from landing page.
- ☐ **Sentry in production** — frontend + backend SDKs. Free tier covers our volume. Replaces "scrape Railway logs after a customer complains" with proactive alerts.
- ☐ **Production analytics** — PostHog or Mixpanel free tier. Track which tools customers actually use (submittals, RFIs, daily logs, observations) to inform roadmap.
- ☐ **Onboarding email** — auto-sent after install. Welcome + link to user guide + support email. SendGrid free tier or similar.
- ☐ **FAQ page** — 8-10 common questions. Reuse troubleshooting sections from `RMS_Importer_User_Guide.md` and `sync-user-guide.md`.

---

## Phase 3 — Nice to have, post-launch

- ☐ **SOC 2 Type I** — only if enterprise customers ask. Vanta/Drata path; ~3-6 months and $10-30k. Skip until pulled.
- ☐ **Multi-tenancy hardening review** — already per-project, but a security read of `database.py` and the `_doc_cache` (which is in-memory, per ProcoreAPI instance) before scaling beyond a few customers.
- ☐ **Customer-installable trial flow** — currently the app assumes the user already has the integration available. For self-serve, may need a trial mode / sandbox project.
- ☐ **Help center** — hosted docs (Notion / GitBook) instead of markdown in repo. Public, search-engine-indexable.

---

## Drafted artifacts (live in this repo)

| File | Purpose | Status |
|------|---------|--------|
| `docs/marketplace-overview.md` | Reviewer-facing integration summary | Done |
| `docs/data-retention.md` | Engineering data policy | Done |
| `docs/marketplace-launch-checklist.md` | This file | Done |
| `docs/marketplace-landing-page.md` | Marketing site copy (markdown) | Drafted — needs design + hosting |
| `docs/marketplace-listing.md` | ~250-word description for Procore listing | Drafted — needs review |
| `docs/marketplace-case-study-dobbins.md` | Case study draft | Drafted — needs quote + final numbers |

---

## Open questions for the team

1. Domain name — `globalgo.io/rms-importer` vs dedicated domain?
2. Pricing model + price point.
3. Who owns customer support? Solo (mckayje3) or shared inbox?
4. Are we OK ungating the app to non-USACE projects, or scoping the listing to government construction only?
5. ~~Is GlobalGo, LLC the entity on the Procore Partner agreement, or a different entity?~~ **Resolved 2026-04-30: The Test Experts, LLC** (1000 Peachtree Ind Blvd, STE 6352, Suwanee, GA 30024) is the SaaS operator for the marketplace listing. GlobalGo, LLC remains the prime contractor on the Dobbins case study but is not the SaaS entity.
