#!/usr/bin/env python3
"""Network-backed validation for catalog contact email domains and webpages."""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import SplitResult, urljoin, urlsplit


class DNSNoAnswer(Exception):
    """The domain exists but has no records of the requested type."""


class DNSLookupError(Exception):
    """The DNS lookup could not establish that the domain exists."""


@dataclass(frozen=True)
class EmailDomainPolicy:
    timeout_seconds: float
    fallback_record_types: tuple[str, ...]


@dataclass(frozen=True)
class WebpagePolicy:
    allowed_ports: tuple[int, ...]
    timeout_seconds: float
    max_redirects: int
    max_response_bytes: int
    allowed_content_types: tuple[str, ...]


@dataclass(frozen=True)
class ContactNetworkPolicy:
    email_domain: EmailDomainPolicy
    webpage: WebpagePolicy

    @classmethod
    def load(cls, path: Path) -> "ContactNetworkPolicy":
        data = json.loads(path.read_text(encoding="utf-8"))
        email = data["email_domain"]
        webpage = data["webpage"]
        return cls(
            email_domain=EmailDomainPolicy(
                timeout_seconds=float(email["timeout_seconds"]),
                fallback_record_types=tuple(email["fallback_record_types"]),
            ),
            webpage=WebpagePolicy(
                allowed_ports=tuple(int(port) for port in webpage["allowed_ports"]),
                timeout_seconds=float(webpage["timeout_seconds"]),
                max_redirects=int(webpage["max_redirects"]),
                max_response_bytes=int(webpage["max_response_bytes"]),
                allowed_content_types=tuple(
                    str(value).lower() for value in webpage["allowed_content_types"]
                ),
            ),
        )


@dataclass(frozen=True)
class WebResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


DNSResolver = Callable[[str, str, float], Sequence[str]]
AddressResolver = Callable[[str, int], Sequence[str]]
WebRequester = Callable[[SplitResult, str, float, int], WebResponse]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def validate_email_domain(
    email: str,
    policy: EmailDomainPolicy,
    *,
    resolver: DNSResolver | None = None,
) -> str | None:
    """Return an error when an address's domain has no usable mail DNS."""
    if email.count("@") != 1:
        return "must contain one @ separating the local part and domain"

    local_part, raw_domain = email.rsplit("@", 1)
    if not local_part or not raw_domain:
        return "must contain a non-empty local part and domain"

    domain, domain_error = _normalize_domain(raw_domain)
    if domain_error:
        return domain_error

    resolve = resolver or _resolve_dns
    try:
        mx_records = resolve(domain, "MX", policy.timeout_seconds)
    except DNSNoAnswer:
        mx_records = ()
    except DNSLookupError as exc:
        return str(exc)

    if mx_records:
        exchanges = [str(record).strip().rstrip(".") for record in mx_records]
        if any(not exchange for exchange in exchanges):
            return f"domain '{domain}' publishes a null MX record and does not accept email"
        return None

    for record_type in policy.fallback_record_types:
        try:
            if resolve(domain, record_type, policy.timeout_seconds):
                return None
        except DNSNoAnswer:
            continue
        except DNSLookupError as exc:
            return str(exc)

    return f"domain '{domain}' has no MX, A, or AAAA records"


def validate_webpage(
    url: str,
    policy: WebpagePolicy,
    *,
    address_resolver: AddressResolver | None = None,
    requester: WebRequester | None = None,
) -> str | None:
    """Return an error unless an HTTPS URL resolves publicly to an HTML page."""
    resolve_addresses = address_resolver or _resolve_addresses
    make_request = requester or _request_webpage
    current_url = url
    visited: set[str] = set()

    for redirect_count in range(policy.max_redirects + 1):
        parsed, parse_error = _parse_https_url(current_url, policy.allowed_ports)
        if parse_error:
            return parse_error

        normalized_url = parsed.geturl()
        if normalized_url in visited:
            return "redirect loop detected"
        visited.add(normalized_url)

        host = parsed.hostname or ""
        port = parsed.port or 443
        try:
            raw_addresses = resolve_addresses(host, port)
        except (OSError, socket.gaierror) as exc:
            return f"host '{host}' could not be resolved: {exc}"

        addresses, address_error = _require_public_addresses(host, raw_addresses)
        if address_error:
            return address_error

        response: WebResponse | None = None
        request_errors: list[str] = []
        for address in addresses:
            try:
                response = make_request(
                    parsed,
                    address,
                    policy.timeout_seconds,
                    policy.max_response_bytes,
                )
                break
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                request_errors.append(str(exc))

        if response is None:
            detail = request_errors[-1] if request_errors else "no address was returned"
            return f"could not connect to '{host}': {detail}"

        if response.status in _REDIRECT_STATUSES:
            location = response.headers.get("location", "").strip()
            if not location:
                return f"HTTP {response.status} response has no Location header"
            if redirect_count == policy.max_redirects:
                return f"exceeded {policy.max_redirects} redirects"
            current_url = urljoin(normalized_url, location)
            continue

        if not 200 <= response.status < 300:
            return f"returned terminal HTTP status {response.status}"

        content_type = response.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type not in policy.allowed_content_types:
            shown_type = media_type or "missing Content-Type"
            return f"returned '{shown_type}', not an HTML webpage"
        if not response.body.strip():
            return "returned an empty response body"
        return None

    return "redirect limit exceeded"


