"""Regenerates the PWA home-screen icons (apple-touch-icon.png, icon-512.png)
baked as base64 constants in `render.py`.

Dev-machine-only tool, never a domus dependency or part of any deploy step
-- same relationship home_dashboard/deploy.sh's Meteocons SVGs have (vendored
once, not regenerated on every run). Needs Pillow (`pip install pillow` in a
throwaway venv; not a runtime dependency of this package, so it's
deliberately not in any requirements/venv the deployed code uses).

This exists specifically to fix a real gap found in this project's history:
the *original* icon generator was never committed -- only its output (the
base64 PNG bytes) survived, baked into render.py with no way to reproduce or
tweak them. This script is the replacement, checked in this time.

Usage:
    python3 home_dashboard/generate_pwa_icons.py
    # prints two base64 strings -- paste over _APPLE_TOUCH_ICON_PNG_BASE64
    # and _APP_ICON_512_PNG_BASE64 in render.py, then re-run that package's
    # tests to confirm nothing else needs updating.
"""

from __future__ import annotations

import base64
import io
import math

from PIL import Image, ImageDraw

# Matches home_dashboard/icons/clear-day.svg's actual fill value (confirmed
# via grep, not re-hardcoded from memory) -- same amber tone as the
# vendored Meteocons "clear-day" icon this glyph is meant to echo.
SUN_COLOR = (0xF8, 0xAF, 0x18)

# Matches site_shared.theme.DARK.bg -- this kiosk is normally dark (passive
# auto-only, no toggle -- see docs/home-dashboard.md), so the home-screen
# icon should read consistently against that, not a color it never
# actually shows adjacent to.
BG_COLOR = (0x0B, 0x0E, 0x14)


def _draw_sun(size: int) -> Image.Image:
    # Supersampled 4x then downscaled -- cheap anti-aliasing for clean
    # circle/ray edges at small icon sizes without a dependency beyond
    # Pillow itself.
    scale = 4
    big = size * scale
    img = Image.new("RGB", (big, big), BG_COLOR)
    draw = ImageDraw.Draw(img)

    cx = cy = big / 2
    core_r = big * 0.22
    ray_inner = big * 0.30
    ray_outer = big * 0.44
    ray_width = big * 0.045

    for i in range(8):
        angle = i * (2 * math.pi / 8)
        dx, dy = math.cos(angle), math.sin(angle)
        px, py = -dy, dx  # perpendicular, for ray width
        x1, y1 = cx + dx * ray_inner, cy + dy * ray_inner
        x2, y2 = cx + dx * ray_outer, cy + dy * ray_outer
        draw.line(
            [(x1 - px * ray_width, y1 - py * ray_width), (x2 - px * ray_width, y2 - py * ray_width)],
            fill=SUN_COLOR,
            width=1,
        )
        draw.polygon(
            [
                (x1 - px * ray_width, y1 - py * ray_width),
                (x1 + px * ray_width, y1 + py * ray_width),
                (x2 + px * ray_width, y2 + py * ray_width),
                (x2 - px * ray_width, y2 - py * ray_width),
            ],
            fill=SUN_COLOR,
        )

    draw.ellipse([cx - core_r, cy - core_r, cx + core_r, cy + core_r], fill=SUN_COLOR)

    return img.resize((size, size), Image.LANCZOS)


def _png_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def main() -> int:
    apple_touch_icon = _draw_sun(180)
    app_icon_512 = _draw_sun(512)

    print("_APPLE_TOUCH_ICON_PNG_BASE64 (180x180):")
    print(_png_base64(apple_touch_icon))
    print()
    print("_APP_ICON_512_PNG_BASE64 (512x512):")
    print(_png_base64(app_icon_512))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
