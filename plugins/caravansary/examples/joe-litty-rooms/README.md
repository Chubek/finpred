# Joe Litty Rooms — CaravanScript profile reference

[`reference.caf`](reference.caf) shows how to record the requested Booking.com
profile URL in a market script **without fetching it**. It is a parse-only
example, not a configured market workflow. The real URL appears only as inert
`profile_url` metadata. Neither fixture ID resolves to a supplied capture, and
there is no host grant, scheduled job, or pricing evidence for this property.

## Public logistics

Sources observed **2026-11-26**:

| Field | Source and qualification |
| --- | --- |
| Name and address | [It-RomeHotels](https://joe-litty-rooms.it-romehotels.com/) lists Joe Litty Rooms at Via Giovanni Giolitti 255, Rome, Italy. [Lazio Hotels](https://hotelgalliaroma.com/hotel-rome-710.html) corroborates the street and city and gives postal code 00185. These are public third-party listings, not operator verification. |
| Booking reference | The [requested Booking.com URL](https://www.booking.com/hotel/it/joe-litty-rooms.html) yielded no readable listing on direct fetch. The [public search index preview](https://html.duckduckgo.com/html/?q=%22Joe+Litty+Rooms%22) showed the exact URL and the title “Joe Litty Rooms, Rome”. No access controls were bypassed. |
| Civil timezone | [IANA tzdb `zone.tab`](https://data.iana.org/time-zones/tzdb/zone.tab) lists `IT` as `Europe/Rome`. The market dialect has no timezone field; the script records this as a comment. |
| Currency | The example chooses `EUR` as its reporting currency; [Council Regulation (EC) No 974/98, Articles 1–2](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A31998R0974) lists Italy and defines 100 cents per euro. This says nothing about any particular offer's currency. |

The required WGS84 strings `41.90`, `12.48` are a **coarse city reference**
rounded from IANA's `+4154+01229` entry; they are not a geocode of the address.
`type = "unverified"` does not affirm the directories' hotel/star labels or
any licensed property class. An operator needs to verify a property pin and
classification before using either in comparable selection. The mandatory
discovery radius and candidate limit are illustrative, the two `unbound-*`
IDs are placeholders, and 1–2 euro cents are schema-only pricing bounds,
**not observed rates, suggested bounds, or a recommendation**. No prices,
inventory, occupancy, or availability are recorded in the example.

## Offline validation

From the repository root with the pinned `on1xc` already built:

```sh
sh plugins/caravansary/examples/joe-litty-rooms/check.sh
```

By default, the check compiles with Clang into an isolated
`build/caravansary/W7/` tree.
It parses the local script, checks that the profile URL stays in the metadata,
then runs the local `scrape` command with an empty host-grant registry. The
command must fail authorization without an artifact or any capture attempt.
The check does not need credentials or a network connection. It uses `ON1XC`
if set; otherwise it resolves the normal MuLIB build directory. To select the
isolated pinned compiler, set `FINPRED_MULIB_BUILD_DIR=build/caravansary/toolchain`.

If the market CLI is already deployed, use `--reuse-market` to skip rebuilding
it while still compiling the parser check and testing grant denial. This uses
the launcher's usual `FINPRED_BUILD_DIR` (default `build/dev`):

```sh
FINPRED_BUILD_DIR=build/caravansary/W7/out \
  sh plugins/caravansary/examples/joe-litty-rooms/check.sh --reuse-market
```

For a **successful fictional replay instead**, use the separate [Canal Market
workflow](../workflows/README.md) and its explicit host grants:

```sh
examples=plugins/caravansary/examples
workflows=$examples/workflows
FINPRED_BUILD_DIR="${FINPRED_BUILD_DIR:-build/caravansary/W7/out}" \
  bin/caravansary scrape "$workflows/canal-market.caf" --source booking_profile \
    --input-root "$examples" --host-grants "$workflows/host-grants.json" \
    --as-of 2026-11-26T10:00:00Z
```

Its `booking.example` capture and resulting report have no connection to Joe
Litty Rooms. Do not point its grants at `reference.caf` or treat a fixture
result as an observation about this property.
