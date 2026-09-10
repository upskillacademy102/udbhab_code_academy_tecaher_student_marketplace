# Daily Work Log — 02-09-2026

## Trust & Safety Program — Work Log

*The whole session went to one program: an anti-fraud and identity-verification
layer for the marketplace. Ten build phases, each the size of a normal feature
release, then two passes back over the finished work to hunt for faults. The theme
throughout — every new safeguard ships switched off, so none of it can affect a
single current user until we deliberately turn it on.*

---

## 1. The problem this program solves

On the platform, students post what tutoring they need. Teachers see those posts as
"leads" and spend tokens (bought with real money) to unlock a student's contact
details. Money and personal contact details changing hands is exactly what attracts
abuse. The five real risks:

| Risk | In plain English |
|---|---|
| Fake / throwaway accounts | One person running many student or teacher accounts. |
| Going off-platform | A teacher getting a student to pay them directly to dodge the platform fee — usually by hiding a phone number or payment handle in their profile. |
| Payment fraud | Stolen cards, chargebacks (a bank reversing a payment after the tokens are spent), refund abuse. |
| Fake leads | A student posting requests they never follow up, so teachers pay to unlock dead ends. |
| Fake reviews | A teacher arranging glowing reviews from accounts they control. |

---

## 2. What we built — the ten safeguards

Every phase ended only once its own tests passed, the full test suite stayed green
with the new switch **off**, and a live walkthrough as a student, a teacher, and an
admin showed nothing had broken.

### A. The safeguards

| Phase | In plain English, it… | What it stops |
|---|---|---|
| **1. Email & mobile verification** | Sends real 6-digit codes to a person's email and phone. Codes expire in 10 minutes, are single-use, and lock after 5 wrong guesses. | Throwaway accounts made with fake contact details. |
| **2. Step-up re-verification** | Makes changing your email, phone, or password a two-step action — request, then confirm a code — with a cancel window and a warning to the current contact. | A stranger who gets into an account quietly taking it over. |
| **3. Conditional CAPTCHA** | Shows a challenge only to a device that has cycled through many accounts in a short window. Ordinary users never see it. | Bulk automated sign-ups (account farms). |
| **4. Duplicate-person detection** | Spots two accounts that are really one person — same phone written differently, a Gmail with dots or a "+tag", or the same device. Contact details stored only as one-way hashes. | The multi-accounting behind most fake-lead, fake-review and refund schemes. |
| **5. Teacher verification checklist & lead scaling** | A 10-item checklist (profile, subjects, availability, email, phone, government ID, selfie, address, interview). Progress shows as a bar and a score. Below the minimum: no leads. Above it: a small ranking boost. 100% earns a "Fully verified" badge. | Unvetted teachers reaching students; also gives teachers a real reason to finish verification. |
| **6. Student verification & lead-quality feedback** | Requires a verified email and phone before posting a request; checks a student's phone is reachable before a teacher is charged; lets teachers rate a lead *genuine / unreachable / fake* and refunds their tokens once enough independent teachers flag the same student. Also caps requests per day. | Teachers paying for dead-end leads; the platform keeping a bad actor's money. |
| **7. Payment & transaction fraud** | Verifies the charged amount with the gateway before crediting tokens; credits exactly once even if the gateway sends a confirmation twice; flags one card funding many accounts, purchase spikes and failed-payment bursts; freezes (not takes) the tokens behind a disputed payment; reconciles our records against the ledger every night; caps and holds purchases in a new account's first day. | Stolen-card top-ups, double-crediting, chargeback losses, refund abuse, silent accounting drift. |
| **8. Off-platform leakage, moderation & reviews** | Scans profile and review text for phone numbers, payment handles, emails and links — a hit hides the profile from search until it's fixed. Adds a review system that blocks self-reviews, requires a real prior lead, allows one review per lead, and watches for rating rings. Adds report & block. | Deals moving off-platform (the biggest revenue leak); fake social proof. |
| **9. Risk scoring, anomaly alerts & the ops queue** | Rolls every finding from every phase into one score per account (*normal / limited / review / suspended*). Adds new-country / new-device login alerts. Puts every kind of flag into one Super-Admin review queue with assign and resolve actions. | An ops team chasing a dozen disconnected alerts; risky accounts slipping through unreviewed. |
| **10. Full verification & documentation** | No new features. Proved the whole system holds together with all 18 switches on at once, and wrote the operator handbook (every switch, the vendor-swap guide, the recommended go-live order, the known limitations). | A safety system nobody knows how to operate. |

