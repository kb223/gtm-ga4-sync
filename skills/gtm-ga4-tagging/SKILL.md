---
name: gtm-ga4-tagging
description: Wire dataLayer events on a site and provision the matching GTM triggers/variables/tags + GA4 custom dimensions in one pass. Use when setting up event tracking on a new site, adding new engagement events, or migrating from manual GTM clicks to declarative config. Works for React/Vue/Next.js/any JS site.
argument-hint: "[site or project name]"
---

# GTM + GA4 Event Tagging Workflow

End-to-end methodology for setting up engagement event tracking on a site and provisioning the corresponding GTM resources + GA4 custom dimensions via API — no clicking through the GTM UI, no manual GA4 Admin trips.

Pairs with the `gtm-ga4-sync` CLI at https://github.com/kb223/gtm-ga4-sync (or local checkout at `~/Library/Mobile Documents/.../RSC - Web Apps/github-repos/gtm-ga4-sync`).

## When to use this skill

- Adding analytics to a new site that doesn't have event tracking yet
- Adding new events to a site that already has some (`trackCtaClick` etc.)
- Migrating a team from manual GTM clicks to declarative event config
- Replacing scroll/CTA/outbound tracking heuristics with explicit dataLayer pushes

## Methodology

### Step 1 — Discover engagement surfaces

Before proposing any event map, grep the codebase for the click/link/submit surfaces that matter:

```bash
grep -rnE "onClick|href=|onSubmit|mailto:" src/ --include="*.tsx" --include="*.jsx" --include="*.vue" --include="*.svelte"
```

Also check:
- Hero CTAs (Home / landing pages)
- Navigation clicks (if a marketing nav — skip for in-app)
- Product/portfolio/blog card clicks
- External outbound links (demo, GitHub, partner sites)
- Form submits (contact, lead, newsletter)
- Chat / support widget open + send
- File downloads (PDFs, assets)
- Video play / progress
- Search queries + results count
- Booking / scoping-call clicks

### Step 2 — Propose the event map

Before writing code, present a table to the user:

| Event | Params | Why |
|---|---|---|
| `virtual_page_view` | `page_path`, `page_title` | SPA route changes — GA4's default `page_view` only fires on hard loads |
| `cta_click` | `cta_name`, `cta_destination`, `cta_location` | Every Button click — hero, CTA bands, etc. |
| ... | ... | ... |

Keep naming:
- **Events**: snake_case, noun_verb, generic enough to reuse across the site (`cta_click` not `home_hero_view_work_click`)
- **Params**: snake_case, one value per key, flat (no nested objects)
- **Values**: stable slugs for bucketing (`home_hero`, not "Home page hero banner")

**Common mistakes to avoid:**
- Too granular — don't make `cta_click` and `hero_cta_click` and `footer_cta_click`. One `cta_click` with `cta_location` param is better.
- Too sparse — a single `click` event with a free-text `label` param is useless for reporting.
- Reusing GA4 reserved names — `source`, `medium`, `campaign`, `currency`, `value`, `items` conflict with standard dimensions/ecommerce. Rename to `event_source`, `click_source`, etc. if GA4 rejects on registration.

Wait for user approval before writing code.

### Step 3 — Write the analytics helper

Centralize dataLayer pushes in one place. Example for TypeScript:

```ts
// src/utils/analytics.ts
declare global {
  interface Window {
    dataLayer: Record<string, unknown>[]
  }
}

export function pushEvent(event: string, params?: Record<string, unknown>) {
  if (typeof window === 'undefined') return
  window.dataLayer = window.dataLayer || []
  window.dataLayer.push({ event, ...params })
}

export function trackCtaClick(name: string, destination: string, location: string) {
  pushEvent('cta_click', { cta_name: name, cta_destination: destination, cta_location: location })
}

// ... one typed helper per event
```

Rules:
- One helper per event name — gives you type safety on params
- Always guard `typeof window === 'undefined'` for SSR (Next.js, SvelteKit)
- Never let analytics block navigation — fire before `navigate()`/`<a href>` traversal, don't `await` anything

### Step 4 — Wire the helpers across the codebase

Instrument each surface from Step 1. For React/Vue/Svelte, the pattern is `onClick={() => trackXxx(...)}`.

**SPA page views**: install a route-change listener once at the layout level:

```tsx
// React Router example
import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { trackPageView } from './utils/analytics'

function Layout() {
  const location = useLocation()
  useEffect(() => {
    trackPageView(location.pathname + location.search, document.title)
  }, [location.pathname, location.search])
  // ...
}
```

**Anchor-mode buttons**: make sure your `<Button>` component forwards `onClick` to the `<a>` element when `href` is used. Common footgun — many Button components only spread props to `<button>`.

### Step 5 — Provision GTM + GA4 via API

Write an `events.yml` in the project root or `scripts/gtm-sync/events.yml`:

```yaml
events:
  virtual_page_view:
    params: [page_path, page_title]
  cta_click:
    params: [cta_name, cta_destination, cta_location]
  contact_initiated:
    params: [method, location]

metrics:
  - message_length

display_names:
  cta_name: "CTA Name"
```

Preview with a dry-run first:

```bash
gtm-ga4-sync discover  # find your account/container/property IDs
gtm-ga4-sync apply \
  --config events.yml \
  --gtm-account <id> \
  --gtm-container <id> \
  --ga4-property <id> \
  --dry-run
```

