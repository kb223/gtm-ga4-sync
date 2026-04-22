# gtm-ga4-sync

Declare your dataLayer events in YAML. One command provisions the matching GTM triggers, variables, and GA4 Event tags — and registers every custom parameter as a custom dimension or metric in GA4.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Install

Two paths. Pick whichever matches how you work.

### Path A — Hand it to Claude Code (or another AI coding agent)

1. **Open** a Claude Code session in any directory you're comfortable cloning into.

2. **Paste this prompt into the session and send it:**

> I'm giving you a skill called gtm-ga4-tagging. Please do the following in order:
>
> 1. Clone the repo: `git clone https://github.com/kb223/gtm-ga4-sync`
> 2. Symlink the skill into my Claude Code skills folder: `ln -s "$PWD/gtm-ga4-sync/skills/gtm-ga4-tagging" ~/.claude/skills/gtm-ga4-tagging`
> 3. Install the CLI: `cd gtm-ga4-sync && python3 -m venv .venv && .venv/bin/pip install .`
> 4. Walk me through the one-time Google Cloud OAuth client setup from the README in the repo.
> 5. Once OAuth is done, help me tag the engagement events on my site end-to-end.

Claude Code will clone, install, prompt you through the Google Cloud steps, and (after auth) help you design an event map and apply it to your GTM + GA4. You stay in chat the whole time — Claude runs the terminal commands itself.

### Path B — Run it yourself in the terminal

**Terminal commands** (no AI agent involved):

```bash
git clone https://github.com/kb223/gtm-ga4-sync
cd gtm-ga4-sync
python3 -m venv .venv
.venv/bin/pip install .
```

The CLI is now at `.venv/bin/gtm-ga4-sync`. Activate the venv (`source .venv/bin/activate`) or invoke the binary directly.

---

## How you use it after install

### 1. Write an `events.yml` describing your events

```yaml
events:
  virtual_page_view:
    params: [page_path, page_title]
  cta_click:
    params: [cta_name, cta_destination, cta_location]
  form_submit:
    params: [form_id, form_name, form_destination]

metrics:
  - results_count
```

See [`events.example.yml`](./events.example.yml) for a full starter covering page views, CTAs, outbound links, forms, downloads, search, video, and newsletter signups.

### 2. Find your GTM + GA4 IDs

**Terminal command:**

```bash
gtm-ga4-sync discover
```

Prints every GTM account/container and GA4 property your authenticated user can see. Copy the IDs you'll use.

### 3. Preview with a dry run

**Terminal command:**

```bash
gtm-ga4-sync apply \
  --config events.yml \
  --gtm-account <id> --gtm-container <id> \
  --ga4-property <id> \
  --dry-run
```

The CLI prompts you to pick a **workspace** — never defaults to the Default Workspace. GTM best practice: do every change in a dedicated workspace so you can diff and QA before publishing. Create one in the GTM UI first if you don't have one, or pick an existing one.

It also auto-detects your **measurement ID** from the existing Google Tag config in the selected workspace. If multiple tags exist, it prompts you to pick. If none exists, it asks you to enter a `G-XXXXXXXXXX` manually. Pass `--measurement-id G-XXXXXXX` to skip the prompt entirely.

Dry-run shows every would-be-created, skipped, or reused resource with a summary at the end. No writes hit Google.

### 4. Apply

**Terminal command** (same as above, without `--dry-run`):

```bash
gtm-ga4-sync apply \
  --config events.yml \
  --gtm-account <id> --gtm-container <id> \
  --ga4-property <id>
```

### 5. Push to your dataLayer from your app

```javascript
window.dataLayer = window.dataLayer || []
window.dataLayer.push({
  event: 'cta_click',
  cta_name: 'view_my_work',
  cta_destination: '/projects',
  cta_location: 'home_hero',
})
```

### 6. Review + publish

Open the GTM UI → your workspace → review the new tags/triggers/variables → **Submit** → give the version a name → **Publish**. The tool never publishes for you; review is always a human step.

---

## One-time Google Cloud OAuth setup

Needed before the first `gtm-ga4-sync apply` or `discover`. The tool uses your own OAuth client in your own GCP project — Google treats it as first-party, so sensitive scopes (`tagmanager.edit.containers`, `analytics.edit`) don't hit the "unverified app" block you'd hit with a generic OAuth client.

