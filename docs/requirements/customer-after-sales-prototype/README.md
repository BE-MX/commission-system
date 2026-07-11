# Customer After-sales Prototype

Independent interactive prototype for the customer after-sales management requirement dated 2026-07-10.

## Folder contract

- `src/` contains prototype-only React UI and interactions.
- `public/` contains prototype-only raster assets.
- `design-qa*.png` and `design-qa.md` preserve the final visual comparison and QA decision.
- Production API calls, credentials, real customer data, and the source SOP document do not belong here.
- Remove the whole folder when this requirement is retired; do not clean individual generated files ad hoc.

## Demo coverage

- Open a demo after-sales case from the list.
- Review customer, order, product, issue and evidence information.
- Generate a structured AI recommendation with SOP citations.
- Switch between a non-compensation action and a compensation action.
- Submit to the direct supervisor.
- Simulate supervisor approval and conditional sales-director approval.
- Confirm the resulting DingTalk notification state.

## Run

```powershell
pnpm install
pnpm run dev -- --host 0.0.0.0 --port 4173 --strictPort
```
