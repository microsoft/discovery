"""Credential factory robust to long-running CI jobs that authenticate via OIDC.

An OIDC federated token (the AAD "client assertion") is short-lived
(~5 minutes). Tooling such as ``azure/login`` / ``DefaultAzureCredential``
exchanges a single assertion for one Azure access token at the start of a job.
Once that access token expires, or a token for a *different* audience is
requested later in the run (e.g. the Foundry evaluation after a long
investigation), the SDK falls back to re-authenticating with the now-expired
assertion and fails with::

    AADSTS700024: Client assertion is not within its valid time range.

When running in a CI environment with OIDC enabled, this module returns the
SDK's own ``ClientAssertionCredential``. That credential caches the Azure
access token in memory and only invokes its callback to mint a fresh OIDC
assertion when it actually needs a new access token (on expiry or for a new
audience), so refresh works for jobs of any length. All security-critical token
exchange and caching is handled by the Azure Identity SDK, not by this module;
the only custom code is a plain HTTPS GET to the GitHub OIDC endpoint (the same
call ``azure/login`` makes internally). Outside such an environment (e.g. local
dev) it falls back to ``DefaultAzureCredential``.

Requires (in CI): the ability to mint OIDC tokens plus ``AZURE_CLIENT_ID`` and
``AZURE_TENANT_ID`` exported to the step.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

# Fixed audience expected by an Azure AD federated identity credential.
_GITHUB_OIDC_AUDIENCE = "api://AzureADTokenExchange"


def _fetch_github_oidc_token() -> str:
    """Mint a fresh GitHub Actions OIDC token for the AAD token-exchange audience."""
    req_url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    req_token = os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
    url = f"{req_url}&audience={urllib.parse.quote(_GITHUB_OIDC_AUDIENCE)}"
    # Guard against non-HTTPS schemes (e.g. file://) reaching urlopen: the OIDC
    # request URL must be the GitHub Actions HTTPS token endpoint.
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("ACTIONS_ID_TOKEN_REQUEST_URL must be an https URL")
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {req_token}"})
    with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["value"]


def get_credential():
    """Return a TokenCredential suited to the current environment.

    In GitHub Actions with OIDC configured, returns a ``ClientAssertionCredential``
    that re-mints a short-lived GitHub OIDC assertion only when the SDK needs a
    new access token (so long jobs never outlive their assertion); the SDK caches
    the access token itself. Otherwise returns ``DefaultAzureCredential``.
    """
    client_id = os.environ.get("AZURE_CLIENT_ID")
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    in_actions_oidc = bool(
        os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
        and os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        and client_id
        and tenant_id
    )
    if in_actions_oidc:
        from azure.identity import ClientAssertionCredential

        return ClientAssertionCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            func=_fetch_github_oidc_token,
        )

    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()
