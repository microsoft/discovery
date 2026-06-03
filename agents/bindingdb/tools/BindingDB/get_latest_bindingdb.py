#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import os
import re
import sys
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DOWNLOAD_PAGE = "https://www.bindingdb.org/rwd/bind/chemsearch/marvin/Download.jsp"
_PATTERN = re.compile(r"BindingDB_All_(\d{6})_tsv\.zip", re.IGNORECASE)

LOG = logging.getLogger("bindingdb_fetcher")


def _configure_logging(level: str = "INFO") -> None:
    """Configure root logger with a consistent format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    LOG.debug("Logger initialized at level %s", level)


def _session_with_retries(total=5, backoff=0.5) -> requests.Session:
    """Return a requests.Session with robust retry policy."""
    retry = Retry(
        total=total,
        connect=total,
        read=total,
        status=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    s = requests.Session()
    s.headers.update({"User-Agent": "bindingdb-fetcher/1.0"})
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    LOG.debug("HTTP session with retries created (total=%s, backoff=%s)", total, backoff)
    return s


def find_latest_bindingdb_tsv_url(download_page_url: str = DOWNLOAD_PAGE,
                                  verify_head: bool = True) -> tuple[str, str]:
    """
    Scrape the BindingDB download page and return the absolute URL of the latest
    'BindingDB_All_YYYYMM_tsv.zip'.

    Raises:
        RuntimeError if no candidate link is found or verification fails.
    """
    s = _session_with_retries()

    LOG.info("Fetching download page: %s", download_page_url)
    try:
        resp = s.get(download_page_url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        LOG.error("Failed to load download page: %s", e)
        raise RuntimeError(f"Failed to load download page: {e}") from e

    LOG.debug("Download page fetched (status=%s, bytes=%d)", resp.status_code, len(resp.content))

    # Extract all href values via regex (robust to minor HTML layout changes).
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', resp.text, flags=re.IGNORECASE)
    LOG.info("Found %d href(s) on page", len(hrefs))

    candidates = []
    for href in hrefs:
        m = _PATTERN.search(href)
        if not m:
            continue
        yyyymm = int(m.group(1))
        abs_url = urljoin(download_page_url, href)
        canonical_name = m.group(0)
        LOG.debug("Candidate: yyyymm=%d url=%s name=%s", yyyymm, abs_url, canonical_name)
        candidates.append((yyyymm, abs_url, canonical_name))

    if not candidates:
        LOG.error("No BindingDB_All_YYYYMM_tsv.zip links found on the page")
        raise RuntimeError("No BindingDB_All_YYYYMM_tsv.zip links found on the page.")

    # Select the most recent by YYYYMM value.
    candidates.sort(key=lambda t: t[0], reverse=True)
    latest_yyyymm, latest_url, latest_name = candidates[0]
    LOG.info("Selected latest candidate: %d -> %s (name=%s)", latest_yyyymm, latest_url, latest_name)

    if verify_head:
        LOG.info("Verifying URL with HEAD: %s", latest_url)
        try:
            h = s.head(latest_url, allow_redirects=True, timeout=20)
        except Exception as e:
            LOG.error("HEAD request failed for %s: %s", latest_url, e)
            raise RuntimeError(f"Verification failed for {latest_url}: {e}") from e

        LOG.debug("HEAD status=%s redirects=%d", h.status_code, len(h.history))
        if h.status_code >= 400:
            LOG.error("HEAD check failed status=%s for %s", h.status_code, latest_url)
            raise RuntimeError(f"HEAD check failed with status {h.status_code} for {latest_url}")

        LOG.debug("Content-Type: %s | Content-Length: %s",
                  h.headers.get("Content-Type"), h.headers.get("Content-Length"))

    return latest_url, latest_name


def _download(url: str, output_path: str) -> None:
    """Stream download with progress logs."""
    s = _session_with_retries()
    LOG.info("Starting download: %s", url)
    with s.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", "0") or 0)
        if total:
            LOG.info("Total size: %.2f MB", total / (1024 * 1024))
        else:
            LOG.info("Total size: unknown (no Content-Length)")

        bytes_written = 0
        report_every = 25 * 1024 * 1024  # log every 25 MB
        next_report = report_every

        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                bytes_written += len(chunk)
                if bytes_written >= next_report:
                    if total:
                        LOG.info("Downloaded %.2f / %.2f MB",
                                 bytes_written / (1024 * 1024),
                                 total / (1024 * 1024))
                    else:
                        LOG.info("Downloaded %.2f MB so far",
                                 bytes_written / (1024 * 1024))
                    next_report += report_every

    LOG.info("Download complete: wrote %.2f MB to %s",
             bytes_written / (1024 * 1024), output_path)


def main():
    ap = argparse.ArgumentParser(
        description="Fetch latest BindingDB TSV zip URL (BindingDB_All_YYYYMM_tsv.zip)."
    )
    ap.add_argument("--page", default=DOWNLOAD_PAGE, help="Download page URL to scan.")
    ap.add_argument("--no-verify", action="store_true", help="Skip HEAD verification of the final URL.")
    # --download can be given without a value: use current directory and original filename
    ap.add_argument("--download", nargs='?', const='.', metavar="PATH",
                    help="If set, download the ZIP to PATH. If PATH is omitted, save to current directory with the original snapshot filename.")
    ap.add_argument("--download-dir", metavar="DIR",
                    help="Shorthand: download to DIR using the original snapshot filename.")
    ap.add_argument("--verbose", action="store_true", help="Enable DEBUG-level logs.")
    ap.add_argument(
        "--log-level",
        default=None,
        help="Explicit log level (overrides --verbose). One of: DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )
    args = ap.parse_args()

    level = "DEBUG" if args.verbose else (args.log_level or "INFO")
    _configure_logging(level)
    LOG.debug("Arguments: %s", vars(args))

    try:
        url, canonical_name = find_latest_bindingdb_tsv_url(args.page, verify_head=False)
    except Exception as e:
        LOG.exception("Failed to resolve latest BindingDB TSV URL")
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    # Construct a direct download URL that points to the real ZIP file in the
    # downloads directory (avoids HTML wrapper pages like SDFdownload.jsp).
    # Example: https://www.bindingdb.org/rwd/bind/downloads/BindingDB_All_202511_tsv.zip
    if canonical_name:
        direct_download_base = "https://www.bindingdb.org/rwd/bind/downloads/"
        download_url = urljoin(direct_download_base, canonical_name)
    else:
        download_url = url

    LOG.info("Resolved direct download URL: %s", download_url)

    # Perform HEAD verification on the direct ZIP URL unless user requested skip
    if not args.no_verify:
        LOG.info("Verifying direct download URL with HEAD: %s", download_url)
        try:
            sess = _session_with_retries()
            h = sess.head(download_url, allow_redirects=True, timeout=20)
            h.raise_for_status()
            LOG.debug("Direct HEAD status=%s", h.status_code)
        except Exception as e:
            LOG.error("HEAD check failed for direct download URL: %s", e)
            # Fall back to verifying the originally-discovered URL
            try:
                LOG.info("Falling back to HEAD verify wrapper URL: %s", url)
                sess = _session_with_retries()
                h2 = sess.head(url, allow_redirects=True, timeout=20)
                h2.raise_for_status()
            except Exception as e2:
                LOG.exception("Verification failed for both direct and wrapper URLs")
                print(f"ERROR: verification failed: {e2}", file=sys.stderr)
                sys.exit(1)

    # Determine download target. Default behavior: download into current directory
    # as 'BindingDB_All.zip' to make the script easy to call without flags.
    download_target = None
    if args.download is not None:
        # args.download is either '.' (const) or a provided path
        download_target = args.download
    elif args.download_dir:
        download_target = args.download_dir

    # If user didn't request a download, default to downloading into cwd
    if download_target is None:
        download_target = '.'

    if download_target is not None:
        # Resolve output path. If target is a directory (or '.'), save using the snapshot basename.
        try:
            parsed = urlparse(url)
            # Use a stable default filename for local builds/CI: 'BindingDB_All.zip'
            # If the user provided an explicit file path, preserve it. If they provided
            # a directory (or omitted the path via --download without value), save
            # to that directory using 'BindingDB_All.zip' to provide a consistent name.
            default_basename = 'BindingDB_All.zip'
            # Use canonical_name if present to detect the actual snapshot name, but
            # default to the simpler stable name above for local storage.
            canonical = canonical_name or os.path.basename(parsed.path) or None
            # Prefer canonical if the user explicitly provided a filename that looks like the snapshot
            # Otherwise, use the stable default_basename.
            basename = default_basename if canonical is None else default_basename

            # If user provided a directory (existing or explicit '.'), join basename
            if download_target in ('.', './') or download_target.endswith(os.path.sep) or os.path.isdir(download_target):
                out_path = os.path.join(download_target, basename) if download_target not in ('.', './') else basename
            else:
                # Treat as file path; ensure parent exists
                parent = os.path.dirname(download_target)
                if parent and not os.path.exists(parent):
                    os.makedirs(parent, exist_ok=True)
                out_path = download_target

            # Download the direct ZIP URL when available to avoid HTML wrappers
            _download(download_url, out_path)
            print(f"Downloaded to {out_path}")
        except Exception as e:
            LOG.exception("Download failed")
            print(f"ERROR downloading {url}: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        print(url)


if __name__ == "__main__":
    main()
