# Connecting the OpenAlex MCP tool

This walkthrough follows the Azure API operations used to connect `OpenAlexResearchLandscape` to
the provider-hosted server at `https://mcp.openalex.org/mcp`. It creates a project-specific custom
OAuth connection, registers an OpenAlex OAuth client, attaches the read-only MCP tools to a new
agent version, and verifies a real tool call through Discovery.

**Validation boundary:** the API path was exercised with one user in a development workspace.
The examples below replace private identifiers with inputs. They were syntax-checked, but were not
rerun to create another OAuth client. Foundry UI setup, Discovery Studio's consent-link display,
and independent installation by another user remain unverified. See
[`../TEST_RESULTS.md`](../TEST_RESULTS.md).

## 1. Deploy the agent

Deploy [`../agent.yaml`](../agent.yaml) with your project's model deployment replacing
`{{CHAT-MODEL}}`. The repository's
[agent deployer](../../../.github/skills/discovery-services-agent-deployer/SKILL.md) can do this:

```powershell
pwsh -NoProfile -File .github\skills\discovery-services-agent-deployer\scripts\deploy-discovery-agent.ps1 openalex-research-landscape -SkipValidation
```

Run from the repository root and supply the deployer's required local configuration as described in
its [configuration reference](../../../.github/skills/discovery-services-agent-deployer/references/configuration.md).
This agent ships no container. The runner still requires `acrName` and `forceToolImageRebuild`;
`"not-used"` and `false` were used in the test configuration, without provisioning a registry.
Validation is deferred here because the OAuth connection and MCP binding do not exist yet.
Deployment success alone is not integration success.

## 2. Set inputs and authenticate

Use PowerShell 7+, Azure CLI, and an account authorized for the target tenant and subscription.
Creating a project connection requires the appropriate Foundry project-management permissions.
Creating the MCP-bound agent version also requires agent-write permissions; agent-consumption
permission alone is not enough for setup. OAuth identity passthrough requires the user's Microsoft
Entra tenant to match the project's tenant. See Microsoft's
[MCP documentation](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol).

Get the **backing Foundry project's** resource ID and endpoint from its project overview; do not
substitute the Discovery project's name or resource group. Verify that its data-plane endpoint is
reachable under your organization's network policies. A `NetworkSecurityPerimeter` denial needs
administrator resolution, not a different OAuth payload or a fabricated capability tag.

Set these inputs in one PowerShell session. URLs are service endpoints, not filesystem paths.

