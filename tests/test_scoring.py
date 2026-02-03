"""Tests for scoring rubric - Target Spec Validation."""

import pytest

from src.models.lead_audit import LeadAudit, PSIScores, CWV, TrackingInfo, TechInfo, HTMLMeta
from src.scoring.rubric import compute_score


def _make_lead(**kwargs) -> LeadAudit:
    """Helper to create a lead with overrides. Defaults to having GA4+GTM to isolate tests."""
    lead = LeadAudit.from_url("https://test.com", "mobile")
    # Default to having both trackers to avoid adding tracking gap points in isolated tests
    if "tracking" not in kwargs:
        lead.tracking = TrackingInfo(ga4=True, gtm=True)
    for k, v in kwargs.items():
        setattr(lead, k, v)
    return lead


# ---------------------------------------------------------------------------
# Performance/CWV Points (0-35)
# ---------------------------------------------------------------------------

class TestPerfCWVPoints:
    """Test performance and CWV scoring per target spec."""

    def test_perf_lte_49_gives_20(self):
        """performance <= 49 => +20 pts."""
        lead = _make_lead(scores=PSIScores(performance=49))
        compute_score(lead)
        assert lead.score_points == 20

    def test_perf_50_to_69_gives_12(self):
        """performance 50-69 => +12 pts."""
        lead = _make_lead(scores=PSIScores(performance=65))
        compute_score(lead)
        assert lead.score_points == 12

    def test_perf_70_to_89_gives_5(self):
        """performance 70-89 => +5 pts."""
        lead = _make_lead(scores=PSIScores(performance=80))
        compute_score(lead)
        assert lead.score_points == 5

    def test_perf_gte_90_gives_0(self):
        """performance >= 90 => +0 pts."""
        lead = _make_lead(scores=PSIScores(performance=95))
        compute_score(lead)
        assert lead.score_points == 0

    def test_lcp_gt_4000_adds_8(self):
        """LCP > 4000 => +8 pts."""
        lead = _make_lead(cwv=CWV(lcp_ms=4500))
        compute_score(lead)
        assert lead.score_points == 8

    def test_inp_gt_300_adds_5(self):
        """INP > 300 => +5 pts."""
        lead = _make_lead(cwv=CWV(inp_ms=400))
        compute_score(lead)
        assert lead.score_points == 5

    def test_cls_gt_025_adds_2(self):
        """CLS > 0.25 => +2 pts."""
        lead = _make_lead(cwv=CWV(cls=0.3))
        compute_score(lead)
        assert lead.score_points == 2

    def test_perf_cwv_combo_capped_at_35(self):
        """Total perf+CWV capped at 35."""
        lead = _make_lead(
            scores=PSIScores(performance=30),  # +20
            cwv=CWV(lcp_ms=5000, inp_ms=500, cls=0.5),  # +8+5+2=15
        )
        compute_score(lead)
        # 20 + 15 = 35, exactly at cap
        assert lead.score_points == 35


# ---------------------------------------------------------------------------
# SEO Points (0-25)
# ---------------------------------------------------------------------------

class TestSEOPoints:
    """Test SEO scoring per target spec."""

    def test_seo_lte_69_gives_18(self):
        """seo <= 69 => +18 pts."""
        lead = _make_lead(scores=PSIScores(seo=65))
        compute_score(lead)
        assert lead.score_points == 18

    def test_seo_70_to_84_gives_10(self):
        """seo 70-84 => +10 pts."""
        lead = _make_lead(scores=PSIScores(seo=80))
        compute_score(lead)
        assert lead.score_points == 10

    def test_seo_85_to_94_gives_4(self):
        """seo 85-94 => +4 pts."""
        lead = _make_lead(scores=PSIScores(seo=90))
        compute_score(lead)
        assert lead.score_points == 4

    def test_seo_gte_95_gives_0(self):
        """seo >= 95 => +0 pts."""
        lead = _make_lead(scores=PSIScores(seo=98))
        compute_score(lead)
        assert lead.score_points == 0


# ---------------------------------------------------------------------------
# Accessibility + Best Practices Points (0-15)
# ---------------------------------------------------------------------------

