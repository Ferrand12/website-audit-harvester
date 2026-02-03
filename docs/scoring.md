# Scoring Specification

This document describes the scoring rubric used to evaluate website leads.

## Overview

The scoring system assigns points (0-100) based on opportunity signals detected during the audit. Higher scores indicate more opportunity for improvement, making them better leads.

## Point Categories

### 1. Performance / Core Web Vitals (0-35 points)

| Condition | Points |
|-----------|--------|
| Performance score ≤ 49 | +20 |
| Performance score 50-69 | +12 |
| Performance score 70-89 | +5 |
| Performance score ≥ 90 | +0 |
| LCP > 4000ms | +8 |
| INP > 300ms | +5 |
| CLS > 0.25 | +2 |

**Cap:** Maximum 35 points from this category.

### 2. SEO (0-25 points)

| Condition | Points |
|-----------|--------|
| SEO score ≤ 69 | +18 |
| SEO score 70-84 | +10 |
| SEO score 85-94 | +4 |
| SEO score ≥ 95 | +0 |

### 3. Accessibility + Best Practices (0-15 points)

| Condition | Points |
|-----------|--------|
| Accessibility score ≤ 79 | +6 |
| Best Practices score ≤ 79 | +6 |
| Both ≤ 79 (bonus) | +3 |

### 4. Tracking Maturity Gap (0-15 points)

| Condition | Points |
|-----------|--------|
| Neither GA4 nor GTM present | +15 |
| Missing one of GA4/GTM | +8 |
| Both GA4 and GTM present | +0 |

### 5. Tech Opportunity (0-10 points)

| Condition | Points |
|-----------|--------|
| WordPress/WooCommerce AND performance ≤ 69 | +6 |
| Third-party script count ≥ 15 | +4 |

## Letter Grades

| Grade | Score Range |
|-------|-------------|
| A | ≥ 70 |
| B | 40-69 |
| C | < 40 |

## Override Rules

These rules guarantee minimum grades regardless of point total:

1. **Failed status:** Always C with 0 points
2. **Poor Performance + SEO:** If performance ≤ 49 AND SEO ≤ 69 → minimum B
3. **Tracking Gap + Weak SEO:** If (missing GA4 or GTM) AND SEO ≤ 84 → minimum B

## Score Reasons

The top 3 contributing factors are recorded in `score_reasons` for quick reference:
- `perf 45` - Low performance score
- `seo 62` - Low SEO score
- `no GA4/GTM` - Missing analytics
- `LCP 4500ms` - Poor Largest Contentful Paint
- `a11y 70` - Low accessibility score
- `WP+perf65` - WordPress with performance issues
- `18 scripts` - Many third-party scripts

## Examples

### Example 1: High Opportunity (A)
```
Performance: 42, SEO: 58, Accessibility: 65, Best Practices: 70
No GA4, No GTM
WordPress site

Points:
- Performance ≤49: +20
- SEO ≤69: +18
- Accessibility ≤79: +6
- No GA4/GTM: +15
- WordPress + perf≤69: +6
Total: 65 → capped at category limits

Result: 70+ points = Grade A
```

### Example 2: Medium Opportunity (B)
```
Performance: 75, SEO: 82
GA4 present, GTM missing

Points:
- Performance 70-89: +5
- SEO 70-84: +10
- Missing GTM: +8
Total: 23

Override: Missing tracking + SEO≤84 → minimum B

Result: 23 points, Grade B (via override)
```

### Example 3: Low Opportunity (C)
```
Performance: 95, SEO: 98
GA4 and GTM both present

Points: 0
Result: Grade C
```
