# Postman API Ingestion Script

Automate API discovery by ingesting OpenAPI specs into Postman Spec Hub, generating collections with JWT auth, and syncing updates.

## Business Value

### Problem Statement
Senior engineers spend significant time manually integrating APIs. A recent analysis showed one engineer spent **47 minutes** discovering and setting up the refund API - time that could be spent on higher-value work.

### Solution
This automated ingestion script reduces API discovery time to **under 30 seconds**:
- Automatically uploads OpenAPI specs to Postman Spec Hub
- Generates ready-to-use collections with all endpoints
- Configures JWT authentication with token caching
- Sets up Dev, QA, UAT, and Prod environments
- Exports collections for CI/CD integration

### ROI Calculation

```
Baseline:
  47 min/API discovery x 14 engineers x 2 discoveries/week = 21.9 hrs/week wasted

After Automation:
  30 sec/discovery = 0.23 hrs/week

Weekly Savings:
  21.7 hrs/week

Annual Value:
  21.7 hrs/week x $150/hr x 52 weeks = $169,260/year

Additional Benefits:
  - Test coverage improvement (11% -> 70%): Fewer production incidents
  - Workspace consolidation (413 -> 15 domain workspaces): Easier governance
  - CI/CD integration: Specs always in sync with code
  - Reduced onboarding time for new engineers

Total ROI justifies $480K renewal with room for expansion
```

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your POSTMAN_API_KEY
```

Get your API key from: https://go.postman.co/settings/me/api-keys

### 2. Run the Script

```bash
# Basic usage - creates new workspace
uv run postman_ingestion.py --spec specs/payment-refund-api-openapi.yaml

# Use existing workspace
WORKSPACE_ID=abc123 uv run postman_ingestion.py --spec specs/my-api.yaml

# Export for CI/CD
uv run postman_ingestion.py --spec specs/my-api.yaml --export ./exports/

# Force sync existing spec
uv run postman_ingestion.py --spec specs/my-api.yaml --sync
```

## Features

### Spec Management (Upsert)
- **Create**: New specs are uploaded to Postman Spec Hub
- **Update**: Existing specs (matched by title) are patched in place
- **No duplicates**: Smart detection prevents duplicate specs

### Collection Generation
- Automatic collection generation from OpenAPI spec
- All endpoints organized by tags
- Request examples populated from spec
- Linked to spec for automatic updates

### JWT Authentication
Pre-request script automatically handles:
- Token fetching using client credentials flow
- Token caching to avoid redundant auth calls
- Automatic refresh before expiry (1-minute buffer)

Environment variables needed:
- `client_id`: OAuth client ID
- `client_secret`: OAuth client secret
- `token_url`: Token endpoint URL

### Environment Setup
Creates four environments from spec servers:
- **Dev**: Development environment
- **QA**: Quality Assurance environment
- **UAT**: User Acceptance Testing environment
- **Prod**: Production environment

Each environment includes:
- `base_url`: API base URL for that environment
- `client_id`: Auth client ID (secret, empty by default)
- `client_secret`: Auth client secret (secret, empty by default)
- `token_url`: OAuth token endpoint
- `jwt_token`: Cached token (auto-managed)
- `token_expiry`: Token expiry timestamp (auto-managed)

### CI/CD Export
Export collections and environments for Newman testing:

```bash
python postman_ingestion.py --spec spec.yaml --export ./exports/
```

Output:
```
./exports/
├── payment-processing-api-refund-service-collection.json
├── env-dev.json
├── env-qa.json
├── env-uat.json
└── env-prod.json
```

## CLI Reference

```
usage: postman_ingestion.py [-h] --spec SPEC [--export DIR] [--sync]

Ingest OpenAPI specs into Postman Spec Hub

options:
  -h, --help    show this help message and exit
  --spec SPEC   Path to OpenAPI spec file (YAML or JSON)
  --export DIR  Export collection and environments to directory
  --sync        Force sync of linked collections

Examples:
  python postman_ingestion.py --spec resources/payment-refund-api.yaml
  python postman_ingestion.py --spec spec.yaml --export ./exports/
  WORKSPACE_ID=abc123 python postman_ingestion.py --spec spec.yaml --sync
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTMAN_API_KEY` | Yes | Your Postman API key |
| `WORKSPACE_ID` | No | Target workspace ID (creates new if not set) |
| `SPEC_PATH` | No | Default spec path (can use --spec instead) |

## Workflow

```
┌─────────────────┐
│ OpenAPI Spec    │
│ (local file)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐    No    ┌─────────────────┐
│ Spec exists in  │────────►│ Create new API  │
│ workspace?      │          │ with schema     │
└────────┬────────┘          └────────┬────────┘
         │ Yes                        │
         ▼                            │
