# Self-hosted fonts

Latin-subset variable `woff2` files, pulled from the Google Fonts CDN once and
committed so the app has **no runtime CDN dependency** — the offline PWA shell
caches them alongside the rest of the shell in `sw.js`.

| File | Family | Axes shipped | Source |
|---|---|---|---|
| `fraunces-latin-var.woff2` | Fraunces (display) | `wght 600–800` | Fraunces v38, latin subset |
| `manrope-latin-var.woff2` | Manrope (text) | `wght 400–800` | Manrope v20, latin subset |

Both are licensed under the **SIL Open Font License 1.1**
(<https://openfontlicense.org/>) — redistribution in this form is permitted;
neither is sold on its own and neither file is renamed to a reserved name.

The `unicode-range` in `styles.css` must stay in sync with the latin subset
these files were cut from — widening it makes the browser stop falling back for
characters the file does not contain, which renders as tofu.

To refresh: request the `css2` API with a desktop UA, take the `@font-face`
block whose `unicode-range` includes `U+0000-00FF`, and download that URL.