Dry-run lists what would be created, what already exists by name, what would be reused because a semantically-equivalent resource already exists under a different name, and what would error. No writes.

Re-run without `--dry-run` to apply:

```bash
gtm-ga4-sync apply --config events.yml --gtm-account <id> --gtm-container <id> --ga4-property <id>
```

Which creates, idempotently:
- One `DLV - <param>` per unique parameter (unless an existing variable already reads that dataLayer key)
- One `CE - <event>` trigger per event (unless an existing Custom Event trigger already matches it)
- One `GA4 - <event>` tag per event, wired to its trigger + sending all params (unless an existing GA4 Event tag already sends that eventName)
- Custom dimensions + metrics in GA4

Tags land in the Default Workspace as drafts. User publishes manually in the GTM UI after review.

### Duplicate detection (two layers)

1. **Name match** — if a resource with the target name already exists (e.g. `DLV - cta_name`), skip it. Standard idempotency.
2. **Function match** — if an existing resource does the same thing under a different name (a `1PC - Client Id` variable that already reads the `client_id` dataLayer key, or a `Click - Search Submit` trigger that already matches event `search`), skip creating a duplicate. Output flags it as `[reuse]`.

The function-match layer catches containers that were set up manually before and uses community-norm names different from ours. Prevents the "run the tool once, now you have two of everything" footgun.

### Step 6 — Validate

Three layers to verify:

1. **Browser console** — open the site, click a CTA, check `window.dataLayer` contains the event with expected params:
   ```js
   dataLayer.filter(d => d.event === 'cta_click')
   ```

2. **GTM Preview mode** — in GTM UI click Preview, enter site URL, click around. Every dataLayer push should appear in the debugger with its trigger firing.

3. **GA4 DebugView** — Admin → DebugView. Events appear within ~10s of firing. Standard reports take 24-48h to populate.

## One-time OAuth setup

Required before the first `gtm-ga4-sync apply`. See the repo's README for current Google Cloud Console UI — it was renamed to **Google Auth Platform** in 2025/2026:

- Consent screen is now at `console.developers.google.com/auth/branding`
- OAuth clients are at `console.developers.google.com/auth/clients`
- Create an **Internal** app if on Workspace (skips verification for sensitive scopes)
- Create a **Desktop app** OAuth client, download JSON
- `gtm-ga4-sync auth --client-secret /path/to/client_secret.json` once

The required scopes (`tagmanager.edit.containers` + `analytics.edit`) are both "sensitive" in Google's taxonomy. An Internal app in your own Workspace bypasses the verification requirement. On a personal Gmail account (External app), Google Workspace policy can block grants — in that case, prefer trusting the Google Cloud SDK client in admin settings, OR pivot to the Internal-app path.

## GTM naming conventions (community norms)

Follow these so your container reads consistently for anyone who opens it later:

- `DLV - <name>` — Data Layer Variable
- `CJS - <name>` — Custom JavaScript Variable
- `CON - <name>` — Constant Variable
- `LT - <name>` — Lookup Table
- `RXT - <name>` — RegEx Table
- `CE - <name>` — Custom Event Trigger
- `PV - <name>` — Page View Trigger
- `Click - <name>` — Click / Link Click Trigger
- `GA4 - <name>` — GA4 Event Tag
- `HTML - <name>` — Custom HTML Tag

## Rate-limiting

- Tag Manager API: ~30 writes/minute per user. The CLI throttles at 2s between writes and retries 429s with exponential backoff. A 20-event config is ~2 minutes of wall time.
- GA4 Admin API: 10 writes/second but very tight daily quotas on dimension creation. Rare to hit unless registering 100+ dimensions.

## Common failure modes + fixes

| Symptom | Cause | Fix |
|---|---|---|
| `This app is blocked` on OAuth consent | Workspace app-access control blocking sensitive scope for a first-party OAuth client | Create your own Internal OAuth app in your own GCP project (don't rely on gcloud's client) |
| GA4 rejects display name | Contains `()` or `-` | Only alphanumeric, underscore, or space. Strip punctuation. |
| Tag fires but no params in GA4 | DLV name in GTM doesn't match dataLayer key | GTM Preview shows the DLV value — if empty, check the exact `dataLayer.push` key name |
| `429 rate limit` halfway through sync | Hit ~30 writes/min cap | Wait 60s, rerun — script is idempotent, picks up where it left off |
| Custom dimension not appearing in reports | Hasn't propagated yet OR no events with that param have fired | Verify in DebugView first. Standard reports take 24-48h. |

## What this skill does NOT do

- Doesn't set up GA4 conversion events — those are configured in the GA4 Admin UI after data is flowing
- Doesn't configure cross-domain linking or enhanced measurement
- Doesn't handle server-side GTM
- Doesn't publish the GTM workspace — user reviews the diff and publishes manually (this is by design)

## References

- Tool: https://github.com/kb223/gtm-ga4-sync
- GTM Tag Manager API: https://developers.google.com/tag-platform/tag-manager/api/v2
- GA4 Admin API: https://developers.google.com/analytics/devguides/config/admin/v1
- GA4 reserved event / parameter names: https://support.google.com/analytics/answer/13316687
