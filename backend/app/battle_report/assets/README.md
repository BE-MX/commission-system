# Battle poster theme v2 — platinum

Warm white/platinum campaign theme with pale champagne-gold decoration and the original running silhouettes. Cards use dark text and antique-gold numbers. Red/green pace fills sit on pale tracks; the white time marker has a dark outline. Only the company logo is embedded; no team-logo walls or avatar compositions are used.

- `background.png`: September 23 platinum recolor of the September 22 background, edited using the built-in imagegen tool. Generation happens only during asset authoring.
- `company-logo.png`: transparent gold restyling of the user-supplied leShine Hair company mark.
- `poster.css` / `poster.html`: deterministic responsive-height layout; all names, dates, goals, amounts, ranks and pace status are supplied by the current database snapshot, never generated into the art.

The September calligraphic heading is used only for September campaigns; other months use a dynamic gold heading. No business snapshot, user avatars, personal photos or credentials are stored in these assets.

The offline HTML embeds its own palette tokens from `poster.css`; it does not load the main frontend stylesheet or any network resources. Historical delivered images remain cached; the new theme applies when a poster is rendered again.

Image edit prompt: preserve the original tall composition, exact title “9月冲刺战报”, slogan “不破目标 绝不松懈”, and all five runners; replace scarlet areas with warm ivory white and pale champagne gold; use darker antique-gold calligraphy and bronze running silhouettes; keep the middle empty; add no logos, business data, badges or text.
