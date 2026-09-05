# Kroger internal coupon API — recon

Findings as of 2026-09-05. Unofficial, undocumented, subject to change without
notice. Confidence tags are from source inspection of working third-party
implementations, not from Kroger.

## Endpoints

Base host is the Banner domain (`www.kroger.com`, `www.frysfood.com`,
`www.marianos.com`, `www.harristeeter.com` — same gateway, same paths).

| Method + Path | Purpose | Confidence |
| --- | --- | --- |
| `GET /atlas/v1/savings-coupons/v1/coupons` | Enumerate coupons | Confirmed, 4 independent repos |
| `POST /atlas/v1/savings-coupons/v1/clip-unclip` | Clip/unclip ONE coupon | Confirmed, 2 independent repos |
| `GET /atlas/v1/savings-coupons/v1/coupons?filter.krogerCouponNumber=…&filter.type=standard&projections=coupons.full` | Coupon detail incl. qualifying UPCs | Confirmed |
| `POST /atlas/v1/modality/preferences?filter.restrictLafToFc=false` | Resolve current store to a LAF object | Confirmed, 2 repos |
| `POST /atlas/v1/modality/options` | Store search by ZIP | Confirmed |

`clip-unclip` body: `{"action": "CLIP" | "UNCLIP", "couponId": "<id>"}`.

**There is no batch clip endpoint.** One POST per coupon.

The `/p/np/4230/Kroger/coupon/clip` endpoint seen in older tools is the
pre-2018 SoftCoin-era API and is dead. It is the origin of the widely repeated
"first 150 coupons, sorted by relevance" folklore.

## Query parameters on the enumerate endpoint

`projections=coupons.compact` · `filter.status` (repeatable: `unclipped` /
`active` / `redeemed`) · `page.size` · `page.offset` · `filter.sort`
(`relevance` / `recent` / `expiration` / `value`) · `filter.category`
(repeatable) · `filter.modality` (`IN_STORE` / `PICKUP` / `DELIVERY`) ·
`filter.specialSavings` · `filter.searchString` · `filter.onlyNewCoupons` ·
`filter.upc` · `filter.type` (`standard` / `cash_back`)

Response: `data.coupons[]`, `meta.coupons.page.hasMore`,
`meta.coupons.filterSummaryByType.{totalCount, newCouponsCount, categories, specialSavings}`.

## Coupon object fields

`id`, `krogerCouponNumber`, `brand`, `brandName`, `title`, `shortDescription`,
`displayDescription`, `requirementDescription`, `expirationDate`,
`displayStartDate`, `displayEndDate`, `addedToCard`, `canBeAddedToCard`,
`canBeRemoved`, `categories[]`, `modalities[]`, `specialSavings[]`, `imageUrl`,
`upcs[]` (full projection only).

`addedToCard` is the already-clipped flag. There is no numeric discount value in
the compact projection — the amount is prose in `shortDescription`.

## Authentication

Cookie-based only. No `Authorization` header, no bearer token, no CSRF header in
any of six independent implementations. Login goes through Azure AD B2C at
`login.kroger.com`, but the SPA does not carry a token forward — it relies on the
session cookie set on the Banner domain.

Beyond cookies, the API requires store context as headers: `x-laf-object` (JSON
describing store/modality/fulfillment), `x-facility-id` (8-digit location id,
first 3 digits are the division), `x-modality`, `x-modality-type`,
`x-kroger-channel: WEB`, plus browser-shaped `sec-fetch-*` and a matching
`referer`. Missing `sec-fetch-*` or `referer` yields 403.

The specific session cookie name is **not** established — every working
implementation ships the entire cookie jar for the domain. A `KRGRHH` cookie name
appears in some web-search summaries with no primary evidence behind it; treat it
as unverified.

## Bot protection

Akamai Bot Manager, blocking at the TLS/HTTP fingerprint layer *before* any HTTP
status is returned. Verified directly during recon: `curl` over HTTP/2 to
`www.kroger.com` gets `RST_STREAM INTERNAL_ERROR` mid-response; over HTTP/1.1 it
hangs to timeout; Python `urllib` times out identically; a control host returns
200 instantly.