### B. Things that run all the time now

These aren't behind a switch — they're just correct behaviour:

| Now always on | In plain English |
|---|---|
| Server-side payment amount checks | Refuses to credit tokens if the gateway says a different amount was charged. |
| Duplicate-proof payment processing | Credits the wallet exactly once, no matter how many times the confirmation arrives. |
| Nightly payment reconciliation | Compares our payment records against the wallet ledger and reports any drift. |
| Duplicate-account & anomaly detection | Records matches and login anomalies into the review queue (without acting on them). |
| The review queue & risk scoring | Calculates scores and opens queue items — recommend-only, no automatic action. |
| Report & block | The actions work and are logged; only the filtering *effect* is behind a switch. |
| Audit logging | Every verification and dispute action is written to the security log. |

---

## 3. Bugs and broken workflows we fixed

Two deliberate review passes went back over finished work. The first re-checked
Phase 6 (built across an interrupted session). The second read all ten phases end to
end. **Fourteen real problems** — every one fixed, every fix covered by a new
automated check.

### A. Found in the Phase 6 re-check (6 fixes)

| Area | In plain English, what was wrong | What we changed |
|---|---|---|
| Abandonment tracking | It ran on every request submission — writing to the database — even with its feature switched off. | Gated it behind its switch so it does nothing, and costs nothing, when off. |
| Abandonment tracking | It counted a student's brand-new requests as "abandoned" before teachers had a chance to work them, so an active student looked like an abuser. | It now only counts requests that have actually closed or expired. |
| Unlocking a lead | If two teachers unlocked the same student's lead in the same instant, the reachability check tried to save the same record twice and crashed. | Switched to a "get-or-create" that absorbs the race safely. |
| Risk signals | A signal's description wasn't trimmed to the database column size, and re-recording a time-limited signal could accidentally make it permanent. | Trim the text everywhere; only touch a signal's timer when a new one is explicitly given. |
| Rating a lead | Sending the wrong data type for the verdict crashed the endpoint (a "500") instead of returning a clean error. | Input is coerced to text first, so bad input gets a clean "bad request". |
| Held-request bookkeeping | Opening the review-queue item for a held request could fail the whole request, even though the request was already saved. | Wrapped it so a failure there is logged and passed over, not shown to the user. |

### B. Found in the full ten-phase review (8 fixes)

| Area | In plain English, what was wrong | What we changed |
|---|---|---|
| Scheduled email / phone change (Phase 2) | If the new address got taken during the cooling-off window, a background job retried the change every minute, forever, silently. | The job now gives up cleanly after one failure, marks the request expired, and emails the owner. |
| Verification badge (Phase 5) | A teacher's "Fully verified" badge and ranking score only refreshed on a code verification or a 6-hour sweep — stale for hours after they finished their profile. | Added a refresh whenever a teacher saves their details, profile, or availability. |
| Error message (Phase 5) | Submitting an unknown verification item returned "Bank verification isn't available yet" — unrelated and confusing. | A clear message: "that is not a verification item you can submit." |
| **Payment webhook (Phase 7 — significant)** | The code read the payment gateway's unique message ID from the message body, but the real gateway puts it in a header. In production every confirmation would have arrived with a blank ID. | Read the ID from the header first, then the body, then a fingerprint of the message. The endpoint now always replies "OK" so the gateway doesn't retry forever. |
| Chargeback matching (Phase 7) | A payment confirmed only by the background webhook (customer closed the browser mid-checkout) never recorded the gateway's payment ID, so a later chargeback had nothing to link to. | The confirmation webhook now records that ID if it's missing. |
| New-account token freeze (Phase 7) | Frozen tokens were released based on how old the *freeze* was, not the *account* — a late purchase stayed frozen up to a full extra day. | Releases are now keyed to the account's age. |
| Teacher rating (Phase 8) | The reviews page recalculated *and saved* the rating on every view — opening it for a teacher with an old manual rating and no reviews reset that rating to zero. | Reads no longer write. The stored rating changes only on a real review create / delete / moderation. |
| Unblocking (Phase 8) | You couldn't unblock a user who had since been deactivated — "user not found". | Unblock now removes the block record directly, whatever the other account's state. |

### C. Two issues that were in the test setup, not the product

- **Phase 7:** a reconciliation test occasionally failed because Windows reports the
  clock in coarser steps, so a payment created "now" and reconciled "now" shared one
  timestamp. Fixed by using a realistic time window in the test.
