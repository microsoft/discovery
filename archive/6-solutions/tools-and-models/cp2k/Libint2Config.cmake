# CMake shim for conda-forge libint2 — bridges pkg-config to CMake target
# CP2K's find_package(Libint2) needs CMake config; conda only provides .pc
find_package(PkgConfig REQUIRED)
pkg_check_modules(_LIBINT2 REQUIRED IMPORTED_TARGET libint2)
if(NOT TARGET Libint2::int2)
    add_library(Libint2::int2 INTERFACE IMPORTED)
    set_target_properties(Libint2::int2 PROPERTIES
        INTERFACE_LINK_LIBRARIES PkgConfig::_LIBINT2
    )
endif()
if(NOT TARGET Libint2::cxx)
    add_library(Libint2::cxx INTERFACE IMPORTED)
    set_target_properties(Libint2::cxx PROPERTIES
        INTERFACE_LINK_LIBRARIES Libint2::int2
    )
endif()
# Tell CP2K we have Libint2
set(Libint2_FOUND TRUE)
set(Libint2_LIBRARIES PkgConfig::_LIBINT2)
set(Libint2_INCLUDE_DIRS "${_LIBINT2_INCLUDE_DIRS}")