```powershell
$ErrorActionPreference = 'Stop'
$SubscriptionId = '<your subscription ID>'
$FoundryProjectResourceId = '<full ARM resource ID of the backing Foundry project>'
$FoundryProjectEndpoint = '<Foundry project endpoint ending in /api/projects/project-name>'
$WorkspaceEndpoint = '<Discovery workspace API endpoint>'
$DiscoveryProject = '<Discovery project name>'
$AgentName = 'OpenAlexResearchLandscape'
$ConnectionName = 'openalex'

$FoundryProjectEndpoint = $FoundryProjectEndpoint.TrimEnd('/')
$WorkspaceEndpoint = $WorkspaceEndpoint.TrimEnd('/')
$FoundryProjectResourceId = $FoundryProjectResourceId.TrimEnd('/')

function Get-AccessToken([string]$Resource) {
    $token = az account get-access-token --subscription $SubscriptionId `
        --resource $Resource --query accessToken -o tsv --only-show-errors
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
        throw "Could not obtain an access token for $Resource."
    }
    return $token.Trim()
}
```

Azure credentials authorize the Microsoft APIs. They do not replace the user's free OpenAlex
account or the separate OpenAlex consent step. Never paste passwords, API keys, or OAuth tokens into
an agent conversation.

## 3. Create the connection and register its OAuth client

The verified connection API version was `2025-04-01-preview`. Run this block only for a **new**
connection name. It refuses to overwrite an existing connection. For an existing `openalex`
connection, inspect its endpoint and OAuth settings, and reuse it only if they are correct.

```powershell
$ConnectionId = "$FoundryProjectResourceId/connections/$ConnectionName"
$ConnectionUrl = "https://management.azure.com${ConnectionId}?api-version=2025-04-01-preview"
$ArmHeaders = @{ Authorization = "Bearer $(Get-AccessToken 'https://management.azure.com')" }
$Existing = Invoke-WebRequest -Method Get -Uri $ConnectionUrl -Headers $ArmHeaders `
    -SkipHttpErrorCheck
if ($Existing.StatusCode -eq 200) {
    throw 'Connection already exists. Inspect it instead of overwriting its credentials.'
}
if ($Existing.StatusCode -ne 404) {
    throw "Connection lookup failed with HTTP $($Existing.StatusCode)."
}

$ConnectionBody = @{
    properties = @{
        authType = 'OAuth2'
        category = 'RemoteTool'
        target = 'https://mcp.openalex.org/mcp'
        credentials = @{ clientId = 'pending-registration'; clientSecret = 'pending-registration' }
        authorizationUrl = 'https://mcp.openalex.org/authorize'
        tokenUrl = 'https://mcp.openalex.org/oauth/token'
        scopes = @('openalex:query')
        peRequirement = 'NotRequired'
    }
}
$Created = Invoke-RestMethod -Method Put -Uri $ConnectionUrl -Headers $ArmHeaders `
    -ContentType 'application/json' -Body ($ConnectionBody | ConvertTo-Json -Depth 10)
$RedirectUrl = $Created.properties.redirectUrl
if ([string]::IsNullOrWhiteSpace($RedirectUrl)) {
    throw 'The connection did not return its OAuth redirect URL. Inspect it before proceeding.'
}

$RegistrationBody = @{
    client_name = 'Microsoft Discovery - OpenAlex'
    redirect_uris = @($RedirectUrl)
    grant_types = @('authorization_code', 'refresh_token')
    response_types = @('code')
}
$Registration = Invoke-RestMethod -Method Post -Uri 'https://mcp.openalex.org/oauth/register' `
    -ContentType 'application/json' -Body ($RegistrationBody | ConvertTo-Json -Depth 5)
if (-not $Registration.client_id -or -not $Registration.client_secret) {
    throw 'OpenAlex did not return complete client credentials.'
}
$ConnectionBody.properties.credentials = @{
    clientId = $Registration.client_id
    clientSecret = $Registration.client_secret
}
$SavedConnection = Invoke-RestMethod -Method Put -Uri $ConnectionUrl -Headers $ArmHeaders `
    -ContentType 'application/json' -Body ($ConnectionBody | ConvertTo-Json -Depth 10)
