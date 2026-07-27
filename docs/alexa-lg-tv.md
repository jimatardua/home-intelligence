# Alexa Smart Home support for the LG webOS TV

Native, natural-phrasing Alexa control of the family room's LG 55UM7300AUE
(webOS 4.10.2) -- "turn on/off the TV," "mute the TV," and per-app launching
for Netflix/Plex/Prime Video/Apple TV/YouTube TV/antenna (exact phrasing in
the table below -- several needed a small rename to dodge an Alexa platform
quirk) -- built entirely on Home Assistant's own local `webostv` integration
plus HA's free, self-hosted Alexa Smart Home Skill (not Nabu Casa, not LG's
own cloud-to-cloud skill, which is unusable for this TV). **Fully verified
working end-to-end with real Alexa voice commands** -- see "Status" below.

## Why this exists

LG's direct Alexa integration doesn't work for this TV. Home Assistant
already talks to it locally (no LG cloud involved) via the built-in
`webostv` integration; the only piece missing was a way for Alexa to reach
that control surface at all. HA has exactly one way to do that without a
paid service: the self-hosted Alexa Smart Home Skill, which needs a small
AWS Lambda bridge and (the one real cost of this approach) HA becoming
reachable from the public internet for two specific flows -- covered in
"Known risks" and the infra handoff below.

## Why not a local-only alternative (emulated_hue)

HA's `emulated_hue` integration can expose entities to Alexa over the LAN
only, no cloud, no public exposure. Rejected here specifically because it
only supports on/off (and brightness) -- there's no way to express "mute"
naturally through it, which is one of the explicit target commands for this
project. It would have handled the app-launch commands fine (as fake lights
triggering scripts) but not that one.

## Design

Alexa's `InputController` interface (the normal way `media_player` source
selection reaches Alexa) only recognizes a fixed vocabulary of generic AV
inputs (`HDMI 1`-`10`, `DVD`, `CABLE`, `BLU-RAY`, etc.) -- confirmed against
HA's own Alexa integration docs. It does not accept arbitrary app names, so
"Alexa, turn on Netflix" cannot be wired through source selection. The real
design has two parts instead:

### 1. `media_player.tv` -- a Universal Media Player wrapping the real TV

The real entity from the `webostv` integration,
`media_player.lg_webos_tv_55um7300aue`, does not support `turn_on` at all
(confirmed by decoding its own `supported_features` bitmask: `24381` covers
pause/volume/mute/select_source/stop/play/turn_off, but not turn_on -- and
independently confirmed by reading its config entry in
`.storage/core.config_entries`, which stores only `host` and
`client_secret`, no MAC/WOL config). This matches what HA's own `webostv`
docs say: turning the TV on needs an external mechanism (Wake-on-LAN or
HDMI-CEC), the integration doesn't do it itself.

**First attempt, and the real error it hit**: the obvious-looking fix was a
`template:` `media_player:` block, matching the existing
`template: binary_sensor:` entry already in `configuration.yaml` for the
AC-running sensor. This fails outright -- HA's modern unified `template:`
integration never added `media_player` support; it only covers
sensor/binary_sensor/switch/number/select/etc. domains. Deploying it produced
a real, immediate config error: `'media_player' is an invalid option for
'template'`. The actual currently-supported mechanism for "wrap an existing
media_player and override just one action" is the built-in **Universal
Media Player** (`media_player: - platform: universal`), which is simpler
than what the failed attempt tried to build by hand: any command not
explicitly listed under `commands:` automatically forwards to the (single)
child entity, so only `turn_on` needed overriding --  `volume_mute`,
`volume_set`, `select_source`, and `turn_off` all just work by virtue of the
one `children:` entry, with no manual proxy wiring for each.

```yaml
media_player:
  - platform: universal
    name: "TV"
    unique_id: tv_universal
    device_class: tv
    children:
      - media_player.lg_webos_tv_55um7300aue
    commands:
      turn_on:
        action: wake_on_lan.send_magic_packet
        data:
          mac: "64:95:6C:8C:F5:D6"
          broadcast_address: "192.168.128.255"

wake_on_lan:
```

`media_player.tv` (not the raw `webostv` entity) is what's exposed to Alexa
for `PowerController` and `Speaker` (mute/volume) -- covering "turn on/off
the TV" and "mute the TV" directly, with a real, working power-on for the
first time.

Wake-on-LAN itself was confirmed working at the network level before any of
this HA config existed: a hand-built magic packet sent from domus
(`192.168.128.20`, same `/24` as the TV) to the TV's MAC woke it from a
fully-off state. The TV is wired Ethernet only (Wi-Fi disabled), which is the
more WOL-reliable configuration, and it's on the same L2 segment as domus --
no VLAN boundary for the broadcast to cross.

### 2. Six scripts, one per app/input, exposed to Alexa as scenes

Per HA's own Alexa integration behavior, **scripts are activated by Alexa
with a plain "turn on" utterance** -- exactly the phrasing wanted, no
workaround. Each script:

1. Turns on `media_player.tv` (harmless no-op if already on; sends the WOL
   packet if not)
