# ROI Signals & Business Signal Detection

This document describes the business signals extracted from homepage HTML and how they inform ROI (Return on Investment) prioritization for lead scoring.

## Business Signals

Business signals are heuristics extracted from homepage HTML to assess a company's ability to pay and likelihood of conversion. These signals help prioritize outreach efforts.

### Signal Definitions

| Signal | Field | Description |
|--------|-------|-------------|
| Careers Page | `has_careers_page` | Links to /careers, /jobs, /recrutement, /emploi, etc. |
| Pricing Page | `has_pricing_page` | Links to /pricing, /plans, /tarifs |
| Services Page | `has_services_page` | Links to /services, /solutions, /prestations |
| Contact Form | `has_contact_form` | `<form>` containing email/contact/message/textarea |
| Ecommerce | `has_ecommerce` | Tech detection (WooCommerce, Shopify) or cart/checkout hints |
| Multiple Locations | `has_multiple_locations_hint` | "Locations", "stores", multiple addresses detected |
| Languages | `languages_hint` | Languages from `<html lang>` or content-language meta |
| Phone Present | `phone_present` | Phone number pattern detected |
| Email Present | `email_present` | Email address pattern detected |
| Social Links | `social_links_count` | Count of unique social platforms (FB, LinkedIn, Twitter, etc.) |

### Detection Patterns

#### Careers Keywords
```
careers|jobs|recrutement|emploi|karriere|carriere
```
Detected in href attributes of anchor tags.

#### Pricing Keywords
```
pricing|tarifs?|prices?|plans?|abonnement
```

#### Services Keywords
```
services?|prestations?|solutions?|offerings?
```

#### Contact Form
Detected via `<form>` tags containing keywords: email, contact, message, textarea.

#### Ecommerce Hints
From tech detection (WooCommerce, Shopify, PrestaShop, Magento) or HTML patterns:
```
cart|panier|checkout|add-to-cart|buy-now|shop
```

#### Multiple Locations
Keywords + multiple address patterns:
```
locations?|stores?|magasins?|agences?|nos agences|find us|nos boutiques|points de vente
```
Address pattern: `\d{1,5}\s+[\w\s]+(street|st|avenue|ave|road|rd|boulevard|blvd|rue|place)`

#### Social Domains
- facebook.com, fb.com → facebook
- instagram.com → instagram
- linkedin.com → linkedin
- twitter.com, x.com → twitter
- tiktok.com → tiktok

## ROI Priority Classification

Leads are classified into three ROI priority levels based on score letter grade and business signals.

### Priority Levels

| Priority | Criteria | Meaning |
|----------|----------|---------|
| **high** | Grade A or B **AND** (services OR pricing OR ecommerce OR multi-location) | High conversion likelihood, ability to pay |
| **medium** | Grade A or B without signals **OR** Grade C with pricing/ecommerce | Moderate opportunity |
| **low** | Grade C without pricing/ecommerce | Lower priority for outreach |

### ROI Reasons

The `roi_reasons` field explains why a lead was classified at its priority level:

- `"A-grade lead"` / `"B-grade lead"` — Base grade reasoning
- `"offers services"` — Has services page
- `"has pricing page"` — Has explicit pricing
- `"ecommerce detected"` — Runs an online store
- `"multiple locations"` — Multi-location business (larger company)
- `"C-grade: limited signals"` — Lower grade without strong business signals

## Data Flow

1. **HTML Inspection** (`src/audits/html_inspector.py`)
   - Fetches homepage HTML
   - Extracts `BusinessSignals` via `_extract_business_signals()`
   - Populates `lead.business_signals`

2. **Business Insights** (`src/insights/business.py`)
   - `_compute_roi_priority()` analyzes score + signals
   - Sets `lead.roi_priority` and `lead.roi_reasons`

3. **Export** (`src/exporters/export.py`)
   - Includes `roi_priority`, `roi_reasons`, and all `business_signals.*` fields in CSV/JSON

## Example Output

```json
{
  "business_signals": {
    "has_careers_page": true,
    "has_pricing_page": true,
    "has_services_page": true,
    "has_contact_form": true,
    "has_ecommerce": false,
    "has_multiple_locations_hint": false,
    "languages_hint": ["en", "fr"],
    "phone_present": true,
    "email_present": true,
    "social_links_count": 3
  },
  "roi_priority": "high",
  "roi_reasons": ["A-grade lead", "offers services", "has pricing page"]
}
```

## Limitations

1. **Homepage-only analysis** — Signals are extracted from the homepage only, not crawled pages
2. **Pattern-based** — Detection relies on URL patterns and keywords, may miss non-standard implementations
3. **No verification** — Presence of a link doesn't guarantee the page exists or is functional
4. **Language limitations** — Keyword patterns cover English and French primarily

## Future Improvements

- Sitemap analysis for more accurate page detection
- WHOIS/company database enrichment
- Revenue estimation via employee count heuristics
- Industry classification