def _normalize_domain(raw_domain: str) -> tuple[str, str | None]:
    if raw_domain != raw_domain.strip() or raw_domain.endswith("."):
        return "", "email domain must not contain whitespace or a trailing dot"
    try:
        domain = raw_domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return "", "email domain is not a valid IDNA hostname"

    if len(domain) > 253:
        return "", "email domain exceeds 253 characters"
    labels = domain.split(".")
    if len(labels) < 2:
        return "", "email domain must be a fully qualified domain name"
    for label in labels:
        if (
            not 1 <= len(label) <= 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(character.isalnum() or character == "-" for character in label)
        ):
            return "", f"email domain '{domain}' is not a valid hostname"
    return domain, None


def _resolve_dns(domain: str, record_type: str, timeout: float) -> Sequence[str]:
    try:
        import dns.exception
        import dns.resolver
    except ImportError as exc:
        raise DNSLookupError("DNS validation requires the 'dnspython' package") from exc

    try:
        answer = dns.resolver.resolve(domain, record_type, lifetime=timeout)
    except dns.resolver.NoAnswer as exc:
        raise DNSNoAnswer from exc
    except dns.resolver.NXDOMAIN as exc:
        raise DNSLookupError(f"domain '{domain}' does not exist in DNS") from exc
    except dns.exception.Timeout as exc:
        raise DNSLookupError(f"DNS lookup for '{domain}' timed out") from exc
    except dns.resolver.NoNameservers as exc:
        raise DNSLookupError(f"DNS lookup for '{domain}' had no usable nameserver") from exc

    if record_type == "MX":
        return [str(record.exchange) for record in answer]
    return [str(record) for record in answer]


def _resolve_addresses(host: str, port: int) -> Sequence[str]:
    records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(record[4][0] for record in records))


def _require_public_addresses(
    host: str,
    raw_addresses: Sequence[str],
) -> tuple[tuple[str, ...], str | None]:
    if not raw_addresses:
        return (), f"host '{host}' has no A or AAAA records"

    addresses: list[str] = []
    for raw_address in raw_addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError:
            return (), f"host '{host}' resolved to invalid address '{raw_address}'"
        if not address.is_global:
            return (), f"host '{host}' resolves to non-public address '{address}'"
        text = str(address)
        if text not in addresses:
            addresses.append(text)
    return tuple(addresses), None


def _parse_https_url(
    url: str,
    allowed_ports: Sequence[int],
) -> tuple[SplitResult, str | None]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        return SplitResult("", "", "", "", ""), f"is not a valid URL: {exc}"

    if parsed.scheme.lower() != "https":
        return parsed, "must use HTTPS"
    if not parsed.hostname:
        return parsed, "must include a hostname"
    if parsed.username is not None or parsed.password is not None:
        return parsed, "must not include embedded credentials"
    if parsed.hostname.lower() == "localhost" or parsed.hostname.lower().endswith(".localhost"):
        return parsed, "must not target localhost"

    effective_port = port or 443
    if effective_port not in allowed_ports:
        return parsed, f"port {effective_port} is not allowed"

    request_target = parsed.path or "/"
    if parsed.query:
        request_target += f"?{parsed.query}"
    if any(character.isspace() or ord(character) < 0x20 for character in request_target):
        return parsed, "contains whitespace or control characters"
    return parsed, None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        hostname: str,
        address: str,
        port: int,
        timeout: float,
    ) -> None:
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._validated_address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._validated_address, self.port),
            timeout=self.timeout,
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def _request_webpage(
    parsed: SplitResult,
    address: str,
    timeout: float,
    max_response_bytes: int,
) -> WebResponse:
    hostname = (parsed.hostname or "").encode("idna").decode("ascii")
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"

    connection = _PinnedHTTPSConnection(hostname, address, port, timeout)
    try:
        host_header = hostname if port == 443 else f"{hostname}:{port}"
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "identity",
                "Connection": "close",
                "Host": host_header,
                "User-Agent": "microsoft-discovery-contact-validator/1.0",
            },
        )
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        body = response.read(max_response_bytes)
        return WebResponse(status=response.status, headers=headers, body=body)
    finally:
        connection.close()