Akamai cookie set observed: `_abck`, `bm_sz`, `bm_sv`, `bm_s`, `bm_so`, `bm_ss`,
`bm_mi`, `bm_lso`, `ak_bmsc`, `AKA_A2`, `akaalb_KT_Digital_BannerSites`. Also
Dynatrace (`rxVisitor`, `dtCookie`, `dtPC`) and Kroger's own `DD_modStore`,
`x-active-modality`, `abTest`.

Consequence: a stock Python HTTP client cannot reach this API at all, regardless
of cookies. Working approaches are (1) `curl_cffi` with a browser
`impersonate` profile, (2) browser warmup then hand cookies + UA to an HTTP
client, or (3) issue the JSON calls from inside a real browser page context.

## Store scoping

Coupon availability is store-dependent. The enumerate endpoint returns HTTP 500
for a category unavailable at the active store. The current store is resolvable
at runtime from the modality preferences endpoint, so it need not be configured.

## Confirmed by a real sign-in (2026-09-05)

A successful `login` against a live account captured 49 cookies and settled
several of the questions below.

- **`/accountmanagement/api/profile` is dead** — it returns HTTP 404. Inherited
  from the older kroger-cli; do not use it as an auth check.
- **There is no `KRGRHH` cookie.** The name appears in web-search summaries with
  no primary source. It was not present in the real jar. Treat it as fabricated.
- **Session-identity candidates**: `kroger-si-customer-data-token`, `loggedIn`,
  `JSESSIONID`, plus the Azure B2C pair `x-ms-cpim-sso:eciamp.onmicrosoft.com_0`
  and `x-ms-cpim-csrf`.
- **Akamai set present as documented**: `_abck`, `ak_bmsc`, `bm_sz`, `bm_s`,
  `bm_so`, `bm_sv`, `bm_sc`, `bm_lso`, `AKA_A2`.
- **Dynatrace cookies carry a per-install suffix** (`dtCookieg9i8dbl7`,
  `rxVisitorg9i8dbl7`, …), so never match these by exact name.
- **Store context is partly in cookies**: `DD_modStore`, `DivisionID`,
  `StoreCode`. Worth checking whether these remove the need to call the modality
  endpoint before enumerating.
- **Akamai rate-limits by IP**, returning a JSON body with `message: "Too many
  requests"` and the caller's IP. Six browser sessions within a few minutes was
  enough to trigger it. It cleared without intervention.

## Ground truth: the request the SPA actually makes

Observed by attaching to a real signed-in browser and watching the coupons page
issue its own call. Returned HTTP 200.

```
GET /atlas/v1/savings-coupons/v1/coupons
    ?projections=coupons.compact
    &filter.status=unclipped&filter.status=active
    &page.size=24&page.offset=0
```

Headers that matter (cookies omitted):

| Header | Example |
| --- | --- |
| `x-facility-id` | `09900999` (synthetic; the real value is store-identifying) |
| `x-modality-type` | `IN_STORE` |
| `x-modality` | `{"type":"IN_STORE","locationId":"09900999"}` |
| `x-laf-object` | JSON array with `modality`, `handoffLocation.storeId`/`facilityId`, and the store's postal address |
| `x-kroger-channel` | `WEB` |
| `referer` | `https://www.kroger.com/savings/cl/coupons/` |

`filter.status` is repeated, not comma-joined. `page.offset` is sent explicitly.
A request omitting the store headers and `page.offset` returns **HTTP 400 with an
empty body** — a malformed-request signal, not an auth failure.

Also present but treated as telemetry and deliberately not replayed:
`traceparent`, `tracestate`, `x-dtpc`, `x-ab-test`, `x-call-origin`,
`user-time-zone`, and the `sec-ch-*` client hints.

Because the browser already assembles `x-laf-object`, `login` captures these
headers from a real request rather than rebuilding them from the modality
endpoint. `x-laf-object` contains the store's street address, so it is
PII-adjacent: it lives in the mode-0600 session file and must be scrubbed from
any committed fixture.

## Open questions requiring an authenticated session

- Name of the actual session cookie.
- Whether enumerate works anonymously (clip certainly does not).
- `clip-unclip` response body, and its behavior for already-clipped, expired, and
  household-limit-rejected coupons. Every known implementation checks only
  `res.ok` and parses nothing.
- Server-side cap on total clipped coupons, if any.
- Rate-limit tolerance for N sequential clip POSTs. This is the largest practical
  unknown.
- Maximum accepted `page.size`.
- Akamai cookie lifetime before a browser re-warm is required.
