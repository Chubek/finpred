cmake_minimum_required(VERSION 3.20)
project(finpred_native_review LANGUAGES C)
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "The FinPRED store review candidate requires Linux openat2 and O_TMPFILE")
endif()
add_library(finpred_native_store STATIC store.c)
set_target_properties(finpred_native_store PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)
target_include_directories(finpred_native_store PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

set(FINPRED_TEMPORAL_MULIB_ROOT "" CACHE PATH "MuLIB checkout for the optional native temporal review target")
if(FINPRED_TEMPORAL_MULIB_ROOT)
  add_library(finpred_native_temporal STATIC temporal.c)
  set_target_properties(finpred_native_temporal PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)
  target_include_directories(finpred_native_temporal SYSTEM PRIVATE "${FINPRED_TEMPORAL_MULIB_ROOT}/kernels")
  target_link_libraries(finpred_native_temporal PUBLIC finpred_native_store)
endif()

include(CTest)
if(BUILD_TESTING)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_executable(store_contract_test tests/store_contract.c)
  set_target_properties(store_contract_test PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)
  target_link_libraries(store_contract_test PRIVATE finpred_native_store)
  target_link_options(store_contract_test PRIVATE
    -Wl,--wrap=fsync -Wl,--wrap=read -Wl,--wrap=write -Wl,--wrap=fchmod)
  add_test(NAME native_store_contract COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/run.py $<TARGET_FILE:store_contract_test>)
  add_test(NAME native_store_v1_bytes COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/run.py $<TARGET_FILE:store_contract_test> copy-v1)

  add_executable(store_process_test tests/store_process.c)
  set_target_properties(store_process_test PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)
  target_link_libraries(store_process_test PRIVATE finpred_native_store)
  target_link_options(store_process_test PRIVATE
    -Wl,--wrap=write -Wl,--wrap=fsync -Wl,--wrap=linkat)
  add_test(NAME native_store_process_death COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/process_death.py $<TARGET_FILE:store_process_test>)
  set_tests_properties(native_store_process_death PROPERTIES TIMEOUT 90)

  if(TARGET finpred_native_temporal)
    add_executable(temporal_test_driver tests/temporal_driver.c)
    set_target_properties(temporal_test_driver PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)
    target_include_directories(temporal_test_driver SYSTEM PRIVATE "${FINPRED_TEMPORAL_MULIB_ROOT}/kernels")
    target_link_libraries(temporal_test_driver PRIVATE finpred_native_temporal)
    target_link_options(temporal_test_driver PRIVATE -Wl,--wrap=fsync -Wl,--wrap=linkat)
    add_test(NAME native_temporal_oracle_and_recovery COMMAND ${Python3_EXECUTABLE} -B
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/temporal.py $<TARGET_FILE:temporal_test_driver>)
    set_tests_properties(native_temporal_oracle_and_recovery PROPERTIES TIMEOUT 90)
  endif()
endif()
