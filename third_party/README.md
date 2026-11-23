Place the MuLIB checkout at `third_party/mulib/` (not bundled in this ZIP).

Pinned reference inspected for this package:
  Chubek/mulib master 49de89acbc97efbee493d6b28d02c8f64ed4f725

The verified C11 build initialized `on1x/third_party/libstone` at
`b5c962721a32df18b2fb22de136c1f2ef8b6390d`. From the FinPRED root:

```sh
git -C third_party/mulib submodule update --init on1x/third_party/libstone
cmake -S third_party/mulib/on1x -B third_party/mulib/build/on1x -DBUILD_TESTING=ON
cmake --build third_party/mulib/build/on1x --parallel 4 --target on1xc
./bin/build.sh
```

`bin/build.sh` runs the selected local toolchain; it does not download
dependencies. A checkout elsewhere can be selected via `MULIB_ROOT` and
an existing compiler via `ON1XC`. See the [verification record](../docs/IMPLEMENTATION.md#acceptance-record).
