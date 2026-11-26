packages <- read.csv("/tmp/packages.csv", colClasses = "character")
for (i in seq_len(nrow(packages))) {
  package <- packages$package[i]
  version <- packages$version[i]
  url <- sprintf(
    "https://cran.r-project.org/src/contrib/Archive/%s/%s_%s.tar.gz",
    package, package, version
  )
  archive <- tempfile(fileext = ".tar.gz")
  downloaded <- tryCatch(
    {
      download.file(url, archive, mode = "wb", quiet = FALSE)
      TRUE
    },
    error = function(error) {
      message(sprintf("Archive download failed for %s %s: %s", package, version, conditionMessage(error)))
      FALSE
    }
  )
  if (!downloaded) {
    url <- sprintf("https://cran.r-project.org/src/contrib/%s_%s.tar.gz", package, version)
    message(sprintf("Trying the current CRAN location for the same pinned version: %s", url))
    download.file(url, archive, mode = "wb", quiet = FALSE)
  }
  install.packages(archive, repos = NULL, type = "source", dependencies = FALSE)
  unlink(archive)
  if (!requireNamespace(package, quietly = TRUE) ||
      packageVersion(package) != package_version(version)) {
    stop(sprintf("Installation/version check failed for %s %s", package, version))
  }
}
stopifnot(capabilities("cairo"))