> Google renamed "OAuth consent screen" to **Google Auth Platform → Branding** in 2025/2026. The URLs below use the new paths.

**Terminal command — create the project and enable the APIs:**

```bash
gcloud projects create my-analytics-ops --name="Analytics Ops"
gcloud config set project my-analytics-ops
gcloud services enable tagmanager.googleapis.com analyticsadmin.googleapis.com
```

**In your browser — configure the consent screen:**

Go to https://console.developers.google.com/auth/branding?project=my-analytics-ops

- App name: anything
- User support email: yours
- Audience → User type: **Internal** if on Google Workspace (recommended — skips scope verification), **External** otherwise
- Developer contact: yours
- Accept the policy → **Create**. You can skip the scopes screen — the tool requests them at runtime.

**In your browser — create the OAuth client:**

Go to https://console.developers.google.com/auth/clients?project=my-analytics-ops

- **Create Client**
- Application type: **Desktop app**
- Name: anything
- **Create** → **Download JSON** → save to `~/.config/gtm-ga4-sync/client-secret.json`

**Terminal command — first auth:**

```bash
gtm-ga4-sync auth --client-secret ~/.config/gtm-ga4-sync/client-secret.json
```

Opens your browser, you approve the scopes, token gets cached at `~/.config/gtm-ga4-sync/token.json`. Subsequent runs reuse it — you don't need `--client-secret` again unless you run with `--force-reauth` or rotate the client.

---

## Commands reference

```
gtm-ga4-sync auth         Run one-time OAuth consent, cache refresh token
gtm-ga4-sync discover     List every GTM account/container + GA4 property you can access
gtm-ga4-sync apply        Provision GTM resources + GA4 dimensions from events.yml
  --config FILE           events.yml path  (required)
  --gtm-account ID        (required)
  --gtm-container ID      (required)
  --workspace NAME/ID     Target workspace. Omit to pick interactively.
  --ga4-property ID       (required)
  --measurement-id G-X    Override auto-detection of the GA4 measurement ID
  --dry-run               Preview without writing
  --skip-gtm              Only register GA4 dimensions/metrics
  --skip-ga4              Only provision GTM resources
  --force-reauth          Force browser consent even if a token is cached
```

---

## Duplicate detection (two layers)

Safe to point at containers that were set up manually before:

1. **By name** — if `DLV - cta_name` already exists, skip.
2. **By function** — if an existing variable already reads the `cta_name` dataLayer key under a different name (e.g. `1PC - CTA Name`), reuse it instead of creating a second one. Works the same for Custom Event triggers (matched by the event name they filter on) and GA4 Event tags (matched by their `eventName`).

Dry-run labels each item: `[skip]` for name matches, `[reuse]` for function matches, `[+]` for new creates.

---

## events.yml structure

```yaml
events:
  <event_name>:
    params: [<param1>, <param2>, ...]

metrics:               # optional — params to register as GA4 custom metrics (numeric)
  - <numeric_param>

display_names:         # optional — defaults to Title Case of param name
  <param>: "Friendly Name"
```

Param names follow GA4 rules: alphanumeric + underscore only, avoid reserved names like `source`, `medium`, `campaign`, `currency`, `value`, `items`. Display names: alphanumeric, underscore, or space only (no hyphens or parentheses).

---

## GTM naming conventions

Follows community norms so the container reads consistently:

| Prefix | Resource |
|---|---|
| `DLV - ` | Data Layer Variable |
| `CJS - ` | Custom JavaScript |
| `CON - ` | Constant |
| `LT - ` | Lookup Table |
| `RXT - ` | RegEx Table |
| `CE - ` | Custom Event Trigger |
| `PV - ` | Page View Trigger |
| `Click - ` | Click Trigger |
| `GA4 - ` | GA4 Event Tag |
| `HTML - ` | Custom HTML Tag |

---

## Limitations

- Publishes nothing — you review the diff in GTM and hit Submit. Intentional.
- Doesn't delete resources when you remove events from config. Clean up in the UI.
- GA4 property + data stream must exist first — doesn't create those.
- One container per run. Multi-container is a shell loop away if you need it.

## Author

Built by [Kenneth J. Buchanan](https://kennethjbuchanan.com).

## License

MIT — see [LICENSE](./LICENSE).
