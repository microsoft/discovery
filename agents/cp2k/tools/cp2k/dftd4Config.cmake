# Auto-generated CMake config for conda-forge dftd4 package.
# conda-forge dftd4 provides libdftd4.so + dftd4.pc (pkg-config) but NOT
# CMake config files. CP2K's find_package(dftd4) needs dftd4Config.cmake.
# This shim bridges pkg-config -> CMake target dftd4::dftd4.
#
# CP2K's CMakeLists.txt displays these variables in the summary:
#   DFTD4_DFTD4, DFTD4_MCTC, DFTD4_INCLUDE_DIR, DFTD4_LIBDIR
# We populate them from pkg-config for diagnostic purposes.

find_package(PkgConfig REQUIRED)

# Find dftd4 and its dependency mctc-lib via pkg-config
pkg_check_modules(PC_DFTD4 REQUIRED IMPORTED_TARGET dftd4)
pkg_check_modules(PC_MCTC QUIET IMPORTED_TARGET mctc-lib)

if(NOT TARGET dftd4::dftd4)
  add_library(dftd4::dftd4 INTERFACE IMPORTED)
  set_target_properties(dftd4::dftd4 PROPERTIES
    INTERFACE_LINK_LIBRARIES "PkgConfig::PC_DFTD4"
    INTERFACE_INCLUDE_DIRECTORIES "${PC_DFTD4_INCLUDE_DIRS}"
  )
endif()

# Set display variables that CP2K's summary expects
set(DFTD4_DFTD4 "${PC_DFTD4_INCLUDEDIR}" CACHE PATH "dftd4 module dir")
set(DFTD4_MCTC "${PC_MCTC_INCLUDEDIR}" CACHE PATH "mctc-lib module dir")
set(DFTD4_INCLUDE_DIR "${PC_DFTD4_INCLUDE_DIRS}" CACHE PATH "dftd4 include dirs")
set(DFTD4_LIBDIR "${PC_DFTD4_LINK_LIBRARIES}" CACHE STRING "dftd4 libraries")

set(dftd4_FOUND TRUE)
set(dftd4_VERSION "${PC_DFTD4_VERSION}")
include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(dftd4
  REQUIRED_VARS PC_DFTD4_FOUND
  VERSION_VAR dftd4_VERSION
)