if ($SavedConnection.properties.redirectUrl -ne $RedirectUrl) {
    throw 'The redirect URL changed. Stop and inspect the connection and registration.'
}
$Registration = $null
$ConnectionBody.properties.credentials = $null
```

The registration response is assigned to a variable, not printed or written to disk. Do not log or
save it with repository artifacts. The real client secret is stored in Foundry. If setup is
interrupted, inspect the existing connection and complete the interrupted stage deliberately; do
not repeatedly register clients or overwrite a working connection.

Leave `token_endpoint_auth_method` out of the registration request. OpenAlex defaults to
`client_secret_basic` and also accepts credentials in the token request body. Include the exact
Foundry-generated redirect URL; do not invent one. OpenAlex grants `openalex:query` and issues
refresh tokens independently of the requested scope. Request only `openalex:query`: the provider's
OAuth metadata advertises no other scope, so do not add `offline_access`.

## 4. Attach MCP without replacing Discovery's tools

The verified Foundry agent API version was `v1`. Do not edit the agent concurrently with this step.
It copies the latest definition, preserving the model, instructions, and Discovery's injected
resource functions, then appends one MCP tool. It refuses to add a duplicate `openalex` binding.

```powershell
$AllowedTools = @(
    'search_works', 'get_work', 'resolve_references', 'list_citations',
    'search_entities', 'get_entity', 'group_works', 'analyze_works',
    'check_oql', 'calculate_works', 'find_keywords', 'keyword_search', 'read_docs'
)
$FoundryHeaders = @{ Authorization = "Bearer $(Get-AccessToken 'https://ai.azure.com')" }
$AgentUrl = "$FoundryProjectEndpoint/agents/$AgentName"
$Agent = Invoke-RestMethod -Uri "${AgentUrl}?api-version=v1" -Headers $FoundryHeaders
$Latest = $Agent.versions.latest
if (-not $Latest.version -or $Latest.definition.kind -ne 'prompt') {
    throw 'No deployed prompt-agent version was found.'
}
$Definition = $Latest.definition | ConvertTo-Json -Depth 100 | ConvertFrom-Json -AsHashtable
$Tools = @()
if ($Definition.ContainsKey('tools') -and $null -ne $Definition.tools) {
    $Tools = @($Definition.tools)
}
if (@($Tools | Where-Object { $_.type -eq 'mcp' -and $_.server_label -eq 'openalex' }).Count) {
    throw 'An openalex binding already exists. Inspect it instead of appending a duplicate.'
}
$Definition.tools = $Tools + @(@{
    type = 'mcp'
    server_label = 'openalex'
    server_url = 'https://mcp.openalex.org/mcp'
    project_connection_id = $ConnectionId
    allowed_tools = $AllowedTools
    require_approval = 'never'
})
$VersionBody = @{ definition = $Definition }
if ($null -ne $Latest.description) { $VersionBody.description = $Latest.description }
if ($null -ne $Latest.metadata) { $VersionBody.metadata = $Latest.metadata }
$Current = Invoke-RestMethod -Uri "${AgentUrl}?api-version=v1" -Headers $FoundryHeaders
if ($Current.versions.latest.version -ne $Latest.version) {
    throw 'The agent changed during setup. Reload it before creating a version.'
}
$SavedVersion = Invoke-RestMethod -Method Post -Uri "$AgentUrl/versions?api-version=v1" `
    -Headers $FoundryHeaders -ContentType 'application/json' `
    -Body ($VersionBody | ConvertTo-Json -Depth 100)
$Mcp = @($SavedVersion.definition.tools | Where-Object {
    $_.type -eq 'mcp' -and $_.server_label -eq 'openalex'
})
if ($Mcp.Count -ne 1) { throw 'The saved version did not contain exactly one openalex binding.' }
$Names = if ($Mcp[0].allowed_tools -is [array]) {
    @($Mcp[0].allowed_tools)
} else {
    @($Mcp[0].allowed_tools.tool_names)
}
if ((Compare-Object $AllowedTools $Names) -or $Mcp[0].require_approval -ne 'never' -or
    $Mcp[0].project_connection_id -ne $ConnectionId -or
    $Mcp[0].server_url -ne 'https://mcp.openalex.org/mcp') {
    throw 'The saved MCP settings did not match the requested read-only binding.'
}
```

Foundry normalized `allowed_tools` to `{"tool_names": [...]}` when reading the saved version.
**Never leave the allowlist empty:** empty means all tools, including profile-curation tools.
Auto-approval is appropriate only for this explicitly restricted research-tool list.

Recheck the latest agent version after any subsequent save or redeployment. A connection existing
in the project is not proof that the latest agent version uses it.

## 5. Consent and validation

The verified Discovery API version was `2026-06-01`. The following block creates a validation
investigation and a fresh conversation in your chosen project. Keep them until you have inspected
the result; delete them through your normal project workflow afterward if no longer needed.

```powershell
$DiscoveryHeaders = @{ Authorization = "Bearer $(Get-AccessToken 'https://discovery.azure.com')" }
$InvestigationName = 'openalex-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$InvestigationUrl = "$WorkspaceEndpoint/projects/$DiscoveryProject/investigations/$InvestigationName"
$Investigation = Invoke-RestMethod -Method Put `
    -Uri "${InvestigationUrl}?api-version=2026-06-01" -Headers $DiscoveryHeaders `
    -ContentType 'application/json' -Body (@{
        displayName = $InvestigationName
        description = 'OpenAlex connection validation'
    } | ConvertTo-Json)