2. Waits up to 20s for it to report `on`
3. Calls `media_player.select_source` targeting `media_player.tv` with the
   real source name

Source names were read live from `media_player.lg_webos_tv_55um7300aue`'s
`source_list` attribute (Developer Tools -> States) rather than assumed --
notably, this attribute is **not** persisted to HA's recorder database (the
same "HA silently excludes certain attributes from recorder" pattern already
documented for `sun.sun` in `docs/home-dashboard.md`), so it had to be read
from live state, not history.

| Script | Alexa name(s) | Real source name |
|---|---|---|
| `script.tv_watch_netflix` | "Netflix Mode" | `Netflix` |
| `script.tv_watch_plex` | "Plex Mode" | `Plex` |
| `script.tv_watch_prime_video` | "Prime Mode" | `Prime Video` |
| `script.tv_watch_appletv` | "Apple TV" | `Apple TV` |
| `script.tv_watch_appletv_mode` | "Apple Mode" (alias, see below) | -- (delegates to `tv_watch_appletv`) |
| `script.tv_watch_youtubetv` | "YouTube Mode" | `YouTube TV` |
| `script.tv_watch_antenna` | "Live Mode" | `Live TV` |

**The Alexa names above are not what was originally planned** -- the
original one-to-one mapping ("Netflix," "Plex," "Prime Video," "YouTube TV,"
"Antenna TV"/"Live TV") ran straight into a real Alexa platform quirk,
discovered only through live voice testing (see "Known risks" for the full
story): Alexa's own built-in recognition of major media/content brand names
intercepts those exact words before they ever reach our scene, regardless of
phrasing ("turn on X," bare "X," or "activate X" all failed identically for
the affected names). The fix was renaming the affected scenes to add a
disambiguating word ("Netflix" -> "Netflix Mode," etc.) -- confirmed working
for all four cases this way. Apple TV was the one exception: it works fine
under its literal name with "turn on Apple TV," but *not* with the bare
"Alexa, Apple TV" (which Alexa instead tries to route to on-device audio
playback and fails) -- `script.tv_watch_appletv_mode` was added purely so
"Apple Mode" is *also* available, for naming consistency with the other four
apps, without giving up the also-working "Apple TV" phrasing on the original
script.

### `alexa: smart_home:` exposure

```yaml
alexa:
  smart_home:
    filter:
      include_entities:
        - media_player.tv
        - script.tv_watch_netflix
        - script.tv_watch_plex
        - script.tv_watch_prime_video
        - script.tv_watch_appletv
        - script.tv_watch_appletv_mode
        - script.tv_watch_youtubetv
        - script.tv_watch_antenna
    entity_config:
      media_player.tv:
        name: TV
        display_categories: TV
      script.tv_watch_netflix:
        name: Netflix Mode
      script.tv_watch_plex:
        name: Plex Mode
      script.tv_watch_prime_video:
        name: Prime Mode
      script.tv_watch_appletv:
        name: Apple TV
      script.tv_watch_appletv_mode:
        name: Apple Mode
      script.tv_watch_youtubetv:
        name: YouTube Mode
      script.tv_watch_antenna:
        name: Live Mode
```

Deliberately scoped with `include_entities` to just these eight entities --
not the rest of the house -- since there's no reason for Alexa's cloud to
see anything else this integration doesn't need it to.

This config lives only in domus's own `configuration.yaml` / `scripts.yaml`
(not version-controlled in this repo, same as every other HA-side config --
see "File layout" below).

## The AWS Lambda bridge (`alexa_smart_home_bridge/`)

Alexa's Smart Home Skill invokes a Lambda function directly (no API Gateway)
for every directive; the Lambda's only job is forwarding the directive to
HA's `/api/alexa/smart_home` endpoint with the caller's bearer token and
relaying the response back unchanged. Deliberately stdlib-only
(`urllib.request`, not `requests`) -- same stdlib-only-in-production bias as
`energy_report`/`home_dashboard`, and it means the deployed package is just
the one file, no dependency zip to build.

- **`lambda_function.py`** -- the handler. Notably: Alexa puts the bearer
  token in different places depending on directive type (`payload.scope`
  for Discovery, `endpoint.scope` for almost everything else) --
  `_extract_token()` checks both rather than assuming one location.
- **`tests/`** -- 9 passing tests, `urllib.request.urlopen` mocked
  throughout (no live AWS or HA calls). Run via a scoped `.venv`, same
  convention as every other package here.
- **`deploy.sh`** -- zips and pushes code via `update-function-code` once
  the function exists; otherwise prints (does not run) the one-time IAM
  role / function creation / Alexa-invoke-permission steps, since those
  touch a real AWS account.

### What's actually deployed

- Lambda function `alexaSmartHomeBridge`, region `us-east-1`
  (`arn:aws:lambda:us-east-1:539435717249:function:alexaSmartHomeBridge`),
  `BASE_URL=https://domus.ardua.com`
- IAM role `alexa-smart-home-bridge-role` (`AWSLambdaBasicExecutionRole`
  only -- this function needs no other AWS permissions)
