"""Verification utilities for validating lead audit data integrity."""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("harvester")


@dataclass
class VerifyIssue:
    """A single verification issue."""
    domain: str
    lead_id: str
    severity: str  # "hard" or "soft"
    code: str
    message: str


@dataclass
class VerifyReport:
    """Complete verification report."""
    total_leads: int = 0
    hard_failures: int = 0
    soft_warnings: int = 0
    issues: list[VerifyIssue] = field(default_factory=list)

    def add_issue(self, issue: VerifyIssue) -> None:
        self.issues.append(issue)
        if issue.severity == "hard":
            self.hard_failures += 1
        else:
            self.soft_warnings += 1


def _check_hard_invariants(lead: dict, report: VerifyReport) -> None:
    """Check hard invariants that must be true."""
    domain = lead.get("domain", "unknown")
    lead_id = lead.get("lead_id", "unknown")

    # score_points between 0 and 100
    score_points = lead.get("score_points", 0)
    if not (0 <= score_points <= 100):
        report.add_issue(VerifyIssue(
            domain=domain, lead_id=lead_id, severity="hard",
            code="SCORE_POINTS_RANGE",
            message=f"score_points={score_points} not in 0-100",
        ))

    # score_letter in A/B/C
    score_letter = lead.get("score_letter")
    if score_letter not in ("A", "B", "C", None):
        report.add_issue(VerifyIssue(
            domain=domain, lead_id=lead_id, severity="hard",
            code="SCORE_LETTER_INVALID",
            message=f"score_letter={score_letter} not in A/B/C",
        ))

    # tracking_evidence is dict[str, list[str]]
    tracking_evidence = lead.get("tracking_evidence", {})
    if not isinstance(tracking_evidence, dict):
        report.add_issue(VerifyIssue(
            domain=domain, lead_id=lead_id, severity="hard",
            code="TRACKING_EVIDENCE_TYPE",
            message=f"tracking_evidence is not a dict: {type(tracking_evidence)}",
        ))
    else:
        for k, v in tracking_evidence.items():
            if not isinstance(v, list):
                report.add_issue(VerifyIssue(
                    domain=domain, lead_id=lead_id, severity="hard",
                    code="TRACKING_EVIDENCE_VALUE_TYPE",
                    message=f"tracking_evidence[{k}] is not a list: {type(v)}",
                ))
                break

    # tech_confidence is dict[str, float] with valid keys and values
    tech_confidence = lead.get("tech_confidence", {})
    valid_keys = {"cms", "framework", "ecommerce", "hosting"}
    if not isinstance(tech_confidence, dict):
        report.add_issue(VerifyIssue(
            domain=domain, lead_id=lead_id, severity="hard",
            code="TECH_CONFIDENCE_TYPE",
            message=f"tech_confidence is not a dict: {type(tech_confidence)}",
        ))
    else:
        for k, v in tech_confidence.items():
            if k not in valid_keys:
                report.add_issue(VerifyIssue(
                    domain=domain, lead_id=lead_id, severity="hard",
                    code="TECH_CONFIDENCE_KEY",
                    message=f"tech_confidence has invalid key: {k}",
                ))
            if not isinstance(v, (int, float)) or not (0 <= v <= 1):
                report.add_issue(VerifyIssue(
                    domain=domain, lead_id=lead_id, severity="hard",
                    code="TECH_CONFIDENCE_VALUE",
                    message=f"tech_confidence[{k}]={v} not in 0-1",
                ))

    # html_meta.third_party_script_count >= 0
    html_meta = lead.get("html_meta", {})
    script_count = html_meta.get("third_party_script_count", 0)
    if not isinstance(script_count, int) or script_count < 0:
        report.add_issue(VerifyIssue(
            domain=domain, lead_id=lead_id, severity="hard",
            code="SCRIPT_COUNT_NEGATIVE",
            message=f"third_party_script_count={script_count} < 0",
        ))

    # If status=="failed": score_points==0 and score_letter=="C"
    status = lead.get("status")
    if status == "failed":
        if score_points != 0:
            report.add_issue(VerifyIssue(
                domain=domain, lead_id=lead_id, severity="hard",
                code="FAILED_SCORE_POINTS",
                message=f"status=failed but score_points={score_points}",
            ))
        if score_letter != "C":
            report.add_issue(VerifyIssue(
                domain=domain, lead_id=lead_id, severity="hard",
                code="FAILED_SCORE_LETTER",
                message=f"status=failed but score_letter={score_letter}",
            ))


