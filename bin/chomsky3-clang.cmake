# Scoped to the pinned LibStone Chomsky3 subproject. Keep known upstream
# diagnostics visible without disabling -Werror in On1x or the application.
if(CMAKE_C_COMPILER_ID STREQUAL "Clang")
  add_compile_options(
    -Wno-error=sometimes-uninitialized
    -Wno-error=gnu-zero-variadic-macro-arguments
    -Wno-error=unused-function)
endif()
