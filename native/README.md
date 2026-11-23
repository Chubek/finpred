No FinPRED-specific native adapter is needed for this MVP. The On1x standard
library supplies bounded C11 adapters for filesystem I/O, mutable i64 array
handles, and MuLIB's BLAKE3 hashing. They are raw ABI bridges rather than
independently reviewed KernelBind imports. The operator must select a trusted,
matching MuLIB/On1x checkout.
