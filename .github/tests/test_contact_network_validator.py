from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from contact_network_validator import (  # noqa: E402
    DNSNoAnswer,
    ContactNetworkPolicy,
    WebResponse,
    validate_email_domain,
    validate_webpage,
)


POLICY = ContactNetworkPolicy.load(
    Path(__file__).resolve().parents[1] / "policy" / "contact-network.json"
)


def test_email_domain_accepts_mx_record() -> None:
    def resolve(domain: str, record_type: str, timeout: float) -> list[str]:
        assert (domain, record_type, timeout) == ("example.com", "MX", 5.0)
        return ["mail.example.com."]

    assert validate_email_domain(
        "owner@example.com", POLICY.email_domain, resolver=resolve
    ) is None


def test_email_domain_accepts_implicit_mx_fallback() -> None:
    def resolve(domain: str, record_type: str, timeout: float) -> list[str]:
        if record_type == "MX":
            raise DNSNoAnswer
        if record_type == "A":
            return ["93.184.216.34"]
        raise AssertionError("AAAA should not be queried after A succeeds")

    assert validate_email_domain(
        "owner@example.com", POLICY.email_domain, resolver=resolve
    ) is None


def test_email_domain_rejects_null_mx() -> None:
    error = validate_email_domain(
        "owner@example.com",
        POLICY.email_domain,
        resolver=lambda *_: ["."],
    )

    assert error is not None
    assert "null MX" in error


def test_email_domain_rejects_domain_without_dns_records() -> None:
    def resolve(domain: str, record_type: str, timeout: float) -> list[str]:
        raise DNSNoAnswer

    error = validate_email_domain(
        "owner@example.invalid", POLICY.email_domain, resolver=resolve
    )

    assert error == "domain 'example.invalid' has no MX, A, or AAAA records"


def test_webpage_accepts_public_html_page() -> None:
    requested: list[tuple[str, str]] = []

    def request(parsed, address, timeout, max_response_bytes):
        requested.append((parsed.geturl(), address))
        return WebResponse(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=b"<!doctype html><title>Support</title>",
        )

    error = validate_webpage(
        "https://example.com/support",
        POLICY.webpage,
        address_resolver=lambda *_: ["93.184.216.34"],
        requester=request,
    )

    assert error is None
    assert requested == [("https://example.com/support", "93.184.216.34")]


def test_webpage_rejects_redirect_to_private_address() -> None:
    requested: list[str] = []

    def resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"] if host == "example.com" else ["127.0.0.1"]

    def request(parsed, address, timeout, max_response_bytes):
        requested.append(parsed.hostname)
        return WebResponse(
            status=302,
            headers={"location": "https://internal.example/admin"},
            body=b"redirect",
        )

    error = validate_webpage(
        "https://example.com/support",
        POLICY.webpage,
        address_resolver=resolve,
        requester=request,
    )

    assert error == "host 'internal.example' resolves to non-public address '127.0.0.1'"
    assert requested == ["example.com"]


def test_webpage_rejects_non_html_response() -> None:
    error = validate_webpage(
        "https://example.com/support",
        POLICY.webpage,
        address_resolver=lambda *_: ["93.184.216.34"],
        requester=lambda *_: WebResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=b"{}",
        ),
    )

    assert error == "returned 'application/json', not an HTML webpage"