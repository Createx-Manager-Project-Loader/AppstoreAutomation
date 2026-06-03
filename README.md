# App Store Automation

Shared scripts for uploading App Store Connect metadata, screenshots, ASO, and What's New text.

Used as a **git submodule** or **GitHub Actions checkout** inside each app repository.

## App repository layout

Each app repo should contain:

```text
automation/                  # this repo (submodule or CI checkout)
automation-config.yaml       # per-app settings (copy from config.example.yaml)
.github/workflows/app-store-automation.yml
metadata/                    # locale metadata files
account.env                  # optional, local only — App Store Connect keys
```

## Configuration

Copy `config.example.yaml` to `automation-config.yaml` in the **app repo root** and edit:

- `run_mode` — `screenshots`, `aso`, `whats_new`, or `all`
- `google_sheet_url` — ASO Google Sheet URL
- `screenshots_zip_url` — Google Drive ZIP with screenshots
- `release_notes` — fallback What's New text

Environment overrides (set in GitHub Actions workflow):

| Variable | Default |
|---|---|
| `AUTOMATION_CONFIG_PATH` | `$REPO_ROOT/automation-config.yaml` |
| `AUTOMATION_PREPARED_DIR` | `$REPO_ROOT/automation-prepared` |

CI artifacts (prepared metadata, screenshots, reports) are written to `automation-prepared/` in the app repo, not inside this shared repo.

### Partial uploads (`RUN_MODE=all` / `aso`)

Upload steps (metadata, app name, subscriptions, screenshots, What's New) run independently. If one step or locale fails (for example app name already taken, or screenshots for an unavailable locale), later steps still run and successful locales are kept. The final report status is `PARTIAL` and the job exits with code `1` so CI shows a warning. Prepare/validation failures still stop the run immediately.

## Connect to an app repository

### Option A — Git submodule

```bash
cd your-app-repo
git submodule add https://github.com/Createx-Manager-Project-Loader/AppstoreAutomation.git automation
cp automation/config.example.yaml automation-config.yaml
git add automation automation-config.yaml .gitmodules
git commit -m "Add shared App Store automation"
```

Pin a release:

```bash
cd automation && git checkout v1.0.0 && cd ..
git add automation && git commit -m "Bump automation to v1.0.0"
```

### Option B — CI checkout only

In `.github/workflows/app-store-automation.yml`:

```yaml
- uses: actions/checkout@v4
  with:
    ref: main
    persist-credentials: true

- uses: actions/checkout@v4
  with:
    repository: Createx-Manager-Project-Loader/AppstoreAutomation
    ref: v1.0.0
    path: automation
```

Set env on all automation steps:

```yaml
env:
  AUTOMATION_CONFIG_PATH: ${{ github.workspace }}/automation-config.yaml
  AUTOMATION_PREPARED_DIR: ${{ github.workspace }}/automation-prepared
```

## GitHub Secrets (per app repo)

- `APPSTORE_CONNECT_API_KEY_ID`
- `APPSTORE_CONNECT_API_ISSUER_ID`
- `APPSTORE_CONNECT_API_PRIVATE_KEY`
- `BUNDLE_IDENTIFIER`
- `GOOGLE_SERVICE_ACCOUNT_JSON`

## Local run

```bash
cp config.example.yaml ../automation-config.yaml   # in app repo root
pip install -r requirements.txt
export AUTOMATION_CONFIG_PATH=/path/to/app-repo/automation-config.yaml
export AUTOMATION_PREPARED_DIR=/path/to/app-repo/automation-prepared
bash scripts/run_all.sh
```

## Releases

Tag versions in this repo (`v1.0.0`, `v1.1.0`, …) and update the ref in each app repository.
