# Bundled UI typefaces

The main operator UI uses Noto Sans KR for Korean, Noto Sans SC for Simplified
Chinese, and Inter for English. These fonts are loaded privately into the
Windows process by `load_bundled_fonts`; users do not need to install fonts.

The variable-font sources were downloaded from the Google Fonts repository:

- `ofl/notosanskr/NotoSansKR[wght].ttf`
- `ofl/notosanssc/NotoSansSC[wght].ttf`
- `ofl/inter/Inter[opsz,wght].ttf`

`prepare_fonts.py` generates the Regular, Medium, and Bold static fonts used at
runtime. Their application-specific family names prevent an installed system
font with the same public family name from changing the rendered UI.
Each family is distributed under the SIL Open Font License 1.1; the matching
license files are in this directory.
