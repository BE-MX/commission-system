# Public-pool staged research framework

## Contents

1. Enterprise knowledge grounding
2. Industry gate
3. Social-first path
4. Focused and deep research
5. Customer and deal classification
6. Evidence and output rules

## 1. Enterprise knowledge grounding

Search narrowly for: target industries and exclusions; product families and differentiators; buyer personas; known pains/switch triggers; successful or failed deal patterns. Prefer 2-5 relevant published documents rather than a broad dump. Store only exact document/revision/version IDs in `knowledge_references`; do not persist a model-written excerpt or summary of internal content into the broader sales result.

## 2. Industry gate

Use only low-cost identity/business signals first: trusted seed, search results opened at source, official/social bio, visible product/service content, local business/booking listing, and historical order context.

For `source_system=ark_lead`, the trusted seed comes from intelligent acquisition rather than OKKI. Its profile match score and reasons are routing signals only: independently verify the official domain, entity, industry, products, activity, and exclusions before passing the gate.

- `core`: directly sells, installs, teaches, distributes, brands, or repeatedly discusses target products/services.
- `adjacent`: serves the same buyer/use case and has a plausible cross-sell path, but the target category is not proven core business.
- `uncertain`: entity or business scope remains too sparse/ambiguous. Continue only a bounded identity/social check.
- `irrelevant`: reliable evidence establishes an unrelated industry/business with no plausible target-category use. Require at least one opened public source and a clear reason.

Apply the current published Ark exclusions when retrieved from knowledge: a customer whose main business or current request is only wigs, closure, hair bundles, or frontal is non-target for the professional installation-extension route. Do not exclude mixed portfolios from one keyword; mark `uncertain`/review-required and verify the current purchase purpose. Do not confuse “bundle deal,” company closure notices, or “frontal view” with excluded hair products. Never infer exclusion from country, race, skin tone, name, or photos.

Do not classify irrelevant from missing website, free email, inactive single account, generic company name, or failed searches. On `irrelevant`, stop before contacts, social relationships, supplier analysis, deep reputation/risk search, and outreach drafting.

## 3. Social-first path

When the website is absent, broken, thin, or stale, social and commerce/booking pages become primary operating evidence.

Search likely name/handle variants across Instagram, Facebook, TikTok, LinkedIn, Pinterest, YouTube, Google Business, Vagaro, Booksy, Fresha, StyleSeat, GlossGenius, Yelp, and relevant brand/stylist directories. Keep only business-relevant profiles.

For each profile capture:

- platform, canonical profile URL, handle/account name;
- identity matches: country/city, phone/email/domain, logo/avatar, reciprocal links, business name;
- latest visible activity date and `active` (≤30 days), `recent` (31-90), `dormant` (>90), or `unknown`;
- observed signals: products/services, retail/wholesale, booking, training, store count, team size, branded content, target-product posts;
- follower count only when visible, as an audience signal—not a purchasing-capacity fact.

One matching handle is only an OSINT candidate. Confirm it through two compatible anchors or label it low confidence. Social bio and post content may prove current operations; they do not by themselves prove legal entity, supplier, purchase volume, or decision authority.

### Weak-lead address cross-check

Trigger this bounded fallback only when the first pass remains weak: identity is `candidate`/`unverifiable` or industry relevance is `uncertain`. T3 alone is not sufficient. The backend never parses or exposes raw free-text `customer_info.address`; it exposes `trusted_seed.address_search_hint` only when the address is present and a city/region comes from an explicit structured column or structured JSON key. If that hint is absent, do not use address search. Combine it only with the company/business name in at most 2-3 searches. Never add a person's name, private phone/WhatsApp, email address, email local part, or reconstruct a precise address from other fields. Prefer public business registries, official business/social profiles, booking/store pages, and reputable directories.

`address_search_hint` is an internal search hint, not proof. Do not publish it as a research fact or use it to join a same-name entity unless an opened public business source independently matches the coarse location plus at least one other business anchor. Record only the public source URL and its observed claim. If no corroboration appears, keep identity unresolved; do not broaden into residential-person research.

## 4. Focused and deep research

After the gate, choose the smallest depth that changes action:

- `focused`: identity, activity, buyer type, target fit, reachability, 1-3 major risks, and next questions.
- `deep`: add decision role, public supplier/import evidence, scale signals, switch/timing triggers, registration/reputation checks. Use for strong-fit, high-value, T1 reactivation, or meaningful risk signals.

Use official pages/registries first, then active business social pages, booking/store pages, industry directories/events, reputable company/review sources. Search a negative/risk dimension only after relevance is established. No public negative result means “not found in searched sources,” never “no risk.”

## 5. Customer and deal classification

Set customer type: salon, stylist, educator, brand owner, e-commerce, distributor, wholesaler, salon chain, other, or unclear. Set professional level, purchase stage, volume band, and development difficulty only from observable signals; otherwise use unclear.

Use Ark knowledge mappings when available:

- Brand builder signals: own brand, private label, logo/packaging, custom colors, ongoing launches; one logo alone does not prove a mature brand.
- Salon/stylist signals: installation/service menu, bookings, client work, restock; a person or free-email account can still be a valid B2B stylist.
- Distributor/wholesaler signals: resale, downstream salons/retailers, territory/channel, inventory and repeat replenishment; do not infer distribution from a wholesale-price request alone.
- Educator is an influence multiplier only with real academy, certification, regular workshops, or organized professional community—not occasional tutorial posts or follower count.
- Purchase stage: first cross-border, supplier exploration, testing, regular buying, expansion, dormant/lost, or unknown. Map these to the nearest API enum and preserve nuance in positive signals/unknowns.
- Scale requires team/store/location/channel evidence; follower count alone never establishes scale or buying capacity.

For product fit, prioritize professional installation extensions (weft, tape-in, I-tip/pre-bonded and other published supported lines). Compare observed needs against knowledge-backed differentiators such as batch/color consistency, replenishment, product development, small-sample verification, installation method, private label, education support, or approved quality evidence. Never turn a knowledge claim into a customer fact or commercial promise.

Score dimensions:

- Industry fit /25: direct target category and channel fit; adjacent but plausible scores lower; irrelevant must be 0.
- Pain/switch trigger /20: verified gaps, expansion, complaints, assortment/lead-time/private-label/education needs. Unknown supplier is not a trigger.
- Intent/reactivation /20: recent inquiry/order/activity, explicit wholesale/buyer behavior, historical relationship change.
- Buying capacity /15: store/team/assortment/volume/import/booking footprint; follower count alone is weak.
- Reachability /10: public business channels and verified role/contact—not guessed email.
- Timing /10: current expansion, launches, hiring, events, seasonal need, recent target-category activity.
- Risk penalty /30: entity mismatch, inactivity, weak evidence, reputational/legal/payment signals, entrenched supplier evidence.

Separate three concepts: customer type, ICP fit, and Ark A/B/C/D priority. Do not make a brand/distributor automatically high grade. Grade must reflect evidence quality, purchase readiness, reachable decision process, relevant capacity, timing, and risks. Treat public research as incomplete for non-public dimensions such as budget, payment compliance, decision authority, and actual monthly volume; list them as unknowns and let sales verify them.

In `commercial_profile`, list positive signals, negative signals, unknowns, and the exact low-risk questions a salesperson should verify. The model provides components; Ark recomputes final scores and grade.

When evidence permits, populate all ten `qualification_dimensions` on a 1-5 scale: authenticity/maturity, purchase potential, demand readiness, industry professionalism, product-market fit, growth/brand potential, decision authority, transaction compliance, engagement momentum, and strategic value. Use `score=null` plus a specific reason whenever public research cannot establish a dimension. Ark calculates a normalized `qualification_score` only over scored dimensions and a separate `qualification_coverage`; never present a high partial score with low coverage as a complete customer rating.

## 6. Evidence and output rules

Evidence levels:

- High: first-party/official or two independent reliable sources agree.
- Medium: one reliable opened source.
- Low: social bio, directory, weak name match, or uncorroborated inference.
- OSINT candidate: username/account hit awaiting cross-check.
- Unverified inference: sales hypothesis explicitly marked as such.

Output should answer: who the customer is; why relevant; how active; customer type and scale; likely product fit; what proves/weakens a deal; what is unknown; who/which business channel to contact; what to verify next; and why the recommended outreach angle follows from evidence and enterprise knowledge.