$Conversation = Invoke-RestMethod -Method Post `
    -Uri "$WorkspaceEndpoint/conversations?api-version=2026-06-01" -Headers $DiscoveryHeaders `
    -ContentType 'application/json' -Body (@{
        displayName = $InvestigationName
        investigationName = "/projects/$DiscoveryProject/investigations/$InvestigationName"
        projectName = $DiscoveryProject
    } | ConvertTo-Json)
if (-not $Conversation.name) { throw 'Conversation creation returned no name.' }
$ResponsesUrl = "$WorkspaceEndpoint/conversations/$($Conversation.name)/openai/v1/responses"
$Request = @{
    agent_reference = @{ type = 'agent_reference'; name = $AgentName }
    input = @(@{
        type = 'message'
        role = 'user'
        content = @(@{
            type = 'input_text'
            text = 'Use get_work once for DOI 10.1038/nmat3066. Return only the tool-returned title, year, DOI, and OpenAlex URL. Do not answer from memory or create files. Stop if consent or a tool error prevents the lookup.'
        })
    })
}

function Wait-DiscoveryResponse([string]$Id) {
    $Deadline = (Get-Date).AddMinutes(3)
    do {
        $Result = Invoke-RestMethod -Uri "$ResponsesUrl/$Id" -Headers $DiscoveryHeaders
        if ($Result.status -in @('completed', 'failed', 'cancelled', 'canceled',
                'expired', 'incomplete', 'requires_action')) {
            return $Result
        }
        Start-Sleep -Seconds 10
    } while ((Get-Date) -lt $Deadline)
    throw "Response $Id is still pending. Inspect it before submitting another request."
}

$Accepted = Invoke-RestMethod -Method Post -Uri $ResponsesUrl -Headers $DiscoveryHeaders `
    -ContentType 'application/json' -Body ($Request | ConvertTo-Json -Depth 10)
if (-not $Accepted.id) { throw 'Response submission returned no ID.' }
$Response = Wait-DiscoveryResponse $Accepted.id
$Consent = @($Response.output | Where-Object { $_.type -eq 'oauth_consent_request' })
if ($Consent.Count) { $Consent | Select-Object consent_link }
```

If consent was requested, open its HTTPS Microsoft consent link yourself, sign in with your free
OpenAlex account, approve access, and wait for confirmation. Do not follow links automatically or
paste credentials into chat. Consent URLs expire; if one expires, obtain a new consent request.
Do not publish raw responses containing consent links.

**Only after consent succeeds**, continue the saved response in the same conversation:

