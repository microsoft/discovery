#!/usr/bin/env python3
r"""
Fetch and bundle GitHub documentation into a single Markdown file.

Defaults to microsoft/discovery main/docs, but works for any public repo/path.

Features:
- Recursively lists files in a GitHub repo directory via GitHub Contents API.
- Filters Markdown files (*.md) and optionally YAML files (*.yaml, *.yml) and concatenates them into one document.
- Support for multiple GitHub URLs to combine documentation from different sources.
- Optional YAML front-matter removal (--- ... --- at top).
- Optional link fixer to convert relative links to absolute GitHub raw URLs.
- Simple per-file section header with a source link.
- Optional Table of Contents for files with GitHub URLs.
- Supports anonymous access or authentication via GITHUB_TOKEN env var.

Usage examples (PowerShell):
  # Single repository
  python .\Utils\fetch_discovery_docs.py \
    --owner microsoft --repo discovery --branch main --path docs \
    --output .\combined-discovery-docs.md --remove-frontmatter --fix-links --toc

  # Multiple URLs with internal link fixing
  python .\Utils\fetch_discovery_docs.py \
    --urls "https://github.com/microsoft/discovery/tree/main/docs" \
           "https://github.com/microsoft/another-repo/tree/main/documentation" \
    --output .\combined-docs.md --include-yaml --fix-internal-links --toc

  # Include YAML files and fix internal links
  python .\Utils\fetch_discovery_docs.py \
    --url "https://github.com/microsoft/discovery/tree/main/docs" \
    --include-yaml --fix-internal-links --output .\combined-docs.md

Environment:
  GITHUB_TOKEN (optional) to increase rate limits and access private repos.

Exit codes: 0 on success, non-zero on failure.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests

API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"


def _normalize_exclude_folders(values: Optional[List[str]]) -> List[str]:
    """Normalize CLI exclude folders to posix-style relative prefixes.

    Examples:
      - '6-solutions/' -> '6-solutions'
      - './6-solutions' -> '6-solutions'
      - '6-solutions\\foo' -> '6-solutions/foo'
    """
    if not values:
        return []

    normalized: List[str] = []
    for raw in values:
        if raw is None:
            continue
        p = str(raw).strip().replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        p = p.strip("/")
        if p:
            normalized.append(p)

    # De-dupe while preserving order
    seen = set()
    out: List[str] = []
    for p in normalized:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _is_excluded_path(path_posix: str, exclude_prefixes: List[str]) -> bool:
    if not exclude_prefixes:
        return False
    p = path_posix.strip("/")
    for ex in exclude_prefixes:
        if p == ex or p.startswith(ex + "/"):
            return True
    return False


def github_headers(token_override: Optional[str] = None) -> Dict[str, str]:
    token = token_override or os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "docs-fetcher"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_github_tree_url(url: str) -> Optional[Dict[str, str]]:
    """Parse a GitHub tree URL like
    https://github.com/<owner>/<repo>/tree/<branch>/<path>
    Returns dict with owner, repo, branch, path. If not a tree URL, tries base repo URL.
    """
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+)(?:/(.*))?)?/?$", url.strip())
    if not m:
        return None
    owner, repo, branch, path = m.group(1), m.group(2), m.group(3), m.group(4)
    if not branch:
        branch = "main"
    if path is None:
        path = ""
    return {"owner": owner, "repo": repo, "branch": branch, "path": path}


def list_repo_tree(
    owner: str,
    repo: str,
    path: str,
    branch: str,
    token: Optional[str] = None,
    verbose: bool = False,
    exclude_folders: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Recursively list files under path. Returns dicts with 'path', 'type', 'download_url', 'html_url'."""
    items: List[Dict[str, Any]] = []

    exclude_prefixes = _normalize_exclude_folders(exclude_folders)

    def recurse(cur_path: str):
        if _is_excluded_path(cur_path, exclude_prefixes):
            if verbose:
                print(f"[LIST] Skip excluded dir: {cur_path}")
            return
        if verbose:
            print(f"[LIST] Enter: {cur_path}")
        url = f"{API_BASE}/repos/{owner}/{repo}/contents/{cur_path}"
        params = {"ref": branch}
        resp = requests.get(url, headers=github_headers(token), params=params, timeout=30)
        if verbose:
            print(f"[HTTP] GET {url}?ref={branch} (auth={'token' if token else 'none'}) -> {resp.status_code}")
        if resp.status_code == 404:
            # If token provided, try anonymous fallback in case token lacks SSO for a public repo
            if token is not None:
                resp2 = requests.get(url, headers=github_headers(None), params=params, timeout=30)
                if verbose:
                    print(f"[HTTP] RETRY {url}?ref={branch} (auth=none) -> {resp2.status_code}")
                if resp2.ok:
                    resp = resp2
                else:
                    raise RuntimeError(f"Path not found: {owner}/{repo}/{cur_path}@{branch}")
            else:
                raise RuntimeError(f"Path not found: {owner}/{repo}/{cur_path}@{branch}")
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            reset = resp.headers.get("X-RateLimit-Reset")
            wait_s = max(0, int(reset) - int(time.time())) if reset and reset.isdigit() else 60
            print(f"[RATE] Hit rate limit. Waiting {wait_s}s...", flush=True)
            time.sleep(wait_s)
            resp = requests.get(url, headers=github_headers(token), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("type") == "file":
            items.append({
                "path": data.get("path", cur_path),
                "type": data.get("type", "file"),
                "download_url": data.get("download_url"),
                "html_url": data.get("html_url"),
            })
            if verbose:
                print(f"[LIST] File: {items[-1]['path']}")
            return
        if not isinstance(data, list):
            return
        for entry in data:
            etype = entry.get("type")
            if etype == "file":
                entry_path = (entry.get("path") or "").replace("\\", "/")
                if _is_excluded_path(entry_path, exclude_prefixes):
                    if verbose:
                        print(f"[LIST] Skip excluded file: {entry_path}")
                    continue
                items.append({
                    "path": entry.get("path"),
                    "type": "file",
                    "download_url": entry.get("download_url"),
                    "html_url": entry.get("html_url"),
                })
                if verbose:
                    print(f"[LIST] File: {items[-1]['path']}")
            elif etype == "dir":
                dir_path = (entry.get("path") or "").replace("\\", "/")
                if _is_excluded_path(dir_path, exclude_prefixes):
                    if verbose:
                        print(f"[LIST] Skip excluded dir: {dir_path}")
                    continue
                if verbose:
                    print(f"[LIST] Dir:  {dir_path}")
                recurse(entry.get("path"))
            # ignore symlinks/submodules for simplicity

    recurse(path.strip("/"))
    return items


def list_single_dir(owner: str, repo: str, path: str, branch: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """List a single directory level (non-recursive). Returns list of entries or raises for non-200."""
    cur_path = path.strip("/")
    url = f"{API_BASE}/repos/{owner}/{repo}/contents/{cur_path}" if cur_path else f"{API_BASE}/repos/{owner}/{repo}/contents"
    params = {"ref": branch}
    resp = requests.get(url, headers=github_headers(token), params=params, timeout=30)
    if resp.status_code == 404 and token is not None:
        # Retry anonymously for public repos when token lacks SSO
        resp2 = requests.get(url, headers=github_headers(None), params=params, timeout=30)
        if resp2.ok:
            resp = resp2
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def fetch_raw(url: str, token: Optional[str] = None, verbose: bool = False) -> str:
    if verbose:
        print(f"[FETCH] {url}")
    r = requests.get(url, headers=github_headers(token), timeout=60)
    if verbose:
        print(f"[HTTP] GET {url} (auth={'token' if token else 'none'}) -> {r.status_code}")
    if r.status_code == 403 and "rate limit" in r.text.lower():
        reset = r.headers.get("X-RateLimit-Reset")
        wait_s = max(0, int(reset) - int(time.time())) if reset and reset.isdigit() else 60
        print(f"[RATE] Hit rate limit on fetch. Waiting {wait_s}s...", flush=True)
        time.sleep(wait_s)
        r = requests.get(url, headers=github_headers(token), timeout=60)
        if verbose:
            print(f"[HTTP] RETRY {url} (auth={'token' if token else 'none'}) -> {r.status_code}")
    if r.status_code == 404 and token is not None:
        # Retry anonymously
        r2 = requests.get(url, headers=github_headers(None), timeout=60)
        if verbose:
            print(f"[HTTP] RETRY {url} (auth=none) -> {r2.status_code}")
        if r2.ok:
            r = r2
    r.raise_for_status()
    if verbose:
        size = len(getattr(r, "content", r.text))
        print(f"[FETCH] -> {r.status_code}, {size} bytes")
    return r.text


def strip_frontmatter(md: str) -> str:
    if md.startswith("---\n"):
        # find closing --- at start
        end = md.find("\n---\n", 4)
        if end != -1:
            return md[end + 5 :]
    return md


LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^):#][^)\s]*)\)")
INTERNAL_LINK_RE = re.compile(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+?)(?:\.md)?(?=#|$)")


def fix_links(md: str, owner: str, repo: str, branch: str, file_dir: str) -> str:
    """Convert relative markdown links to absolute raw URLs.
    - Keeps http(s) links intact
    - For relative links, builds RAW_BASE/owner/repo/branch/<file_dir>/target
    """
    def repl(m):
        prefix = m.group(1)  # '![alt](' or '[text]('
        target = m.group(2)
        if target.startswith("http://") or target.startswith("https://") or target.startswith("mailto:"):
            return m.group(0)
        # anchor-only links left unchanged
        if target.startswith("#"):
            return m.group(0)
        # build absolute raw URL
        joined = f"{file_dir}/{target}" if file_dir else target
        # normalize .. and . segments
        parts = []
        for seg in joined.split('/'):
            if seg == '..':
                if parts:
                    parts.pop()
            elif seg == '.' or seg == '':
                continue
            else:
                parts.append(seg)
        norm = '/'.join(parts)
        abs_url = f"{RAW_BASE}/{owner}/{repo}/{branch}/{norm}"
        return f"{prefix}{abs_url})"

    return LINK_RE.sub(repl, md)


def fix_internal_links(md: str, file_paths: List[str], sections: List[Dict[str, Any]]) -> str:
    """Convert internal document references to anchors within the combined document.
    - Converts links like https://raw.githubusercontent.com/owner/repo/branch/path/file.md to #anchor
    - Converts relative links like path/file.md to #anchor
    - Only converts links that point to files actually included in the combined document
    """
    # Create a mapping of file paths to their anchors
    path_to_anchor = {}
    included_file_paths = set()
    
    for section in sections:
        title = section['title']
        anchor = section['anchor']
        path_to_anchor[title] = anchor
        included_file_paths.add(title)
        
        # Also map without .md extension
        if title.endswith('.md'):
            path_to_anchor[title[:-3]] = anchor
            included_file_paths.add(title[:-3])
    
    # Also extract relative paths from the original file paths
    for file_path in file_paths:
        if '/docs/' in file_path:
            relative_path = file_path.split('/docs/', 1)[1]
            included_file_paths.add(relative_path)
            if relative_path.endswith('.md'):
                included_file_paths.add(relative_path[:-3])

    # Pattern to match markdown links containing raw GitHub URLs
    MARKDOWN_INTERNAL_LINK_RE = re.compile(r'(\[[^\]]*\])\(https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/([^)]+)\)')
    
    # Pattern to match relative markdown links
    RELATIVE_LINK_RE = re.compile(r'(\[[^\]]*\])\(([^)#]+\.md|[^)#]+/)\)')
    
    def repl_github(m):
        link_text = m.group(1)  # [link text]
        # owner/repo/branch not needed for resolution; keep pattern groups for matching.
        path = m.group(5)
        
        # Remove .md extension if present for matching
        clean_path = path
        if clean_path.endswith('.md'):
            clean_path = clean_path[:-3]
        
        # Check if this path exists in our combined document
        path_with_md = f"{clean_path}.md"
        if path_with_md in path_to_anchor:
            return f"{link_text}({path_to_anchor[path_with_md]})"
        
        # Try without .md extension
        if clean_path in path_to_anchor:
            return f"{link_text}({path_to_anchor[clean_path]})"
        
        # If not found, leave the original link unchanged
        return m.group(0)
    
    def _normalize_rel_link_path(p: str) -> str:
        p = p.strip()
        # normalize common markdown forms
        while p.startswith("./"):
            p = p[2:]
        # drop querystring fragments here; fragment is not part of the captured group
        p = p.replace("\\", "/")
        return p

    def _try_resolve_to_anchor(candidate_paths: List[str]) -> Optional[str]:
        for cand in candidate_paths:
            if not cand:
                continue
            if cand in path_to_anchor:
                return path_to_anchor[cand]
            if cand.endswith('.md') and cand[:-3] in path_to_anchor:
                return path_to_anchor[cand[:-3]]
        return None

    def repl_relative(m):
        link_text = m.group(1)  # [link text]
        link_path_raw = m.group(2)  # path/file.md or path/
        link_path = _normalize_rel_link_path(link_path_raw)

        # Back-compat: attempt a few common base prefixes, but prefer direct matches first.
        base_paths = ["", "docs/", "docs/4-in-depth-tutorials/"]

        # Handle directory links (ending with /)
        if link_path.endswith('/'):
            readme_names = ["README.md", "readme.md", "index.md"]
            candidates: List[str] = []
            for base in base_paths:
                for name in readme_names:
                    candidates.append(f"{base}{link_path}{name}")
            resolved = _try_resolve_to_anchor(candidates)
            if resolved:
                return f"{link_text}({resolved})"

            # Fall back: if the directory itself matches a section key (rare), use it.
            resolved = _try_resolve_to_anchor([f"{base}{link_path.rstrip('/')}" for base in base_paths])
            if resolved:
                return f"{link_text}({resolved})"
        else:
            candidates = []
            for base in base_paths:
                candidates.append(f"{base}{link_path}")
                # If someone links without extension, try adding it
                if not link_path.endswith('.md'):
                    candidates.append(f"{base}{link_path}.md")

            resolved = _try_resolve_to_anchor(candidates)
            if resolved:
                return f"{link_text}({resolved})"

        # If we can't find the target file, mark as broken link
        clean_link = link_path.replace('/', '-').replace('.md', '').replace('_', '-')
        return f"{link_text}(#broken-link-{clean_link})"
    
    # Replace GitHub links first
    md = MARKDOWN_INTERNAL_LINK_RE.sub(repl_github, md)
    
    # Then replace relative links
    md = RELATIVE_LINK_RE.sub(repl_relative, md)
    
    return md


def build_toc(sections: List[Dict[str, Any]]) -> str:
    if not sections:
        return ""
    lines = ["## Table of Contents"]
    for sec in sections:
        # Use GitHub URL if available, otherwise fall back to anchor
        link_target = sec.get('github_url') or sec['anchor']
        lines.append(f"- [{sec['title']}]({link_target})")
    return "\n".join(lines) + "\n\n"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\s\-_]", "", text).strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    if not s:
        s = "section"
    return "#" + s


def list_local_tree(root_folder: str, verbose: bool = False, exclude_folders: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Recursively list files under a local folder.

    Returns items shaped similarly to GitHub items so the rest of the pipeline can reuse them.
    Each item has: path (posix), type='file', local_path (absolute str).
    """
    root = Path(root_folder).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Local folder not found or not a directory: {root}")

    excluded_dir_names = {
        ".git",
        ".github",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
    }

    exclude_prefixes = _normalize_exclude_folders(exclude_folders)

    items: List[Dict[str, Any]] = []
    for p in root.rglob("*"):
        if p.is_dir() and p.name in excluded_dir_names:
            # Skip walking into heavy/irrelevant directories
            # (Path.rglob can't prune directly, so we just skip collecting files within; best-effort.)
            continue
        if not p.is_file():
            continue
        if any(part in excluded_dir_names for part in p.parts):
            continue

        rel_path = p.relative_to(root).as_posix()
        if _is_excluded_path(rel_path, exclude_prefixes):
            if verbose:
                print(f"[LIST] Skip excluded local file: {rel_path}")
            continue
        items.append({
            "path": rel_path,
            "type": "file",
            "local_path": str(p),
            "source_kind": "local",
            "source_root": str(root),
        })
        if verbose:
            print(f"[LIST] Local file: {rel_path}")
    return items


def main():
    ap = argparse.ArgumentParser(description="Bundle GitHub docs into a single Markdown file")
    ap.add_argument("--owner", default="microsoft", help="GitHub owner")
    ap.add_argument("--repo", default="discovery", help="GitHub repo")
    ap.add_argument("--branch", default="main", help="Git branch/ref")
    ap.add_argument("--path", default="docs", help="Path within repo to gather")
    ap.add_argument("--output", default="combined-docs.md", help="Output Markdown file path")
    ap.add_argument("--remove-frontmatter", action="store_true", help="Remove YAML front-matter blocks")
    ap.add_argument("--fix-links", action="store_true", help="Rewrite relative links to absolute raw URLs")
    ap.add_argument("--fix-internal-links", action="store_true", help="Convert internal document references to anchors within the combined document")
    ap.add_argument("--toc", action="store_true", help="Include a simple table of contents")
    ap.add_argument("--max-files", type=int, default=0, help="Limit number of files (0 = no limit)")
    ap.add_argument("--token", help="GitHub token (overrides GITHUB_TOKEN env var)")
    ap.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    ap.add_argument("--url", help="GitHub URL like https://github.com/<owner>/<repo>/tree/<branch>/<path>")
    ap.add_argument("--urls", nargs="+", help="Multiple GitHub URLs to combine (takes precedence over --url)")
    ap.add_argument("--include-yaml", action="store_true", help="Include YAML files (.yaml, .yml) in addition to Markdown files")
    ap.add_argument("--local-folder", help="Local folder containing documentation to bundle (skips GitHub fetching)")
    ap.add_argument(
        "--exclude-folder",
        action="append",
        default=[],
        help="Exclude a folder prefix (relative path) from inclusion; can be specified multiple times",
    )
    ap.add_argument(
        "--build-index",
        action="store_true",
        help="Build/rebuild the v2 retrieval index after generating the combined docs",
    )
    ap.add_argument(
        "--index-dir",
        default=None,
        help="Directory to store the retrieval index (default: .retrieval_index next to output file)",
    )
    args = ap.parse_args()

    # Local-folder mode takes precedence over GitHub fetching.
    local_mode = bool(args.local_folder)

    all_items: List[Dict[str, Any]] = []
    processed_sources: List[str] = []

    if local_mode:
        if args.verbose:
            print(f"[INFO] Local-folder mode enabled: {args.local_folder}")
        try:
            all_items = list_local_tree(args.local_folder, verbose=args.verbose, exclude_folders=args.exclude_folder)
        except (RuntimeError, OSError) as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
        processed_sources.append(f"local:{Path(args.local_folder).expanduser().resolve()}")

        if args.fix_links:
            print("[WARN] --fix-links is only supported for GitHub sources; leaving local relative links unchanged.")
    else:
        # Determine URLs to process
        urls_to_process = []
        if args.urls:
            # Multiple URLs provided
            urls_to_process = args.urls
            if args.verbose:
                print(f"[INFO] Processing {len(urls_to_process)} URLs: {urls_to_process}")
        elif args.url:
            # Single URL provided
            urls_to_process = [args.url]
        else:
            # No URL provided, use individual parameters
            urls_to_process = [f"https://github.com/{args.owner}/{args.repo}/tree/{args.branch}/{args.path}"]

        # Process each URL
        for url_idx, url in enumerate(urls_to_process):
            if args.verbose:
                print(f"[INFO] Processing URL {url_idx + 1}/{len(urls_to_process)}: {url}")

            # Parse URL for this iteration
            if url.startswith("https://github.com/"):
                parsed = parse_github_tree_url(url)
                if not parsed:
                    print(f"[ERROR] Could not parse URL: {url}")
                    continue
                if args.verbose:
                    print(f"[INFO] Parsed URL -> owner={parsed['owner']} repo={parsed['repo']} branch={parsed['branch']} path={parsed['path']}")
                current_owner = parsed["owner"]
                current_repo = parsed["repo"]
                current_branch = parsed["branch"]
                current_path = parsed["path"] if parsed["path"] else ""
            else:
                print(f"[ERROR] Invalid URL format: {url}")
                continue

            print(f"[INFO] Listing {current_owner}/{current_repo}/{current_path}@{current_branch}")
            try:
                items = list_repo_tree(
                    current_owner,
                    current_repo,
                    current_path,
                    current_branch,
                    token=args.token,
                    verbose=args.verbose,
                    exclude_folders=args.exclude_folder,
                )
                # Add source information to each item
                for item in items:
                    item['source_url'] = url
                    item['source_owner'] = current_owner
                    item['source_repo'] = current_repo
                    item['source_branch'] = current_branch
                all_items.extend(items)
                processed_sources.append(f"{current_owner}/{current_repo}/{current_path}@{current_branch}")
            except (RuntimeError, requests.exceptions.RequestException) as e:
                msg = str(e)
                if "Path not found" in msg:
                    # Try to auto-discover correct folder casing at repo root
                    try:
                        root_entries = list_single_dir(current_owner, current_repo, "", current_branch, token=args.token)
                        dirs = [ent.get("path") for ent in root_entries if ent.get("type") == "dir"]
                        # Case-insensitive match
                        matches = [d for d in dirs if d and d.lower() == (current_path or "").lower()]
                        if matches:
                            fixed = matches[0]
                            if args.verbose:
                                print(f"[INFO] Auto-discovered path casing: '{current_path}' -> '{fixed}'")
                            current_path = fixed
                            items = list_repo_tree(
                                current_owner,
                                current_repo,
                                current_path,
                                current_branch,
                                token=args.token,
                                verbose=args.verbose,
                                exclude_folders=args.exclude_folder,
                            )
                            # Add source information to each item
                            for item in items:
                                item['source_url'] = url
                                item['source_owner'] = current_owner
                                item['source_repo'] = current_repo
                                item['source_branch'] = current_branch
                            all_items.extend(items)
                            processed_sources.append(f"{current_owner}/{current_repo}/{current_path}@{current_branch}")
                        else:
                            print(f"[ERROR] {msg} for URL: {url}")
                            if dirs:
                                print("[HINT] Top-level directories:")
                                for d in dirs:
                                    print(f"  - {d}")
                            continue
                    except (RuntimeError, requests.exceptions.RequestException) as ie:
                        print(f"[ERROR] {msg} for URL: {url}")
                        print(f"[HINT] Unable to list repo root to auto-discover path: {ie}")
                        continue
                else:
                    print(f"[ERROR] {e} for URL: {url}")
                    continue

    # Filter files based on type and sort: README.md first in each directory if present, then others lexicographically
    def is_supported_file(item):
        if item.get("type") != "file":
            return False
        path = str(item.get("path") or "").lower()
        if path.endswith(".md"):
            return True
        if args.include_yaml and (path.endswith(".yaml") or path.endswith(".yml")):
            return True
        return False
    
    supported_files = [it for it in all_items if is_supported_file(it)]
    if not supported_files:
        file_types = "markdown" + (" and YAML" if args.include_yaml else "")
        print(f"[WARN] No {file_types} files found.")
        sys.exit(0)

    # Sort by path with preference: README.md before others in same directory
    def sort_key(x):
        p = str(x.get("path") or "")
        dirp, base = os.path.split(p)
        pref = 0 if base.lower() == "readme.md" else 1
        return (dirp.lower(), pref, base.lower())

    supported_files.sort(key=sort_key)
    if args.max_files and args.max_files > 0:
        supported_files = supported_files[: args.max_files]

    file_types = "markdown" + (" and YAML" if args.include_yaml else "")
    if local_mode:
        print(f"[INFO] Found {len(supported_files)} {file_types} files. Reading from disk...")
    else:
        print(f"[INFO] Found {len(supported_files)} {file_types} files. Fetching...")
    if args.verbose and supported_files:
        for it in supported_files:
            print(f"[INFO] File: {it.get('path')} (from {it.get('source_url', 'unknown source')})")

    out_lines: List[str] = []
    sections: List[Dict[str, Any]] = []

    # Document header
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if not processed_sources:
        print("[ERROR] No valid sources processed")
        sys.exit(1)
    elif len(processed_sources) == 1:
        out_lines.append("# Combined Documentation for Microsoft Discovery\n")
    else:
        out_lines.append(f"# Combined Documentation from {len(processed_sources)} sources\n")
        out_lines.append(f"Sources: {', '.join(processed_sources)}\n")
    out_lines.append(f"_Generated: {ts}_\n\n")

    for i, f in enumerate(supported_files, start=1):
        rel_path = str(f.get("path") or "")
        file_dir = os.path.dirname(rel_path)
        source_info = "(local)" if local_mode else f"from {f.get('source_owner', 'unknown')}/{f.get('source_repo', 'unknown')}"
        
        if args.verbose:
            print(f"[FILE] {rel_path} {source_info}")
        try:
            if local_mode:
                local_path = f.get("local_path")
                if not local_path:
                    raise RuntimeError("Missing local_path for local item")
                with open(local_path, "r", encoding="utf-8") as lf:
                    content = lf.read()
            else:
                durl = f.get("download_url")
                if not durl:
                    # build raw URL manually
                    source_owner = f.get('source_owner', args.owner)
                    source_repo = f.get('source_repo', args.repo)
                    source_branch = f.get('source_branch', args.branch)
                    raw_url = f"{RAW_BASE}/{source_owner}/{source_repo}/{source_branch}/{f['path']}"
                    durl = raw_url
                if args.verbose:
                    print(f"[FILE] Raw URL: {durl}")
                content = fetch_raw(durl, token=args.token, verbose=args.verbose)
        except (OSError, UnicodeDecodeError, RuntimeError, requests.exceptions.RequestException) as fe:
            print(f"[WARN] Failed to fetch {f['path']} {source_info}: {fe}")
            continue

        # Handle content based on file type
        file_ext = rel_path.lower().split('.')[-1] if '.' in rel_path else ''
        
        if file_ext in ['yaml', 'yml']:
            # For YAML files, wrap content in code block
            if args.remove_frontmatter:
                content = strip_frontmatter(content)
            content = f"```yaml\n{content.rstrip()}\n```"
        else:
            # For Markdown files, process normally
            if args.remove_frontmatter:
                content = strip_frontmatter(content)
            if args.fix_links and not local_mode:
                source_owner = f.get('source_owner', args.owner)
                source_repo = f.get('source_repo', args.repo)
                source_branch = f.get('source_branch', args.branch)
                content = fix_links(content, source_owner, source_repo, source_branch, file_dir)

        # File section header + anchor
        title = rel_path
        anchor = slugify(title)
        # Source link
        source_owner = f.get('source_owner', args.owner)
        source_repo = f.get('source_repo', args.repo)
        source_branch = f.get('source_branch', args.branch)
        if local_mode:
            html_url = None
        else:
            html_url = f.get("html_url") or f"https://github.com/{source_owner}/{source_repo}/blob/{source_branch}/{rel_path}"
        sections.append({"title": title, "anchor": anchor, "github_url": html_url})
        out_lines.append(anchor)
        out_lines.append(f"\n\n## {title}\n")
        if local_mode:
            out_lines.append(f"Source: {rel_path} {source_info}\n\n")
        else:
            out_lines.append(f"Source: [{rel_path}]({html_url}) {source_info}\n\n")
        # Content
        out_lines.append(content.rstrip() + "\n\n")
        print(f"  [{i}/{len(supported_files)}] {rel_path} {source_info}")

    # Prepend TOC if requested
    if args.toc and sections:
        toc = build_toc(sections)
        out_lines.insert(2, toc)  # after title and generated line

    # Apply internal link fixing if requested (after all content is processed)
    if args.fix_internal_links:
        print("[INFO] Fixing internal document links...")
        # Join all content, fix internal links, then split back
        full_content = "".join(out_lines)
        all_file_paths = [section['title'] for section in sections]
        full_content = fix_internal_links(full_content, all_file_paths, sections)
        out_lines = [full_content]

    try:
        if args.verbose:
            print(f"[WRITE] Output -> {args.output}")
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("".join(out_lines))
        print(f"[OK] Wrote {args.output}")
    except OSError as we:
        print(f"[ERROR] Failed to write output: {we}")
        sys.exit(2)

    # Build retrieval index if requested
    if args.build_index:
        build_retrieval_index(
            docs_path=args.output,
            index_dir=args.index_dir,
            verbose=args.verbose,
        )


def build_retrieval_index(
    docs_path: str,
    index_dir: Optional[str] = None,
    verbose: bool = False,
) -> bool:
    """Build or rebuild the v2 retrieval index for the given docs file.
    
    Args:
        docs_path: Path to the combined markdown documentation file.
        index_dir: Directory to store the index. Defaults to .retrieval_index next to docs.
        verbose: Enable verbose logging.
        
    Returns:
        True if successful, False otherwise.
    """
    print("[INDEX] Building v2 retrieval index...")
    
    # Resolve paths
    docs_path_resolved = Path(docs_path).expanduser().resolve()
    if not docs_path_resolved.exists():
        print(f"[ERROR] Docs file not found: {docs_path_resolved}")
        return False
    
    if index_dir:
        index_dir_resolved = Path(index_dir).expanduser().resolve()
    else:
        index_dir_resolved = docs_path_resolved.parent / ".retrieval_index"
    
    if verbose:
        print(f"[INDEX] Docs: {docs_path_resolved}")
        print(f"[INDEX] Index dir: {index_dir_resolved}")
    
    # Import the retriever
    try:
        # Add parent directory to path for imports
        script_dir = Path(__file__).parent.parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        
        from discovery_docs_retriever import DiscoveryRetriever
    except ImportError as e:
        print(f"[ERROR] Could not import retriever: {e}")
        print("[HINT] Make sure discovery_docs_retriever.py is in the agent-workbench directory")
        return False
    
    try:
        # Delete existing index to force fresh build
        import shutil
        if index_dir_resolved.exists():
            if verbose:
                print(f"[INDEX] Removing old index at {index_dir_resolved}")
            shutil.rmtree(index_dir_resolved, ignore_errors=True)
        
        # Create retriever which will build and save the index
        retriever = DiscoveryRetriever(
            docs_path=str(docs_path_resolved),
            index_dir=str(index_dir_resolved),
            embedding_fn=None,  # Skip embeddings for CLI builds
            llm_rerank_fn=None,  # Skip LLM reranking for CLI builds
            use_embeddings=False,
            use_llm_rerank=False,
        )
        
        print(f"[OK] Built index with {retriever.chunk_count} chunks")
        print(f"[OK] Index saved to: {index_dir_resolved}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to build index: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return False


if __name__ == "__main__":
    main()