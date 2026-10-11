# Runbook: real posting for pilot users (Q-42)

Without a posting grant every post stops before Post (dry run). A grant lets **one Workspace** post for
real on **one TikTok account**, up to N posts until a date, with visibility **"only you"**.

## Before the first grant
1. The customer's PC runs **Agent 0.4.0 or later**. Older Agents never receive a live post: they don't
   send `can_post_live`, so they keep getting dry runs.
2. The phone is on the web's **โทรศัพท์** page with the TikTok account filled in (`expected_account`).
   The grant's account must be the same handle.
3. The phone/TikTok version is one we tested (`agent/compat.py`). Anything else stops with
   `UNSUPPORTED_DEVICE` before TikTok is touched.
4. A dry-run post on that phone went through (file in the Gallery).

## Give a grant (admin only)
Admin → find the Workspace → **เปิด** → **สิทธิ์โพสต์จริง**. Fill in the TikTok account, the most posts
allowed, how many days it lasts (1–90) and a reason (≥ 10 characters). The grant is audited
(`admin.posting_grant.create`). The customer sees it on the **โทรศัพท์** page.

## What happens on a post
- **Claim:** the post goes out live only if a grant for that phone's account is active and has room
  after the live posts already handed out. Otherwise it is a dry run.
- **Agent:** checks the account on screen, sets "only you", types the exact caption plus the attempt
  marker, then reports SUBMITTING.
- **Server at SUBMITTING:** checks the approval again, then locks the grant and counts **one use**.
  If the grant was revoked, expired or used up, the post becomes `NEEDS_ACTION` (`POSTING_GRANT_*`)
  and Post is never pressed.
- **Post:** the Agent presses Post once, then verifies by the marker on the private tab.
  `VERIFIED_SUCCESS` needs that evidence. Anything unsure after Post is `UNKNOWN`. It is never retried
  and needs a person to resolve it.

A use is counted per submit attempt. A post that was submitted but turns out not published still
used one. So the number of real posts can never exceed the grant.

## Stop real posting
Revoke the grant on the Admin page (with a reason). Posts already past SUBMITTING finish and are
verified. Every later post is refused at SUBMITTING or goes out as a dry run.

## Not available yet
- **Public visibility:** needs a PO decision and a public step tested on the real phone. The server
  refuses any visibility other than `only_me`.
- **Turning posting on without a grant:** there is no env value, setting or CLI command for it.
