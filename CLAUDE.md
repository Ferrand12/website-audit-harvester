# CLAUDE.md - Website Audit Harvester

## Project Overview

Pipeline CLI tool for harvesting website audit data using Google PageSpeed Insights and HTML inspection. Identifies leads (websites with optimization opportunities) and generates personalized outreach messages.

**Tech Stack:** Python 3.11+, Pydantic, PyYAML, pytest

## Quick Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"

# Run audit
python main.py --input data/sample_urls.csv --output out --strategy mobile --max-urls 5

# Run with cache disabled
python main.py --input data/sample_urls.csv --output out --force

# Resume interrupted run
python main.py --input data/sample_urls.csv --output out --resume

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
│   └── config.yaml              # PSI API key, timeouts, rate limits
├── src/
│   ├── audits/
│   │   ├── html_inspector.py    # HTML fetch + tracking/tech/biz signal detection
│   │   └── psi.py               # PageSpeed Insights API integration
│   ├── exporters/
│   │   └── export.py            # JSON + CSV export (74 columns)
│   ├── insights/
│   │   └── business.py          # Pain detection, ROI priority, outreach generation
│   ├── models/
│   │   └── lead_audit.py        # Pydantic data models (LeadAudit, PSIScores, etc.)
│   ├── pipeline/
│   │   └── runner.py            # Main pipeline orchestration + caching
│   ├── scoring/
│   │   └── rubric.py            # Scoring rules (0-100 pts, A/B/C grades)
│   └── utils/
│       ├── cache.py             # SHA1-keyed JSON cache manager
│       ├── http.py              # HTTP fetch with retries
│       ├── logging.py           # File + console logging
│       └── verify.py            # Data integrity verification
├── tests/                       # pytest tests (~1900 lines)
├── docs/
│   ├── scoring.md               # Scoring specification
│   ├── roi_signals.md           # Business signals documentation
│   └── implementation_summary.md
└── out/                         # Default output directory
    ├── leads.json               # Full audit results
    ├── leads.csv                # Flattened CSV
    ├── run.log                  # Debug log
    └── cache/                   # Cached HTML/PSI results
```

## Data Flow

```
CSV (URLs) → LeadAudit.from_url()
  → HTML Inspection (tracking, tech, business signals)
  → PSI Audit (scores, CWV, opportunities)
  → Scoring (points 0-100, letter A/B/C)
  → Business Insights (pains, ROI priority, outreach)
  → JSON/CSV Export
