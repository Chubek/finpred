cmake_minimum_required(VERSION 3.20)
project(finpred_sdk VERSION 1.1.0 LANGUAGES C)

include(GNUInstallDirs)
add_library(finpred_sdk sdk.c sdk_v2.c)
target_compile_features(finpred_sdk PUBLIC c_std_11)
set_target_properties(finpred_sdk PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON
                      C_EXTENSIONS OFF VERSION ${PROJECT_VERSION} SOVERSION 1)
target_include_directories(finpred_sdk PUBLIC "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>")
install(TARGETS finpred_sdk)
install(FILES sdk.h sdk_v2.h DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/finpred)
