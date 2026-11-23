No FinPRED-specific native adapter is needed for this MVP. The On1x standard
library supplies bounded C11 adapters for filesystem I/O, mutable i64 array
handles, and MuLIB's BLAKE3 hashing. They are raw ABI bridges rather than
independently reviewed KernelBind imports. The operator must select a trusted,
matching MuLIB/On1x checkout.

The [P1 store admission decision](STORE_ADMISSION.md) records the pinned
compiler rejection and the interface and evidence needed for durable,
directory-relative publication. No storage admission has been granted.
