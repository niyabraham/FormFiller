# Security model: what a guarded walk lets out of the browser

This is the reference for the multi-step network guard (`formfill/web/guard.py`, `netpolicy.py`, `sharedworkers.py`). Every
"blocked" and "permitted" line below is backed by a test that runs the same page action without the guard first (a positive
control that must reach a local server) and then with it. Tests: `tests/web/test_network_guard.py`,
`tests/web/test_network_guard_extra.py`, `tests/web/test_wizard_navigation.py`, `tests/web/test_netpolicy.py`. The wizard
benchmark (`tools/evaluate_wizards.py`, 16 scenarios, also run in CI) checks on every walk that each request the local server
received was relayed under a rule and recorded, that answers reached it only under an `answer_data` rule, and that no final
submission arrived.

**Playwright request routing is not a network sandbox, and neither is this guard.** It closes the channels listed under
"Blocked", measured on Playwright 1.64.1 / Chromium 156 (Windows and Linux) and, for the guard tests, Playwright 1.48.0 /
Chromium 130 (Linux). It does not provide absolute isolation; see "Cannot be guaranteed". For a stronger boundary, run the
browser where the operating system or a proxy restricts egress to the portal's origin (outside FormFiller's scope).

## Modes

| mode | how to choose it | what may leave the browser |
|---|---|---|
| `block_all` (default) | `run_form(..., policy=DiscoveryPolicy())` | nothing (see the exceptions under "Cannot be guaranteed") |
| `allow_listed` | `run_form(..., policy=..., network_policy=NetworkPolicy(rules=(AllowRule(...), ...)))` | only HTTP(S) requests matching an explicit rule, relayed by FormFiller |

In `allow_listed` mode the browser context still stays offline. A request that matches a rule is replayed by Playwright's own
request client (`route.fetch`) and its response handed to the page (`route.fulfill`). Redirects are followed by the relay one
hop at a time, and every hop is checked against the rules again (a hop to another origin is refused unless a rule names it).
So the channels that routing cannot see remain blocked in both modes.

A rule names an exact origin, a path glob, methods, optionally resource types, and two explicit permissions:

* `answer_data=True`: the request may carry values FormFiller entered (a background save, a step POST). Without it, any request
  whose URL or body contains an entered answer (4+ characters, case-insensitive, URL- and JSON-decoded) is blocked; so is any
  write method (POST, PUT, ...).
* `form_navigation=True` (requires `answer_data=True`): a Next button that submits a form to this endpoint may be pressed.
  Final-action labels (Submit, Send, Sign, Certify, Accept, Finish, ...) are still never pressed.

## Blocked (both modes)

| channel | how | evidence |
|---|---|---|
| fetch, XHR, `sendBeacon`, images, scripts, CSS, iframes, `EventSource`, `a[ping]`, form navigation, `form.submit()`, `requestSubmit()`, `location` changes, popups' loads | context route aborts (or relays, if a rule allows) | network-guard tests |
| requests from dedicated workers and service workers | context route | network-guard tests |
| requests a caller's own `page.route(...).continue_()` passes through | offline emulation fails them | network-guard tests |
| WebSockets (page, worker, caller pass-through routes) | WebSocket route never connects; offline emulation | network-guard tests |
| `<link rel=prefetch>` | offline emulation | network-guard tests |
| WebRTC STUN/ICE to a UDP listener | offline emulation | `test_webrtc_ice_gathering_is_stopped...` |
| SharedWorker construction (main frame, same- and cross-origin iframes, `srcdoc`, other tabs of the context, `.prototype.constructor`) | in-page fence in every frame plus a context init script | SharedWorker tests |
| SharedWorkers that existed before the walk | put offline through the DevTools protocol (Chromium) | `test_a_shared_worker_created_before_the_walk_is_taken_offline` |
| `WebTransport` construction | the same in-page fence | `test_webtransport_is_refused...` |
| downloads started with `<a download>` (attached or not) | browser-level DevTools request interception (Chromium); these requests bypass routing AND offline emulation | `test_a_download_started_by_next_is_blocked...` |
| redirect hops to another origin during a relayed request | each hop re-checked by the policy | `test_a_relayed_request_is_not_followed_to_another_origin` |
| a page controlled by, or with any registered, service worker | refused before anything is touched | service-worker tests |

Also: browser dialogs are dismissed, never accepted; popups are closed; `submit` events are cancelled by a capturing listener on
`document`; submit-type controls are refused unless a `form_navigation` rule covers the form; commit-labelled buttons are never
pressed; every walk ends `incomplete` or `unconfirmed`, so `run_form(submit=True)` never submits after a walk.

