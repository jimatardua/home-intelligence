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
  battery.py -- ok / low / not-reporting status for battery-powered sensors,
                shared by home_dashboard's battery strip and cigar_dashboard's
                cards (see docs/home-dashboard.md, "Battery strip")
  favicon.py -- shared browser-tab icon (a house): <link rel="icon"> tags and
                install_favicon_files(), which copies favicon_files/* next to
                each page's index.html (see "Favicon" below)
  favicon_files/ -- favicon.ico / favicon.svg / favicon-32.png (generated)
  favicon-src/   -- source art: chosen.svg plus runner-ups alt-b/alt-c.svg
```

`battery.py` is the one module here that isn't pure presentation: it reads
the recorder (via `energy_report.ha_recorder`), because the threshold, the
grace period and the wording all have to be identical on both pages, and
this is the only package both already import.

### Theming

One shared palette (`site_shared/theme.py`): light default, dark applied
via `@media (prefers-color-scheme: dark)`. Every page always follows the
OS setting -- there is no manual override anywhere (see "Auto-only
theming" below for why that changed from the original toggle design); the
CSS still carries a `:root[data-theme="dark"]`/`[data-theme="light"]`
manual-override rule for completeness, but nothing sets that attribute
anymore, so it's currently unreachable. Dark reuses `home_dashboard`/
`cigar_dashboard`'s already-tuned values unchanged; light is a fresh
design (loosely referencing `energy_report`'s old palette, but its accent
`#2563eb` is reconciled to the shared `#4da3ff`, since 2 of 3 pages
already used that blue -- one brand accent across the whole site now, not
three competing blues). `warn` gets a real light/dark pair
(`#dc2626`/`#ef4444`), unlike per-series identity colors (Govee device
colors, energy chart dataset colors), which stay fixed across themes on
purpose -- brand/series colors staying constant while only neutrals swap
is normal, defensible practice. `caution` (`#b45309`/`#f5a524`, added
2026-11-18) is the amber step below `warn` -- "act soon" rather than
"something is wrong"; currently used only for low batteries.

### Auto-only theming (no manual toggle)

The original design had a light/dark/auto toggle on `cigar_dashboard`/
`energy_report` (the kiosk was excluded from the start -- see "Swipe
navigation" for how that reasoning has since shifted). After using it
live, the preference turned out to be simpler: always follow the OS,
everywhere, no manual override at all. `nav.render_nav_html()` no longer
takes a `show_toggle` parameter -- the toggle HTML/CSS/click-handling
script was deleted outright rather than defaulted off, since no caller
would ever request it again.

`theme.render_theme_bootstrap_script()`'s job changed with it: it used to
read `localStorage` and apply a saved override before first paint (FOUC
avoidance for the toggle). With no toggle left to ever write that key
again, it now actively clears any leftover value instead -- otherwise
anyone who'd clicked "Dark"/"Light" before this change would stay stuck
in that manual override forever, with no UI left to undo it. Still
inlined early in `<head>` on every page, same insertion point as before.

**Chart/canvas redraw**: CSS custom properties don't reach into `<canvas>`
(Chart.js, in `energy_report`) or baked SVG attribute strings (the
hand-rolled sparkline/multi-series charts in the other two) -- those need
an explicit redraw on theme change, not just new CSS.
`theme.render_theme_watch_script()` dispatches a `themechange` DOM event
whenever the OS scheme changes while a page is open -- now the *only* way
that event ever fires, since there's no toggle click to dispatch it
anymore -- and `nav.render_nav_html()` includes it unconditionally on
every page (previously bundled inside the toggle's own markup, which
meant the kiosk had to include it via a second, separate call; that's
gone now that there's only one code path). Needed for pages that stay
open indefinitely -- `home_dashboard`'s kiosk in particular, since iOS's
system dark mode can auto-switch on a schedule while the display never
reloads. Each page's own script listens for `themechange` and
re-invokes its own draw call from cached last-applied data (no refetch
needed, since the underlying data hasn't changed, only which colors it
should be drawn with) -- `energy_report`'s three `Chart.js` instances are
named (`disaggChart`/`peakChart`/`tempChart`, previously anonymous) so
`.update()` is callable from the listener.

### Navigation

`nav.render_nav_html(active_page)` renders links for every page in
`PAGES` (current page highlighted) -- 4 as of `control_panel`'s addition
(`docs/control-panel.md`), originally 3. No manual light/dark/auto
control exists anywhere -- see
"Theming," below -- so every page uses the shared component's default
top-bar layout unmodified, including the kiosk (`home_dashboard`), which
originally had its own small-corner CSS override for a now-removed
toggle-avoidance reason. That override still exists (see "Swipe
navigation" below for why) but the *reason* for it changed.

### Swipe navigation

`nav.render_swipe_nav_script(active_page)` -- a horizontal touch swipe
past a threshold navigates to the next/previous page in `PAGES`' fixed
order (Home <-> Cigars <-> Energy <-> Control). This is a real page
navigation (full reload), not an animated slide-over -- these are
separate static pages, not a single-page app, matching every other page
in this repo (`control_panel` included, despite talking to a live
backend -- see `docs/control-panel.md`); building a true slide transition
would mean loading all of them
simultaneously (iframes or a full SPA rewrite), a real architecture
change for a cosmetic win. Reuses the same PWA-scope fix below, so it
stays inside the installed app rather than kicking out to browser chrome.

Neighbor computation (`_neighbor_hrefs()`) is pure and unit-tested
separately from the JS it feeds -- the script itself is a small, generic
touchstart/touchend handler with no page-specific logic, consuming
whatever `prevHref`/`nextHref` string literals (or `null` at either end)
Python computed. No wraparound: swiping past the last page does nothing
rather than surprise-landing back at the first.

**Confirmed working on a real iPad.** Prompted by that live test, the
same script also hides `.site-nav` entirely on any touch-capable device
(`'ontouchstart' in window || navigator.maxTouchPoints > 0`) -- once
swipe works, the link row is redundant there, and hiding it (rather than
reskinning it small, which is what the kiosk's own corner-CSS override
originally did for a different reason -- fitting inside its hand-tuned
100vh layout) is what actually makes every page's look consistent on an
iPad/iPhone: nothing shows on any of them (including `control_panel`,
added after this was written -- same behavior, no extra work needed). Non-touch visitors (e.g. a
laptop browser loading these URLs directly) keep the visible links, since
swipe isn't available to them as a substitute -- `cigar_dashboard`/
`energy_report` are still meant to be normally browsable, not touch-only.
The kiosk's small-corner nav styling still exists as that same non-touch
fallback, even though the actual kiosk hardware (always touch) now hides
it outright rather than ever showing it small.

Threshold (`_SWIPE_MIN_PX = 60`, off-axis ratio `0.5`) is a starting
point, not a measured value, but the gesture itself -- and the touch-hide
behavior -- are both confirmed working end-to-end on a real touch device,
not just inferred from static checks: booted an iPad Air simulator
(`xcrun simctl boot`, after fixing `xcode-select` to point at the
newly-installed Xcode.app rather than the command-line-tools path) and
confirmed by screenshot on all three live pages that `.site-nav` is fully
hidden, plus a real swipe gesture (`iPad Air 11-inch (M3)`, 820x1180pt
coordinate space) navigating correctly in both directions
(Cigars -> Energy on a left swipe, Energy -> Cigars on a right swipe).
Unit tests for the neighbor computation and script content, `node --check`
on every script block, and live `curl` confirmation of the correct
`prevHref`/`nextHref` values round out the coverage.

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

### Favicon

All four pages (`/dashboard/`, `/cigars/`, `/energy-report/`, `/control/`)
share one tab icon, so they're recognizable in a tab bar but not
distinguishable from each other. `favicon.render_favicon_links()` emits
three `rel="icon"` tags (ico, svg, 32 px png) with **relative** hrefs, and
each page's generator calls `favicon.install_favicon_files(output_dir)` to
copy the files next to its `index.html` -- the same "the generator is the
only way to put a static file in output/" mechanism home_dashboard already
uses for its manifest. No nginx change, no new bind mount.

- **No root `/favicon.ico`.** The root of domus.ardua.com belongs to Home
  Assistant (ha-proxy's catch-all `location /`), so Safari's direct
  `/favicon.ico` request still gets HA's icon; the per-page link tags are
  what override it.
- **No apple-touch-icon from here.** `cigar_dashboard`/`energy_report`/
  `control_panel` deliberately stay non-installable (see above), and
  `home_dashboard` keeps its own PWA touch icon (`generate_pwa_icons.py`).
- **Deploy order matters:** `site_shared/deploy.sh` must run before (or
  with) any page's deploy, or that page's generator fails on
  `import site_shared.favicon`. control_panel's static shell must be
  regenerated once by hand (`generate_page.py`); the other three pick the
  icon up on their next cron run.
- To regenerate the files from `favicon-src/chosen.svg`, use the favicon
  skill's `generate.py` into `favicon_files/`, then delete the
  `apple-touch-icon.png` it also writes (unused).

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
- **The visual result has now been confirmed on a real touch device.**
  Earlier in this project, the visual result had only been checked via
  `curl`/`node --check`, not a screenshot -- the available browser-preview
  tool returned a per-action-approval error that couldn't be resolved.
  That gap is closed for the nav-hide/swipe behavior specifically: booted
  an iPad Air simulator (Xcode wasn't fully installed earlier in this
  project; it is now), loaded all three live pages, and confirmed by
  screenshot that `.site-nav` is fully hidden on all three (including the
  kiosk) and that a real swipe gesture navigates correctly in both
  directions. The kiosk's fixed-corner nav placement relative to the hero
  row specifically was not re-checked, since it's now hidden outright on
  any touch device rather than shown small -- see the next point.
- **`home_dashboard`'s `.site-nav` corner placement is now a non-touch
  fallback only, not something the actual kiosk hardware ever shows** --
  on the real wall-mounted iPad (always touch), the nav is hidden
  entirely by the touch check, so `top:max(1vh,env(safe-area-inset-top))`
  potentially overlapping the hero row only matters for the rare case of
  loading this URL from a non-touch browser, not the kiosk itself. Not
  re-verified against the physical iPad specifically, but lower stakes
  than when it mattered on every kiosk load.
