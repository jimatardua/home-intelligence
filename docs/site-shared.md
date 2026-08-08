# Shared navigation, theme, and PWA scope across the three dashboards

`site_shared/` is a small, pure-Python-source package providing shared
navigation, light/dark/auto theming, and (a one-line fix, not new
infrastructure) PWA scope correctness across the three sibling static
pages served from `domus`: `home_dashboard` (`/dashboard/`),
`cigar_dashboard` (`/cigars/`), and `energy_report` (`/energy-report/`).

## Why this exists

The three pages were each built independently over time, with no shared
code, no cross-page navigation, and no consistent visual language:
`home_dashboard`/`cigar_dashboard` were dark-only, `energy_report` was
light-only, and none had `prefers-color-scheme`/light-dark support at all.
The user wanted to move between all three, have that navigation keep
working inside the installed `home_dashboard` PWA rather than kicking out
to browser chrome, have all three follow system light/dark/auto
appearance, and have a harmonized look-and-feel instead of three unrelated
designs.

## A real scope correction, not just a design choice

The first draft of this plan proposed shared PWA infrastructure -- a
shared manifest/icon set served from a new nginx location, with a
`ha-proxy` bind mount and container recreation. That was solving a problem
that doesn't exist: only `home_dashboard` should ever be independently
installable as a PWA; `cigar_dashboard`/`energy_report` explicitly should
not gain a manifest/apple-touch-icon link. Cutting that means **this
entire project needed zero nginx changes, zero new bind mounts, and no
`ha-proxy` container recreation** -- confirmed directly after the fact via
`docker inspect ha-proxy --format '{{json .HostConfig.Binds}}'`, byte-for-
byte unchanged from before this feature started. Every page in this repo
is already 100% self-contained inline HTML (no external CSS/JS files
anywhere), so `site_shared` is plain Python source, deployed the same
rsync-only way `energy_report.ha_recorder` is already imported as a
sibling by two other packages -- no cron entry, no nginx location, nothing
ever served directly from it.

## Architecture

```
site_shared/
  theme.py   -- light/dark palettes, CSS custom-property block, FOUC-avoiding
                bootstrap script, and a "watch for OS scheme changes" script
  nav.py     -- shared top nav bar (links + optional light/dark/auto toggle)
```

### Theming

One shared palette (`site_shared/theme.py`): light default, dark applied
via `@media (prefers-color-scheme: dark)`, plus a manual `:root[data-theme="dark"]`/`[data-theme="light"]`
override for the toggle -- no `data-theme` attribute set at all means
"auto." Dark reuses `home_dashboard`/`cigar_dashboard`'s already-tuned
values unchanged; light is a fresh design (loosely referencing
`energy_report`'s old palette, but its accent `#2563eb` is reconciled to
the shared `#4da3ff`, since 2 of 3 pages already used that blue -- one
brand accent across the whole site now, not three competing blues).
`warn` gets a real light/dark pair (`#dc2626`/`#ef4444`), unlike
per-series identity colors (Govee device colors, energy chart dataset
colors), which stay fixed across themes on purpose -- brand/series colors
staying constant while only neutrals swap is normal, defensible practice.

**FOUC avoidance**: `theme.render_theme_bootstrap_script()` is a tiny,
synchronous `<script>` inlined early in `<head>` (before the `<style>`
block) that reads `localStorage` and sets `data-theme` on `<html>` before
first paint -- every other script block in these pages runs at the end of
`<body>`, but this one specifically can't, or the page would flash its
default theme before the saved override applies. Included on `home_dashboard`
too, even though it has no toggle UI of its own to ever write that key --
`localStorage` is shared across all three pages on this origin, so a
choice made on `/cigars/` or `/energy-report/` should still be honored
consistently if that same browser ever loads `/dashboard/`.