- Invoke permission granted specifically to this Alexa skill
  (`amzn1.ask.skill.70d68cbe-5a29-470f-a0a8-01991211512c`), not
  Alexa-connectedhome broadly
- Alexa Smart Home Skill created (dev-mode only, no certification/publishing
  needed for personal use), endpoint pointed at the Lambda ARN above,
  account linking configured: Auth Code Grant, Authorization URI
  `https://domus.ardua.com/auth/authorize`, Access Token URI
  `https://domus.ardua.com/auth/token`, Client ID
  `https://pitangui.amazon.com/` (fixed Amazon-owned value for the US
  region, not self-issued), arbitrary Client Secret (HA doesn't check it),
  "Credentials in request body" auth scheme, `smart_home` scope

## File layout

- `alexa_smart_home_bridge/lambda_function.py` -- the Lambda handler
- `alexa_smart_home_bridge/tests/` -- mocked unit tests
- `alexa_smart_home_bridge/deploy.sh` -- package + push to AWS
- `alexa_smart_home_bridge/.env.example` -- documents `BASE_URL` (informational
  only; the real value is set as a Lambda environment variable via AWS, not
  read from a `.env` file at runtime)
- Everything else (the `media_player.tv` Universal Media Player, the seven
  scripts, `wake_on_lan:`, `alexa: smart_home:`) lives only in domus's own
  `configuration.yaml`/`scripts.yaml` -- this repo doesn't version-control
  the live HA config (confirmed: only `custom_components/` and standalone
  packages like this one are tracked here), so it's documented here in full
  instead of committed as YAML.

## Known risks / things to watch

- **Alexa's built-in recognition of media/content brand names intercepts
  scene names that exactly match one, regardless of phrasing.** Found live,
  not anticipated in the original design: "turn on Netflix," "Alexa,
  Netflix," and "Alexa, activate Netflix" all failed identically with
  "Watching Netflix is not supported on this device" -- Alexa's own
  built-in "watch a video app" intent grabs the recognized brand name before
  it ever reaches our scene. Confirmed to affect Netflix, Plex, Prime Video,
  YouTube TV, and (surprisingly) the literal phrase "Live TV" (itself a real
  broadcast-channel brand name, and also a Fire TV content concept) -- but
  *not* "Apple TV," which behaves as a plain scene name fine. The only
  reliable fix found was renaming the affected scenes to something Alexa
  doesn't recognize as a media brand (the "___ Mode" pattern, confirmed
  working for all five affected names). This is an opaque, undocumented part
  of Alexa's own language routing -- if any of these scenes are ever
  renamed again, re-test each phrasing rather than assuming a new name is
  safe.
- **Cold-boot response timing wasn't specifically stress-tested.** Alexa's
  smart-home directive response window is short (~8s); real voice testing
  so far hasn't isolated a from-fully-off cold boot through Alexa
  specifically (as opposed to the network-level WOL test, which was
  confirmed separately). Worth watching for an occasional "not responding"
  result from Alexa on a command that still causes the TV to turn on a few
  seconds late.
- **Wake-on-LAN depends on the TV staying wired and on the same L2 segment
  as domus.** Both are true today (confirmed: Wi-Fi disabled on the TV,
  same `/24` as domus); if either changes (e.g. TV moved to Wi-Fi, or a
  future network re-segmentation), WOL would need re-verifying.
- **`media_player.tv`'s `commands.turn_on` hardcodes the TV's MAC address**
  (`64:95:6C:8C:F5:D6`). If the TV is ever replaced or its network interface
  changes, this needs updating.

## Status

- [x] `webostv` integration paired with the TV, entity
      `media_player.lg_webos_tv_55um7300aue`
- [x] Wake-on-LAN confirmed working at the network level (magic packet from
      domus wakes the TV from fully off)
- [x] `media_player.tv` (Universal Media Player wrapper) -- turn_on
      confirmed working via WOL, mute/volume/select_source/turn_off
      confirmed working via automatic child passthrough
- [x] Seven per-app/alias scripts, source names confirmed against the TV's
      live `source_list`
- [x] `alexa: smart_home:` component configured and scoped to just the
      eight relevant entities
- [x] `alexa_smart_home_bridge/` Lambda package: code, 9 passing tests,
      deployed to AWS
- [x] Alexa Smart Home Skill created, endpoint set, account linking
      configured
- [x] **Infrastructure handoff complete** -- `domus.ardua.com` is publicly
      reachable (public DNS -> pfSense NAT -> sideshowbob nginx vhost ->
      existing domus `ha-proxy`, full passthrough, no HA-side
      `trusted_proxies` change needed). See
      `docs/infra-handoff-alexa-lg-tv.md` for the full return handoff.
- [x] **Verified end-to-end with real Alexa voice commands**: account
      linking completed, all 7 scenes discovered, and every target command
      confirmed working by voice -- "turn on/off the TV," "mute the TV,"
      and app launching for all six apps/inputs (five under a "___ Mode"
      name due to the brand-name collision above, plus "Apple TV" under its
      original name and an added "Apple Mode" alias for naming
      consistency).
