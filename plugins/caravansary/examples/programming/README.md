# Call a typed CaravanScript function

`bounded.caf` declares two inert aggregator profile aliases on one local
target and a pure module. The host invokes `eligible` on a distance and
quality score, then invokes `example_price` on two integer minor-unit
amounts. These are function demonstrations: the second result is **not**
an admitted market price recommendation, and neither invocation performs
collection, persistence, or scheduling.

Run from the repository root, with the pinned On1x compiler built:

```sh
sh plugins/caravansary/build.sh --check-programming
```

Expected output: `true` then `12250`.
