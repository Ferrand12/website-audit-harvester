"""Tests for verification utilities."""

import json
import pytest
from pathlib import Path

from src.utils.verify import (
    VerifyReport,
    VerifyIssue,
    verify_leads,
    verify_file,
    save_report,
)


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

def _make_lead(
    domain="example.com",
    score_points=50,
    score_letter="B",
    status="complete",
    tracking_evidence=None,
    tech_confidence=None,
    tracking=None,
    scores=None,
    html_meta=None,
):
    """Create a minimal valid lead dict."""
    return {
        "lead_id": "test-123",
        "url": f"https://{domain}",
        "domain": domain,
        "status": status,
        "score_points": score_points,
        "score_letter": score_letter,
        "tracking_evidence": tracking_evidence or {},
        "tech_confidence": tech_confidence or {"cms": 0.0, "framework": 0.0, "ecommerce": 0.0, "hosting": 0.0},
        "tracking": tracking or {"ga4": True, "gtm": True},
        "scores": scores or {"performance": 70, "seo": 80, "accessibility": 85, "best_practices": 90},
        "html_meta": html_meta or {"http_status": 200, "final_url": f"https://{domain}/", "third_party_script_count": 5},
    }


# ---------------------------------------------------------------------------
# Hard Invariant Tests
# ---------------------------------------------------------------------------

class TestHardInvariants:
    """Test hard invariant validation."""

    def test_valid_lead_no_issues(self):
        """Valid lead should have no hard failures."""
        lead = _make_lead()
        report = verify_leads([lead])

        assert report.hard_failures == 0

    def test_score_points_over_100(self):
        """score_points > 100 should trigger hard failure."""
        lead = _make_lead(score_points=150)
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "SCORE_POINTS_RANGE" for i in report.issues)

    def test_score_points_negative(self):
        """score_points < 0 should trigger hard failure."""
        lead = _make_lead(score_points=-5)
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "SCORE_POINTS_RANGE" for i in report.issues)

    def test_invalid_score_letter(self):
        """score_letter not in A/B/C should trigger hard failure."""
        lead = _make_lead(score_letter="D")
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "SCORE_LETTER_INVALID" for i in report.issues)

    def test_tracking_evidence_not_dict(self):
        """tracking_evidence not dict should trigger hard failure."""
        lead = _make_lead(tracking_evidence=["not", "a", "dict"])
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "TRACKING_EVIDENCE_TYPE" for i in report.issues)

    def test_tracking_evidence_value_not_list(self):
        """tracking_evidence values not list should trigger hard failure."""
        lead = _make_lead(tracking_evidence={"gtm": "not-a-list"})
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "TRACKING_EVIDENCE_VALUE_TYPE" for i in report.issues)

    def test_tracking_evidence_valid_shape(self):
        """Valid tracking_evidence shape should pass."""
        lead = _make_lead(tracking_evidence={"gtm": ["GTM-ABC"], "ga4": ["G-123"]})
        report = verify_leads([lead])

        assert not any(i.code.startswith("TRACKING_EVIDENCE") for i in report.issues if i.severity == "hard")

    def test_tech_confidence_not_dict(self):
        """tech_confidence not dict should trigger hard failure."""
        lead = _make_lead(tech_confidence=0.5)
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "TECH_CONFIDENCE_TYPE" for i in report.issues)

    def test_tech_confidence_invalid_key(self):
        """tech_confidence with invalid key should trigger hard failure."""
        lead = _make_lead(tech_confidence={"invalid_key": 0.5})
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "TECH_CONFIDENCE_KEY" for i in report.issues)

    def test_tech_confidence_value_out_of_range(self):
        """tech_confidence value > 1 should trigger hard failure."""
        lead = _make_lead(tech_confidence={"cms": 1.5})
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "TECH_CONFIDENCE_VALUE" for i in report.issues)

    def test_tech_confidence_negative_value(self):
        """tech_confidence value < 0 should trigger hard failure."""
        lead = _make_lead(tech_confidence={"cms": -0.1})
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "TECH_CONFIDENCE_VALUE" for i in report.issues)

    def test_negative_script_count(self):
        """Negative third_party_script_count should trigger hard failure."""
        lead = _make_lead(html_meta={"third_party_script_count": -1})
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "SCRIPT_COUNT_NEGATIVE" for i in report.issues)

    def test_failed_status_nonzero_points(self):
        """status=failed with nonzero score_points should trigger hard failure."""
        lead = _make_lead(status="failed", score_points=50, score_letter="C")
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "FAILED_SCORE_POINTS" for i in report.issues)

    def test_failed_status_not_c_grade(self):
        """status=failed with letter != C should trigger hard failure."""
        lead = _make_lead(status="failed", score_points=0, score_letter="B")
        report = verify_leads([lead])

        assert report.hard_failures >= 1
        assert any(i.code == "FAILED_SCORE_LETTER" for i in report.issues)

    def test_failed_status_valid(self):
        """status=failed with 0 points and C grade should pass."""
        lead = _make_lead(status="failed", score_points=0, score_letter="C")
        report = verify_leads([lead])

        assert not any(i.code in ("FAILED_SCORE_POINTS", "FAILED_SCORE_LETTER") for i in report.issues)