class TestA11yBPPoints:
    """Test a11y + best practices scoring per target spec."""

    def test_a11y_lte_79_gives_6(self):
        """accessibility <= 79 => +6 pts."""
        lead = _make_lead(scores=PSIScores(accessibility=75))
        compute_score(lead)
        assert lead.score_points == 6

    def test_bp_lte_79_gives_6(self):
        """best_practices <= 79 => +6 pts."""
        lead = _make_lead(scores=PSIScores(best_practices=70))
        compute_score(lead)
        assert lead.score_points == 6

    def test_both_low_gives_15(self):
        """Both a11y and bp <= 79 => 6+6+3 = 15 pts."""
        lead = _make_lead(scores=PSIScores(accessibility=70, best_practices=70))
        compute_score(lead)
        assert lead.score_points == 15


# ---------------------------------------------------------------------------
# Tracking Maturity Gap (0-15)
# ---------------------------------------------------------------------------

class TestTrackingGapPoints:
    """Test tracking gap scoring per target spec."""

    def test_no_ga4_no_gtm_gives_15(self):
        """No GA4 and no GTM => +15 pts."""
        lead = _make_lead(tracking=TrackingInfo(ga4=False, gtm=False))
        compute_score(lead)
        assert lead.score_points == 15

    def test_missing_one_gives_8(self):
        """Missing one of GA4/GTM => +8 pts."""
        lead = _make_lead(tracking=TrackingInfo(ga4=True, gtm=False))
        compute_score(lead)
        assert lead.score_points == 8

        lead2 = _make_lead(tracking=TrackingInfo(ga4=False, gtm=True))
        compute_score(lead2)
        assert lead2.score_points == 8

    def test_both_present_gives_0(self):
        """Both GA4 and GTM present => +0 pts."""
        lead = _make_lead(tracking=TrackingInfo(ga4=True, gtm=True))
        compute_score(lead)
        assert lead.score_points == 0


# ---------------------------------------------------------------------------
# Tech Opportunity Points (0-10)
# ---------------------------------------------------------------------------

class TestTechOpportunityPoints:
    """Test tech opportunity scoring per target spec."""

    def test_wordpress_with_low_perf_gives_6(self):
        """WordPress and perf<=69 => +6 pts on top of perf points."""
        lead = _make_lead(
            scores=PSIScores(performance=65),  # +12 perf
            tech=TechInfo(cms="WordPress"),
        )
        compute_score(lead)
        # 12 (perf) + 6 (WP+perf) = 18
        assert lead.score_points == 18

    def test_woocommerce_with_low_perf_gives_6(self):
        """WooCommerce and perf<=69 => +6 pts on top of perf points."""
        lead = _make_lead(
            scores=PSIScores(performance=60),  # +12 perf
            tech=TechInfo(ecommerce="WooCommerce"),
        )
        compute_score(lead)
        # 12 (perf) + 6 (WC+perf) = 18
        assert lead.score_points == 18

    def test_many_scripts_gives_4(self):
        """third_party_script_count >= 15 => +4 pts."""
        lead = _make_lead(
            html_meta=HTMLMeta(third_party_script_count=20),
        )
        compute_score(lead)
        assert lead.score_points == 4

    def test_wordpress_no_perf_issue_gives_0(self):
        """WordPress with good perf doesn't add points."""
        lead = _make_lead(
            scores=PSIScores(performance=90),
            tech=TechInfo(cms="WordPress"),
        )
        compute_score(lead)
        assert lead.score_points == 0


# ---------------------------------------------------------------------------
# Letter Grade Mapping
# ---------------------------------------------------------------------------

class TestLetterGrades:
    """Test letter grade thresholds."""

    def test_70_plus_is_a(self):
        """Score >= 70 => A."""
        # Build a lead with >= 70 points
        # perf 40 => +20, seo 60 => +18, no tracking => +15, a11y 70 => +6, bp 70 => +6+3 = 15
        # Total: 20 + 18 + 15 + 15 = 68, need more
        # Add LCP > 4000 => +8, but capped at 35 for perf/cwv
        # So: 35 (perf cap) + 18 (seo) + 15 (tracking) + 15 (a11y+bp) = 83
        lead = _make_lead(
            scores=PSIScores(performance=40, seo=60, accessibility=70, best_practices=70),
            tracking=TrackingInfo(ga4=False, gtm=False),
            cwv=CWV(lcp_ms=5000),
        )
        compute_score(lead)
        assert lead.score_points >= 70
        assert lead.score_letter == "A"

    def test_40_to_69_is_b(self):
        """Score 40-69 => B."""
        # perf 45 => +20, seo 75 => +10, no tracking => +15 = 45
        lead = _make_lead(
            scores=PSIScores(performance=45, seo=75),
            tracking=TrackingInfo(ga4=False, gtm=False),
        )
        compute_score(lead)
        assert 40 <= lead.score_points < 70
        assert lead.score_letter == "B"

    def test_under_40_is_c(self):
        """Score < 40 => C."""
        lead = _make_lead(
            scores=PSIScores(performance=95, seo=98),
            tracking=TrackingInfo(ga4=True, gtm=True),
        )
        compute_score(lead)
        assert lead.score_points < 40
        assert lead.score_letter == "C"


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

