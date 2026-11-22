"""Writes the Allectricity mark SVGs into app/public: a circuit-trace "A" standing on a ground symbol.

    python3 scripts/brand_mark.py

app/src/components/BrandMark.jsx inlines the same paths; change both together. apple-touch-icon.png is a 180 px
render of brand/allectricity-app-icon.svg without the rounded corners (iOS rounds them).
"""

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "public"
SLOPE = 12 / 28  # legs of the inner A; the outer trace runs parallel to them
LIGHT = ("#12332c", "#288778", "#3ea894")  # ink, trace, accent on light surfaces (app)
DARK = ("#e9fbf5", "#3ea894", "#9ef0d8")  # on the landing's #041411
TILE = "#041411"


def right_leg(t):
    y = 6 + 41 * t
    return f"{36 + SLOPE * (y - 6):.2f} {y:.2f}"


def mark(ink, trace, accent, stroke):
    return (f'<g fill="none" stroke-width="{stroke}" stroke-linecap="butt" stroke-linejoin="miter">'
            f'<path d="M15.43 40 L29.57 6 H36 L{right_leg(.17)}" stroke="{trace}"/>'
            f'<path d="M{right_leg(.27)} L{right_leg(.42)}" stroke="{accent}"/>'
            f'<path d="M{right_leg(.52)} L{right_leg(.83)}" stroke="{trace}"/>'
            f'<path d="M5 47 H20 L32 19 L44 47 H59 M24.71 36 H39.29" stroke="{ink}"/>'
            f'<path d="M45 53 H57 M48 59 H54" stroke="{accent}"/></g>')


def favicon_mark(ink, trace, accent):
    """16–32 px: no dash, a single ground bar and heavier strokes."""
    return (f'<g fill="none" stroke-width="7" stroke-linejoin="miter">'
            f'<path d="M15.43 40 L29.57 6 H36 L{right_leg(.3)}" stroke="{trace}"/>'
            f'<path d="M{right_leg(.5)} L{right_leg(.83)}" stroke="{trace}"/>'
            f'<path d="M5 47 H20 L32 19 L44 47 H59 M24.71 36 H39.29" stroke="{ink}"/>'
            f'<path d="M46 56 H56" stroke="{accent}"/></g>')


def svg(body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">{body}</svg>\n'


def tile(body, scale, dx, dy, radius=14):
    return f'<rect width="64" height="64" rx="{radius}" fill="{TILE}"/><g transform="translate({dx} {dy}) scale({scale})">{body}</g>'


if __name__ == "__main__":
    (OUT / "brand").mkdir(parents=True, exist_ok=True)
    (OUT / "brand" / "allectricity-mark.svg").write_text(svg(mark(*LIGHT, 3.6)))
    (OUT / "brand" / "allectricity-mark-dark.svg").write_text(svg(mark(*DARK, 3.6)))
    (OUT / "brand" / "allectricity-app-icon.svg").write_text(svg(tile(mark(*DARK, 5), .78, 7.04, 5.87)))
    (OUT / "favicon.svg").write_text(svg(tile(favicon_mark(*DARK), .84, 5.12, 3.9)))
