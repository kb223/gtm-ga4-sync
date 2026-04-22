# gtm-ga4-sync

> **Declare your dataLayer events in YAML. One command provisions the matching GTM triggers, variables, tags — and registers the custom dimensions in GA4.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## What you get

Define your site's engagement events once:

```yaml
# events.yml
events:
  virtual_page_view:
    params: [page_path, page_title]
  cta_click:
    params: [cta_name, cta_destination, cta_location]
  outbound_link_click:
    params: [outbound_url, outbound_domain, link_text]
  form_submit:
    params: [form_id, form_name, form_destination]
  # ... add more — see events.example.yml for the full starter
```

Then one command creates everything on the Google side:

```bash
gtm-ga4-sync apply --config events.yml \
  --gtm-account 1234567890 --gtm-container 987654321 \
  --ga4-property 111222333
```

Which produces, in the Default Workspace of your GTM container:

- **Data Layer Variables** — one `DLV - <param>` per unique event parameter
- **Custom Event Triggers** — one `CE - <event>` firing on matching `dataLayer.push`
- **GA4 Event Tags** — one `GA4 - <event>` bound to its trigger, wired to send every param, using your existing `{{CON - Measurement ID}}` (or a measurement ID you pass)

And in your GA4 property:

- **Custom Dimensions** (event-scoped) — one per string-valued parameter, registered so they show up in Explorations and standard reports
- **Custom Metrics** (event-scoped) — for numeric parameters you mark as metrics

Nothing gets published — tags land in the Default Workspace as drafts for review. Idempotent: rerun safely, only missing resources are created.

## Why it exists

Event tagging for a new site used to mean an afternoon of clicking through the GTM UI:
- Create 16 Data Layer Variables, one field at a time
- Create 10 Custom Event triggers, each with a regex filter
- Create 10 GA4 Event tags, each binding every parameter by hand
- Switch to GA4 Admin, register every parameter as a custom dimension

Any meaningful engagement-tracking setup is that much tedium, and all of it is mechanical. The GTM and GA4 Admin APIs have been available for years — the friction isn't the APIs, it's the OAuth setup for scopes that Google classifies as "sensitive."

This tool is the end-to-end version of that workflow:

1. A **declarative config** for your events
2. **OAuth once** with the right scopes
3. **One apply command** that provisions both GTM and GA4
4. **Idempotent** so adding an event later is a one-line config change + rerun

On a mid-complexity SPA (React, Vue, Next.js), setting this up used to take two to three hours of manual clicking. With `gtm-ga4-sync` it's the time it takes to read through the config — under five minutes including the first OAuth consent.

---

## Install

Not on PyPI yet — install from source:

```bash
git clone https://github.com/kb223/gtm-ga4-sync
cd gtm-ga4-sync
python3 -m venv .venv
.venv/bin/pip install .
```

The CLI will be at `.venv/bin/gtm-ga4-sync`. Activate the venv (`source .venv/bin/activate`) or call the binary directly.

## One-time setup (ten minutes)

You need an OAuth client for a Google Cloud project you control. Using your own client means Google treats it as first-party — no "unverified app" consent blockers, no Workspace admin approval loops.

> **Google renamed the consent flow in 2025/2026.** What used to be "OAuth consent screen" is now **Google Auth Platform > Branding**. The URLs below use the new paths.

1. **Create a Google Cloud project** (or use an existing one):
   ```bash
   gcloud projects create my-analytics-ops --name="Analytics Ops"
   gcloud config set project my-analytics-ops
   gcloud services enable tagmanager.googleapis.com analyticsadmin.googleapis.com
   ```

2. **Configure the Google Auth Platform Branding** at
   https://console.developers.google.com/auth/branding?project=my-analytics-ops
   - App name: anything (e.g. "Analytics Ops")
   - User support email: your email
   - Audience → User type: **Internal** if you're on Google Workspace (recommended — skips scope verification), or **External** for a personal Gmail account
   - Contact info → Developer contact email: your email
   - Accept the policy, click **Create**
   - You can skip configuring scopes on this screen — the tool requests them at runtime when you auth

3. **Create an OAuth Client ID** at
   https://console.developers.google.com/auth/clients?project=my-analytics-ops
   - Click **Create Client**
   - Application type: **Desktop app**
   - Name: anything (e.g. "Analytics Ops CLI")
   - Click **Create**
   - Click **Download JSON** on the resulting client — save it somewhere you can reference later, e.g.
     `~/.config/gtm-ga4-sync/client-secret.json`

