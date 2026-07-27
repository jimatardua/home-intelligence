# Infra handoff: public reachability for Alexa Smart Home (LG TV project)

**From:** `home-intelligence` **To:** `infrastructure`

All the work possible inside `home-intelligence` for native Alexa control of
the family room LG TV is done (see `docs/alexa-lg-tv.md` for the full
writeup) and stops here, per our usual split: this repo doesn't own public
ingress, reverse proxies, certs, or DNS, and shouldn't guess at how the
`infrastructure` repo wants to implement changes to them.

## What needs to change, and why

Home Assistant's self-hosted Alexa Smart Home Skill (the free, non-Nabu-Casa
path -- a hard requirement here) needs **`domus.ardua.com` reachable over
HTTPS from the public internet**, for two specific server-to-server calls
that cannot be satisfied any other way:

1. **OAuth token exchange during account linking.** When "Enable skill" is
   tapped in the Alexa app, Amazon's own servers call HA's `/auth/token`
   directly, server-to-server -- not through the user's phone/browser. There
   is no LAN-only or VPN-only way to satisfy this; Amazon's servers have no
   path onto the home network.
2. **Runtime directive delivery.** Every voice command ("turn on the TV,"
   etc.) results in an AWS Lambda function (already deployed, in our own
   AWS account, not infrastructure's concern) calling HA's
   `/api/alexa/smart_home` endpoint directly. Same constraint -- this call
   originates from AWS, not the home network.

Both are hard requirements of the Alexa Smart Home Skill architecture itself,
not a design choice made in this project.

## What's already true on the domus side (may simplify your decision)

domus already runs a local `ha-proxy` container (`nginx:alpine`) terminating
TLS for `domus.ardua.com` with a real Let's Encrypt cert, and it already
reverse-proxies the **entire** HA application (`location / { proxy_pass
http://127.0.0.1:8123; ... }`, full `X-Forwarded-*` headers, WebSocket
upgrade support already configured) -- not a scoped subset of paths. HA's own
`http:` config already trusts this local proxy
(`trusted_proxies: [127.0.0.1]`).

Concretely, this means:

- **The "should exposure be scoped to just `/auth/*` and
  `/api/alexa/smart_home`" question is not something we're asking you to
  solve inside HA** -- there's no path-level scoping happening at the domus
  layer today; the whole app is already behind one local proxy. If you want
  to scope what's publicly reachable, that's a decision entirely at your own
  layer (sideshowbob/sideshowmel), and worth testing carefully before
  committing to it: `/auth/authorize` serves an actual HTML login page,
  which likely needs HA's frontend static assets to render and submit
  correctly, so a naive "just these three paths" allowlist could leave the
  login page broken. We're flagging this as a real risk to test, not
  handing you a scoping requirement.
- **If your chosen path continues to terminate at this existing local
  `ha-proxy` container** (rather than some other proxy hitting HA's
  port 8123 directly), **no change is needed to HA's `trusted_proxies`
  config at all** -- it already trusts 127.0.0.1, which is the only hop that
  ever touches HA directly today, regardless of how many proxy hops exist
  upstream of that.
- **If your design instead has some other host/container hit HA's port 8123
  directly** (bypassing the existing local `ha-proxy`), then HA's
  `trusted_proxies` would need to include that host's address as seen at
  domus's network interface, and `home-intelligence` needs that address from
  you before we can finish that one config line.

## What we need back from you

1. Confirmation that `https://domus.ardua.com` (or whatever hostname you
   choose) is reachable from the public internet, terminating however your
   own architecture review determines is best.
2. If the answer to the "existing `ha-proxy` stays the single direct hop to
   HA" question above is no: the actual address `home-intelligence` should
   add to HA's `http: trusted_proxies:`.
3. Anything about the chosen approach that changes what we should expect
   (e.g. if you scope exposure to a subset of paths and it turns out the
   login page needs more than the three bare endpoints, we'd want to know
   before assuming account linking will just work).

Once we have that, `home-intelligence` will do the actual account-linking
test (enable the skill in the Alexa app) and confirm real voice commands
reach HA end-to-end, then update `docs/alexa-lg-tv.md`'s status section.

## Return handoff received -- closed out

`infrastructure` confirmed back:

```
Amazon -> domus.ardua.com (public DNS CNAME -> home WAN IP)
        -> pfSense NAT:443 -> sideshowbob:443 (new nginx vhost, Let's Encrypt cert)
        -> domus.ardua.lan:443 (existing ha-proxy, unchanged)
        -> 127.0.0.1:8123 (HA)
```

- Existing `ha-proxy` stays the single direct hop to HA -- no
  `trusted_proxies` change needed, as anticipated above.
- No path scoping -- full proxy, same pattern as `books.ardua.com`; login
  page and static assets confirmed reachable.
- Cert: `domus.ardua.com` (Let's Encrypt, valid through Oct 25, auto-renews
  via certbot).

Account linking tested for real in the Alexa app and completed successfully;
all 7 scenes discovered. Every target voice command verified working --
see `docs/alexa-lg-tv.md`'s "Status" section for the full result. This
handoff is closed.