```powershell
if ($Consent.Count) {
    $Request.previous_response_id = $Response.id
    $Accepted = Invoke-RestMethod -Method Post -Uri $ResponsesUrl -Headers $DiscoveryHeaders `
        -ContentType 'application/json' -Body ($Request | ConvertTo-Json -Depth 10)
    if (-not $Accepted.id) { throw 'Continuation returned no response ID.' }
    $Response = Wait-DiscoveryResponse $Accepted.id
}
```

Use `agent_reference`, not preview's `agent` field. Omit `tool_choice`: Discovery rejected that field
as unsupported during validation. An OAuth consent request can have response status `completed`
without having executed a research tool. Require actual execution evidence:

```powershell
if ($Response.status -ne 'completed' -or $Response.error) {
    throw "Response did not succeed: $($Response.status). Inspect its error and output."
}
$Calls = @($Response.output | Where-Object {
    $_.type -eq 'mcp_call' -and $_.server_label -eq 'openalex' -and $_.name -eq 'get_work'
})
if ($Calls.Count -ne 1 -or $Calls[0].status -ne 'completed' -or $Calls[0].error) {
    throw 'No successful get_work MCP call was found. Inspect consent and tool errors.'
}
$Work = $Calls[0].output | ConvertFrom-Json
if ($Work.error -or $Work.isError -or $Work.doi -ne '10.1038/nmat3066' -or
    -not $Work.title -or -not $Work.year -or -not $Work.openalex_url) {
    throw 'The tool output did not contain the requested work.'
}
$Work | Select-Object title, year, doi, openalex_url
```

A fresh conversation for the same signed-in user and connection reused the grant without another
consent request during testing. A later same-day request required consent again; authorization and
continuation restored the DOI lookup. Do not assume automatic refresh works. The user subsequently
confirmed a successful Engine chat lookup, but the UI consent display/resumption itself was not
tested. This does not establish second-user authorization or unattended Discovery Engine support.

## Allowed research tools

| Tool | Purpose |
| --- | --- |
| `search_works` | Keyword, exact, semantic, or OQL search; preview returns a count and sample |
| `get_work` | One work by OpenAlex ID, DOI, PMID, or PMCID |
| `resolve_references` | Up to 25 references with match confidence and identifiers |
| `list_citations` | Citing, referenced, or related works |
| `search_entities` | Authors, institutions, sources, topics, funders, and publishers |
| `get_entity` | One entity profile |
| `group_works` | Counts by one dimension |
| `analyze_works` | Counts, trends, and leading contributors for a matching set |
| `check_oql` | Query validation and price check |
| `calculate_works` | OQL calculations |
| `find_keywords` | Keywords for a high-recall search |
| `keyword_search` | Keyword-aware high-recall search |
| `read_docs` | Provider documentation and syntax |

Exclude account/profile tools: `get_my_account`, `claim_author_profile`, `find_candidate_works`,
`submit_curations`, and `list_my_curations`. Also exclude any expert-finding or alert tools the
provider enables later. OpenAlex controls its server's tool list; the agent's allowlist must remain
explicit and nonempty.

## Operational limits and alternatives

- **Missing model deployment:** `DeploymentNotFound` can originate from the project's default
  Discovery agent before OpenAlex runs. Verify the exact deployment name used by both agents,
  not just the model family. Correct a shared default agent only with the project owner's approval,
  preserving its other settings; this is separate from changing the OpenAlex connection.
- **Query constraints observed in testing:** stemmed keyword searches rejected wildcards; literal
  Boolean terms worked. `analyze_works` requires `top_n` of at least 3. Use current tool schemas and
  `read_docs` rather than guessing after an error.
- **Budget:** calls spend the connected user's OpenAlex budget, or the organization's budget for an
  organization owner. Never buy a plan to complete these validation checks. Budget exhaustion and
  throttling were not deliberately triggered.
- **Registration lifetime:** the reviewed OpenAlex server kept dynamic clients for 90 days, access
  tokens for one hour, and refresh tokens for 90 days. Register a replacement client and update the
  connection before client expiry; expect users to authorize again. Refresh and renewal were not
  tested. Rotating the user's OpenAlex API key can require reconnection.
- **Foundry UI alternative:** the equivalent settings are a custom OAuth `RemoteTool` connection,
  the endpoint and OAuth URLs above, scope `openalex:query`, and this same allowlist.
  The UI creation/edit workflow was not exercised. Do not treat a portal configuration screenshot
  as proof that a Discovery tool call succeeded.
- **Workspace writes:** OpenAlex queries are read-only, but the agent's Discovery resource tools can
  save finished reports. The validation prompts explicitly requested no files; saving a report
  remains untested.

Provider references: [connector documentation](https://help.openalex.org/access/connector/),
[OAuth metadata](https://mcp.openalex.org/.well-known/oauth-authorization-server), and
[server source](https://github.com/ourresearch/openalex-mcp-server).
