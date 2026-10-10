# Cost model (G1-06, G6-01)

Inputs from the PO (chat, 2026-10-10). Finance approver: ปิยศักดิ์ (PO, also Finance under Q-20).

| Input | Value | Source |
|---|---|---|
| Exchange rate | 1 USD = 35 THB | Finance |
| Render (staging web service) | $7 / month = **฿245** | PO |
| Supabase (DB, Auth, Storage) | **฿0** at the start (free plan) | PO |
| Supabase Pro, when needed | $25 / month = **฿875** | supabase.com pricing (list price) |
| Domain `tomatoparadise.online` | 48 per 3 years → **฿47 / month** | PO; *assumed USD* ($16/yr × 35 / 12). If the 48 is baht, this line is ~฿1 and nothing below changes materially |
| Stripe fee | **3 %** of each payment | PO (the account's rate) |
| Agent code-signing certificate | none | PO did not choose one: Windows may show "unknown publisher" when installing |
| Customers expected in the first 3 months | 50 | PO |

## Why the cost per clip is near zero

Clips are cut and rendered on the customer's own PC (Q-15 ข2). The server never receives the video. Per clip, it keeps:
- **One preview still** (3 frames side by side, 810×480 JPEG) for approval. **Measured** on 15 real clips (YouTube/Bilibili from `var/poc`, `services/worker/clipflow_worker/delivery.py` `contact_sheet`): min 21.8 KB, **mean 31.1 KB**, max 44.3 KB. Stills are deleted after the plan's `retention_days` (30).
- **Database rows** (clip, metadata versions, schedule item, attempt and events, audit, quota ledger). **Estimate**, not measured: about 8 KB per clip including indexes (conservative). These rows are kept as history.

So the processing time and electricity are the customer's, and the server cost is mostly fixed per month.

## Processing time (benchmark, `docs/compatibility.md`)

- Render on the QA PC: 0.56–0.79 × the clip length (15 real clips: mean 25.8 s per clip at 0.56 s per clip-second; a 5-minute clip took 236 s ≈ 0.79×).
- A job of 3 clips × 5 minutes takes about 12 minutes of rendering on one PC, plus the download.
- Customer PC: Windows 10/11 x64, at least 5 GB free on the clips drive (the Agent stops at less), a PC in the same class as the QA PC for these times.

## Monthly fixed cost

| Stage | Items | ฿ / month |
|---|---|---|
| Start (Supabase free) | Render 245 + domain 47 | **292** |
| Growth (Supabase Pro) | Render 245 + Supabase 875 + domain 47 | **1,167** |

## Per plan (D05), after the Stripe fee

| Plan | Price | Stripe 3 % | Net | Server cost per clip |
|---|---|---|---|---|
| Starter | ฿200 | ฿6.00 | **฿194.00** | ≈ 0 |
| Pro | ฿400 | ฿12.00 | **฿388.00** | ≈ 0 |
| Business | ฿888 | ฿26.64 | **฿861.36** | ≈ 0 (no clip cap: see fair use) |
| Free trial (5 days, 30 clips) | ฿0 | — | ฿0 | 30 stills ≈ 0.9 MB, deleted after 30 days |

**Break-even:** on the free plan ฿292 → **2 Starter** customers. On Supabase Pro ฿1,167 → **7 Starter** or **4 Pro** or **2 Business**.

## 50 customers (first 3 months)

The plan mix is an **assumption** (60 % Starter, 30 % Pro, 10 % Business). Replace it with real sales.

| | Starter | Pro | Business | Total |
|---|---|---|---|---|
| Customers | 30 | 15 | 5 | 50 |
| Revenue / month | 6,000 | 6,000 | 4,440 | **฿16,440** |
| Stripe 3 % | | | | ฿493 |
| Fixed (Supabase Pro) | | | | ฿1,167 |
| **Gross margin** | | | | **฿14,780 (≈ 90 %)** |

## When Supabase Pro is needed

Free-plan limits: database 500 MB, storage 1 GB, egress 5 GB / month, and **the project pauses after 7 days without use**.

| Usage | Clips / month (50 customers, mix above) | Stills kept (30 days) | DB growth / month |
|---|---|---|---|
| 30 % of the caps (Business ~1,500) | ~25,500 | ~0.79 GB (of 1 GB) | ~200 MB (500 MB in ~2.5 months) |
| Full caps (Business ~5,000) | ~85,000 | ~2.6 GB | ~680 MB |

So **move to Supabase Pro at about 20 paying customers**, or when Supabase shows storage above 0.7 GB or the database above 350 MB, whichever comes first. With 50 customers in 3 months, that is around month 2. Egress for viewing stills (~2 views each, ~1.6 GB/month at 30 % use) fits the free plan.

## Limits accepted with these prices

- **Business is unlimited (D05):** one customer making tens of thousands of clips a month raises storage and DB use without paying more. Recommendation for Finance: a fair-use line in the terms (e.g. review above 10,000 clips/month). Not decided.
- **Supabase free pauses after 7 idle days:** fine while customers use it daily; Pro removes it.
- **Supabase's built-in email sends only a few messages per hour:** sign-up and password emails need an external SMTP before 50 customers (free tiers exist). Not a cost today.
- **No code-signing certificate:** installers show "unknown publisher".
- **Not included:** VAT/tax (registration threshold ฿1.8 M/year; decision for Finance under D06), the PO's time, the customer's PC and electricity.
- **Real payments** still need production (`APP_ENV=production`), live Stripe keys and the G6 gate (`docs/runbooks/stripe.md` §4).

## Re-check

Every month, compare the Render invoice, Supabase usage (Database size, Storage size, Egress) and the Stripe fees against this sheet. Update the plan mix with real customers.
