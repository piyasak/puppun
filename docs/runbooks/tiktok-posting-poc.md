# TikTok posting POC — QA phone run (P1, G1-03 / G1-04)

Date: 2026-10-07 • Device: POCO 25078PC3EG (Xiaomi HyperOS 2.0, Android 15 / SDK 35) • TikTok `com.ss.android.ugc.trill` 40.0.0 • Account `@patsy4404` (PO-designated test account) • Authorization: Q-19 (one test post, visibility "Only me")

Screenshots are kept locally in `var/evidence/phone/` (gitignored). They contain a real account's screens, so they are never committed.

## Device prerequisites (done by the phone owner, not by the Agent)

| Setting | Why | Symptom without it |
|---|---|---|
| USB debugging + "Allow" prompt | ADB access | `adb devices` shows `unauthorized` |
| Xiaomi: Developer options → **Install via USB** | Install ADBKeyboard | `INSTALL_FAILED_VERIFICATION_FAILURE` |
| Xiaomi: **USB debugging (Security settings)** | Inject taps/text into other apps | Taps ignored or rejected |
| ADBKeyboard (`senzhk/ADBKeyBoard` master APK, SHA-256 `E698ADEA…CDC59`) enabled (not default) | Thai/emoji text entry | `input text` cannot type Thai |

## Flow that worked

1. Read the logged-in account on Profile (`@patsy4404`). Record a baseline of the private-videos tab: no videos, only a Story archive tile.
2. Write `CLAIMED` and `TRANSFERRING` to the journal. Push the clip through staging, verify its SHA-256 on the device, and rename it into `Movies/ClipFlow/` (E-20).
3. Look up the clip's MediaStore `_id`, then write `PREPARING` to the journal.
4. Share the exact file into TikTok. Don't pick it from the gallery grid:
   `am start -a android.intent.action.SEND -t video/mp4 --eu android.intent.extra.STREAM content://media/external/video/media/<id> -f 1 -n com.ss.android.ugc.trill/com.ss.android.ugc.aweme.share.SystemShareActivity`
5. The "แชร์บน TikTok" sheet appears. Press **วิดีโอ**, not "ข้อความ".
6. The editor appears. Press **ถัดไป**. **Never press "Story ของคุณ"**: it publishes straight to Story.
7. On the post screen, set the visibility first: tap "ทุกคนสามารถดูโพสต์นี้ได้", choose "เฉพาะคุณเท่านั้น", then check that the row reads "เฉพาะคุณเท่านั้นที่ดูโพสต์นี้ได้" (lock icon).
8. Caption:
   1. Focus the field.
   2. Run `ime set com.android.adbkeyboard/.AdbIME`.
   3. Run `am broadcast -a ADB_INPUT_B64 --es msg <base64 UTF-8>`.
   4. Run `ime set <original IME>` straight away.
   5. Check that the EditText text equals the approved caption, then hide the keyboard with BACK.
9. Before Post: take a screenshot and confirm the caption, visibility, that the share-to toggles are off, and that the account is unchanged. Write `SUBMITTING` to the journal, then press **โพสต์**.
10. Verify:
    1. TikTok returns to the feed with the toast "ดูวิดีโอส่วนตัวบนโปรไฟล์ของคุณ". The toast alone is **not** proof.
    2. Open Profile → private tab. A new tile (0 views, lock) should be there.
    3. Open the tile. The detail should show "patsy · ส่วนตัว".
    4. Expand the caption and look for the marker `cf2143e0`.

## Results

| Check | Result |
|---|---|
| Transfer + on-device SHA-256 + Gallery | Pass |
| Thai + emoji + hashtag caption (T16) | Pass. EditText text equals the approved string; the rendered caption is correct on the post detail |
| Visibility "Only me" | Pass. Post detail shows "ส่วนตัว" |
| Account (FR-16) | `@patsy4404` read on Profile before posting; post detail shows creator "patsy". Matching is still manual, not automated yet |
| Agent crash right after pressing Post (T18) | Journal `SUBMITTING` → `recover` → `UNKNOWN`, `may_retry: false`; nothing was re-posted |
| Reconciliation | `resolve(found_published, evidence)` → `VERIFIED_SUCCESS`. Evidence: private-tab baseline vs after, plus the caption marker |
| Exactly one post was made | Yes |

## Findings for the P5 TikTok adapter

- **A plain `input tap` did not reach TikTok's share bottom sheet.** It fell through to the activity underneath and opened the **Shop** tab. A short press (`input swipe x y x y 120`) works everywhere. Any mis-tap in an app with a shop and checkout is a risk, so check the screen before and after every press.
- **`uiautomator dump` can return a stale tree** after TikTok switches activity or window: it showed the old share sheet and the old post screen after both had gone. Check state from a screenshot and from `dumpsys window | grep mCurrentFocus`, and only trust a dump when it matches.
- The share intent pins the exact verified file. This avoids picking the wrong video from the gallery grid (FR-17).
- **Verification method.** The post must appear in Profile → private (or public) videos, and its caption must contain the attempt's short marker. This ties the post to both the account and the attempt (PRD §H). The marker changes the user's caption, so whether to keep it in production is an open decision (Q-21).
- Coordinates were measured on a 720×1600 screen. The adapter must find elements by text, content-desc or resource-id, check them against a screenshot, and stop with `NEEDS_ACTION` on any unknown screen, login wall or CAPTCHA (G5-03, T25).
- Xiaomi needs the extra security settings listed above. Device onboarding (FR-15) must detect a missing setting and explain it to the user.
- ADBKeyboard is left installed but not set as the default keyboard. The original IME (Gboard) is restored after every text entry.
