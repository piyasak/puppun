# P7.1 — Critical UAT cases T01–T25 (PRD §O.13)

Run on 2026-10-09 against the working tree after `45df1bc`.
- **Machine:** Windows 11 QA PC.
- **Services:** API + Postgres 16 from compose (throwaway DB per run), simulated Agents over real HTTP, and the web app on local Supabase.
- **Commands:**
  - `py tasks.py test-integration`: 213 passed, 8 opt-in skipped.
  - `py tasks.py test-unit`: 167 passed.
  - `py tasks.py test-e2e`: 10 passed.
- **Evidence sources:**
  - Automated tests validate logic, not live integration (CLAUDE.md).
  - Real-device or real-source evidence is listed only where it was actually run, with the date.
- **Not a pilot:** this is a regression run on one PC. P7.2 (10 users), P7.3 (50 + 50 eligible runs) and the pilot itself need G2 = Yes and D07 (Q-24, Q-31).

| Test | Case | Result | Automated evidence | Live evidence |
|---|---|---|---|---|
| T01 | A's Job/Device/Clip called by B | Pass | `services/api/tests/test_uat.py::test_t01…` sweeps **every** route with an id: 25 web routes and 3 Agent routes. B gets exactly what a missing id gets (same status and code), and none of A's data changes. Media needs A's signature; a forged one looks missing. Also `test_tenant_isolation.py`, `test_clips.py::test_clips_are_tenant_scoped` | — |
| T02 | Token with the wrong username | Pass | `test_agent_sessions.py::test_wrong_username_unknown_and_revoked_tokens_look_the_same`, `test_agent_tokens.py::test_verify_accepts_owner_and_rejects_everything_else` | — |
| T03 | Same Agent reconnects 20 times | Pass | `test_agent_sessions.py::test_reconnect_twenty_times_keeps_one_registration`, `test_agent_client_http.py::test_restart_and_reconnect_twenty_times_over_http` | — |
| T04 | Two processes with one installation_id | Pass | `test_agent_sessions.py::test_second_process_with_same_installation_fences_the_first`, `test_agent_client_http.py::test_copied_install_running_twice_is_fenced_over_http` | — |
| T05 | Client changes its Environment | Pass | `test_agent_sessions.py::test_authenticate_returns_session_scoped_to_the_token_environment` (client claim ignored) | — |
| T06 | Token revoked while idle / during Submit | Pass | `test_post_fencing.py`: revoked mid-transfer → Agent stops and removes the file; revoked after Post → UNKNOWN, never re-sent. `test_agent_sessions.py::test_revoke_and_rotate_end_live_sessions_immediately` | — |
| T07 | Serial already owned is registered again | Pass | `test_devices.py::test_phone_bound_elsewhere_is_never_moved` | `test_real_device_registration.py` on POCO 25078PC3EG (P2) |
| T08 | Link redirects to a private address | Pass | `services/worker/tests/test_netguard.py::test_redirect_to_internal_address_is_refused_through_yt_dlp`, `test_agent_job_runner_http.py::test_source_pointing_at_an_internal_address_is_refused` | — |
| T09 | Source too short for 6 clips | Pass | `test_jobs.py::test_short_source_reduces_clip_count_and_says_so`, `test_agent_job_runner_http.py::test_short_source_is_refused_not_padded` | — |
| T10 | Render fails and the event repeats | Pass | `test_jobs.py::test_render_failure_releases_once_even_when_events_repeat` | — |
| T11 | 19:00 every 2 h, window ends 21:00 | Pass | `tests/unit/test_slots.py::test_prd_next_day_example`, `test_schedules.py::test_preview_follows_the_prd_rules_and_saves_nothing` (19:00 → 09:00, 11:00 the next day) | — |
| T12 | Phone offline for three slots, then online | Pass | `test_posts.py::test_missed_posts_are_deferred_with_their_spacing_not_fired_together`, `…_skipped_when_the_series_says_so`, `test_schedule_changes.py::test_paused_series_hands_out_nothing_and_resumes_without_a_burst` | — |
| T13 | Two series, same phone, same time | Pass | `test_schedules.py::test_same_phone_same_time_is_queued_not_refused`, `test_posts.py::test_two_agents_racing_never_get_the_same_post` | — |
| T14 | Pause/resume, and cancel after a claim | Pass | `test_uat.py::test_t14_cancel_after_claim_leaves_the_started_post_to_finish` (started post can't be cancelled; the rest are; it reports its own end), `test_schedule_changes.py::test_pause_does_not_stop_a_post_already_on_the_phone` | — |
| T15 | Wrong account, or name can't be read | Pass | `tests/unit/test_tiktok_ui.py::test_wrong_account_stops_before_anything_is_opened`, `::test_an_unreadable_account_stops_before_anything_is_opened` (new), `test_agent_post_runner_http.py::test_wrong_account_on_the_phone_parks_the_post` | Real app: ACCOUNT_MISMATCH before opening the clip (2026-10-08, G5-03) |
| T16 | Thai caption + emoji + hashtags | Pass | `tests/unit/test_tiktok_ui.py::test_caption_that_does_not_match_stops_and_the_keyboard_is_restored` | Real app: text matched character for character (2026-10-08, G5-02); real post with marker (Q-30) |
| T17 | Agent lost before Submit | Pass | `tests/unit/test_agent.py::test_crash_before_submit_is_retryable`, `test_posts.py::test_lost_agent_before_submit_is_redelivered_then_parked` | — |
| T18 | Agent lost after Submit, before ACK | Pass | `tests/unit/test_agent.py::test_crash_at_or_after_submit_is_unknown_and_never_retried`, `test_agent_live_post_http.py::test_crash_right_after_post_becomes_unknown_and_is_not_retried` | Real post Q-30: crash after Post → UNKNOWN → resolved with phone evidence (G5-04) |
| T19 | Server restart / redelivery | Pass | `test_uat.py::test_t19_restart_never_hands_out_a_submitted_post_again`: a second server process on the same DB. The old session is fenced, a submitted post becomes UNKNOWN and is never handed out again, and an unsubmitted one is redelivered as the same item. Also `test_agent_job_runner_http.py::test_restart_mid_job_resumes_without_double_charge` | — |
| T20 | Payment webhook repeated / forged / out of order | Pass (sandbox) | `test_billing.py::test_forged_repeated_and_late_events_never_grant_twice` | Omise/Stripe not connected (G6-02) |
| T21 | Two jobs, one quota unit left | Pass | `test_jobs.py::test_two_jobs_cannot_both_take_the_last_units` | — |
| T22 | Subscription ends with posts waiting / submitting | Pass (**found + fixed**) | `test_uat.py::test_t22_expiry_holds_waiting_posts_and_lets_a_submitted_one_finish`, `test_billing.py::test_expired_subscription_blocks_new_jobs_and_holds_posts`. Found: a post refused at Submit for an expired subscription was **parked** (NEEDS_ACTION), unlike a not-yet-claimed one, which waits. It now waits (SCHEDULED) and runs after renewal under the late rules | — |
| T23 | Storage cleanup while a job runs | Pass | `test_uat.py::test_t23_cleanup_never_deletes_files_of_a_running_job`, `test_admin.py::test_retention_deletes_old_files_but_never_ones_still_needed` | — |
| T24 | Restore the database from backup | **Not tested** | Backup/restore and the restore-time reconciliation (SUBMITTING/UNKNOWN before replay) are P8 (G8), not built yet | Needs staging + backup procedure (G2-05, P8) |
| T25 | TikTok UI / Agent version not supported | Pass | `test_agent_post_runner_http.py::test_untested_tiktok_version_is_never_driven`, `tests/unit/test_tiktok_ui.py::test_an_unexpected_screen_is_never_guessed_at`, `agent/compat.py` (D03 matrix) | — |

**Summary:** 24 of 25 pass. One finding was fixed (T22). T24 is not tested and waits for P8.

**Defects:**
- Critical/High: none open.
- T22 (Medium, fixed): a post refused at Submit because the subscription expired was parked instead of waiting.
