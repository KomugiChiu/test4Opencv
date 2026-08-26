cmake_minimum_required(VERSION 3.10)
project(opencv_camera_api_test_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Python3 REQUIRED COMPONENTS Interpreter)

# C++ OpenCV source selection: CPP_OPENCV_SOURCE=apt|selfbuild (default apt)
if(NOT DEFINED CPP_OPENCV_SOURCE)
  set(CPP_OPENCV_SOURCE "apt")
endif()
if(CPP_OPENCV_SOURCE STREQUAL "selfbuild")
  if(DEFINED OPENCV_SOURCE_DIR)
    set(_OPENCV_SRC "${OPENCV_SOURCE_DIR}")
  else()
    set(_OPENCV_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../opencv_source_code")
    message(WARNING "OPENCV_SOURCE_DIR not set; using ${_OPENCV_SRC}")
  endif()
  if(DEFINED OPENCV_BUILD_DIR)
    set(_OPENCV_BUILD "${OPENCV_BUILD_DIR}")
  else()
    set(_OPENCV_BUILD "${CMAKE_CURRENT_SOURCE_DIR}/../build")
    message(WARNING "OPENCV_BUILD_DIR not set; using ${_OPENCV_BUILD}")
  endif()
  # Source header is canonical for selfbuild
  if(EXISTS "${_OPENCV_SRC}/modules/videoio/include/opencv2/videoio.hpp")
    set(VIDEOIO_HEADER "${_OPENCV_SRC}/modules/videoio/include/opencv2/videoio.hpp")
  else()
    message(WARNING "selfbuild source header not found, falling back to installed")
    set(VIDEOIO_HEADER "/usr/include/opencv4/opencv2/videoio.hpp")
  endif()
  # Directly point OpenCV_DIR to selfbuild build tree
  if(EXISTS "${_OPENCV_BUILD}/OpenCVConfig.cmake")
    set(OpenCV_DIR "${_OPENCV_BUILD}" CACHE PATH "" FORCE)
  elseif(EXISTS "${_OPENCV_BUILD}/lib/cmake/opencv4/OpenCVConfig.cmake")
    set(OpenCV_DIR "${_OPENCV_BUILD}/lib/cmake/opencv4" CACHE PATH "" FORCE)
  endif()
else()
  set(VIDEOIO_HEADER "/usr/include/opencv4/opencv2/videoio.hpp")
  if(NOT EXISTS "${VIDEOIO_HEADER}")
    if(DEFINED OpenCV_INCLUDE_DIRS)
      set(VIDEOIO_HEADER "${OpenCV_INCLUDE_DIRS}/opencv2/videoio.hpp")
    endif()
  endif()
endif()

find_package(OpenCV REQUIRED COMPONENTS core imgproc videoio)

# Detect actual source: /usr = apt, anything else = selfbuild
string(FIND "${OpenCV_DIR}" "/usr/" _SYS_POS)
if(_SYS_POS EQUAL 0)
  set(OPENCV_SOURCE_DETECTED "apt")
else()
  set(OPENCV_SOURCE_DETECTED "selfbuild")
endif()
message(STATUS "auto_cpp OpenCV: requested=${CPP_OPENCV_SOURCE} detected=${OPENCV_SOURCE_DETECTED} version=${OpenCV_VERSION} dir=${OpenCV_DIR}")

# Header extraction: re-generate on every configure
set(HEADER_GEN_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/tools/gen_cap_prop_table_from_header.py")
set(HEADER_GEN_OUTPUT "${CMAKE_CURRENT_SOURCE_DIR}/include/cap_prop_table.hpp")

add_custom_command(
  OUTPUT "${HEADER_GEN_OUTPUT}"
  COMMAND ${Python3_EXECUTABLE} "${HEADER_GEN_SCRIPT}" --header "${VIDEOIO_HEADER}" --out "${HEADER_GEN_OUTPUT}"
  DEPENDS "${VIDEOIO_HEADER}" "${HEADER_GEN_SCRIPT}"
  COMMENT "Generating cap_prop_table.hpp from ${VIDEOIO_HEADER} (source=${CPP_OPENCV_SOURCE})"
  VERBATIM
)
add_custom_target(cap_prop_table ALL DEPENDS "${HEADER_GEN_OUTPUT}")

add_executable(opencv_camera_api_test_cpp src/main.cpp)
add_dependencies(opencv_camera_api_test_cpp cap_prop_table)
target_compile_definitions(opencv_camera_api_test_cpp PRIVATE
  OPENCV_SOURCE_LABEL="${OPENCV_SOURCE_DETECTED}"
  OPENCV_VERSION_STR="${OpenCV_VERSION}")
target_include_directories(opencv_camera_api_test_cpp PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(opencv_camera_api_test_cpp ${OpenCV_LIBS})

if(MSVC)
  target_compile_options(opencv_camera_api_test_cpp PRIVATE /O2 /W3)
else()
  target_compile_options(opencv_camera_api_test_cpp PRIVATE -O2 -Wall -Wextra)
endif()