# ---------------------------------------------------------------------------
# Soft Warning Tests
# ---------------------------------------------------------------------------

class TestSoftWarnings:
    """Test soft warning detection."""

    def test_tag_bloat_warning(self):
        """script_count >= 50 should trigger tag bloat warning."""
        lead = _make_lead(html_meta={"third_party_script_count": 55, "final_url": "https://example.com/"})
        report = verify_leads([lead])

        assert report.soft_warnings >= 1
        assert any(i.code == "TAG_BLOAT" for i in report.issues)

    def test_missing_final_url_warning(self):
        """Missing final_url on complete status should warn."""
        lead = _make_lead(html_meta={"http_status": 200, "third_party_script_count": 5})
        report = verify_leads([lead])

        assert any(i.code == "MISSING_FINAL_URL" for i in report.issues)

    def test_missing_http_status_warning(self):
        """Missing http_status on complete status should warn."""
        lead = _make_lead(html_meta={"final_url": "https://example.com/", "third_party_script_count": 5})
        report = verify_leads([lead])

        assert any(i.code == "MISSING_HTTP_STATUS" for i in report.issues)

    def test_evidence_tracking_mismatch(self):
        """Evidence present but tracking bool false should warn."""
        lead = _make_lead(
            tracking_evidence={"gtm": ["GTM-ABC"]},
            tracking={"ga4": True, "gtm": False},  # gtm=False but evidence present
        )
        report = verify_leads([lead])

        assert any(i.code == "EVIDENCE_TRACKING_MISMATCH" for i in report.issues)

    def test_no_evidence_mismatch_when_consistent(self):
        """No warning when evidence matches tracking bools."""
        lead = _make_lead(
            tracking_evidence={"gtm": ["GTM-ABC"]},
            tracking={"ga4": True, "gtm": True},
        )
        report = verify_leads([lead])

        assert not any(i.code == "EVIDENCE_TRACKING_MISMATCH" for i in report.issues)

    def test_good_metrics_not_c_warning(self):
        """Good metrics (perf>=90, seo>=95, tracking ok) with B/A grade should warn."""
        lead = _make_lead(
            score_letter="A",  # Should probably be C with good metrics
            scores={"performance": 95, "seo": 98, "accessibility": 90, "best_practices": 95},
            tracking={"ga4": True, "gtm": True},
        )
        report = verify_leads([lead])

        assert any(i.code == "GOOD_METRICS_NOT_C" for i in report.issues)


# ---------------------------------------------------------------------------
# Report Tests
# ---------------------------------------------------------------------------

class TestVerifyReport:
    """Test report functionality."""

    def test_add_hard_issue(self):
        """Adding hard issue should increment hard_failures."""
        report = VerifyReport()
        issue = VerifyIssue(
            domain="test.com",
            lead_id="123",
            severity="hard",
            code="TEST",
            message="test",
        )
        report.add_issue(issue)

        assert report.hard_failures == 1
        assert report.soft_warnings == 0

    def test_add_soft_issue(self):
        """Adding soft issue should increment soft_warnings."""
        report = VerifyReport()
        issue = VerifyIssue(
            domain="test.com",
            lead_id="123",
            severity="soft",
            code="TEST",
            message="test",
        )
        report.add_issue(issue)

        assert report.soft_warnings == 1
        assert report.hard_failures == 0

    def test_total_leads_count(self):
        """Report should track total leads count."""
        leads = [_make_lead(domain=f"{i}.com") for i in range(5)]
        report = verify_leads(leads)

        assert report.total_leads == 5

    def test_save_report(self, tmp_path):
        """Report should save as JSON."""
        lead = _make_lead(score_points=150)  # Invalid
        report = verify_leads([lead])

        output_path = tmp_path / "report.json"
        save_report(report, output_path)

        assert output_path.exists()
        with open(output_path) as f:
            data = json.load(f)

        assert data["total_leads"] == 1
        assert data["hard_failures"] >= 1
        assert len(data["issues"]) >= 1


# ---------------------------------------------------------------------------
# File Verification Tests
# ---------------------------------------------------------------------------

class TestVerifyFile:
    """Test file-based verification."""

    def test_verify_file(self, tmp_path):
        """Should load and verify leads from file."""
        leads_file = tmp_path / "leads.json"
        leads_data = [
            _make_lead(domain="good.com"),
            _make_lead(domain="bad.com", score_points=150),
        ]
        with open(leads_file, "w") as f:
            json.dump(leads_data, f)

        report = verify_file(leads_file)

        assert report.total_leads == 2
        assert report.hard_failures >= 1
