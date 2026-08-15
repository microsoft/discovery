"""Weekly URLhaus and PhishTank reputation audit."""

from __future__ import annotations

import json
from pathlib import Path

import url_reputation_audit as audit


def _catalog_url(url: str = "https://example.com/support") -> audit.CatalogUrl:
    return audit.CatalogUrl(
        url=url,
        locations=(audit.CatalogLocation("agents/demo/metadata.yaml", "publisher.support_url", 3),),
    )


def test_collect_catalog_urls_deduplicates_and_preserves_locations(tmp_path: Path):
    metadata = tmp_path / "agents" / "demo" / "metadata.yaml"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        "publisher:\n  support_url: https://example.com/support\n",
        encoding="utf-8",
    )
    kit = tmp_path / "starter-kits" / "demo" / "kit.json"
    kit.parent.mkdir(parents=True)
    kit.write_text(json.dumps({
        "author": {"url": "https://example.com/support"},
        "homepage": "https://example.com/home",
    }, indent=2), encoding="utf-8")

    urls = audit.collect_catalog_urls(tmp_path)

    assert [item.url for item in urls] == [
        "https://example.com/home",
        "https://example.com/support",
    ]
    assert len(urls[1].locations) == 2
    assert urls[1].locations[0].line == 2


def test_audit_checks_each_url_with_both_providers():
    checked: list[tuple[str, str, str]] = []

    def clean(provider: str):
        def lookup(url: str, key: str):
            checked.append((provider, url, key))
            return None

        return lookup

    result = audit.audit_catalog_urls(
        [_catalog_url()],
        "urlhaus-secret",
        "phishtank-secret",
        urlhaus_lookup=clean("URLhaus"),
        phishtank_lookup=clean("PhishTank"),
    )

    assert result["passed"] is True
    assert result["provider_checks"] == {"URLhaus": 1, "PhishTank": 1}
    assert checked == [
        ("URLhaus", "https://example.com/support", "urlhaus-secret"),
        ("PhishTank", "https://example.com/support", "phishtank-secret"),
    ]


def test_audit_reports_malware_and_verified_phishing_matches():
    result = audit.audit_catalog_urls(
        [_catalog_url()],
        "urlhaus-secret",
        "phishtank-secret",
        urlhaus_lookup=lambda *_: ("malware distribution", "online"),
        phishtank_lookup=lambda *_: ("verified phishing", "online"),
    )

    assert result["passed"] is False
    assert [finding["provider"] for finding in result["findings"]] == [
        "URLhaus",
        "PhishTank",
    ]
    summary = audit.render_markdown(result)
    assert "`agents/demo/metadata.yaml:3`" in summary
    assert "`https://example.com/support`" in summary


def test_provider_failure_does_not_prevent_other_provider_check():
    def unavailable(*_):
        raise audit.ReputationServiceError("URLhaus could not be reached")

    result = audit.audit_catalog_urls(
        [_catalog_url()],
        "urlhaus-secret",
        "phishtank-secret",
        urlhaus_lookup=unavailable,
        phishtank_lookup=lambda *_: None,
    )

    assert result["provider_checks"] == {"URLhaus": 0, "PhishTank": 1}
    assert result["errors"] == [{
        "provider": "URLhaus",
        "message": "URLhaus could not be reached",
    }]


def test_urlhaus_key_is_sent_in_header_not_endpoint(monkeypatch):
    captured: dict = {}

    def post_json(provider, endpoint, fields, headers=None):
        captured.update({
            "provider": provider,
            "endpoint": endpoint,
            "fields": fields,
            "headers": headers,
        })
        return {"query_status": "no_results"}

    monkeypatch.setattr(audit, "_post_json", post_json)

    assert audit.query_urlhaus("https://example.com", "secret-key") is None
    assert "secret-key" not in captured["endpoint"]
    assert captured["headers"] == {"Auth-Key": "secret-key"}
    assert captured["fields"] == {"url": "https://example.com"}


def test_phishtank_requires_verified_valid_match(monkeypatch):
    responses = iter([
        {"results": {"in_database": True, "verified": "y", "valid": "y"}},
        {"results": {"in_database": True, "verified": "y", "valid": "n"}},
    ])

    def post_json(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr(audit, "_post_json", post_json)

    assert audit.query_phishtank("https://example.com", "secret-key") == (
        "verified phishing",
        "online",
    )
    assert audit.query_phishtank("https://example.com", "secret-key") is None


def test_phishtank_key_is_posted_not_in_endpoint(monkeypatch):
    captured: dict = {}

    def post_json(provider, endpoint, fields, headers=None):
        captured.update({
            "provider": provider,
            "endpoint": endpoint,
            "fields": fields,
            "headers": headers,
        })
        return {"results": {"in_database": False}}

    monkeypatch.setattr(audit, "_post_json", post_json)

    assert audit.query_phishtank("https://example.com", "secret-key") is None
    assert "secret-key" not in captured["endpoint"]
    assert captured["fields"] == {
        "url": "https://example.com",
        "format": "json",
        "app_key": "secret-key",
    }


def test_missing_credentials_are_configuration_errors():
    result = audit.audit_catalog_urls([_catalog_url()], "", "")

    assert result["passed"] is False
    assert [error["provider"] for error in result["errors"]] == [
        "URLhaus",
        "PhishTank",
    ]