**Chart/canvas redraw**: CSS custom properties don't reach into `<canvas>`
(Chart.js, in `energy_report`) or baked SVG attribute strings (the
hand-rolled sparkline/multi-series charts in the other two) -- those need
an explicit redraw on theme change, not just new CSS. `nav.py`'s toggle
dispatches a `themechange` DOM event on click; `theme.render_theme_watch_script()`
dispatches the same event when the OS scheme changes while in `auto` mode
(needed for pages that stay open indefinitely -- `home_dashboard`'s kiosk
in particular, since iOS's system dark mode can auto-switch on a schedule
while the display never reloads). Each page's own script listens for
`themechange` and re-invokes its own draw call from cached last-applied
data (no refetch needed, since the underlying data hasn't changed, only
which colors it should be drawn with) -- `energy_report`'s three
`Chart.js` instances are named (`disaggChart`/`peakChart`/`tempChart`,
previously anonymous) so `.update()` is callable from the listener.

### Navigation

`nav.render_nav_html(active_page, show_toggle=True)` renders the 3 page
links (current page highlighted) plus, when `show_toggle`, the light/dark/auto
control. **Kiosk decision** (confirmed with the user): `home_dashboard`
calls this with `show_toggle=False` -- it's an unattended wall-mounted
iPad, and a tap target there is unnecessary risk to a carefully vh/vw-tuned
single-viewport layout (`overflow:hidden`, no scroll) for a control nobody
will use unattended. It still gets page-switch links, positioned as a
small `position:fixed` corner element (a page-local CSS override of the
shared `.site-nav` class, same pattern as the existing `.battery-corner`)
so it doesn't compete for space in that page's flex-column vh budget at
all -- the other two pages use the shared component's default top-bar
layout unmodified.

### PWA scope fix (not new infrastructure)

`home_dashboard/render.py`'s `render_manifest_json()` changed `"scope": "."`
to `"scope": "/"` -- a one-field edit to the manifest that already existed,
not a new shared asset. Confirmed live: `curl https://domus.ardua.com/dashboard/manifest.json`
shows `"scope": "/"`. On Chrome/Android, an installed PWA's shell enforces
manifest scope on every navigation -- without this, clicking the shared
nav from an installed `home_dashboard` to `/cigars/` would have kicked the
user out to a Custom Tab. On iOS, standalone mode attaches to the
launching browsing context rather than being scope-enforced per
navigation, so this is a no-op there either way -- matching the existing
`orientation: landscape` precedent in the same file, already documented as
a spec-correct no-op on iOS. Real fix for Android, harmless for iOS.
`cigar_dashboard`/`energy_report` gained no manifest/apple-touch-icon link
at all -- explicitly verified via a regression-guard test in both packages'
suites (`rel="manifest"` / `rel="apple-touch-icon"` absent).

## Rollout order and why

`site_shared` first (harmless no-op until consumed), then `energy_report`
(least-frequently-viewed, currently the only light page, so adding dark
there was symmetric net-new work -- lowest risk of visibly breaking an
existing look), then `cigar_dashboard`, then `home_dashboard` last (highest
stakes: the one physical kiosk device, and the toggle/redraw mechanism was
already proven working on the two lower-stakes pages by that point).

## Known risks / things not verified

- **PWA cross-page-nav-stays-standalone on iOS is reasoned from documented
  WebKit behavior, not confirmed on the physical device** -- same
  "confirmed in-browser, not on-device yet" caveat this project has
  applied to every other PWA behavior claim (Wake Lock, "Add to Home
  Screen" icon fidelity, etc. in `docs/home-dashboard.md`). Worth testing
  by tapping the nav links from within the already-installed kiosk PWA the
  next time someone's physically at it.
- **The visual result hasn't been eyeballed in an actual browser** --
  verified via direct HTML/CSS/JS inspection (`curl`, `node --check` on
  every extracted inline `<script>` block) and the full pytest suite
  across all four packages (201 tests), not a screenshot -- the available
  browser-preview tool returned a per-action-approval error this session
  that couldn't be resolved from here. Worth a quick look in a real
  browser, especially the toggle's actual visual states and the
  kiosk's fixed-corner nav placement relative to the hero row.
- **`home_dashboard`'s `.site-nav` corner placement was reasoned about,
  not measured on the physical iPad** -- `top:max(1vh,env(safe-area-inset-top))`
  should sit within the existing `padding:max(4vh,...)` margin above the
  hero row without overlapping it, but this page's layout has historically
  needed real-device iteration (see the PWA/Wake-Lock section of
  `docs/home-dashboard.md`) more than once.