┌─────────────────┐                   │
│ Update existing │                   │
│ schema content  │                   │
└────────┬────────┘                   │
         │                            │
         ▼                            ▼
┌─────────────────────────────────────┐
│ Get/Generate linked collection      │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│ Inject JWT pre-request script       │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│ Create/update environments          │
│ (Dev, QA, UAT, Prod)                │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│ Export to JSON (optional)           │
└─────────────────────────────────────┘
```

## GitHub Actions Integration

This repository includes a pre-configured GitHub Action that automatically syncs specs to Postman when you push changes.

### Setting Up GitHub Secrets

Before the workflow can run, add these secrets to your repository:

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add:

| Secret | Description |
|--------|-------------|
| `POSTMAN_API_KEY` | Your Postman API key (get from https://go.postman.co/settings/me/api-keys) |
| `WORKSPACE_ID` | Target Postman workspace ID (find in workspace URL) |

### Automatic Sync on Push

The workflow in `.github/workflows/sync-specs.yml` triggers automatically when you:
- Push changes to any file in `specs/**/*.yaml` or `specs/**/*.json`
- Manually trigger via GitHub Actions UI with a specific spec file

### Manual Trigger

You can also manually run the workflow:
1. Go to **Actions** → **Sync API Specs to Postman**
2. Click **Run workflow**
3. Enter the spec file path (e.g., `specs/payment-refund-api-openapi.yaml`)

### Extended Workflow with Newman Testing

For API testing, extend the workflow:

```yaml
# .github/workflows/api-tests.yml
name: API Tests

on:
  push:
    paths:
      - 'specs/**/*.yaml'
  workflow_dispatch:

jobs:
  sync-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Setup Python
        run: uv python install 3.14

      - name: Install dependencies
        run: uv sync

      - name: Sync spec to Postman & Export
        env:
          POSTMAN_API_KEY: ${{ secrets.POSTMAN_API_KEY }}
          WORKSPACE_ID: ${{ secrets.WORKSPACE_ID }}
        run: |
          uv run python postman_ingestion.py \
            --spec specs/payment-refund-api-openapi.yaml \
            --export ./exports/ \
            --sync

      - name: Run Newman tests
        run: |
          npx newman run exports/*-collection.json \
            -e exports/env-dev.json \
            --reporters cli,junit \
            --reporter-junit-export results.xml

      - name: Upload test results
        uses: actions/upload-artifact@v4
        with:
          name: newman-results
          path: results.xml
```

## Scaling Strategy

### Week 1-2: Payment Processing Domain (15 APIs)
- Run script for each API spec
- Establish collection structure templates
- Document naming conventions

### Week 3-4: Second Domain Onboarding
- Train domain team on script usage
- Create domain-specific workspace
- Gather feedback and iterate

### Month 2-3: Self-Service Rollout
- GitHub Actions template for auto-sync
- Documentation and training videos
- Domain champions program
- Governance dashboard

## Workspace Governance

### Naming Conventions
- **Workspace**: `{domain}-apis` (e.g., `payments-apis`, `orders-apis`)
- **API/Spec**: `{service-name}` (e.g., `Payment Refund Service`)
- **Collection**: Auto-generated from spec title
- **Environment**: `{env-name}` (Dev, QA, UAT, Prod)

### Ownership
- One workspace per domain (not per API)
- Collection ownership tied to API team
- Cross-team visibility via shared workspaces

## Troubleshooting

### "POSTMAN_API_KEY environment variable is required"
Set your API key in `.env` or export it:
```bash
export POSTMAN_API_KEY=your-key-here
```

### "Spec file not found"
Verify the path exists and is readable:
```bash
ls -la "resources/payment-refund-api-openapi (3).yaml"
```

### Rate Limiting
The script handles rate limiting automatically with exponential backoff. If you see rate limit warnings, the script will retry.

### "Workspace not found"
Verify your `WORKSPACE_ID` is correct. Find it in the Postman URL:
```
https://www.postman.com/workspace/{WORKSPACE_ID}
```

## File Structure

```
hm-postman-adoption-starter-kit/
├── postman_ingestion.py       # Main script
├── pyproject.toml             # Python dependencies (uv)
├── .env                       # Your environment variables (gitignored)
├── .env.example               # Environment variable template
├── specs/                     # OpenAPI specs (triggers CI/CD)
│   └── payment-refund-api-openapi.yaml
├── resources/                 # Documentation and reference materials
│   └── RESOURCES.md
├── exports/                   # Generated exports (gitignored)
│   ├── *-collection.json
│   └── env-*.json
├── .github/
│   └── workflows/
│       └── sync-specs.yml     # GitHub Action for auto-sync
└── README.md                  # This file
```

## License

Internal use only.
