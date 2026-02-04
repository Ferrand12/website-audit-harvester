# CLAUDE.md - Website Audit Harvester

## Project Overview

Pipeline CLI tool for harvesting website audit data using Google PageSpeed Insights and HTML inspection. Identifies leads (websites with optimization opportunities) and generates personalized outreach messages.

**Tech Stack:** Python 3.11+, Pydantic, PyYAML, pytest

## Quick Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"

# Run audit (concurrent by default, 4 workers)
python main.py --input data/sample_urls.csv --output out --strategy mobile --max-urls 5

# Run with more workers
python main.py --input data/sample_urls.csv --output out --concurrency 8

# Run with cache disabled
python main.py --input data/sample_urls.csv --output out --force

# Resume interrupted run
python main.py --input data/sample_urls.csv --output out --resume

# Skip PSI API key validation
python main.py --input data/sample_urls.csv --output out --skip-psi-validation

# Verify data integrity
python main.py verify --input out/leads.json --report out/verify_report.json

# Run tests
pytest -q
```

## Project Structure

```
website-audit-harvester/
├── main.py                      # CLI entry point
├── config/
│   └── config.yaml              # PSI API key, timeouts, rate limits, cache TTL
├── src/
│   ├── audits/
│   │   ├── html_inspector.py    # HTML fetch + tracking/tech/biz signal detection
│   │   └── psi.py               # PSI API + validation + stats tracking
│   ├── exporters/
│   │   └── export.py            # JSON + CSV export (78 columns)
│   ├── insights/
│   │   └── business.py          # Pain detection, ROI priority, outreach generation
│   ├── models/
│   │   └── lead_audit.py        # Pydantic data models (LeadAudit, PSIScores, etc.)
│   ├── pipeline/
│   │   └── runner.py            # Concurrent pipeline with ThreadPoolExecutor
│   ├── scoring/
│   │   └── rubric.py            # Scoring rules (0-100 pts, A/B/C grades)
│   └── utils/
│       ├── cache.py             # Cache with TTL, schema versioning, URL normalization
│       ├── http.py              # HTTP fetch with retries
│       ├── logging.py           # File + console logging
│       ├── rate_limit.py        # Token bucket rate limiter
│       ├── url.py               # URL normalization utilities
│       └── verify.py            # Data integrity verification
├── tests/                       # pytest tests (238 tests)
├── docs/
│   ├── scoring.md               # Scoring specification
│   ├── roi_signals.md           # Business signals documentation
│   └── implementation_summary.md
└── out/                         # Default output directory
    ├── leads.json               # Full audit results
    ├── leads.csv                # Flattened CSV (78 columns)
    ├── run.log                  # Debug log
    └── cache/                   # Cached HTML/PSI results (with TTL)
```

## Data Flow

```
CSV (URLs) → LeadAudit.from_url()
  → [Concurrent Stage A] HTML Inspection (tracking, tech, business signals)
  → [Concurrent Stage B] PSI Audit (scores, CWV, opportunities)
  → Scoring (points 0-100, letter A/B/C)
  → Business Insights (pains, ROI priority, outreach)
  → JSON/CSV Export
