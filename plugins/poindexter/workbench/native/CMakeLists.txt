cmake_minimum_required(VERSION 3.20)
project(poindexter_viewport_review LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
set(MULIB_ROOT "" CACHE PATH "Pinned MuLIB checkout")
if(NOT EXISTS "${MULIB_ROOT}/include/mulib-tui.h")
  message(FATAL_ERROR "Set MULIB_ROOT to the pinned MuLIB checkout; see README.md")
endif()

add_library(px_viewport_review STATIC viewport.c)
target_include_directories(px_viewport_review PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}"
  PRIVATE "${MULIB_ROOT}/include")

include(CTest)
if(BUILD_TESTING)
  add_executable(px_viewport_test test_viewport.c)
  target_include_directories(px_viewport_test PRIVATE "${MULIB_ROOT}/include")
  target_link_libraries(px_viewport_test PRIVATE px_viewport_review)
  foreach(case frame rejection bounds)
    add_test(NAME px_viewport_${case} COMMAND px_viewport_test ${case})
  endforeach()
endif()
