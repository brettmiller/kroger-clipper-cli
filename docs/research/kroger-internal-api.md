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
