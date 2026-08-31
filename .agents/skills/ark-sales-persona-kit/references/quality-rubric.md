# Avatar and video quality rubric

An output is READY only when every critical check passes.

## 1. Avatar checks

| Check | Critical | Pass condition |
|---|---:|---|
| Real identity source | Yes | A permitted photo of the actual salesperson was inspected |
| Identity fidelity | Yes | Face shape, age, skin tone, eyes, nose, mouth, hairline and recognizable features remain the same |
| No synthetic substitution | Yes | Result is not a cartoon, stock person, invented face or face replacement |
| Natural retouch | Yes | Skin texture and normal asymmetry remain; no beauty-filter look |
| Small-size legibility | Yes | Face and expression remain clear at 40×40 |
| Circular-crop safety | Yes | Eyes, face and hair are not clipped in a circular crop |
| Background truthfulness | Yes | No fake factory, fake office, fake badge, fake event or implied documentary scene |
| Privacy | Yes | No customer/order/screen/label/address/QR/family/confidential detail |
| Channel consistency | No | One recognizable avatar can be used across approved channels |
| Professional warmth | No | Clear, tidy, approachable, not stiff or glamorous |

Critical failure actions:

- no valid real photo → BLOCKED_REAL_PHOTO_REQUIRED;
- identity drift or over-retouching → NEEDS_RESHOOT or regenerate from the source;
- privacy or fake-context issue → reject and remove the material.

## 2. Fifteen-second script checks

| Check | Critical | Pass condition |
|---|---:|---|
| Truthful identity | Yes | Name, role and company are confirmed |
| Claim traceability | Yes | Every material company claim is APPROVED and has CURRENT_PUBLISHED or AUTHORIZED_APPROVAL source authority in the ledger |
| Duration | Yes | 28–35 English words, or measured to fit 13–17 seconds at the speaker's real pace |
| One value | Yes | The script communicates one customer-relevant value, not a capability list |
| One CTA | Yes | One simple question or invitation |
| Spoken English | Yes | Short clauses, natural words, no hard-to-pronounce jargon without help |
| Human tone | No | Warm and direct, without fake intimacy or corporate slogans |
| Audience fit | No | Brand, salon, distributor, first-time buyer or general B2B emphasis is clear |
| Privacy | Yes | No private customer, family, order or employee detail without approval |
| No risky promise | Yes | No price, delivery, stock, result, rank, exclusivity, refund or product-performance guarantee |

## 3. Three-minute script checks

All 15-second truth/privacy rules still apply, plus:

- 320–390 English words unless a timed rehearsal proves another length fits.
- Opens with the person, then the customer's decision risk, not a company-history dump.
- Uses no more than three relevant capabilities.
- Each capability is translated into what the customer can verify.
- Explains the focused-sample → real-test → small-repeat → scale path.
- Includes one CTA and no competing next steps.
- Contains no fabricated customer story, result or competitor claim.
- Has timestamped sections and short paragraphs suitable for rehearsal.

## 4. Claim-ledger checks

Fail when:

- a claim has no source, no revision/version, or only a “需确认” source;
- a company claim relies only on OFFLINE_SNAPSHOT or UNVERIFIED_USER_INPUT but is marked APPROVED;
- a dynamic fact lacks a current query time;
- a capability is silently converted into a guaranteed outcome;
- conflicting sources are resolved without showing the conflict;
- REVIEW_REQUIRED or DROP content remains in the public script.

## 5. Review output

Return one row per check:

| check | passed | evidence | exact fix |
|---|---|---|---|

Do not use a total score to override a critical failure.

Record `QA_Mode` and reviewer IDs. `SELF_CHECK_ONLY` is useful for correction but is not an independent verification and cannot by itself make an asset deployable.
