cmake_minimum_required(VERSION 3.20)
project(finpred_sdk VERSION 1.1.0 LANGUAGES C)

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

add_library(finpred_sdk sdk.c sdk_v2.c)
target_compile_features(finpred_sdk PUBLIC c_std_11)
set_target_properties(finpred_sdk PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON
                      C_EXTENSIONS OFF VERSION ${PROJECT_VERSION} SOVERSION 1
                      EXPORT_NAME sdk)
target_include_directories(finpred_sdk PUBLIC
  "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>"
  "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>")
install(TARGETS finpred_sdk EXPORT FinPREDSDKTargets)
install(FILES sdk.h sdk_v2.h DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/finpred)

set(sdk_cmake_dir "${CMAKE_INSTALL_LIBDIR}/cmake/FinPREDSDK")
write_basic_package_version_file(
  "${CMAKE_CURRENT_BINARY_DIR}/FinPREDSDKConfigVersion.cmake"
  VERSION ${PROJECT_VERSION} COMPATIBILITY SameMajorVersion)
install(EXPORT FinPREDSDKTargets FILE FinPREDSDKConfig.cmake
        NAMESPACE FinPRED:: DESTINATION "${sdk_cmake_dir}")
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/FinPREDSDKConfigVersion.cmake"
        DESTINATION "${sdk_cmake_dir}")

option(FINPRED_INSTALL_PYTHON_SDK "Install Python metadata binding alongside the shared SDK" OFF)
if(FINPRED_INSTALL_PYTHON_SDK)
  if(NOT BUILD_SHARED_LIBS)
    message(FATAL_ERROR "FINPRED_INSTALL_PYTHON_SDK requires BUILD_SHARED_LIBS=ON")
  endif()
  install(FILES ../../bindings/python/finpred_sdk.py
          DESTINATION "${CMAKE_INSTALL_LIBDIR}/finpred/python")
endif()
