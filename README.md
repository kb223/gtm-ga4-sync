# gtm-ga4-sync

Declare your dataLayer events in YAML. One command provisions the matching GTM triggers, variables, and GA4 Event tags — and registers every custom parameter as a custom dimension or metric in GA4.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Install this into your AI coding agent (Claude Code)

Paste this message into a Claude Code session and hit send. It'll clone the repo, install the skill + CLI, and walk you through the one-time OAuth setup.

```
I'm giving you a skill called gtm-ga4-tagging. Get the files with:

git clone https://github.com/kb223/gtm-ga4-sync

Then:
1. Symlink the skill into my Claude Code skills folder:
   ln -s "$PWD/gtm-ga4-sync/skills/gtm-ga4-tagging" ~/.claude/skills/gtm-ga4-tagging
2. Install the CLI:
   cd gtm-ga4-sync && python3 -m venv .venv && .venv/bin/pip install .
3. Walk me through the one-time Google Cloud OAuth client setup from the README.
4. Then help me tag the engagement events on my site.
```

The skill teaches Claude Code to grep your codebase for engagement surfaces, propose an event map, write dataLayer pushes, and run `gtm-ga4-sync apply` to provision everything on the Google side.

Works with Gemini CLI and other Markdown-skill-aware agents — just copy the skill body into whatever your client uses for system-prompt context.

---

## Or use the CLI directly (no AI agent needed)

```bash
git clone https://github.com/kb223/gtm-ga4-sync
cd gtm-ga4-sync
python3 -m venv .venv && .venv/bin/pip install .
```

Write an `events.yml`:

```yaml
events:
  virtual_page_view:
    params: [page_path, page_title]
  cta_click:
    params: [cta_name, cta_destination, cta_location]
  outbound_link_click:
    params: [outbound_url, outbound_domain, link_text]
  form_submit:
    params: [form_id, form_name, form_destination]

metrics:
  - results_count
```

Apply it:

```bash
gtm-ga4-sync apply --config events.yml \
  --gtm-account <id> --gtm-container <id> \
  --ga4-property <id>
```

That creates, in your container's Default Workspace:

- **Data Layer Variables** — one `DLV - <param>` per unique event parameter
- **Custom Event Triggers** — one `CE - <event>` firing on each matching `dataLayer.push`
- **GA4 Event Tags** — one `GA4 - <event>` bound to its trigger, sending every param, referencing your existing `{{CON - Measurement ID}}` constant

And in your GA4 property:

- **Custom Dimensions** — one per string-valued parameter, event-scoped
- **Custom Metrics** — for numeric parameters you mark under `metrics:`

Tags land as drafts in the Default Workspace. You hit Submit in GTM when you're ready. Idempotent: re-running skips what already exists.

## One-time Google Cloud OAuth setup

The tool authenticates using your own OAuth client in your own GCP project. Google treats it as first-party, so sensitive scopes don't hit the "unverified app" block.

> Google renamed "OAuth consent screen" to **Google Auth Platform → Branding** in 2025/2026. The URLs below use the new paths.

1. Create a Google Cloud project, enable the required APIs:
   ```bash
   gcloud projects create my-analytics-ops --name="Analytics Ops"
   gcloud config set project my-analytics-ops
   gcloud services enable tagmanager.googleapis.com analyticsadmin.googleapis.com
   ```

2. Configure the Auth Platform branding at
   https://console.developers.google.com/auth/branding?project=my-analytics-ops
   - App name: anything
   - User support email: yours
   - User type: **Internal** if on Google Workspace (skips scope verification), **External** otherwise
   - Developer contact: yours
   - Accept policy → Create. You can skip the scopes screen.

3. Create an OAuth Client ID at
   https://console.developers.google.com/auth/clients?project=my-analytics-ops
   - **Create Client** → Application type: **Desktop app** → Create
   - Download the JSON to `~/.config/gtm-ga4-sync/client-secret.json`

4. First run authenticates in the browser and caches a refresh token:
   ```bash
   gtm-ga4-sync auth --client-secret ~/.config/gtm-ga4-sync/client-secret.json
   ```

Subsequent runs reuse the cached token automatically. You won't need `--client-secret` again.

## Commands

```
gtm-ga4-sync auth        Run one-time OAuth consent, cache refresh token
gtm-ga4-sync discover    List every GTM account/container + GA4 property you can access
gtm-ga4-sync apply       Provision GTM resources + GA4 dimensions from events.yml
  --config FILE          events.yml path
  --gtm-account ID
  --gtm-container ID
  --ga4-property ID
  --measurement-id G-X   Optional — default references {{CON - Measurement ID}}
  --dry-run              Preview without writing
  --skip-gtm             Only register GA4 dimensions/metrics
  --skip-ga4             Only provision GTM resources
```

## How duplicate detection works

Two layers, so you can safely point this at containers that were set up manually before:

1. **By name** — if `DLV - cta_name` already exists, skip.
2. **By function** — if an existing variable already reads the `cta_name` dataLayer key under a different name (`1PC - CTA Name`, say), reuse it instead of creating a second one. Works the same for Custom Event triggers (matched by the `{{_event}}` value they filter on) and GA4 Event tags (matched by their `eventName`).

Dry-run (`--dry-run`) previews the whole plan with labels: `[skip]` for name matches, `[reuse]` for function matches, `[+]` for new creates.

## Events config reference

See [`events.example.yml`](./events.example.yml) for a full starter template covering page views, CTA clicks, outbound links, forms, downloads, search, video, and newsletter signups.

Minimum structure:

```yaml
events:
  <event_name>:
    params: [<param1>, <param2>, ...]

metrics:               # optional — params to register as GA4 custom metrics
  - <numeric_param>

display_names:         # optional — defaults to Title Case of param name
  <param>: "Friendly Name"
```

## GTM naming conventions

Follows community norms so the container reads consistently for the next engineer:

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

## Limitations

- Publishes nothing — you review the diff in GTM and hit Submit. Intentional.
- Doesn't delete resources when you remove events from config. Clean up in the UI.
- GA4 property + data stream must exist first — doesn't create those.
- Targets the Default Workspace only. Multi-workspace support would be a flag away if anyone needs it.

## Contributing

Issues and PRs welcome. Built by [Kenneth J. Buchanan](https://kennethjbuchanan.com).

## License

MIT — see [LICENSE](./LICENSE).
