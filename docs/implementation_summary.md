# Implementation Summary

This document reflects the actual code implementation as of the latest calibration patch.

## Project Structure

```
website-audit-harvester/
├── main.py                          # CLI entry point
├── pyproject.toml                   # Python 3.11+, pydantic, pyyaml, pytest
├── config/config.yaml               # Runtime configuration
├── data/sample_urls.csv             # 20 sample URLs
├── src/
│   ├── models/lead_audit.py         # Pydantic data models
│   ├── audits/
│   │   ├── psi.py                   # Google PageSpeed Insights API
│   │   └── html_inspector.py        # HTML tracking/tech detection
│   ├── scoring/rubric.py            # A/B/C scoring logic
│   ├── insights/business.py         # Pain detection + outreach generation
│   ├── pipeline/runner.py           # Pipeline orchestration
│   ├── exporters/export.py          # JSON/CSV export
│   └── utils/
│       ├── logging.py               # Logging setup
│       └── http.py                  # HTTP utilities with retry
├── tests/                           # pytest test suite
└── docs/                            # Documentation
```

## Data Model (lead_audit.py)

### LeadAudit Fields

| Field | Type | Description |
|-------|------|-------------|
| `lead_id` | str | UUID |
| `url` | str | Original URL |
| `domain` | str | Extracted domain |
| `timestamp_utc` | str | ISO timestamp |
| `status` | str | pending/partial/complete/failed |
| `strategy` | str | mobile/desktop |
| `score_letter` | str | A/B/C |
| `score_points` | int | 0-100 |
| `score_reasons` | list[str] | Top 3 reasons |
| `scores` | PSIScores | performance/seo/accessibility/best_practices |
| `cwv` | CWV | lcp_ms/inp_ms/cls/ttfb_ms/fcp_ms |
| `tracking` | TrackingInfo | Boolean flags for each tracker |
| `tracking_evidence` | dict[str, list[str]] | Matched patterns per tracker |
| `tech` | TechInfo | cms/framework/ecommerce/hosting_hints |
| `tech_confidence` | dict[str, float] | Confidence per category (0-1) |
| `html_meta` | HTMLMeta | http_status/final_url/response_time_ms/third_party_script_count |
| `pains` | list[PainItem] | Detected business pains |
| `outreach_en` | OutreachMessage | Generated outreach message |
| `errors` | list[str] | Error messages |

## Scoring Implementation (rubric.py)

### Point Accumulation

```python
# Performance/CWV (max 35)
perf <= 49: +20
perf 50-69: +12
perf 70-89: +5
LCP > 4000: +8
INP > 300: +5
CLS > 0.25: +2

# SEO (max 25)
seo <= 69: +18
seo 70-84: +10
seo 85-94: +4

# A11y + BP (max 15)
a11y <= 79: +6
bp <= 79: +6
both low: +3 bonus

# Tracking (max 15)
no GA4 AND no GTM: +15
missing one: +8

# Tech (max 10)
WordPress/WooCommerce + perf<=69: +6
third_party_scripts >= 15: +4
```

### Grade Thresholds
- A: >= 70 points
- B: 40-69 points
- C: < 40 points

### Override Rules
1. `status == "failed"` → C, 0 points
2. `perf <= 49 AND seo <= 69` → minimum B
3. `(no GA4 OR no GTM) AND seo <= 84` → minimum B

## HTML Inspector (html_inspector.py)

### Tracking Detection

Detected via regex patterns with captured evidence:

| Tracker | Pattern Examples |
|---------|-----------------|
| GA4 | `gtag/js?id=G-XXXXX` |
| GTM | `GTM-XXXXX` |
| UA | `UA-XXXXX-X` |
| Meta Pixel | `fbq('init'`, `connect.facebook.net` |
| Hotjar | `hotjar.com` |
| Clarity | `clarity.ms/tag/` |
| Segment | `cdn.segment.com/analytics` |
| Mixpanel | `mixpanel.com/libs` |
| LinkedIn Insight | `snap.licdn.com` |
| TikTok Pixel | `analytics.tiktok.com` |

### Tech Detection

| Category | Signals |
|----------|---------|
| **CMS** | WordPress (wp-content, wp-includes, generator), Shopify, Webflow, Wix, Squarespace, Drupal, Joomla |
| **Framework** | Next.js, Nuxt, Gatsby, React, Vue, Angular |
| **Ecommerce** | WooCommerce, Shopify, PrestaShop, Magento |
| **Hosting** | Cloudflare (cf-ray), Vercel, Netlify, Apache, Nginx, LiteSpeed, IIS |

### Third-Party Script Count

Counts `<script src="...">` tags where the host differs from the page domain. Used in tech opportunity scoring.

## Export Format (export.py)

### CSV Columns (stable order)

```
lead_id, url, domain, timestamp_utc, status, strategy,
score_letter, score_points, score_reasons,
scores.performance, scores.seo, scores.accessibility, scores.best_practices,
cwv.lcp_ms, cwv.inp_ms, cwv.cls, cwv.ttfb_ms, cwv.fcp_ms,
html_meta.http_status, html_meta.final_url, html_meta.response_time_ms, html_meta.third_party_script_count,
tracking.ga4, tracking.gtm, tracking.ua, tracking.meta_pixel, tracking.hotjar, tracking.clarity, tracking.segment, tracking.mixpanel, tracking.linkedin_insight, tracking.tiktok_pixel,
tracking_evidence,
tech.cms, tech.framework, tech.ecommerce, tech.hosting_hints, tech_confidence,
pains_summary, outreach_en.subject, outreach_en.body,
errors
```

### Data Serialization

- Lists → JSON strings
- Dicts (`tracking_evidence`, `tech_confidence`) → JSON strings
- CSV encoding: UTF-8 with BOM for Excel compatibility

## Test Coverage

### test_scoring.py
- Performance/CWV point calculations (8 tests)
- SEO point calculations (4 tests)
- A11y + BP point calculations (3 tests)
- Tracking gap calculations (3 tests)
- Tech opportunity calculations (4 tests)
- Letter grade thresholds (3 tests)
- Override rules (3 tests)
- Score reasons (3 tests)

### test_html_inspector.py
- Tracking detection patterns (4 tests)
- Tracking evidence dict shape (2 tests)
- CMS detection (2 tests)
- Framework detection (1 test)
- Third-party script counting (3 tests)
- Mixed detection (1 test)
- Tech confidence structure (2 tests)

### test_psi_parsing.py
- Score extraction (5 tests)
- CWV extraction (5 tests)
- Opportunities/diagnostics extraction (2 tests)

## CLI Usage

```bash
python main.py \
  --input data/sample_urls.csv \
  --output out \
  --strategy mobile \
  --max-urls 10
```

### Output

```
A: 3 | B: 5 | C: 2
Top leads:
  1) example.com - 78 (A) - perf 45, seo 62, no GA4/GTM
  2) slowsite.com - 65 (B) - perf 55, seo 70
  ...
```

### Files Generated

- `out/leads.json` - Full nested JSON
- `out/leads.csv` - Flattened CSV
- `out/run.log` - Debug log