def _check_soft_warnings(lead: dict, report: VerifyReport) -> None:
    """Check soft warnings that indicate potential issues."""
    domain = lead.get("domain", "unknown")
    lead_id = lead.get("lead_id", "unknown")
    scores = lead.get("scores", {})
    tracking = lead.get("tracking", {})
    tracking_evidence = lead.get("tracking_evidence", {})
    html_meta = lead.get("html_meta", {})
    status = lead.get("status")
    score_letter = lead.get("score_letter")

    # Suspicious: good metrics but not grade C
    perf = scores.get("performance")
    seo = scores.get("seo")
    has_ga4 = tracking.get("ga4", False)
    has_gtm = tracking.get("gtm", False)
    if (perf is not None and perf >= 90 and
        seo is not None and seo >= 95 and
        has_ga4 and has_gtm and
        score_letter != "C"):
        report.add_issue(VerifyIssue(
            domain=domain, lead_id=lead_id, severity="soft",
            code="GOOD_METRICS_NOT_C",
            message=f"perf={perf}, seo={seo}, tracking ok, but letter={score_letter}",
        ))

    # Tag bloat: third_party_script_count >= 50
    script_count = html_meta.get("third_party_script_count", 0)
    if script_count >= 50:
        report.add_issue(VerifyIssue(
            domain=domain, lead_id=lead_id, severity="soft",
            code="TAG_BLOAT",
            message=f"third_party_script_count={script_count} (tag bloat)",
        ))

    # Missing final_url/http_status for status ok
    if status not in ("failed", "partial"):
        if not html_meta.get("final_url"):
            report.add_issue(VerifyIssue(
                domain=domain, lead_id=lead_id, severity="soft",
                code="MISSING_FINAL_URL",
                message="status ok but missing final_url",
            ))
        if html_meta.get("http_status") is None:
            report.add_issue(VerifyIssue(
                domain=domain, lead_id=lead_id, severity="soft",
                code="MISSING_HTTP_STATUS",
                message="status ok but missing http_status",
            ))

    # PSI missing for status ok (should be partial)
    if status not in ("failed", "partial"):
        if perf is None and seo is None:
            report.add_issue(VerifyIssue(
                domain=domain, lead_id=lead_id, severity="soft",
                code="PSI_MISSING_STATUS_OK",
                message="status ok but PSI scores missing",
            ))

    # tracking_evidence exists but tracking boolean false (inconsistency)
    if isinstance(tracking_evidence, dict):
        for tracker_name, evidence_list in tracking_evidence.items():
            if evidence_list and not tracking.get(tracker_name, False):
                report.add_issue(VerifyIssue(
                    domain=domain, lead_id=lead_id, severity="soft",
                    code="EVIDENCE_TRACKING_MISMATCH",
                    message=f"tracking_evidence[{tracker_name}] present but tracking.{tracker_name}=False",
                ))


def verify_leads(leads: list[dict]) -> VerifyReport:
    """Verify a list of lead dicts and return a report."""
    report = VerifyReport(total_leads=len(leads))

    for lead in leads:
        _check_hard_invariants(lead, report)
        _check_soft_warnings(lead, report)

    return report


def verify_file(input_path: Path) -> VerifyReport:
    """Load leads.json and verify."""
    with open(input_path, "r", encoding="utf-8") as f:
        leads = json.load(f)
    return verify_leads(leads)


def save_report(report: VerifyReport, output_path: Path) -> None:
    """Save verification report to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "total_leads": report.total_leads,
        "hard_failures": report.hard_failures,
        "soft_warnings": report.soft_warnings,
        "issues": [
            {
                "domain": i.domain,
                "lead_id": i.lead_id,
                "severity": i.severity,
                "code": i.code,
                "message": i.message,
            }
            for i in report.issues
        ],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def print_verify_summary(report: VerifyReport) -> None:
    """Print verification summary to console."""
    print(f"\nVERIFY: hard failures={report.hard_failures} warnings={report.soft_warnings}")

    if report.issues:
        # Group by domain for cleaner output
        by_domain: dict[str, list[VerifyIssue]] = {}
        for issue in report.issues:
            by_domain.setdefault(issue.domain, []).append(issue)

        # Show top warnings
        print("Issues:")
        count = 0
        for domain, issues in sorted(by_domain.items(), key=lambda x: -len(x[1])):
            for issue in issues[:2]:  # Max 2 per domain
                prefix = "ERROR" if issue.severity == "hard" else "WARN"
                print(f"  [{prefix}] {domain}: {issue.message}")
                count += 1
                if count >= 10:
                    remaining = len(report.issues) - count
                    if remaining > 0:
                        print(f"  ... and {remaining} more issues")
                    return


def run_verify_command(input_path: str, report_path: str | None = None) -> int:
    """Run verification as CLI command. Returns exit code."""
    input_file = Path(input_path)
    if not input_file.exists():
        print(f"ERROR: Input file not found: {input_path}")
        return 1

    report = verify_file(input_file)

    if report_path:
        save_report(report, Path(report_path))
        print(f"Report saved to: {report_path}")

    print_verify_summary(report)

    # Exit 1 if hard failures, 0 otherwise
    return 1 if report.hard_failures > 0 else 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Verify leads.json integrity")
    parser.add_argument("--input", "-i", required=True, help="Path to leads.json")
    parser.add_argument("--report", "-r", help="Path to save report JSON")
    args = parser.parse_args()
    sys.exit(run_verify_command(args.input, args.report))
