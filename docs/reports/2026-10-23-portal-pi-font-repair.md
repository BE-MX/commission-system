# Customer PI PDF font repair

## Finding

The Beijing backend configures `PDF_CJK_FONT_PATH` as
`/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`. The file exists and
Pillow can render its Chinese glyphs. ReportLab 4.5.1 rejects its CFF/PostScript
outlines, producing the customer-facing `PDF_UNAVAILABLE` response. The four
installed Noto CJK collection files all fail the same ReportLab compatibility
check. No missing document or amount/state repair is required.

Read-only service inspection found no systemd EnvironmentFiles and no
`PDF_CJK_FONT_PATH` in the running process environment. The effective value
comes from `backend/.env`, which the managed Beijing candidate links during
prepare.

## Local changes

- Keep the existing Pillow Chinese-glyph validation and additionally parse the
  configured font with ReportLab's actual `TTFont` parser.
- Run this validation during Beijing prepare, before any stop or activation.
  Office prepare and application bootstrap already call the shared validator.
- Log only the PI font-registration exception type while preserving the
  customer-safe error response.

No document selection, permissions, prices, publication or snapshot logic changes.
The guard alone does not restore the existing service: production must first
receive a compatible configured font, or the next prepare will correctly fail.

## Validation

- Font preflight and portal PI download: 14 isolated tests passed.
- Invoice PDF resources and PI template export: 14 tests passed.
- Existing backend managed-release tests: 9 passed.
- Added prepare failure test: 1 passed; incompatible fonts prevent all later
  commands and the prepared-release marker.
- Independent risk review found no P1/P2 issue in the affected code.

The configured Ubuntu package mirror supplied `fonts-wqy-zenhei=0.9.45-8`.
It was downloaded and extracted into a private staging directory without
installing a system package. Its font passes both Pillow Chinese-glyph and
ReportLab checks. Package SHA256:
`496969d65dc5664a3291e678d5cbef6815dc308ee5bf37b656c00af2cb490410`.
Font SHA256:
`79c18ebe7b811951e8311bad7103ebeae8c337ed9988ea69e8a78a66cfe029b9`.

A read-only transaction loaded exactly the reported request's current published
snapshot, matching its current invoice document version. A diagnostic process
rendered that unchanged snapshot with the staged compatible font: 633197 bytes,
2 pages, with invoice title, payment terms and total present. The snapshot hash
was verified before and after rendering; no business database writes occurred.
PDF SHA256:
`81e7789c8f31784f8daa1593da86224a240b280119a0f42458248d7123155c54`.
This validates document generation, not the live authenticated download endpoint
or visual/business acceptance.

Private evidence is under `tmp/pi-font-proof/` in this task's worktree and
`.deploy_state/pi-font-repair-20261023/` on Beijing. The real customer PDF is
private evidence and must not be committed or published.

## Release boundary

The user authorized this code and the checkout-height change to be committed,
integrated into main and pushed. Delivery is confirmed by Git ref readback.
This authorization excludes deployment; the live font configuration and service
have not been changed for this repair.

After authorization, retain the package copyright and place the verified font
in a stable service-readable location, back up `backend/.env`, change only
`PDF_CJK_FONT_PATH`, and use the project's managed `deploy/deploy.bat` entry for
the reviewed revision. Preserve every other production configuration and
service baseline. Run the font preflight and health/readback checks, then verify
the authenticated current PI download. An uncertain download/write outcome
must be read back before retrying. Rollback must restore both the prior scoped
font configuration and managed revision where applicable.
