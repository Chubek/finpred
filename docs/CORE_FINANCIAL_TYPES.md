# Checked financial types in the competitor parser

The `hospitality.competitor-snapshot@1` parser checks quote arithmetic in
`source/core/quote_amounts.on1x`. Internally, `NetBase`, `GrossStay`, and
`BundleDiscount` are distinct On1x types. The compiler rejects passing a gross
price as the minimum net base, even though both contain an `i64`.

- A quote calculation returns `Option<QuoteAmounts>`. The base, fee, and tax
  must each be in `0..10^12` minor units, and the discount must be in
  `0..base`. Net base is `base - discount`; gross stay is `net + fee + tax`.
  The code checks the remaining budget before adding either charge.
- A release can omit a bundle discount (`0` rooms, `0` minor units), or offer
  a positive discount on two to four rooms. For a nonempty release, the
  discount cannot exceed that room count times the lowest **net base**, not
  the lowest gross stay price. The count and amount bounds make the product
  safe in `i64`. An empty release cannot offer a discount.
- The parser keeps the typed minimum through release validation. At its
  compatibility boundary it still exposes the existing `core.competitor.Quote`
  and `Release` fields and Basis-array layout. Prices stay in the release
  currency: no implicit FX, precision negotiation, float arithmetic, or
  per-night conversion is added.

The existing wire format, rejection messages for snapshot inputs, plugin
imports, and cube archive format are unchanged. The legacy-loader amounts are
transparent nominal records: constructors do not grant proof of validation,
and arithmetic that accepts those records checks its bounds. The values are
immutable copies, not owners. A `Snapshot` still carries a raw Basis array
handle; callers must use `core.competitor.destroy` once, as before.

## Executable compiler profiles

The production slice uses the existing `.on1x` dotted imports, including for
direct C11 consumers that pass only a source root. The separate test project
uses a real `.on1xm`/`.on1xi` pair and stages the same arithmetic module. Its
declared provider seals a concrete checked result. The direct C11 consumer
can pass the value and observe it with an approved function, but cannot
construct an enum tag. The test also verifies that a mismatching signature
cannot replace a published project generation.

The signed project is intentionally isolated: non-stdlib declared modules
require membership, and the pinned compiler rejects sealed nominal values
on Unit-v1 PPX and MIR routes. The legacy v1 `.on1xi` conformance syntax
does not seal exports. Named arithmetic functions are used instead of adding
operators: this keeps checks and price roles visible and requires no custom
fixity. The explicit `std.operators` imports and `std.operator.utils`
helpers are orthogonal to this slice.

MuLIB Money checks signed minor-unit arithmetic and currency/precision
metadata; FXRate checks explicit rational conversion and point-in-time
availability. Neither is an On1x call admission just because its C
declarations can be discovered. This slice reuses the existing FinPRED
nonnegative bound without an added foreign boundary.

Run `python3 tests/check_core_financial_types.py` with the pinned `MULIB_ROOT`
and `ON1XC`. After building FinPRED, `python3 tests/check_competitor_cube.py`
checks the pinned fixture ID, exact archive replay, and a generated bundle
oracle against the production cube host.
