"""Build index.html from the seminar-2026-10 template (CSS + controller) and slides.html.

Run from the repo root: python docs/slides/progress-2026-10-23/source/build.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK = HERE.parent
TEMPLATE = DECK.parent / "seminar-2026-10" / "index.html"

lines = TEMPLATE.read_text(encoding="utf-8").split("\n")


def find(prefix: str, start: int = 0) -> int:
    return next(i for i in range(start, len(lines)) if lines[i].startswith(prefix))


style_end = find("</style>")
main_open = find('<main class="deck-stage"')
main_close = find("</main>")
chart = find("   CHART — MAE") - 1          # the "/* ====" line before the chart header
editing = find("   INLINE EDITING") - 1

head = "\n".join(lines[:style_end])
head = head.replace(
    "<title>lab-realtime · Giám sát, dự báo, cảnh báo nuôi cá lồng</title>",
    "<title>Hydro-Aqua-Predict · Báo cáo tiến độ 23/10/2026</title>",
)
extra_css = (HERE / "extra.css").read_text(encoding="utf-8")
slides = (HERE / "slides.html").read_text(encoding="utf-8")
# keep the controller, drop the seminar's MAE chart (its SVG is not in this deck)
script = "\n".join(lines[main_close:chart] + lines[editing:])
script = script.replace("lab-realtime-seminar-2026-10-v4", "hap-progress-2026-10-23-v1")

out = "\n".join([head, extra_css, "\n".join(lines[style_end:main_open + 1]), slides, script])
(DECK / "index.html").write_text(out, encoding="utf-8")
print(f"wrote {DECK / 'index.html'} ({len(out) // 1024} KB)")