## Permitted

Only in `allow_listed` mode, only requests that match a rule, only as relayed by FormFiller. Each one is recorded in
`navigation.permitted_requests` (scheme, host and path; status; redirect hops; the rule's note; whether it carried entered
answers).

## Monitored and recorded

* `navigation.blocked_requests`: every refused request (scheme, host and path only; the query string may carry form data),
  refused downloads, refused redirect hops, and fenced constructor attempts (`CONSTRUCT` sharedworker/webtransport) made in the
  main frame or a same-origin frame. Any entry stops the walk with `outbound_request_blocked` and keeps the run in review.
* `navigation.permitted_requests`, `navigation.network_mode`, `navigation.network_policy`, `navigation.versions`
  (Playwright and browser), dialogs seen, popups closed, and notes such as `shared_worker_check_unavailable` /
  `download_check_unavailable` when the DevTools protocol is not available.

## Untested

* Real WebTransport traffic (only the constructor fence is tested; no HTTP/3 server was used).
* WebRTC beyond STUN to a local UDP listener (TURN, TCP candidates), DNS prefetch / preconnect, browser extensions.
* An `EventSource` or other long-lived connection opened before the walk (a pre-opened WebSocket was measured: messages sent
  during the walk were not delivered).
* Firefox and WebKit; Playwright versions other than 1.48.0 and 1.64.1; persistent contexts (`launch_persistent_context`).
* Real portals: all evidence is from local fixtures.

## Cannot be guaranteed (known residuals)

* A SharedWorker created during the walk by a script that kept the browser's original constructor from before the walk, with a
  `blob:`/`data:` script, sends what its start-up script sends before it is noticed (measured 8 of 8); the walk then stops and
  reports it. With an `http(s)` script URL the script request is blocked.
* Requests the page makes before the guard starts (its own start-up, anything before `run_form` begins the walk) and requests
  already in flight at that moment are not stopped. No answer has been entered by then, but the page may send what it already
  holds. Measured: the server-backed fixture fetches its first section from an inline script, and that request reaches the
  server after `page.goto` returns; the wizard benchmark waits for network idle so it is not counted as walk traffic.
* Without the DevTools protocol (not Chromium, or a persistent context) pre-existing SharedWorkers cannot be found and
  `<a download>` requests cannot be intercepted; the run carries a note saying so.
* A fenced constructor attempt inside a cross-origin iframe is refused but cannot be reported to the top page.
* In-page measures can be defeated by a page that is deliberately hostile (captured references, timing). The guard targets the
  realistic case: a portal whose own scripts send data when Next is pressed.
* Anything outside the browser process.

## When the guard fails or loses visibility

| situation | outcome |
|---|---|
| a layer cannot be installed (offline emulation, WebSocket route, a SharedWorker that cannot be put offline, DevTools interception that cannot be enabled) | the walk stops with `network_guard_unavailable` before the page is touched; the context's connectivity is put back as the caller had it |
| the guard's WebSocket route cannot be moved back in front of the caller's | `network_guard_unavailable` |
| the DevTools protocol is not available | the walk continues with the other layers and records `shared_worker_check_unavailable` / `download_check_unavailable` |
| an exception escapes `run_form` mid-walk | the guard stays on (fail closed) and the exception carries a note naming `release_wizard_network_guard(page)` |
| a relayed request fails (timeout, error, too large, too many redirects) | the page gets a failed request, the walk records it and stops |
| the context is closed | the guard ends with it; browser-level interception is released, so other contexts are never affected |

The guard is per browser context: every page in the context goes offline (and receives `offline`/`online` events), not only the
walked one. It ends only when the context closes or `release_wizard_network_guard(page)` is called after human review, which
restores the caller's own connectivity setting.

## Unsupported navigation scenarios

The walk stops safely (never "completes") when a portal:

* needs WebSockets, Server-Sent Events from a pre-existing connection, or any non-HTTP channel to move between steps;
* needs requests no rule allows (the default: every request), including step loads, validation calls, and autosaves;
* redirects to another origin mid-walk (single sign-on, OAuth, payment pages) without a rule for that origin;
* places Next inside an iframe or a shadow root, labels it with words outside the allow list, or uses a submit button whose form
  action no `form_navigation` rule covers;
* asks for a CAPTCHA, a login, a file upload, a signature, or any attestation: these are always left to a person and never
  bypassed;
* needs Back navigation in a server-rendered (document) wizard: the Back re-verification pass is for client-side wizards only.
