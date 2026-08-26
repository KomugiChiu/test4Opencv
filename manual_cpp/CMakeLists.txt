cmake_minimum_required(VERSION 3.10)
project(manual_suite_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Python3 REQUIRED COMPONENTS Interpreter)

if(NOT DEFINED CPP_OPENCV_SOURCE)
  set(CPP_OPENCV_SOURCE "apt")
endif()
if(CPP_OPENCV_SOURCE STREQUAL "selfbuild")
  if(DEFINED OPENCV_SOURCE_DIR)
    set(_OPENCV_SRC "${OPENCV_SOURCE_DIR}")
  else()
    set(_OPENCV_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../opencv_source_code/latest")
  endif()
  if(DEFINED OPENCV_BUILD_DIR)
    set(_OPENCV_BUILD "${_OPENCV_BUILD_DIR}")
  else()
    set(_OPENCV_BUILD "${CMAKE_CURRENT_SOURCE_DIR}/../build/latest")
  endif()
  # Directly point OpenCV_DIR to selfbuild build tree (bypasses search order)
  if(EXISTS "${_OPENCV_BUILD}/OpenCVConfig.cmake")
    set(OpenCV_DIR "${_OPENCV_BUILD}" CACHE PATH "" FORCE)
  elseif(EXISTS "${_OPENCV_BUILD}/lib/cmake/opencv4/OpenCVConfig.cmake")
    set(OpenCV_DIR "${_OPENCV_BUILD}/lib/cmake/opencv4" CACHE PATH "" FORCE)
  endif()
endif()
find_package(OpenCV REQUIRED COMPONENTS core imgproc videoio)

# Detect ACTUAL source: check if OpenCV_DIR points to selfbuild or system
string(FIND "${OpenCV_DIR}" "/usr/" _SYS_POS)
if(_SYS_POS EQUAL 0)
  set(OPENCV_SOURCE_DETECTED "apt")
else()
  set(OPENCV_SOURCE_DETECTED "selfbuild")
endif()
message(STATUS "manual_cpp OpenCV: requested=${CPP_OPENCV_SOURCE} detected=${OPENCV_SOURCE_DETECTED} version=${OpenCV_VERSION} dir=${OpenCV_DIR}")

find_package(yaml-cpp REQUIRED)

add_executable(manual_suite src/manual_suite.cpp)
target_compile_definitions(manual_suite PRIVATE
  OPENCV_SOURCE_LABEL="${OPENCV_SOURCE_DETECTED}"
  OPENCV_VERSION_STR="${OpenCV_VERSION}")
target_include_directories(manual_suite PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${OpenCV_INCLUDE_DIRS}
)
target_link_libraries(manual_suite
  ${OpenCV_LIBS}
  yaml-cpp
)

# Legacy single-file driver (kept for compat)
add_executable(manual_cpp src/main.cpp)
target_link_libraries(manual_cpp ${OpenCV_LIBS})

if(MSVC)
  target_compile_options(manual_suite PRIVATE /O2 /W3)
  target_compile_options(manual_cpp PRIVATE /O2 /W3)
else()
  target_compile_options(manual_suite PRIVATE -O2 -Wall -Wextra)
  target_compile_options(manual_cpp PRIVATE -O2 -Wall -Wextra)
endif()

# Helpers as standalone executables
add_executable(exposure_check src/exposure_check.cpp)
target_include_directories(exposure_check PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(exposure_check ${OpenCV_LIBS} yaml-cpp)

add_executable(autofocus_check src/autofocus_check.cpp)
target_include_directories(autofocus_check PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(autofocus_check ${OpenCV_LIBS} yaml-cpp)

add_executable(white_balance_check src/white_balance_check.cpp)
target_include_directories(white_balance_check PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(white_balance_check ${OpenCV_LIBS} yaml-cpp)

add_executable(reconnect_test src/reconnect_test.cpp)
target_include_directories(reconnect_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(reconnect_test ${OpenCV_LIBS} yaml-cpp)
