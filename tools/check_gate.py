"""Validate an evidence-based gate record (docs/gates/Gn.md).

The tool never decides that a gate passes. It checks that what a record claims
is supported by the record itself:

* every required check ID for the gate is present exactly once, Yes or No;
* a Yes check cites evidence, and every repository path it cites exists;
* the summary lines agree with the check rows and the recorded sign-off;
* a sign-off is only "Yes" when a real approver is named.

Exit codes: 0 = valid record and gate decision Yes; 1 = valid record, gate not
passed; 2 = invalid record (malformed, or a Yes that the evidence does not support).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Number of mandatory checks per gate, from PRD section O.11 (47 in total).
REQUIRED_CHECKS = {0: 5, 1: 6, 2: 5, 3: 5, 4: 5, 5: 6, 6: 5, 7: 5, 8: 5}

SUMMARY_KEYS = (
    "Technical required checks all Yes",
    "Required human sign-off recorded",
    "Phase gate decision",
    "Next phase allowed",
)

PLACEHOLDER = re.compile(r"^(|—|-|tbd|none|n/a|<.*>)$", re.IGNORECASE)
PATH_TOKEN = re.compile(r"`([^`]+)`")


@dataclass
class CheckRow:
    check_id: str
    result: str
    reason: str
    evidence: str


@dataclass
class GateReport:
    gate: int
    errors: list[str] = field(default_factory=list)
    checks: list[CheckRow] = field(default_factory=list)
    summary: dict[str, str] = field(default_factory=dict)
    approver: str = ""

    @property
    def all_yes(self) -> bool:
        return bool(self.checks) and all(c.result == "Yes" for c in self.checks)

    @property
    def passed(self) -> bool:
        return not self.errors and self.summary.get("Phase gate decision") == "Yes"


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _evidence_paths(evidence: str) -> list[str]:
    """Repository paths cited in backticks, ignoring URLs and anchors."""
    paths = []
    for token in PATH_TOKEN.findall(evidence):
        if "://" in token:
            continue
        paths.append(token.split("#", 1)[0].split(":", 1)[0])
    return paths


def parse_gate(text: str, gate: int, repo_root: Path = REPO_ROOT) -> GateReport:
    report = GateReport(gate=gate)
    header: list[str] | None = None
    id_pattern = re.compile(rf"^G{gate}-\d\d$")

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = _split_row(stripped)
            if cells and cells[0] == "Check ID":
                header = [c.lower() for c in cells]
                continue
            if header is None or not cells or not id_pattern.match(cells[0]):
                continue
            row = dict(zip(header, cells))
            report.checks.append(
                CheckRow(
                    check_id=cells[0],
                    result=row.get("yes/no", ""),
                    reason=row.get("reason", ""),
                    evidence=row.get("evidence", ""),
                )
            )
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        if key in SUMMARY_KEYS:
            report.summary[key] = value.strip()
        elif key == "Approver":
            report.approver = value.strip()

    _validate(report, repo_root)
    return report


def _validate(report: GateReport, repo_root: Path) -> None:
    errors = report.errors
    gate = report.gate
    expected = REQUIRED_CHECKS[gate]

    ids = [c.check_id for c in report.checks]
    expected_ids = [f"G{gate}-{i:02d}" for i in range(1, expected + 1)]
    for check_id in expected_ids:
        count = ids.count(check_id)
        if count == 0:
            errors.append(f"{check_id}: missing")
        elif count > 1:
            errors.append(f"{check_id}: listed {count} times")
    for check_id in sorted(set(ids) - set(expected_ids)):
        errors.append(f"{check_id}: not a required check for G{gate}")

    for check in report.checks:
        if check.result not in ("Yes", "No"):
            errors.append(f"{check.check_id}: result must be Yes or No, got {check.result!r}")
            continue
        if not check.reason or PLACEHOLDER.match(check.reason):
            errors.append(f"{check.check_id}: reason is required")
        if check.result == "Yes":
            if PLACEHOLDER.match(check.evidence):
                errors.append(f"{check.check_id}: Yes without evidence")
            for path in _evidence_paths(check.evidence):
                if not (repo_root / path).exists():
                    errors.append(f"{check.check_id}: evidence path does not exist: {path}")

    for key in SUMMARY_KEYS:
        if report.summary.get(key) not in ("Yes", "No"):
            errors.append(f"summary '{key}' must be Yes or No")
    if errors:
        return

    technical = report.summary["Technical required checks all Yes"]
    if technical != ("Yes" if report.all_yes else "No"):
        errors.append(f"summary says technical checks all Yes = {technical}, check rows disagree")

    signoff = report.summary["Required human sign-off recorded"]
    if signoff == "Yes" and PLACEHOLDER.match(report.approver):
        errors.append("sign-off recorded as Yes but no approver is named")

    decision = report.summary["Phase gate decision"]
    if decision == "Yes" and not (report.all_yes and signoff == "Yes"):
        errors.append("phase gate decision Yes requires every check Yes and a recorded sign-off")

    if report.summary["Next phase allowed"] == "Yes" and decision != "Yes":
        errors.append("next phase allowed Yes requires phase gate decision Yes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", type=int, choices=sorted(REQUIRED_CHECKS))
    parser.add_argument("--gates-dir", type=Path, default=REPO_ROOT / "docs" / "gates")
    args = parser.parse_args(argv)
    # Gate records are Thai/Unicode; legacy Windows consoles (e.g. cp874) cannot encode
    # every character, and a crash there would exit 1 and look like "gate not passed".
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    path = args.gates_dir / f"G{args.phase}.md"
    if not path.exists():
        print(f"G{args.phase}: record not found at {path}")
        return 2
    report = parse_gate(path.read_text(encoding="utf-8"), args.phase)

    yes = sum(c.result == "Yes" for c in report.checks)
    print(f"G{args.phase}: {yes}/{REQUIRED_CHECKS[args.phase]} checks Yes")
    for check in report.checks:
        print(f"  {check.check_id}  {check.result:<3}  {check.reason}")
    if report.errors:
        print("INVALID record:")
        for error in report.errors:
            print(f"  - {error}")
        return 2
    print(f"Phase gate decision: {report.summary['Phase gate decision']}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