```

## Current Capabilities

### 1. Concurrent Pipeline (`src/pipeline/runner.py`)

**Architecture:**
- Two-stage concurrent processing with ThreadPoolExecutor
- Stage A: HTML inspection (concurrent)
- Stage B: PSI audits (concurrent with rate limiting)
- Configurable worker count (default: 4)

**Rate Limiting (`src/utils/rate_limit.py`):**
- Token bucket algorithm for API request pacing
- Configurable rate (default: 60/min) and burst
- Thread-safe with blocking acquire

**PSI Validation:**
- API key validated on startup (lightweight test request)
- Clear error messages for invalid/forbidden keys
- Skip validation with `--skip-psi-validation` flag

**Observability (`PSIStats`):**
- Tracks: calls_made, cache_hits, rate_limited_waits, errors
- Thread-safe counters
- Summary logged at pipeline completion

### 2. Caching (`src/utils/cache.py`)

**Features:**
- SHA1-keyed JSON files with metadata
- URL normalization before hashing (`src/utils/url.py`)
- TTL-based expiration (default: 7 days)
- Schema versioning (auto-invalidates on version mismatch)
- Partial result caching (configurable)

**URL Normalization:**
- Strips tracking params: `utm_*`, `gclid`, `fbclid`, `mc_cid`, `mc_eid`, `msclkid`
- Normalizes: scheme (https), trailing slashes, fragments
- Ensures consistent cache keys across URL variants

### 3. HTML Inspection (`src/audits/html_inspector.py`)

**Tracking Detection (10 trackers):**
- GA4, GTM, UA (Universal Analytics)
- Meta Pixel, Hotjar, Clarity
- Segment, Mixpanel
- LinkedIn Insight, TikTok Pixel

**Tech Detection:**
- CMS: WordPress, Shopify, Webflow, Wix, Squarespace, Drupal, Joomla
- Frameworks: Next.js, Nuxt, Gatsby, React, Vue, Angular
- Ecommerce: WooCommerce, Shopify, PrestaShop, Magento
- Hosting: Cloudflare, Vercel, Netlify, Apache, Nginx

**Business Signals:**
- Careers/pricing/services pages
- Contact forms, ecommerce capability
- Multi-location hints, languages
- Phone/email presence, social links

### 4. PSI Integration (`src/audits/psi.py`)

**Metrics Extracted:**
- Scores: performance, seo, accessibility, best_practices (0-100)
- CWV: LCP, INP, CLS, TTFB, FCP
- Top 3 opportunities + diagnostics with impact classification

**API Key Validation:**
- `validate_api_key()` - lightweight test request on startup
- `PSIValidationError` - clear error with HTTP code
- Handles: 400 (bad format), 401 (invalid), 403 (forbidden), 429 (rate limited)

**Statistics Tracking:**
- `PSIStats` dataclass with thread-safe counters
- `get_psi_stats()` / `reset_psi_stats()` for global access

### 5. Scoring System (`src/scoring/rubric.py`)

| Category | Max Pts | Key Thresholds |
|----------|---------|----------------|
| Performance/CWV | 35 | perf≤49: +20, perf 50-69: +12, LCP>4000: +8 |
| SEO | 25 | seo≤69: +18, seo 70-84: +10 |
| A11y + BP | 15 | each ≤79: +6, both: +3 bonus |
| Tracking Gap | 15 | no GA4/GTM: +15, missing one: +8 |
| Tech Opportunity | 10 | WordPress+perf≤69: +6, scripts≥15: +4 |

**Grades:** A (≥70), B (40-69), C (<40)

**Override Rules:**
- `status == "failed"` → C, 0 pts
- `perf ≤ 49 AND seo ≤ 69` → minimum B
- `(no GA4 OR no GTM) AND seo ≤ 84` → minimum B

### 6. ROI Prioritization (`src/insights/business.py`)

- **High:** Grade A/B + (services OR pricing OR ecommerce OR multi-location)
- **Medium:** Grade A/B without signals OR Grade C + (pricing OR ecommerce)
- **Low:** Grade C without business signals

### 7. Pain Detection (5 types)

| Pain ID | Trigger | Severity |
|---------|---------|----------|
| slow_mobile | perf≤69 OR lcp>4000 | high if perf≤49 |
| seo_weak | seo≤84 | high if seo≤64 |
| tracking_gap | missing GA4/GTM | always high |
| accessibility_risk | a11y≤79 | high if ≤59 |
| best_practices_risk | bp≤79 | high if ≤59 |

### 8. CSV Export (`src/exporters/export.py`)

**78 columns including:**
- All LeadAudit fields flattened
- `psi_opportunities_titles` - pipe-delimited titles (e.g., "Title1|Title2|Title3")
- `psi_diagnostics_titles` - pipe-delimited titles
- `psi_opportunities_top3` - JSON array with id/title/impact
- `psi_diagnostics_top3` - JSON array with id/title/impact

## Known Limitations

### Architecture

1. **Memory Usage**
   - Loads entire URL list + leads into memory
   - Resume mode loads full leads.json (problematic for 10k+ URLs)

### Detection

2. **Regex-Based Tech Detection**
   - Pattern matching only (no JS execution for SPAs)
   - Confidence scoring is simplistic (linear weights)
   - No version detection
   - Limited hosting providers

3. **Tracking Detection**
   - Only checks presence, not implementation quality
   - Cannot verify if GTM/GA4 actually fires
   - Captures max 5 matches per tracker

4. **Business Signals**
   - Keyword-based (fragile for non-English sites)
   - No semantic understanding
   - Phone/email regex has false positives

### API

5. **PSI Integration**
   - 404/403 responses not cached
   - No parallel mobile + desktop fetching

### Outreach

6. **Message Generation**
   - Template-based, limited personalization
   - English only (hardcoded)
   - Generic CTA for all leads

## Improvement Opportunities

### High Priority

1. **Enhanced Tech Detection**
   - Wappalyzer API integration
   - JavaScript execution (Playwright) for SPA detection
   - Version detection from JS globals
   - More hosting providers (AWS, GCP, Azure)

2. **Tracking Depth**
   - Parse GTM containers for linked accounts
   - Detect datalayer structure
   - Track script placement (critical path vs deferred)

### Medium Priority

3. **Flexible Scoring**
   - YAML-based rubric customization
   - Industry-specific weights
   - A/B testing harness

4. **HTML Fetch Improvements**
   - Retry logic (currently only PSI has retries)
   - JavaScript rendering option
   - Proxy support for geo-testing

5. **Export Enhancements**
   - Custom column selection
   - Filtering by score/status/ROI

6. **Memory Optimization**
   - Streaming JSON for large datasets
   - Chunked processing for 10k+ URLs

### Lower Priority

7. **Advanced Analytics**
   - Competitive benchmarking
   - Trend tracking over time
   - ML-based scoring

8. **Outreach**
   - Multi-language templates
   - A/B testing with response tracking
   - CRM integration

## Completed Improvements ✓

The following items from the original improvement list have been implemented:

- ✓ **True Concurrency** - ThreadPoolExecutor with configurable workers (~3.5x throughput)
- ✓ **Token Bucket Rate Limiting** - Prevents API quota exhaustion
- ✓ **URL Normalization** - Strips tracking params, normalizes scheme/slashes
- ✓ **Cache TTL Expiration** - 7-day default, configurable per-run
- ✓ **Cache Schema Versioning** - Auto-invalidates on schema changes
- ✓ **PSI API Key Validation** - Validates on startup with clear errors
- ✓ **PSI Observability** - Thread-safe stats (calls, cache hits, errors, rate waits)
- ✓ **CSV Opportunities/Diagnostics** - 4 new columns with titles and JSON data

## Code Conventions

- **Models:** Pydantic BaseModel with explicit field types
- **Errors:** Logged to errors list on LeadAudit, status="partial" on non-fatal
- **Confidence:** 0.0-1.0 scale for tech detection
- **Tracking Evidence:** dict[str, list[str]] with tracker IDs
- **Logging:** DEBUG to file, INFO to console
- **Thread Safety:** Use threading.Lock for shared state (PSIStats, TokenBucket)

## Test Coverage

```
tests/
├── test_business_signals.py  # Pain/ROI/outreach tests
├── test_scoring.py           # Rubric rules + overrides
├── test_verify.py            # Hard/soft invariants
├── test_html_inspector.py    # Tracking/tech detection
├── test_cache.py             # Cache manager, TTL, URL normalization
├── test_psi_parsing.py       # PSI response parsing
├── test_concurrency.py       # Rate limiter, concurrent pipeline
├── test_psi_client.py        # API key validation, PSI stats
└── test_export.py            # CSV column formatting
```

Run: `pytest -q` (238 tests) or `pytest -v` for verbose output.

## Key Files to Modify

| Task | Files |
|------|-------|
| Add new tracker | `src/audits/html_inspector.py` (TRACKING_PATTERNS) |
| Add new CMS/framework | `src/audits/html_inspector.py` (TECH_PATTERNS) |
| Modify scoring rules | `src/scoring/rubric.py` |
| Change ROI logic | `src/insights/business.py` (_compute_roi_priority) |
| Add new pain type | `src/insights/business.py` (_detect_pains) |
| Modify outreach template | `src/insights/business.py` (_generate_outreach) |
| Add export format | `src/exporters/export.py` |
| Add CLI option | `main.py` (argparse) |
| Modify rate limiting | `src/utils/rate_limit.py` (TokenBucket) |
| Change URL normalization | `src/utils/url.py` (normalize_url) |
| Adjust cache behavior | `src/utils/cache.py` (CacheManager) |

## Configuration Reference

```yaml
# config/config.yaml
psi_api_key: ""              # Google PSI API key (optional but recommended)
timeout_seconds: 30          # HTTP timeout
max_retries: 3               # Retry count for transient failures
rate_limit_per_min: 60       # PSI request rate limit (token bucket)
default_strategy: mobile     # Lighthouse strategy

# Cache settings
cache_enabled: true          # Enable caching
cache_dir: out/cache         # Cache directory
cache_ttl_seconds: 604800    # Cache TTL (default: 7 days)
cache_partial: true          # Cache partial/incomplete results

resume_enabled: false        # Resume mode default
verify_strict: true          # Verification strictness
```

## Output Schema Summary

**LeadAudit fields:**
- Identity: lead_id, url, domain, timestamp_utc, status, strategy
- Scoring: score_letter, score_points, score_reasons
- ROI: roi_priority, roi_reasons
- PSI: scores.*, cwv.*, psi_opportunities, psi_diagnostics
- HTML: html_meta.*, tracking.*, tracking_evidence, tech.*, tech_confidence
- Business: business_signals.*, pains, outreach_en

**CSV-specific columns:**
- psi_opportunities_titles, psi_diagnostics_titles (pipe-delimited)
- psi_opportunities_top3, psi_diagnostics_top3 (JSON arrays)

**Status values:** pending → complete | partial | failed
