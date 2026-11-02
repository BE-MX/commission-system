# Battle poster theme v2 — platinum

Warm white/platinum campaign theme with pale champagne-gold decoration and the original running silhouettes. Cards use dark text and antique-gold numbers. Red/green pace fills sit on pale tracks; the white time marker has a dark outline. Only the company logo is embedded; no team-logo walls or avatar compositions are used.

- `background.png`: September 23 platinum recolor of the September 22 background, edited using the built-in imagegen tool. Generation happens only during asset authoring.
- `company-logo.png`: transparent gold restyling of the user-supplied leShine Hair company mark.
- `poster.css` / `poster.html`: deterministic responsive-height layout; all names, dates, goals, amounts, ranks and pace status are supplied by the current database snapshot, never generated into the art.

The September calligraphic heading is used only for September campaigns; other months use a dynamic gold heading. No business snapshot, user avatars, personal photos or credentials are stored in these assets.

The offline HTML embeds its own palette tokens from `poster.css`; it does not load the main frontend stylesheet or any network resources. Historical delivered images remain cached; the new theme applies when a poster is rendered again.

Annual ranking overlays (`annual_ranking.html` / `annual_ranking.css`, 2026-10-19): the lower table progress heading reads “年度GMV同比增长完成进度”. All five podium scores and the twelve lower-table score slots use the dedicated gold score token and weight 900. The original background artwork, other numbers and progress calculation remain unchanged. Changes appear in newly rendered previews/images; existing cached deliveries retain their original image.

Image edit prompt: preserve the original tall composition, exact title “9月冲刺战报”, slogan “不破目标 绝不松懈”, and all five runners; replace scarlet areas with warm ivory white and pale champagne gold; use darker antique-gold calligraphy and bronze running silhouettes; keep the middle empty; add no logos, business data, badges or text.


PK roster update (2026-11-01): `pk-team-one-leading.png` and `pk-team-two-leading.png` were edited with the built-in imagegen tool, retaining 1672×941 dimensions. Remove only Liu Ting, the fifth/rightmost pink-team woman (hair bun, no glasses), her name plaque and count box; reconstruct empty pink neon stadium; preserve all remaining people at their original positions and sizes, cars, banners, crown, totals, reward box, logos and text. One-team-leading edit region is approximately x735–896/y226–518; two-team-leading region x607–757/y254–507. The code now maps four pink-team seats and five blue-team seats. Neutral mode uses the same non-leading halves; names and live counts are still deterministic overlays. Historical cached deliveries are unchanged.

Follow-up portrait correction: edit only the leftmost pink-team woman's head and neck (Luo Xinyu, short side-parted black bob and round glasses). Correct flattened/skewed proportions, align the lenses and eye spacing naturally, reduce excessive sideways tilt and connect the neck to existing shoulders. Preserve identity, expression, style, supporting-member scale and seat, the four-versus-five roster, body, nameplate and all remaining art. The corrected one-team-leading image was also used as a face-only reference for the two-team-leading variant. Both edits used built-in imagegen.

PK average band (2026-11-02): keep the original total/target panels, then render a deterministic HTML comparison strip below the artwork and above the notes. Show each team's participant count, new customers per person (two decimals), and total divided by participants. The center explains the existing per-person comparison and any amount/GMV tiebreak; incomplete data hides formal values, and upcoming/ended labels retain their lifecycle meaning. No bitmap changes or AI generation are involved.
