from pathlib import Path

import pytest

from tools.check_gate import REQUIRED_CHECKS, main, parse_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def record(rows, technical="No", signoff="No", decision="No", next_allowed="No", approver="<real reviewer>"):
    lines = [
        "# Gate G0",
        "| Check ID | Yes/No | Reason | Evidence | Remediation | Owner | Due date |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [f"| {cid} | {res} | {reason} | {ev} | — | PO | TBD |" for cid, res, reason, ev in rows]
    lines += [
        f"Technical required checks all Yes: {technical}",
        f"Required human sign-off recorded: {signoff}",
        f"Phase gate decision: {decision}",
        f"Next phase allowed: {next_allowed}",
        f"Approver: {approver}",
    ]
    return "\n".join(lines)


def all_rows(result="No", evidence="—", reason="Not tested"):
    return [(f"G0-{i:02d}", result, reason, evidence) for i in range(1, 6)]


def test_required_checks_total_47():
    assert sum(REQUIRED_CHECKS.values()) == 47


def test_all_no_record_is_valid_and_not_passed():
    report = parse_gate(record(all_rows()), 0, REPO_ROOT)
    assert report.errors == []
    assert not report.passed


def test_yes_without_evidence_is_invalid():
    rows = all_rows()
    rows[0] = ("G0-01", "Yes", "Approved", "—")
    report = parse_gate(record(rows), 0, REPO_ROOT)
    assert "G0-01: Yes without evidence" in report.errors


def test_yes_citing_missing_file_is_invalid():
    rows = all_rows()
    rows[0] = ("G0-01", "Yes", "Approved", "`docs/does-not-exist.md`")
    report = parse_gate(record(rows), 0, REPO_ROOT)
    assert any("evidence path does not exist" in e for e in report.errors)


def test_yes_citing_existing_file_with_anchor_is_valid():
    rows = all_rows()
    rows[0] = ("G0-01", "Yes", "Reviewed", "`PRD_CLAUDE_CODE.md#a-start-here`")
    report = parse_gate(record(rows), 0, REPO_ROOT)
    assert report.errors == []


def test_missing_and_duplicate_check_ids():
    rows = all_rows()[:4] + [("G0-01", "No", "Not tested", "—")]
    errors = parse_gate(record(rows), 0, REPO_ROOT).errors
    assert "G0-05: missing" in errors
    assert "G0-01: listed 2 times" in errors


def test_decision_yes_requires_signoff_and_all_checks():
    rows = all_rows("Yes", "`PRD_CLAUDE_CODE.md`", "Verified")
    unsigned = parse_gate(record(rows, technical="Yes", decision="Yes"), 0, REPO_ROOT)
    assert any("requires every check Yes and a recorded sign-off" in e for e in unsigned.errors)


def test_signoff_requires_real_approver():
    rows = all_rows("Yes", "`PRD_CLAUDE_CODE.md`", "Verified")
    report = parse_gate(record(rows, technical="Yes", signoff="Yes", decision="Yes"), 0, REPO_ROOT)
    assert "sign-off recorded as Yes but no approver is named" in report.errors


def test_fully_supported_gate_passes():
    rows = all_rows("Yes", "`PRD_CLAUDE_CODE.md`", "Verified")
    text = record(rows, technical="Yes", signoff="Yes", decision="Yes", next_allowed="Yes", approver="Jane PO 2026-10-07")
    report = parse_gate(text, 0, REPO_ROOT)
    assert report.errors == []
    assert report.passed


def test_technical_summary_must_match_rows():
    report = parse_gate(record(all_rows(), technical="Yes"), 0, REPO_ROOT)
    assert any("check rows disagree" in e for e in report.errors)


@pytest.mark.parametrize("phase", sorted(REQUIRED_CHECKS))
def test_repository_gate_records_are_valid(phase):
    """Every committed gate record must at least be internally consistent."""
    assert main([str(phase)]) in (0, 1)
