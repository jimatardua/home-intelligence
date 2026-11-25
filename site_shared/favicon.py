"""Shared browser-tab favicon ("domus" house) for every page served from
domus: `/dashboard/`, `/cigars/`, `/energy-report/`, `/control/`.

Two halves, kept together so the tag markup and the file list can't drift:

- `render_favicon_links()` -- the `<link>` tags, inlined into each page's
  own `<head>` (same convention as `theme`/`nav`).
- `install_favicon_files(output_dir)` -- copies the icon files next to that
  page's `index.html`. Each page's `output/` directory is entirely
  cron/generator-owned and is the only thing nginx serves for that subpath
  (see docs/site-shared.md), so the generator is the one place a static
  file can be put there -- exactly how home_dashboard already ships
  `apple-touch-icon.png`/`manifest.json`.

Hrefs are relative (`favicon.svg`, not `/favicon.svg`): every page lives
under its own subpath and the site root (`/`, and so `/favicon.ico`)
belongs to Home Assistant behind the same nginx proxy, not to us. Every
page is only ever served at its trailing-slash URL (nginx's `location
/dashboard/` etc.), so relative hrefs resolve inside that page's own
directory.

No apple-touch-icon here: only home_dashboard is meant to be installable,
and it keeps its own PWA icon set (generate_pwa_icons.py).

Source art: site_shared/favicon-src/chosen.svg (runner-ups alt-b/alt-c).
Regenerate the files in FAVICON_DIR with the favicon skill's generate.py,
then delete the apple-touch-icon.png it also writes (unused, see above).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

FAVICON_DIR = Path(__file__).resolve().parent / "favicon_files"

# (filename, extra link attributes) -- the single source for both the tags
# and the set of files that must be copied next to the page.
FAVICON_FILES: tuple[tuple[str, str], ...] = (
    ("favicon.ico", 'sizes="48x48"'),
    ("favicon.svg", 'type="image/svg+xml"'),
    ("favicon-32.png", 'type="image/png" sizes="32x32"'),
)


def render_favicon_links() -> str:
    return "\n".join(f'<link rel="icon" href="{name}" {attrs}>' for name, attrs in FAVICON_FILES)


def install_favicon_files(output_dir: Path) -> list[Path]:
    """Copy every favicon file into `output_dir` (atomically, via a temp
    file + rename, so nginx never serves a half-written icon). Returns the
    written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, _ in FAVICON_FILES:
        dest = output_dir / name
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(FAVICON_DIR / name, tmp)
        os.replace(tmp, dest)
        written.append(dest)
    return written
