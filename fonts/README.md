# Caption fonts

The subtitle renderer loads fonts from this directory (`SUBTITLES_FONT_DIR`).

For the exact viral creator look from the reference screenshots, drop
**Anton** (`Anton-Regular.ttf`, SIL Open Font License) into this folder:

- https://fonts.google.com/specimen/Anton (Download family, then extract the TTF)
- or clone it from https://github.com/google/fonts/tree/main/ofl/anton

When `Anton-Regular.ttf` is present, `SUBTITLES_FONT_NAME=Anton` (the default)
uses it automatically on every machine, including the GitHub Actions runners
(the workflows download it for you).

If Anton is missing, the bundled **DejaVu Sans Bold** (Bitstream Vera License,
redistribution permitted) is used as the built-in fallback, so captions always
render even on a fresh checkout.
