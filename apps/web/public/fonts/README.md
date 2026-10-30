# Noto Sans SC subset

`NotoSansSC-Regular-subset.woff2` (400) and `NotoSansSC-Medium-subset.woff2` (500) are cut from
`ofl/notosanssc/NotoSansSC[wght].ttf` in google/fonts. License: SIL OFL 1.1, see `OFL.txt`.

Characters: GB2312 level-1 hanzi (3,755), the GB2312 symbol rows, printable ASCII, and every
character used in `apps/web` and `DESIGN.md`. Anything else falls back per glyph to the system
font stack in `app/globals.css`.

To rebuild (fontTools + brotli, dev only):

```bash
python - <<'PY'
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
for w in (400, 500):
    instancer.instantiateVariableFont(TTFont("NotoSansSC[wght].ttf"), {"wght": w}).save(f"s{w}.ttf")
PY
pyftsubset s400.ttf --text-file=chars.txt --layout-features='*' --flavor=woff2 --output-file=NotoSansSC-Regular-subset.woff2
pyftsubset s500.ttf --text-file=chars.txt --layout-features='*' --flavor=woff2 --output-file=NotoSansSC-Medium-subset.woff2
```
