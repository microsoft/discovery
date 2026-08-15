#!/usr/bin/env python3
"""Weekly URLhaus and PhishTank reputation audit for catalog webpages.

The audit submits catalog URLs only to the providers' lookup APIs. It never
connects to a catalog destination or downloads a malicious payload.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

URLHAUS_ENDPOINT = "https://urlhaus-api.abuse.ch/v1/url/"
PHISHTANK_ENDPOINT = "https://checkurl.phishtank.com/checkurl/"
USER_AGENT = "phishtank/microsoft-discovery"
MAX_RESPONSE_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 15


class ReputationServiceError(RuntimeError):
    """A provider lookup failed without exposing credentials or response data."""


@dataclass(frozen=True)
class CatalogLocation:
    file: str
    field: str
    line: int


@dataclass(frozen=True)
class CatalogUrl:
    url: str
    locations: tuple[CatalogLocation, ...]


@dataclass(frozen=True)
class ReputationFinding:
    provider: str
    url: str
    classification: str
    provider_status: str
    locations: tuple[CatalogLocation, ...]


def _line_for_key(path: Path, key: str) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 1
    pattern = re.compile(rf'^\s*["\']?{re.escape(key)}["\']?\s*:')
    for line_number, line in enumerate(text.splitlines(), start=1):
        if pattern.match(line):
            return line_number
    return 1


def collect_catalog_urls(repo: Path) -> list[CatalogUrl]:
    """Collect and deduplicate the webpage fields governed by POL-018."""
    found: dict[str, list[CatalogLocation]] = {}

    def add(path: Path, field: str, key: str, value: object) -> None:
        if not isinstance(value, str) or not value:
            return
        rel = path.relative_to(repo).as_posix()
        found.setdefault(value, []).append(
            CatalogLocation(rel, field, _line_for_key(path, key))
        )

    for path in sorted((repo / "agents").glob("*/metadata.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        publisher = data.get("publisher") if isinstance(data, dict) else None
        if isinstance(publisher, dict):
            add(path, "publisher.support_url", "support_url", publisher.get("support_url"))

    for path in sorted((repo / "starter-kits").glob("*/kit.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        author = data.get("author")
        if isinstance(author, dict):
            add(path, "author.url", "url", author.get("url"))
        for key in ("homepage", "repository"):
            add(path, key, key, data.get(key))

    return [
        CatalogUrl(url, tuple(locations))
        for url, locations in sorted(found.items())
    ]


def _post_json(
    provider: str,
    endpoint: str,
    fields: dict[str, str],
    headers: dict[str, str] | None = None,
) -> dict:
    body = urlencode(fields).encode("utf-8")
    request_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
        **(headers or {}),
    }
    request = Request(endpoint, data=body, headers=request_headers, method="POST")

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise ReputationServiceError(f"{provider} returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, socket.timeout):
        raise ReputationServiceError(f"{provider} could not be reached") from None

    if len(raw) > MAX_RESPONSE_BYTES:
        raise ReputationServiceError(f"{provider} response exceeded the size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ReputationServiceError(f"{provider} returned an invalid JSON response") from None
    if not isinstance(payload, dict):
        raise ReputationServiceError(f"{provider} returned an unexpected response")
    return payload


def query_urlhaus(url: str, auth_key: str) -> tuple[str, str] | None:
    payload = _post_json(
        "URLhaus",
        URLHAUS_ENDPOINT,
        {"url": url},
        {"Auth-Key": auth_key},
    )
    query_status = payload.get("query_status")
    if query_status == "no_results":
        return None
    if query_status != "ok":
        raise ReputationServiceError("URLhaus rejected a catalog URL lookup")
    status = payload.get("url_status")
    safe_status = status if status in {"online", "offline", "unknown"} else "listed"
    return "malware distribution", safe_status


def _is_true(value: object) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "y", "yes"}


def query_phishtank(url: str, app_key: str) -> tuple[str, str] | None:
    fields = {"url": url, "format": "json"}
    if app_key:
        fields["app_key"] = app_key
    payload = _post_json(
        "PhishTank",
        PHISHTANK_ENDPOINT,
        fields,
    )
    results = payload.get("results")
    if not isinstance(results, dict):
        raise ReputationServiceError("PhishTank returned an unexpected response")
    if not _is_true(results.get("in_database")):
        return None
    if _is_true(results.get("verified")) and _is_true(results.get("valid")):
        return "verified phishing", "online"
    return None


Lookup = Callable[[str, str], tuple[str, str] | None]


def audit_catalog_urls(
    catalog_urls: list[CatalogUrl],
    urlhaus_key: str,
    phishtank_key: str,
    *,
    urlhaus_lookup: Lookup = query_urlhaus,
    phishtank_lookup: Lookup = query_phishtank,
) -> dict:
    findings: list[ReputationFinding] = []
    errors: list[dict[str, str]] = []
    provider_counts = {"URLhaus": 0, "PhishTank": 0}

    providers = (
        ("URLhaus", urlhaus_key, urlhaus_lookup),
        ("PhishTank", phishtank_key, phishtank_lookup),
    )
    for provider, key, lookup in providers:
        if not key:
            errors.append({"provider": provider, "message": f"{provider} credential is not configured"})
            continue
        for catalog_url in catalog_urls:
            try:
                result = lookup(catalog_url.url, key)
            except ReputationServiceError as exc:
                errors.append({"provider": provider, "message": str(exc)})
                break
            provider_counts[provider] += 1
            if result:
                classification, status = result
                findings.append(ReputationFinding(
                    provider=provider,
                    url=catalog_url.url,
                    classification=classification,
                    provider_status=status,
                    locations=catalog_url.locations,
                ))

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "catalog_url_count": len(catalog_urls),
        "provider_checks": provider_counts,
        "passed": not findings and not errors,
        "findings": [asdict(finding) for finding in findings],
        "errors": errors,
    }


def render_markdown(result: dict) -> str:
    lines = [
        "## URL reputation audit",
        "",
        f"Checked {result['catalog_url_count']} unique catalog URL(s) against URLhaus and PhishTank.",
        "",
    ]
    errors = result.get("errors", [])
    findings = result.get("findings", [])
    if errors:
        lines.append("### Provider errors")
        lines.append("")
        for error in errors:
            lines.append(f"- **{error['provider']}**: {error['message']}")
        lines.append("")
    if findings:
        lines.extend([
            "### Reputation matches",
            "",
            "| Provider | Classification | Catalog location | URL |",
            "|---|---|---|---|",
        ])
        for finding in findings:
            locations = ", ".join(
                f"`{location['file']}:{location['line']}` ({location['field']})"
                for location in finding["locations"]
            )
            lines.append(
                f"| {finding['provider']} | {finding['classification']} "
                f"({finding['provider_status']}) | {locations} | `{finding['url']}` |"
            )
        lines.append("")
    if not errors and not findings:
        lines.append("No catalog URLs were listed as malware or verified phishing.")
        lines.append("")
    return "\n".join(lines)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()

    result = audit_catalog_urls(
        collect_catalog_urls(Path(args.repo_root).resolve()),
        os.environ.get("URLHAUS_AUTH_KEY", ""),
        os.environ.get("PHISHTANK_APP_KEY", ""),
    )
    _write(args.output, json.dumps(result, indent=2) + "\n")
    _write(args.summary_output, render_markdown(result))
    if result["errors"]:
        return 2
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())