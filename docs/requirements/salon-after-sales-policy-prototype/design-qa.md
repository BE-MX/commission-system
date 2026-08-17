# Design and interaction QA

## Verified viewports

- Desktop: 1440 × 1200
- Mobile: 390 × 844 with device-level viewport emulation
- Mobile document width: `scrollWidth 390 === clientWidth 390`

## Verified interactions

- Twelve policies render from the structured policy model.
- Deep links select and scroll to the corresponding policy; subsequent hash changes stay synchronised.
- English/Chinese language switch updates visible copy, page metadata and accessibility labels.
- Search indexes customer-visible causes, tests, coverage and care content without internal keys or shared evidence noise; `chlorine` finds 1 policy, `colour` 3 and `batch` 6.
- Filter changes automatically select the first matching policy; zero matches show a dedicated empty state instead of stale policy detail.
- Receiving, post-installation and in-wear stages each show assessment, decision and execution clocks.
- Claim-preparation requires the seven core fields plus care facts for post-installation/in-wear cases, focuses each missing field in order, copies the complete summary, traps modal focus, and restores focus on close.
- Mobile navigation closes with Escape and outside click.
- No browser runtime errors were emitted during the automated flow.
- Muted text contrast is 5.06–5.66:1, gold text is 6.32–7.08:1, and the solid focus ring exceeds 3:1 on light surfaces.

## Visual decision

Pass. The experience reads as an external assurance library rather than an internal dashboard. The hero establishes brand confidence, while the policy workspace keeps timing, verification, coverage, responsibility, ownership and execution targets visible in one continuous decision surface. A prominent proposal notice prevents the prototype from being mistaken for approved customer terms.

## Publication gate

The issue-specific windows are a proposed policy framework derived from the supplied research. Quality, commercial and legal owners must approve the final durations, remedy limits and effective-date language before public release.
