# Offline Booking and Agoda provider fixtures

These are fictional, frozen captures used to qualify Caravansary's fixture
extractors, not copies of live provider responses. No request is sent to Booking,
Agoda, or any other service. The `.example` URLs are identifiers; the adapter
does not open paths, contact hosts, follow links, publish data, or authenticate.

| Fixture ID | Operation | Approved source URL |
|---|---|---|
| `booking-candidates` | `candidates` | `https://booking.example/fixtures/candidates` |
| `booking-profile` | `profile` | `https://booking.example/fixtures/profile` |
| `booking-variant` | `candidates` | `https://booking.example/fixtures/variant` |
| `agoda-candidates` | `candidates` | `https://agoda.example/fixtures/candidates` |
| `agoda-profile` | `profile` | `https://agoda.example/fixtures/profile` |
| `agoda-sparse` | `candidates` | `https://agoda.example/fixtures/sparse` |

Each ID corresponds to the same basename with `.html`. Fixtures can be read
only after a trusted application has selected and approved the exact local
file; when using a registry, verify the captured bytes against its approved
SHA-256 before passing the bytes to the adapter.

## Native interface

`plugins.caravansary.stdlib.provider.adapter.run_fixture(request, html, grant)`
accepts an immutable planning JSON value, already-loaded HTML bytes as an On1x
string, and an independently selected `FixtureGrant` from `provider.api`.
The request requires a versioned kind, provider, operation, fixture ID, URL
and explicit UTC clock. For example:

```json
{
  "kind": "provider-request/v1",
  "mode": "fixture",
  "provider": "booking",
  "operation": "candidates",
  "fixture_id": "booking-candidates",
  "source_url": "https://booking.example/fixtures/candidates",
  "observed_at": "2026-11-26T12:00:00Z"
}
```

The host-supplied grant contains `provider`, `fixture_id`, `source_url`, and
`max_body_bytes` (1–65536), and must match the request exactly. When provided,
`elvi_source` must be a document/capture declaration for the same provider
label, host, and URL. Cookies are rejected. Otherwise the adapter constructs
that declaration. Declarations never authorize captures.

Both providers implement `Provider<ProviderFacts>` using different typed
parsers. The common `run_provider<T>` runs the pinned MuLIB `Probe<T>` over an
authorized in-memory Elvi capture. The synthetic metadata satisfies the
capture value's schema but never appears as evidence of an HTTP or TLS
transaction. Probe parses bytes through the pinned HTML runtime and discards
the optional artifacts.

Success is `provider-observation/v1` with `provider`, `operation`,
`provenance`, and `properties`. Provenance includes `fixture_id`, `source_url`,
`observed_at`, `content_sha256`, `extractor` and the qualification
`fictional-frozen-html`. Errors are `provider-error/v1` with a `code`; scope
errors and unsupported modes do not resemble empty captures.

## Facts and limits

- Property rows contain `property_id`, `url`, and `offers`. When the markup
  has no provider-assigned ID, the accepted URL serves as an exact
  provider-local key, not evidence of a global property identity. Listing
  URLs are bounded to 256 bytes.
  Only marked same-host links with plain path segments are accepted. A
  link is never followed, including search pagination links.
- Optional property fields: `name`, `address`, `latitude`, `longitude`,
  `property_type`, and `amenities`. Coordinates are bounded WGS84 decimal
  strings with at most eight fractional digits. A missing field is omitted;
  a marked but unusable or ambiguous field is `null`.
- Offers can report `amount_minor`, `currency`, `price_basis`, and
  `availability`. A reported integer minor amount takes precedence over
  displayed text; when neither amount nor currency attributes are present,
  plain text like `GBP 120.50` can be converted exactly using the stated
  currency's minor units. This dialect admits USD, SGD, EUR, GBP, and JPY
  only. It does not convert currencies, infer price basis, or infer
  availability from price, offer presence, or the absence of a rate.
  These fixtures do not establish stay context, taxes, meal, cancellation,
  or qualifications for pricing projections.
- `offers:[]` means no offer markers were found; it does not mean the property
  is unavailable. A successfully empty candidate result requires an explicit
  empty-results marker. Unknown markup, a profile without a safe link, or
  candidate markup with no safe links is an error.
- Rows and offers retain document order. Exact duplicate rows collapse.
  Nonidentical rows with the same ID remain available for downstream conflict
  handling; different IDs for one URL return an identity error.
- These selectors cover the snapshot dialect illustrated here, including
  alternate title/offer markers and Agoda anchors wrapping a property title.
  They do not qualify current provider markup, JavaScript rendering, redirects,
  cookies, API sandboxes, or live provider transport.

## Qualification

With the pinned Clang-built On1x compiler available, run:

```sh
sh plugins/caravansary/examples/providers/check.sh
```

The runner uses only local fixtures and Clang. It defaults to
`build/caravansary/toolchain/on1xc`, and `ON1XC` can point to an equivalent
pinned compiler. The complete C11 bridge and kernel link recipe is in that
script. Use one MuLIB kernel implementation translation unit when integrating
the provider adapter.