4. **First run authenticates in the browser**, then caches a refresh token:
   ```bash
   gtm-ga4-sync auth --client-secret ~/.config/gtm-ga4-sync/client-secret.json
   ```

   When your browser opens, sign in to the same Google account that owns your GTM container and GA4 property, approve the scopes, done. Subsequent runs pick up the cached token at `~/.config/gtm-ga4-sync/token.json` automatically — you won't need `--client-secret` again unless you rotate the client or run with `--force-reauth`.

## Usage

### 1. Write an events config

See `events.example.yml` for a complete template. Minimum structure:

```yaml
events:
  virtual_page_view:
    params: [page_path, page_title]
  cta_click:
    params: [cta_name, cta_destination, cta_location]
  search:
    params: [search_term, results_count]

# Parameters to register as GA4 custom METRICS (numeric) rather than dimensions
metrics:
  - results_count

# Optional: friendly display names for GA4 (auto-generated from param name otherwise)
display_names:
  cta_name: "CTA Name"
  cta_destination: "CTA Destination"
```

### 2. Discover your GTM account / container / GA4 property IDs

```bash
gtm-ga4-sync discover
```

Lists every GTM account and container your authenticated user can see, plus GA4 properties. Copy the IDs you want.

### 3. Apply the config

```bash
gtm-ga4-sync apply \
  --config events.yml \
  --gtm-account 1234567890 \
  --gtm-container 987654321 \
  --ga4-property 111222333
```

Output (abbreviated):

```
========== GTM ==========
  workspace: accounts/1234567890/containers/987654321/workspaces/2
  measurement id: {{CON - Measurement ID}}

[GTM 1/3] Data Layer Variables
  [+]   DLV - cta_name
  [+]   DLV - cta_destination
  ...
[GTM 2/3] Custom Event Triggers
  [+]   CE - cta_click
  ...
[GTM 3/3] GA4 Event Tags
  [+]   GA4 - cta_click
  ...

========== GA4 ==========
[GA4 1/2] Custom dimensions on properties/111222333
  [+]   dimension 'cta_name'
  ...
[GA4 2/2] Custom metrics
  [+]   metric 'results_count'

Done. Review GTM in the UI before publishing:
  https://tagmanager.google.com/#/container/accounts/1234567890/containers/987654321
```

Rerun any time — already-existing resources (matched by name) are skipped.

### 4. Push to your dataLayer

From your app:

```javascript
window.dataLayer = window.dataLayer || []
window.dataLayer.push({
  event: 'cta_click',
  cta_name: 'view_my_work',
  cta_destination: '/projects',
  cta_location: 'home_hero',
})
```

Validation: open GTM Preview mode, click around, and watch every event hit the debugger with its parameters. Once you're satisfied, publish the workspace in GTM.

## How it works

- **OAuth2 with `InstalledAppFlow`** — your own OAuth client in your own GCP project. First run opens a browser consent, cached refresh token at `~/.config/gtm-ga4-sync/token.json` afterward. No service account keys to rotate or leak.
- **Required scopes**: `tagmanager.edit.containers` + `analytics.edit`. You only pay the consent cost once.
- **Naming conventions** (follow GTM community norms):
  - Data Layer Variables: `DLV - <param>`
  - Custom Event Triggers: `CE - <event>`
  - GA4 Event Tags: `GA4 - <event>`
- **Rate limiting**: ~2s between writes — GTM's Tag Manager API caps at ~30 writes per minute. A 20-event config takes about 2 minutes.
- **Measurement ID resolution**: by default, references the first existing `{{CON - Measurement ID}}` constant variable in the container. Override with `--measurement-id G-XXXXXXX` if you want a raw ID.

## Limitations / not in scope (yet)

- Publishes nothing — you hit "Submit" in the GTM UI yourself. Intentional: lets you review diff before committing.
- Doesn't delete resources when you remove events from config. Intentional: avoids accidental destructive runs. If you want to clean up, delete in GTM UI.
- GA4 Data Stream / measurement ID creation is out of scope — create your property and data stream first.
- Single-container at a time. Running against multiple containers is just a shell loop.

## Author

Built by [Kenneth J. Buchanan](https://kennethjbuchanan.com) — Senior Agentic Analytics Engineer. If you hit edges, I'd love to hear about it: open an issue, or reach out via [roseskyconsulting.com](https://roseskyconsulting.com/scoping-call/).

## License

MIT. Use it freely, sell services on top of it, attribute whenever's easy.
