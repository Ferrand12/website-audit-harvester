"""Tests for export utilities."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.exporters.export import (
    CSV_COLUMNS,
    MAX_TOP_ITEMS,
    _flatten,
    _opportunities_json,
    _opportunities_titles,
    _pains_summary,
    export_csv,
    export_json,
)
from src.models.lead_audit import (
    LeadAudit,
    OpportunityItem,
    PainItem,
    PSIScores,
    CWV,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_lead() -> LeadAudit:
    """Create a sample lead with PSI data for testing."""
    lead = LeadAudit.from_url("https://example.com", "mobile")
    lead.status = "complete"
    lead.scores = PSIScores(performance=65, seo=80, accessibility=85, best_practices=90)
    lead.cwv = CWV(lcp_ms=3500, inp_ms=200, cls=0.1, ttfb_ms=500, fcp_ms=1500)
    lead.psi_opportunities = [
        OpportunityItem(id="render-blocking-resources", title="Eliminate render-blocking resources", impact="high"),
        OpportunityItem(id="unused-css-rules", title="Reduce unused CSS", impact="medium"),
        OpportunityItem(id="modern-image-formats", title="Serve images in modern formats", impact="medium"),
        OpportunityItem(id="unused-javascript", title="Reduce unused JavaScript", impact="low"),
    ]
    lead.psi_diagnostics = [
        OpportunityItem(id="dom-size", title="Avoid an excessive DOM size", impact="high"),
        OpportunityItem(id="mainthread-work-breakdown", title="Minimize main-thread work", impact="medium"),
    ]
    return lead


@pytest.fixture
def lead_without_psi() -> LeadAudit:
    """Create a lead without PSI data."""
    lead = LeadAudit.from_url("https://no-psi.example.com", "mobile")
    lead.status = "partial"
    return lead


# ---------------------------------------------------------------------------
# CSV Column Tests
# ---------------------------------------------------------------------------

class TestCSVColumns:
    """Test CSV column definitions."""

    def test_csv_columns_include_psi_opportunities_titles(self):
        """CSV columns should include psi_opportunities_titles."""
        assert "psi_opportunities_titles" in CSV_COLUMNS

    def test_csv_columns_include_psi_diagnostics_titles(self):
        """CSV columns should include psi_diagnostics_titles."""
        assert "psi_diagnostics_titles" in CSV_COLUMNS

    def test_csv_columns_include_psi_opportunities_top3(self):
        """CSV columns should include psi_opportunities_top3."""
        assert "psi_opportunities_top3" in CSV_COLUMNS

    def test_csv_columns_include_psi_diagnostics_top3(self):
        """CSV columns should include psi_diagnostics_top3."""
        assert "psi_diagnostics_top3" in CSV_COLUMNS

    def test_csv_columns_order_is_stable(self):
        """CSV columns should maintain consistent order."""
        # Key columns should appear in expected sections
        lead_id_idx = CSV_COLUMNS.index("lead_id")
        score_letter_idx = CSV_COLUMNS.index("score_letter")
        psi_titles_idx = CSV_COLUMNS.index("psi_opportunities_titles")

        assert lead_id_idx < score_letter_idx < psi_titles_idx

    def test_csv_columns_psi_before_html_meta(self):
        """PSI columns should appear before HTML meta columns."""
        psi_idx = CSV_COLUMNS.index("psi_opportunities_titles")
        html_idx = CSV_COLUMNS.index("html_meta.http_status")
        assert psi_idx < html_idx


# ---------------------------------------------------------------------------
# Opportunities Formatting Tests
# ---------------------------------------------------------------------------

class TestOpportunitiesTitles:
    """Test pipe-separated titles formatting."""

    def test_formats_titles_pipe_separated(self, sample_lead):
        """Should format titles with pipe separator."""
        result = _opportunities_titles(sample_lead.psi_opportunities)
        assert "|" in result
        titles = result.split("|")
        assert titles[0] == "Eliminate render-blocking resources"
        assert titles[1] == "Reduce unused CSS"
        assert titles[2] == "Serve images in modern formats"

    def test_limits_to_max_items(self, sample_lead):
        """Should limit to MAX_TOP_ITEMS (3) items."""
        result = _opportunities_titles(sample_lead.psi_opportunities)
        titles = result.split("|")
        assert len(titles) == MAX_TOP_ITEMS
        # Fourth item should not be included
        assert "Reduce unused JavaScript" not in result

    def test_empty_list_returns_empty_string(self):
        """Empty list should return empty string."""
        result = _opportunities_titles([])
        assert result == ""

    def test_single_item_no_separator(self):
        """Single item should have no separator."""
        items = [OpportunityItem(id="test", title="Test Title", impact="high")]
        result = _opportunities_titles(items)
        assert result == "Test Title"
        assert "|" not in result

    def test_custom_max_items(self, sample_lead):
        """Should respect custom max_items parameter."""
        result = _opportunities_titles(sample_lead.psi_opportunities, max_items=2)
        titles = result.split("|")
        assert len(titles) == 2


class TestOpportunitiesJson:
    """Test JSON array formatting."""

    def test_formats_as_json_array(self, sample_lead):
        """Should format as valid JSON array."""
        result = _opportunities_json(sample_lead.psi_opportunities)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == MAX_TOP_ITEMS

    def test_json_contains_required_fields(self, sample_lead):
        """JSON items should contain id, title, impact."""
        result = _opportunities_json(sample_lead.psi_opportunities)
        parsed = json.loads(result)
        for item in parsed:
            assert "id" in item
            assert "title" in item
            assert "impact" in item

    def test_json_values_match_input(self, sample_lead):
        """JSON values should match input items."""
        result = _opportunities_json(sample_lead.psi_opportunities)
        parsed = json.loads(result)
        assert parsed[0]["id"] == "render-blocking-resources"
        assert parsed[0]["title"] == "Eliminate render-blocking resources"
        assert parsed[0]["impact"] == "high"

    def test_limits_to_max_items(self, sample_lead):
        """Should limit to MAX_TOP_ITEMS items."""
        result = _opportunities_json(sample_lead.psi_opportunities)
        parsed = json.loads(result)
        assert len(parsed) == MAX_TOP_ITEMS

    def test_empty_list_returns_empty_array(self):
        """Empty list should return '[]'."""
        result = _opportunities_json([])
        assert result == "[]"
        parsed = json.loads(result)
        assert parsed == []

    def test_json_is_compact(self, sample_lead):
        """JSON should be compact (no extra whitespace)."""
        result = _opportunities_json(sample_lead.psi_opportunities)
        # Compact format uses colon without space after
        assert ": " not in result
        # And comma without space after
        assert ", " not in result

    def test_json_preserves_unicode(self):
        """JSON should preserve Unicode characters."""
        items = [OpportunityItem(id="test", title="Réduire le CSS inutilisé", impact="high")]
        result = _opportunities_json(items)
        assert "Réduire" in result
        parsed = json.loads(result)
        assert parsed[0]["title"] == "Réduire le CSS inutilisé"

    def test_stable_order(self, sample_lead):
        """Items should maintain input order."""
        result = _opportunities_json(sample_lead.psi_opportunities)
        parsed = json.loads(result)
        assert parsed[0]["id"] == "render-blocking-resources"
        assert parsed[1]["id"] == "unused-css-rules"
        assert parsed[2]["id"] == "modern-image-formats"


# ---------------------------------------------------------------------------
# CSV Export Tests
# ---------------------------------------------------------------------------

class TestExportCSV:
    """Test CSV export functionality."""

    def test_creates_file_with_header(self, tmp_path, sample_lead):
        """Should create CSV file with header row."""
        csv_path = tmp_path / "leads.csv"
        export_csv([sample_lead], csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            assert "psi_opportunities_titles" in reader.fieldnames
            assert "psi_diagnostics_titles" in reader.fieldnames
            assert "psi_opportunities_top3" in reader.fieldnames
            assert "psi_diagnostics_top3" in reader.fieldnames

    def test_populates_opportunities_titles(self, tmp_path, sample_lead):
        """Should populate psi_opportunities_titles column."""
        csv_path = tmp_path / "leads.csv"
        export_csv([sample_lead], csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            assert row["psi_opportunities_titles"] == "Eliminate render-blocking resources|Reduce unused CSS|Serve images in modern formats"

    def test_populates_diagnostics_titles(self, tmp_path, sample_lead):
        """Should populate psi_diagnostics_titles column."""
        csv_path = tmp_path / "leads.csv"
        export_csv([sample_lead], csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            assert row["psi_diagnostics_titles"] == "Avoid an excessive DOM size|Minimize main-thread work"

    def test_populates_opportunities_top3_json(self, tmp_path, sample_lead):
        """Should populate psi_opportunities_top3 as valid JSON."""
        csv_path = tmp_path / "leads.csv"
        export_csv([sample_lead], csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            parsed = json.loads(row["psi_opportunities_top3"])
            assert len(parsed) == 3
            assert parsed[0]["id"] == "render-blocking-resources"

    def test_populates_diagnostics_top3_json(self, tmp_path, sample_lead):
        """Should populate psi_diagnostics_top3 as valid JSON."""
        csv_path = tmp_path / "leads.csv"
        export_csv([sample_lead], csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            parsed = json.loads(row["psi_diagnostics_top3"])
            assert len(parsed) == 2  # Only 2 diagnostics in sample
            assert parsed[0]["id"] == "dom-size"

    def test_handles_missing_psi_data(self, tmp_path, lead_without_psi):
        """Should handle leads without PSI data gracefully."""
        csv_path = tmp_path / "leads.csv"
        export_csv([lead_without_psi], csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            # Titles should be empty string
            assert row["psi_opportunities_titles"] == ""
            assert row["psi_diagnostics_titles"] == ""
            # JSON should be empty array
            assert row["psi_opportunities_top3"] == "[]"
            assert row["psi_diagnostics_top3"] == "[]"

    def test_utf8_bom_for_excel(self, tmp_path, sample_lead):
        """Should use UTF-8 BOM for Excel compatibility."""
        csv_path = tmp_path / "leads.csv"
        export_csv([sample_lead], csv_path)

        with open(csv_path, "rb") as f:
            first_bytes = f.read(3)
            assert first_bytes == b"\xef\xbb\xbf"  # UTF-8 BOM

    def test_multiple_leads(self, tmp_path, sample_lead, lead_without_psi):
        """Should export multiple leads correctly."""
        csv_path = tmp_path / "leads.csv"
        export_csv([sample_lead, lead_without_psi], csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 2
            # First lead has PSI data
            assert rows[0]["psi_opportunities_titles"] != ""
            # Second lead doesn't
            assert rows[1]["psi_opportunities_titles"] == ""

    def test_column_order_preserved(self, tmp_path, sample_lead):
        """CSV column order should match CSV_COLUMNS."""
        csv_path = tmp_path / "leads.csv"
        export_csv([sample_lead], csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == CSV_COLUMNS


# ---------------------------------------------------------------------------
# JSON Export Tests
# ---------------------------------------------------------------------------

class TestExportJSON:
    """Test JSON export functionality."""

    def test_creates_valid_json(self, tmp_path, sample_lead):
        """Should create valid JSON file."""
        json_path = tmp_path / "leads.json"
        export_json([sample_lead], json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert isinstance(data, list)
            assert len(data) == 1

    def test_includes_psi_opportunities(self, tmp_path, sample_lead):
        """JSON should include full psi_opportunities."""
        json_path = tmp_path / "leads.json"
        export_json([sample_lead], json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            lead = data[0]
            assert "psi_opportunities" in lead
            assert len(lead["psi_opportunities"]) == 4  # All items, not just top 3

    def test_includes_psi_diagnostics(self, tmp_path, sample_lead):
        """JSON should include full psi_diagnostics."""
        json_path = tmp_path / "leads.json"
        export_json([sample_lead], json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            lead = data[0]
            assert "psi_diagnostics" in lead
            assert len(lead["psi_diagnostics"]) == 2


# ---------------------------------------------------------------------------
# Helper Function Tests
# ---------------------------------------------------------------------------

class TestPainsSummary:
    """Test pains summary formatting."""

    def test_formats_pains_summary(self):
        """Should format pains as semicolon-separated summary."""
        lead = LeadAudit.from_url("https://example.com", "mobile")
        lead.pains = [
            PainItem(pain_id="slow_mobile", severity="high", business_impact="Lost users", proof="LCP > 4s"),
            PainItem(pain_id="seo_weak", severity="medium", business_impact="Low rankings", proof="SEO < 70"),
        ]
        result = _pains_summary(lead)
        assert result == "slow_mobile(high); seo_weak(medium)"

    def test_empty_pains_returns_empty(self):
        """Empty pains should return empty string."""
        lead = LeadAudit.from_url("https://example.com", "mobile")
        result = _pains_summary(lead)
        assert result == ""


class TestFlatten:
    """Test dictionary flattening."""

    def test_flattens_nested_dict(self):
        """Should flatten nested dictionaries."""
        d = {"a": {"b": 1, "c": 2}}
        result = _flatten(d)
        assert result["a.b"] == 1
        assert result["a.c"] == 2

    def test_lists_become_json(self):
        """Lists should become JSON strings."""
        d = {"items": ["a", "b", "c"]}
        result = _flatten(d)
        assert result["items"] == '["a", "b", "c"]'

    def test_empty_list_becomes_empty_string(self):
        """Empty lists should become empty string."""
        d = {"items": []}
        result = _flatten(d)
        assert result["items"] == ""