- **Phase 10:** a batch of tests failed because the fake test browser always presents
  the same fingerprint, tripping the CAPTCHA account-switch counter mid-run. Fixed by
  clearing the shared counter between tests.

Neither affected the product.

---

## 4. Decisions we made — and why

| Decision | In plain English | Why |
|---|---|---|
| Every check is a separate switch, all off by default | 18 independent on/off switches, not one big "fraud protection" toggle. | We can turn each on alone, watch its effect on real numbers, and roll it back instantly — without touching the other 17. |
| Outside vendors sit behind a standard adapter | SMS, ID checks, face-match, phone-reachability, CAPTCHA, location lookup, content scanning — all reached through the same small interface, each with a working stand-in built in. | Zero vendor lock-in during the build; going live is a one-file swap per service; vendors can be changed later without touching anything else. |
| More verification means more leads — predictably, not by lottery | A teacher who completes more of the checklist gets a firm floor plus a measured ranking boost. | A lottery is impossible to explain to a teacher who feels hard done by. A predictable ladder is fair and defensible. |
| The matching engine stays "pure" | The engine that picks eligible teachers still looks only at subject, language, time and location. All trust filtering happens in a layer wrapped around it. | Keeps the matching engine simple and its behaviour identical when every trust switch is off. |
| One review queue for everything | Duplicate accounts, payment disputes, off-platform content, user reports, login anomalies, risk escalations — all in one list, one Super-Admin page. | The alternative is an ops team juggling a dozen alert channels. |
| The risk engine recommends before it enforces | It always scores accounts and opens queue items; whether it also blocks or down-ranks on its own is behind one final switch. | We need to see the false-positive rate on real traffic before letting software act unsupervised. |
| Keep the interface thin (frontend) | Server-rendered pages that just call the backend. New screens: teacher verification progress card, "held for review" banner, lead-quality rating buttons, reviews panel, report / block controls, the Super-Admin review-queue page. | Every rule lives on the backend where it can't be bypassed; the UI just shows the result. |
| Written retention windows (compliance) | Payment records kept 7 years, the security audit log 3 years, risk signals / flags 2 years after they're resolved, hashed identity fingerprints for the life of the account. | A clear, defensible answer to "how long do you keep this?" before any of it holds real customer data. |

---

## 5. Regression & safety guards added

### A. Guards on the bugs we fixed (so they can't come back)

Every one of the 14 fixes above has its own automated check that reproduces the old
fault and confirms it no longer happens — the stuck retry, the double-unlock crash,
the wiped rating, the blank webhook ID, and the rest.

### B. Guards on the safeguards (lock in the protections that work)

Each phase shipped with checks proving both states: with the switch **off** the
platform behaves byte-for-byte as before, and with the switch **on** the safeguard
does exactly what it should. Phase 10 added nine more that run every switch on at
once through full student, teacher, and ops journeys.

### C. Why this matters

| | Before this program | Now |
|---|---|---|
| Automated checks (total) | 283 | 488 |
| Checks covering the 14 fixes from the review passes | 0 | 18 |
| Checks covering the new trust & safety features | 0 | ~190 |
| Safety switches (all off by default) | 0 | 18 |
| Scheduled background jobs | (existing lead jobs) | +6 (reconciliation, risk refresh, cooldown release, and more) |

Every one of these runs on every future code change. The specific problems found
this program — and the safety guarantees that were verified — are now permanently
protected, not just fixed once.

---

## 6. Where things stand

Almost everything is dormant: built, tested, merged, switched off. Nothing in this
program affects a current user today except the "always on" items in section 2B,
which are simply correct behaviour.

**The go-live plan** (from the operator handbook) is seven waves, each left running
about a week before the next:

1. Low-friction identity — step-up re-verification, CAPTCHA
2. Contact verification requirements
3. Teacher-quality lead scaling
4. The non-punitive anti-abuse checks (duplicate blocking, velocity limits, content
   scanning, blocking, anomaly alerts) — still recommend-only
5. The money controls, once the real payment vendors are connected
6. The review system, once there is a moderation rota
7. *Last of all*, letting the risk engine enforce automatically — only once the
   queue is being worked daily and the false-positive rate is understood

**Known limitations** (documented so nobody is surprised later): device
fingerprinting is coarse without a browser-side library; the new-country login
alert needs prior login history to work; there is no in-app appeal for a suspended
account; a chargeback can only recover tokens still in the wallet; ID and liveness
checks use stand-ins with no real document storage yet; the content scanner is blunt
and will flag legitimate links until its rules are tuned.
