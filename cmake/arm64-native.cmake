# Prebuilt relocatable toolchain fragment.
# Included via: cmake -C <toolkit>/cmake/arm64-native.cmake
# Goal: binaries + selfbuild OpenCV libs find each other after
# copy to /opt/camera-toolkit (bin/../lib layout) without LD_LIBRARY_PATH.
set(CMAKE_INSTALL_RPATH "$ORIGIN/../lib:$ORIGIN" CACHE STRING "" FORCE)
set(CMAKE_BUILD_WITH_INSTALL_RPATH TRUE CACHE BOOL "" FORCE)
set(CMAKE_BUILD_RPATH_USE_ORIGIN TRUE CACHE BOOL "" FORCE)
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH FALSE CACHE BOOL "" FORCE)
