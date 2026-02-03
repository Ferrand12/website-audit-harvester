# Website Audit Harvester

Lightweight pipeline for harvesting website audit data using Google PageSpeed Insights and HTML inspection.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick Start

```bash
python main.py --input data/sample_urls.csv --output out --strategy mobile --max-urls 5
```

Output files:
- `out/leads.json` — Full JSON array of lead audits
- `out/leads.csv` — Flat CSV export (Excel-compatible)
- `out/run.log` — Debug log
- `out/cache/` — Cached HTML and PSI results

## Run Tests

```bash
pytest -q
```

## CLI Options

### Main Command

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | (required) | CSV with a `url` column |
| `--output` | `out` | Output directory |
| `--strategy` | `mobile` | `mobile` or `desktop` |
| `--config` | `config/config.yaml` | Config file path |
| `--concurrency` | `4` | Concurrency limit (unused in MVP) |
| `--max-urls` | all | Limit number of URLs processed |
| `--cache` | enabled | Enable caching (default) |
| `--no-cache` | | Disable caching |
| `--cache-dir` | `out/cache` | Cache directory |
| `--resume` | | Skip URLs already in leads.json |
| `--force` | | Ignore cache and resume, re-run all |

### Verify Command

Verify data integrity of a leads.json file:

```bash
python main.py verify --input out/leads.json --report out/verify_report.json
```

| Flag | Description |
|------|-------------|
| `--input`, `-i` | Path to leads.json (required) |
| `--report`, `-r` | Path to save verification report |

Exit codes:
- `0` — No hard failures (soft warnings only)
- `1` — Hard invariant failures detected

## Caching & Resume

### Caching

Results are cached by default to avoid redundant API calls:
- HTML inspection results cached by URL
- PSI results cached by URL + strategy

Cache files are stored in `out/cache/` (configurable via `--cache-dir`).

```bash
# First run - fetches and caches
python main.py --input urls.csv --output out

# Second run - uses cache (fast)
python main.py --input urls.csv --output out

# Force fresh data
python main.py --input urls.csv --output out --force
```

### Resume

Resume a partial run by skipping URLs already in leads.json:

```bash
# Initial run (interrupted)
python main.py --input urls.csv --output out

# Resume from where we left off
python main.py --input urls.csv --output out --resume
```

## Scoring System

Leads are scored 0-100 based on opportunity signals, then assigned a letter grade.

### Point Categories

| Category | Max Points | Key Thresholds |
|----------|------------|----------------|
| Performance/CWV | 35 | perf≤49: +20, perf 50-69: +12, LCP>4000: +8 |
| SEO | 25 | seo≤69: +18, seo 70-84: +10 |
| Accessibility + BP | 15 | a11y≤79: +6, bp≤79: +6, both: +3 bonus |
| Tracking Gap | 15 | no GA4/GTM: +15, missing one: +8 |
| Tech Opportunity | 10 | WordPress+perf≤69: +6, scripts≥15: +4 |

### Letter Grades

| Grade | Score | Meaning |
|-------|-------|---------|
| A | ≥ 70 | High opportunity lead |
| B | 40-69 | Medium opportunity |
| C | < 40 | Low opportunity |

### Override Rules

- `status == "failed"` → C, 0 points
- `perf ≤ 49 AND seo ≤ 69` → minimum B
- `(no GA4 or no GTM) AND seo ≤ 84` → minimum B

See [docs/scoring.md](docs/scoring.md) for full specification.

## ROI Prioritization

Leads are classified by ROI priority based on score grade and business signals.

### Priority Levels

| Priority | Criteria |
|----------|----------|
| **high** | Grade A/B + (services OR pricing OR ecommerce OR multi-location) |
| **medium** | Grade A/B without signals OR Grade C with pricing/ecommerce |
| **low** | Grade C without strong business signals |

### Business Signals

Extracted from homepage HTML:
- `has_careers_page` — Links to /careers, /jobs
- `has_pricing_page` — Links to /pricing, /plans
- `has_services_page` — Links to /services, /solutions
- `has_contact_form` — Form with email/message fields
- `has_ecommerce` — Cart/checkout or ecommerce platform detected
- `has_multiple_locations_hint` — Multiple addresses or "locations" page
- `languages_hint` — Detected languages
- `phone_present` / `email_present` — Contact info detected
- `social_links_count` — Number of social platform links

See [docs/roi_signals.md](docs/roi_signals.md) for detailed documentation.

## Data Schema

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `score_letter` | A/B/C | Lead grade |
| `score_points` | 0-100 | Opportunity score |
| `score_reasons` | list | Top 3 contributing factors |
| `roi_priority` | high/medium/low | ROI-based prioritization |
| `roi_reasons` | list | Reasons for ROI classification |
| `tracking_evidence` | dict | `{"gtm": ["GTM-XXX"], "ga4": ["G-XXX"]}` |
| `tech_confidence` | dict | `{"cms": 0.9, "framework": 0.5, ...}` |
| `html_meta.third_party_script_count` | int | External scripts detected |
| `business_signals.*` | various | Business ability-to-pay signals |

### Tracking Detection

- GA4, GTM, UA (Universal Analytics)
- Meta Pixel, Hotjar, Clarity
- Segment, Mixpanel
- LinkedIn Insight, TikTok Pixel

### Tech Detection

- **CMS:** WordPress, Shopify, Webflow, Wix, Squarespace, Drupal, Joomla
- **Framework:** Next.js, Nuxt, Gatsby, React, Vue, Angular
- **Ecommerce:** WooCommerce, Shopify, PrestaShop, Magento
- **Hosting:** Cloudflare, Vercel, Netlify, Apache, Nginx

## Configuration

Edit `config/config.yaml`:

```yaml
# Google PageSpeed Insights API key (optional, but recommended)
psi_api_key: ""

# HTTP timeout for requests
timeout_seconds: 30

# Retry count for transient failures
max_retries: 3

# Rate limit (requests per minute)
rate_limit_per_min: 60

# Cache settings
cache_enabled: true
cache_dir: out/cache

# Resume from existing leads.json
resume_enabled: false

# Strict mode for verification
verify_strict: true
```

## Documentation

- [Scoring Specification](docs/scoring.md) — Detailed scoring rules
- [ROI Signals](docs/roi_signals.md) — Business signals and ROI prioritization
- [Implementation Summary](docs/implementation_summary.md) — Technical overview

## Example Output

### Console Summary
```
A: 4 | B: 9 | C: 7
ROI: high: 6 | medium: 5 | low: 9
Top leads:
  1) example.com - 78 (A) ROI: high - perf 48, seo 62, no GA4/GTM
  2) slowsite.com - 65 (B) ROI: medium - perf 55, seo 70
```

### CSV Row
```csv
domain,score_letter,score_points,roi_priority,roi_reasons,business_signals.has_pricing_page
example.com,A,78,high,"[""A-grade lead"",""offers services""]",true
```

### Verify Output
```
VERIFY: hard failures=0 warnings=2
Issues:
  [WARN] bloated.com: third_party_script_count=55 (tag bloat)
  [WARN] inconsistent.com: tracking_evidence[gtm] present but tracking.gtm=False
```
