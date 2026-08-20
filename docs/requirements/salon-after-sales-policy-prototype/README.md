# Salon After-sales Assurance Prototype

Independent customer-facing prototype for the LeShine salon policy library.

## What it demonstrates

- Product, concern, and keyword-based policy discovery.
- Issue-specific review windows instead of one blanket warranty period.
- Separate receiving, post-installation, and in-wear review clocks with assessment, decision, and execution targets.
- Clear separation between product quality, salon installation, and client care factors.
- Evidence requirements, verification methods, possible outcomes, and service SLA.
- English-first customer experience with complete Chinese review copy.
- A local claim-preparation drawer that does not submit or persist data.

## Policy status

The policy structure and time windows are a proposed framework synthesized from the two supplied research documents. The prototype labels this status prominently. Commercial, quality, and legal owners must approve durations, remedy ownership, regions, effective dates, and mandatory local-law wording before customer publication.

## Run

```bash
pnpm install
pnpm run dev --host 0.0.0.0 --port 4174 --strictPort
```
