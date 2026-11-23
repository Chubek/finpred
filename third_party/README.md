MuLIB sources live in `third_party/mulib/`; build outputs go in the FinPRED
root's `build/mulib/on1x/` directory. From the FinPRED root:

```sh
git submodule update --init third_party/mulib
git -C third_party/mulib submodule update --init on1x/third_party/libstone
make mulib
make
```

`bin/build.sh` runs the selected local toolchain; it does not download
dependencies. A checkout elsewhere can be selected via `MULIB_ROOT` and
an existing compiler via `ON1XC`. See the [verification record](../docs/IMPLEMENTATION.md#acceptance-record).
