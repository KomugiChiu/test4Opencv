# AArch64 cross toolchain (x86_64 host -> aarch64 target, Ubuntu noble).
# Usage: cmake -DCMAKE_TOOLCHAIN_FILE=<toolkit>/cmake/toolchain-aarch64.cmake
# Sysroot: apt multiarch (arm64 .deb providing /usr/aarch64-linux-gnu + /usr/lib/aarch64-linux-gnu).
# FFmpeg policy: mandatory — no WITH_FFMPEG=OFF fallback (checked in build_prebuilt.sh).
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_SYSTEM_VERSION 1)

set(GNU_MACHINE "aarch64-linux-gnu")
set(CMAKE_C_COMPILER "${GNU_MACHINE}-gcc")
set(CMAKE_CXX_COMPILER "${GNU_MACHINE}-g++")

# Multiarch sysroot lives on host root; keep RPATH relocatable.
set(CMAKE_SYSROOT "/" CACHE PATH "" FORCE)
set(CMAKE_FIND_ROOT_PATH "/" "/usr/${GNU_MACHINE}" CACHE PATH "" FORCE)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER CACHE STRING "" FORCE)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY CACHE STRING "" FORCE)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY CACHE STRING "" FORCE)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY CACHE STRING "" FORCE)

# Never pick host amd64 pkg-config results for target libs.
set(ENV{PKG_CONFIG_SYSROOT_DIR} "/")
set(ENV{PKG_CONFIG_LIBDIR} "/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/lib/pkgconfig:/usr/share/pkgconfig")

# Python codegen (cap_prop_table) must stay on host.
set(Python3_FIND_REGISTRY NEVER CACHE STRING "" FORCE)

# Run target test binaries under qemu during try_run / smoke.
find_program(_QEMU_AARCH64 qemu-aarch64-static qemu-aarch64)
if(_QEMU_AARCH64)
  set(CMAKE_CROSSCOMPILING_EMULATOR "${_QEMU_AARCH64};-L;/")
endif()

# Keep prebuilt relocatable layout bin/../lib.
include("${CMAKE_CURRENT_LIST_DIR}/arm64-native.cmake")
