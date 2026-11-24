cmake_minimum_required(VERSION 3.20)
project(finpred_offline_worker LANGUAGES C)

add_executable(finpred-offline-worker worker.c)
target_compile_features(finpred-offline-worker PRIVATE c_std_11)
set_target_properties(finpred-offline-worker PROPERTIES C_EXTENSIONS OFF)
