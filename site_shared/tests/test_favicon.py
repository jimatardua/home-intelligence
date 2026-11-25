from __future__ import annotations

import re

from site_shared.favicon import FAVICON_DIR, FAVICON_FILES, install_favicon_files, render_favicon_links


def test_every_listed_file_exists_and_is_non_empty():
    for name, _ in FAVICON_FILES:
        path = FAVICON_DIR / name
        assert path.is_file(), path
        assert path.stat().st_size > 0, path


def test_file_signatures_match_their_extensions():
    assert (FAVICON_DIR / "favicon.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert (FAVICON_DIR / "favicon-32.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"<svg" in (FAVICON_DIR / "favicon.svg").read_bytes()


def test_links_are_rel_icon_with_relative_hrefs_for_every_file():
    html = render_favicon_links()

    hrefs = re.findall(r'<link rel="icon" href="([^"]+)"', html)
    assert hrefs == [name for name, _ in FAVICON_FILES]
    # Subpath-served pages: the root (and /favicon.ico) belongs to Home
    # Assistant, so no href may be root-absolute.
    assert all(not h.startswith("/") for h in hrefs)
    assert 'type="image/svg+xml"' in html
    assert 'sizes="32x32"' in html


def test_links_never_include_apple_touch_icon():
    # Only home_dashboard is installable; it emits its own touch icon.
    assert "apple-touch-icon" not in render_favicon_links()


def test_install_copies_every_linked_file_byte_for_byte(tmp_path):
    out = tmp_path / "output"

    written = install_favicon_files(out)

    assert sorted(p.name for p in written) == sorted(name for name, _ in FAVICON_FILES)
    for name, _ in FAVICON_FILES:
        assert (out / name).read_bytes() == (FAVICON_DIR / name).read_bytes()
    # No temp files left behind.
    assert not list(out.glob("*.tmp"))


def test_install_overwrites_existing_files_idempotently(tmp_path):
    (tmp_path / "favicon.ico").write_bytes(b"stale")

    install_favicon_files(tmp_path)
    install_favicon_files(tmp_path)

    assert (tmp_path / "favicon.ico").read_bytes() == (FAVICON_DIR / "favicon.ico").read_bytes()
