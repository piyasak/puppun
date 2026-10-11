# Pilot support log (G7-01, G7-05)

Fill in one row per pilot user and one row per support request. The server-side numbers (minutes to first Agent / phone / job, job and post outcomes) come from Admin → **รายงาน Pilot (G7)**; this log adds what the server cannot see: where people got stuck and how much support time it took.

Rules: no passwords, pairing codes, tokens or payment details here. Use the punpun username, not personal contact details. Do not drop a user or a request because it went badly (PRD P7.4).

## Onboarding (G7-01: ≥ 10 new users, ≥ 80 % started within 20 minutes)

| # | Username | Date | PC (Windows version) | Phone model / Android | Minutes to first job (from the report) | Started within 20 min? | Got stuck at (guide step) | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |

## Support requests (G7-05: support load)

| # | Date/time | Username | Guide step / area | Problem (what the user saw) | Severity (Critical/High/Medium/Low) | Minutes spent | Resolved? | Defect / follow-up |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |

## Monthly summary (for G7-05)

| Month | Pilot users | Requests | Support minutes total | Minutes per user | Top 3 problems | Actual Render + Supabase bill (THB) vs `docs/cost-model.md` |
|---|---|---|---|---|---|---|
| | | | | | | |

Severity follows the Defects list in `docs/uat/p7-uat.md`: Critical/High (duplicate post, wrong account, tenant leak, wrong money/rights) block G7-03 until fixed.
