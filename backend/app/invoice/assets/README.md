# Employee PI template

`portal_pi_template.xlsx` is the exact invoice template supplied by the user on
2026-10-23. Original filename: `发票模板.xlsx`.

SHA256: `098c391084ffd31d54516431a22a7567a5370d492bd7dcc8e790c272f718f413`.

`pi_template.py` fills the first sheet, expands product rows, removes empty sheets
and replaces all sample customer, salesperson, product and fee values. It restores
the original OOXML drawing parts after saving because openpyxl does not retain
floating text boxes (company letterhead and Proforma Invoice title).

`pi_template_pdf.py` renders the same eight-column proportions and original
letterhead/logo on A4 with repeated headers and source amounts. It uses the
configured CJK font and the existing ReportLab dependency, without an Excel or
LibreOffice process. PDF text wraps and pages independently of Excel printing.

Both formats are selected explicitly with `template=leshine_pi`. Default invoice
exports and customer published-snapshot downloads keep their existing renderers.
This is one supplied template, not configurable A/B template selection.
