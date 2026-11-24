# Scalar diagnostics

`plugins.scalar_diagnostics.midpoint.midpoint(left, right)` returns the
floor of the arithmetic midpoint of two unitless integers in `[0, 10^12]`.
For example, 17 and 42 produce 29. Out-of-range direct calls fail before
addition.

The CLI supplies this package's `binding.lookup` and `binding.call` to the
scalar engine. Custom hosts can use the same callbacks with
`ottomat.scalar.lower_with`, `automat.dag.run_with`, or
`automat.scalar_verify.verify_with`. The engine's default entry points do
not resolve this operation.

The binding exposes the function as `midpoint@1`,
owned by `scalar-diagnostics@1`. It accepts two `scalar.level@1` values
and returns one `scalar.level@1` value. The operation is pure, has no host
grants, and costs one graph budget unit. It is admitted in
`automat.scalar-dag@3` and can be imported in [Ottomat v5](../../source/ottomat/README.md#v5-registered-scalar-algorithms).
It is not a Yieldcraft pricing operation or a dynamically loadable SDK package.
