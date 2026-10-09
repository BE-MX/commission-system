# Order card material

`order-glass.png` is the approved pale champagne frosted-glass background,
with one large diffuse gradient halo, right-side starlight and transparent exterior.
Generated with the built-in image generation tool; the final prompt requested an
empty reusable glass plate with all sample text, numbers, brand and avatar removed.

`app/festival/order_card_renderer.py` overlays live event text, amount and the
existing procurement-board avatar. No sample customer, salesperson or order is
baked into this asset. The renderer draws at 1200×675, then downsamples delivery
to 800×450 and encodes a 256-color indexed PNG with transparency. This keeps the
16:9 festival-card proportions while reducing the textured glass payload.
