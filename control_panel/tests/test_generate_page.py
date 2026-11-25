from __future__ import annotations

import re
import sys

from control_panel import generate_page


def test_main_writes_page_and_every_favicon_it_links(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["generate_page", "--output-dir", str(tmp_path)])

    assert generate_page.main() == 0

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    hrefs = re.findall(r'<link rel="icon" href="([^"]+)"', html)
    assert hrefs
    for href in hrefs:
        assert (tmp_path / href).is_file(), href
