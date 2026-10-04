cmake_minimum_required(VERSION 3.16)
project(spat_potential_engine LANGUAGES CXX)

add_executable(spat-potential-engine src/main.cpp)
target_compile_features(spat-potential-engine PRIVATE cxx_std_17)
target_compile_options(spat-potential-engine PRIVATE -O3 -Wall -Wextra -Wpedantic)