```

## Current Capabilities

### 1. HTML Inspection (`src/audits/html_inspector.py`)

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

### 2. PSI Integration (`src/audits/psi.py`)

**Metrics Extracted:**
- Scores: performance, seo, accessibility, best_practices (0-100)
- CWV: LCP, INP, CLS, TTFB, FCP
- Top 3 opportunities + diagnostics with impact classification

### 3. Scoring System (`src/scoring/rubric.py`)

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

### 4. ROI Prioritization (`src/insights/business.py`)

- **High:** Grade A/B + (services OR pricing OR ecommerce OR multi-location)
- **Medium:** Grade A/B without signals OR Grade C + (pricing OR ecommerce)
- **Low:** Grade C without business signals

### 5. Pain Detection (5 types)

| Pain ID | Trigger | Severity |
|---------|---------|----------|
| slow_mobile | perf≤69 OR lcp>4000 | high if perf≤49 |
| seo_weak | seo≤84 | high if seo≤64 |
| tracking_gap | missing GA4/GTM | always high |
| accessibility_risk | a11y≤79 | high if ≤59 |
| best_practices_risk | bp≤79 | high if ≤59 |

### 6. Caching (`src/utils/cache.py`)

- SHA1-keyed JSON files
- Separate caches for HTML and PSI results
- Resume mode: skip URLs already in leads.json
- Force mode: ignore all caches

## Known Limitations

### Architecture

1. **No True Parallelization**
   - `concurrency` parameter exists but pipeline processes URLs sequentially
   - Rate limiting only after requests, not before

2. **Cache Design**
   - No URL normalization (www, trailing slashes, query params)
   - No TTL/expiration (data can be stale indefinitely)
   - No versioning (schema changes break cache)

3. **Memory Usage**
   - Loads entire URL list + leads into memory
   - Resume mode loads full leads.json (problematic for 10k+ URLs)

### Detection

4. **Regex-Based Tech Detection**
   - Pattern matching only (no JS execution for SPAs)
   - Confidence scoring is simplistic (linear weights)
   - No version detection
   - Limited hosting providers

5. **Tracking Detection**
   - Only checks presence, not implementation quality
   - Cannot verify if GTM/GA4 actually fires
   - Captures max 5 matches per tracker

6. **Business Signals**
   - Keyword-based (fragile for non-English sites)
   - No semantic understanding
   - Phone/email regex has false positives

### API

7. **PSI Integration**
   - No API key validation on startup
   - No quota tracking/graceful degradation
   - 404/403 responses not cached

### Export

8. **CSV Flattening**
   - Drops nested arrays (psi_opportunities, psi_diagnostics)
   - No filtering/sorting options

### Outreach

9. **Message Generation**
   - Template-based, limited personalization
   - English only (hardcoded)
   - Generic CTA for all leads

## Improvement Opportunities

### High Priority

1. **Implement True Concurrency**
   - asyncio for I/O-bound operations
   - ThreadPool for CPU-bound parsing
   - Proper rate limiting queue
   - Expected: 4x throughput improvement

2. **Cache Improvements**
   - URL normalization before hashing
   - TTL-based invalidation
   - Version tracking in entries
   - Streaming JSON for large datasets

3. **Enhanced Tech Detection**
   - Wappalyzer API integration
   - JavaScript execution (Playwright) for SPA detection
   - Version detection from JS globals
   - More hosting providers (AWS, GCP, Azure)

4. **Tracking Depth**
   - Parse GTM containers for linked accounts
   - Detect datalayer structure
   - Track script placement (critical path vs deferred)

### Medium Priority

5. **PSI Robustness**
   - API key validation on startup
   - Quota tracking with graceful degradation
   - Parallel mobile + desktop fetching
   - Cache failed requests with TTL

6. **Flexible Scoring**
   - YAML-based rubric customization
   - Industry-specific weights
   - A/B testing harness

7. **HTML Fetch Improvements**
   - Retry logic (currently only PSI has retries)
   - JavaScript rendering option
   - Proxy support for geo-testing

8. **Export Enhancements**
   - Include opportunities/diagnostics in CSV
   - Custom column selection
   - Filtering by score/status/ROI

### Lower Priority

9. **Advanced Analytics**
   - Competitive benchmarking
   - Trend tracking over time
   - ML-based scoring

10. **Outreach**
    - Multi-language templates
    - A/B testing with response tracking
    - CRM integration

## Code Conventions

- **Models:** Pydantic BaseModel with explicit field types
- **Errors:** Logged to errors list on LeadAudit, status="partial" on non-fatal
- **Confidence:** 0.0-1.0 scale for tech detection
- **Tracking Evidence:** dict[str, list[str]] with tracker IDs
- **Logging:** DEBUG to file, INFO to console

## Test Coverage

```
tests/
├── test_business_signals.py  # 421 lines - Pain/ROI/outreach
├── test_scoring.py           # 368 lines - Rubric rules + overrides
├── test_verify.py            # 314 lines - Hard/soft invariants
├── test_html_inspector.py    # 297 lines - Tracking/tech detection
├── test_cache.py             # 292 lines - Cache manager
└── test_psi_parsing.py       # 189 lines - PSI response parsing
```

Run: `pytest -q` or `pytest -v` for verbose output.

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

## Configuration Reference

```yaml
# config/config.yaml
psi_api_key: ""              # Google PSI API key (optional but recommended)
timeout_seconds: 30          # HTTP timeout
max_retries: 3               # Retry count for transient failures
rate_limit_per_min: 60       # PSI request rate limit
default_strategy: mobile     # Lighthouse strategy
cache_enabled: true          # Enable caching
cache_dir: out/cache         # Cache directory
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

**Status values:** pending → complete | partial | failed