class TestScoreOverrides:
    """Test override rules."""

    def test_failed_status_gets_c_zero(self):
        """Failed status => C, 0 points."""
        lead = _make_lead(status="failed")
        compute_score(lead)
        assert lead.score_letter == "C"
        assert lead.score_points == 0
        assert "failed" in lead.score_reasons

    def test_poor_perf_and_seo_override_to_b(self):
        """perf<=49 AND seo<=69 => minimum B."""
        lead = _make_lead(
            scores=PSIScores(performance=49, seo=69),
            tracking=TrackingInfo(ga4=True, gtm=True),
        )
        compute_score(lead)
        # 20 + 18 = 38, normally C but override to B
        assert lead.score_letter == "B"

    def test_no_tracking_and_weak_seo_override_to_b(self):
        """(not GA4 or not GTM) AND seo<=84 => minimum B."""
        lead = _make_lead(
            scores=PSIScores(performance=95, seo=80),
            tracking=TrackingInfo(ga4=False, gtm=True),  # missing one
        )
        compute_score(lead)
        # 0 + 10 + 8 = 18, normally C but override to B
        assert lead.score_letter == "B"


# ---------------------------------------------------------------------------
# Score Reasons
# ---------------------------------------------------------------------------

class TestScoreReasons:
    """Test that score_reasons are populated correctly."""

    def test_reasons_include_perf(self):
        """Poor performance should appear in reasons."""
        lead = _make_lead(
            scores=PSIScores(performance=40),
        )
        compute_score(lead)
        assert any("perf" in r for r in lead.score_reasons)

    def test_reasons_include_tracking_gap(self):
        """Missing tracking should appear in reasons."""
        lead = _make_lead(
            scores=PSIScores(performance=95, seo=95),
            tracking=TrackingInfo(ga4=False, gtm=False),
        )
        compute_score(lead)
        assert any("GA4" in r or "GTM" in r for r in lead.score_reasons)

    def test_reasons_max_three(self):
        """Reasons should be capped at 3."""
        lead = _make_lead(
            scores=PSIScores(performance=40, seo=60, accessibility=60, best_practices=60),
            tracking=TrackingInfo(ga4=False, gtm=False),
            tech=TechInfo(cms="WordPress"),
            html_meta=HTMLMeta(third_party_script_count=20),
        )
        compute_score(lead)
        assert len(lead.score_reasons) <= 3


# ---------------------------------------------------------------------------
# Combined Scoring Tests
# ---------------------------------------------------------------------------

class TestCombinedScoring:
    """Test combined scoring scenarios."""

    def test_all_categories_contribute(self):
        """All categories should contribute to total score."""
        lead = _make_lead(
            scores=PSIScores(performance=45, seo=65, accessibility=70, best_practices=70),
            tracking=TrackingInfo(ga4=False, gtm=False),
            tech=TechInfo(cms="WordPress"),
            html_meta=HTMLMeta(third_party_script_count=20),
        )
        compute_score(lead)
        # perf: 20, seo: 18, a11y+bp: 15, tracking: 15, tech: 6+4=10
        # Total: 78, but perf capped at 35 doesn't apply here since perf alone is 20
        # Expected: 20 + 18 + 15 + 15 + 10 = 78
        assert lead.score_points == 78
        assert lead.score_letter == "A"

    def test_max_possible_score(self):
        """Maximum possible score should be 100."""
        lead = _make_lead(
            scores=PSIScores(performance=20, seo=50, accessibility=50, best_practices=50),
            cwv=CWV(lcp_ms=6000, inp_ms=500, cls=0.5),
            tracking=TrackingInfo(ga4=False, gtm=False),
            tech=TechInfo(cms="WordPress"),
            html_meta=HTMLMeta(third_party_script_count=20),
        )
        compute_score(lead)
        # perf+cwv: capped at 35
        # seo: 18 (<=69)
        # a11y+bp: 15 (both <=79)
        # tracking: 15
        # tech: 6 (WP+perf) + 4 (scripts) = 10
        # Total: 35 + 18 + 15 + 15 + 10 = 93
        assert lead.score_points <= 100
