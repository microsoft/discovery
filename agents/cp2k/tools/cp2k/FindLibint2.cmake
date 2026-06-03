# Replacement FindLibint2.cmake for conda-forge libint2
# Fixes:
# 1. Uses pkg-config result directly (CP2K_LIBINT2_LIBRARIES → LINK_LIBRARIES)
# 2. Does NOT require pre-built libint_f.mod (CP2K generates it at build time)
# 3. Properly resolves library paths for set_target_properties

include(FindPackageHandleStandardArgs)

find_package(PkgConfig REQUIRED)

if(PKG_CONFIG_FOUND)
  pkg_check_modules(CP2K_LIBINT2 IMPORTED_TARGET GLOBAL libint2)
endif()

# pkg_check_modules sets CP2K_LIBINT2_LIBRARIES, but CP2K CMakeLists
# expects CP2K_LIBINT2_LINK_LIBRARIES.  Bridge the two.
if(CP2K_LIBINT2_FOUND AND NOT CP2K_LIBINT2_LINK_LIBRARIES)
  # Resolve library names to full paths for set_target_properties
  set(_libint2_resolved "")
  foreach(_lib ${CP2K_LIBINT2_LIBRARIES})
    find_library(_lib_path NAMES ${_lib}
                 PATHS ${CP2K_LIBINT2_LIBRARY_DIRS}
                 NO_DEFAULT_PATH)
    if(_lib_path)
      list(APPEND _libint2_resolved "${_lib_path}")
    else()
      list(APPEND _libint2_resolved "${_lib}")
    endif()
    unset(_lib_path CACHE)
  endforeach()
  set(CP2K_LIBINT2_LINK_LIBRARIES "${_libint2_resolved}")
  unset(_libint2_resolved)
endif()

# Find include dirs if not already set
if(NOT CP2K_LIBINT2_INCLUDE_DIRS)
  find_path(CP2K_LIBINT2_INCLUDE_DIRS_TMP
    NAMES "libint2.h"
    PATH_SUFFIXES "include" "include/libint2")
  if(CP2K_LIBINT2_INCLUDE_DIRS_TMP)
    set(CP2K_LIBINT2_INCLUDE_DIRS "${CP2K_LIBINT2_INCLUDE_DIRS_TMP}")
  endif()
  unset(CP2K_LIBINT2_INCLUDE_DIRS_TMP CACHE)
endif()

find_package_handle_standard_args(
  Libint2 DEFAULT_MSG
  CP2K_LIBINT2_FOUND
  CP2K_LIBINT2_INCLUDE_DIRS
  CP2K_LIBINT2_LINK_LIBRARIES)

if(CP2K_LIBINT2_FOUND)
  if(NOT TARGET cp2k::Libint2::int2)
    add_library(cp2k::Libint2::int2 INTERFACE IMPORTED)
  endif()

  if(CP2K_LIBINT2_INCLUDE_DIRS)
    set_target_properties(
      cp2k::Libint2::int2 PROPERTIES
      INTERFACE_INCLUDE_DIRECTORIES "${CP2K_LIBINT2_INCLUDE_DIRS}")
  endif()

  set_target_properties(
    cp2k::Libint2::int2 PROPERTIES
    INTERFACE_LINK_LIBRARIES "${CP2K_LIBINT2_LINK_LIBRARIES}")
endif()

mark_as_advanced(CP2K_LIBINT2_FOUND CP2K_LIBINT2_LINK_LIBRARIES
                 CP2K_LIBINT2_INCLUDE_DIRS)
