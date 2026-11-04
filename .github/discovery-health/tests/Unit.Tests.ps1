#Requires -Version 7.2
# Unit tests for pure functions: JSON, templates, redaction, config, specs, receipts, ACR helpers, reports.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'TestHelpers.ps1')
$module = Get-DhTestModule
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path

function InModule { param([scriptblock]$Body, [object[]]$Arguments = @()) return (& $module $Body @Arguments) }

Test-Case 'JSON parsing keeps date-like strings and nested arrays intact' {
  $parsed = InModule { ConvertFrom-DhJson '{"version":"2026-06-01","when":"2026-01-02T03:04:05Z","list":[{"a":1}],"one":["x"]}' }
  Assert-Equal '2026-06-01' $parsed.version
  Assert-True ($parsed.when -is [string]) 'date string preserved'
  Assert-Equal 1 @($parsed.one).Count
  Assert-Equal 1 $parsed.list[0].a
}

Test-Case 'Newtonsoft fallback (pwsh 7.4 without -DateKind) parses identically' {
  $json = '{"version":"2026-06-01","when":"2026-01-02T03:04:05Z","list":[{"a":1,"b":[true,null,2.5]}],"one":["x"],"empty":[],"nested":{"k":"v"}}'
  $fallback = InModule {
    param($j)
    $saved = $script:DhHasDateKind
    $script:DhHasDateKind = $false
    try { ConvertTo-DhJson (ConvertFrom-DhJson $j) -Compress } finally { $script:DhHasDateKind = $saved }
  } @($json)
  $native = InModule { param($j) ConvertTo-DhJson (ConvertFrom-DhJson $j) -Compress } @($json)
  Assert-Equal $native $fallback
  Assert-Match $fallback '"when":"2026-01-02T03:04:05Z"'
  Assert-Match $fallback '"one":\["x"\]'
}

Test-Case 'Handlebars-lite renders variables, if/else and nested blocks' {
  $t = 'python3 /app/entrypoint.py --input {{input_directory}} {{#if accession}}--accession {{accession}}{{/if}}{{#if mode}} --mode {{mode}}{{else}} --mode default{{/if}}'
  $out = InModule { param($t) Expand-DhTemplate -Template $t -Values ([ordered]@{ input_directory = '/dh/input'; accession = 'P00520' }) } @($t)
  Assert-Equal 'python3 /app/entrypoint.py --input /dh/input --accession P00520 --mode default' $out
  $nested = InModule { Expand-DhTemplate -Template '{{#if a}}A{{#if b}}B{{/if}}{{/if}}' -Values @{ a = 'x'; b = '' } }
  Assert-Equal 'A' $nested
}

Test-Case 'redaction removes secrets, tokens, SAS, URLs, GUIDs and registered masks' {
  $text = InModule {
    Add-DhMask 'super-secret-project'
    Protect-DhText 'Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk sig=abc123&se=2030 https://acct.blob.core.windows.net/c/x?sv=1&sig=zzz /subscriptions/0b1c2d3e-0000-1111-2222-333344445555/resourceGroups/rg1 api_key=AKIA123 password: hunter2 AccountKey=abc== super-secret-project 0b1c2d3e-0000-1111-2222-333344445555'
  }
  foreach ($leak in @('eyJhbGci', 'abc123', 'acct.blob', 'zzz', 'AKIA123', 'hunter2', 'abc==', 'super-secret-project', '0b1c2d3e')) { Assert-NotMatch $text ([regex]::Escape($leak)) "leaked $leak" }
}

Test-Case 'public messages sanitize parameters to an allowlist' {
  $msg = InModule { Get-DhMessage -Code 'DH-RUN-001' -Params @{ case = "bad`nvalue <script>"; status = 'Failed' } }
  Assert-NotMatch $msg "`n"
  Assert-Match $msg 'Failed'
  $ok = InModule { Get-DhMessage -Code 'DH-BLD-009' -Params @{ tag = 'abc123def456-202601010000' } }
  Assert-Equal 'Image built: abc123def456-202601010000.' $ok
  $codes = InModule { Import-PowerShellDataFile (Join-Path $script:DhRoot 'templates/messages.psd1') }
  foreach ($file in (Get-ChildItem (Join-Path $repo '.github/discovery-health/src') -Recurse -Filter '*.ps1')) {
    foreach ($m in [regex]::Matches([System.IO.File]::ReadAllText($file.FullName), "'(DH-[A-Z]{3}-\d{3})'")) { Assert-True ($codes.ContainsKey($m.Groups[1].Value)) "message code $($m.Groups[1].Value) used in $($file.Name) is not in the catalog" }
  }
}

Test-Case 'config merges defaults, file and DH_* environment overrides and validates required fields' {
  $env:DH_ACR_NAME = 'envacr123'
  $env:DH_NODE_POOLS = '[{"id":"/x/nodepools/np","skus":["Standard_D4s_v6"],"gpu":false}]'
  $env:DH_POLL_SECONDS = '7'
  try {
    $config = InModule { Read-DhConfig }
    Assert-Equal 'envacr123' $config.acrName
    Assert-Equal 7 $config.pollSeconds
    Assert-Equal 'Standard_D4s_v6' $config.nodePools[0].skus[0]
    Assert-Equal 'dgt-' $config.namePrefix
    $problems = @(InModule { param($c) Test-DhConfig -Config $c -Stages @('build', 'agent-register') } @($config))
    Assert-True (@($problems | Where-Object { $_ -match 'missing: subscriptionId' }).Count -eq 1) 'subscriptionId required'
    Assert-True (@($problems | Where-Object { $_ -match 'missing: chatModel' }).Count -eq 1) 'chatModel required for agent-register'
    $bad = InModule { Read-DhConfig -Overrides @{ namePrefix = '' } }
    Assert-True (@(InModule { param($c) Test-DhConfig -Config $c } @($bad)).Count -gt 0) 'empty namePrefix rejected'
  } finally {
    Remove-Item Env:DH_ACR_NAME, Env:DH_NODE_POOLS, Env:DH_POLL_SECONDS -ErrorAction SilentlyContinue
  }
}

Test-Case 'config template is valid against the schema' {
  $template = Join-Path $repo '.github/discovery-health/config.template.json'
  Assert-True (Test-Json -Json (Get-Content $template -Raw) -SchemaFile (Join-Path $repo '.github/discovery-health/schemas/config.schema.json')) 'template matches schema'
}

Test-Case 'validation receipt port matches deployer semantics' {
  $valid = 'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"slope","actual":2.1,"expected":2.1,"tolerance":1e-8},{"name":"label","actual":"ok","expected":"ok"}],"artifacts":[{"path":"/output/c.csv","bytes":12}]}'
  Assert-Equal '' (InModule { param($t) Test-DhValidationReceipt -Text $t -RequireOutputPrefix } @($valid))
  $cases = @(
    @('no receipt here', 'missing'),
    @('DISCOVERY_VALIDATION_RESULT={"checks":[],"artifacts":[{"path":"/output/a","bytes":1}]}', 'measured checks'),
    @('DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"x","actual":1.0,"expected":2.0,"tolerance":0.5}],"artifacts":[{"path":"/output/a","bytes":1}]}', 'numerical'),
    @('DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"x","actual":1,"expected":1,"tolerance":-1}],"artifacts":[{"path":"/output/a","bytes":1}]}', 'numerical'),
    @('DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"x","actual":true,"expected":"true"}],"artifacts":[{"path":"/output/a","bytes":1}]}', 'validation failed'),
    @('DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"x","actual":1,"expected":1}],"artifacts":[]}', 'artifacts'),
    @('DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"x","actual":1,"expected":1}],"artifacts":[{"path":"/output/../etc","bytes":1}]}', 'artifact'),
    @('DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"x","actual":1,"expected":1}],"artifacts":[{"path":"/tmp/a","bytes":1}]}', 'artifact'),
    @('DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"x","actual":1,"expected":1}],"artifacts":[{"path":"/output/a","bytes":0}]}', 'artifact'),
    @('DISCOVERY_VALIDATION_RESULT={not json', 'JSON')
  )
  foreach ($case in $cases) {
    $reason = InModule { param($t) Test-DhValidationReceipt -Text $t -RequireOutputPrefix } @($case[0])
    Assert-Match $reason $case[1] "receipt case: $($case[0])"
  }
  Assert-Equal '' (InModule { Test-DhValidationReceipt -Text 'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"x","actual":1,"expected":1}],"artifacts":[{"path":"/tmp/a","bytes":1}]}' }) 'tool-run receipts allow any absolute path'
}

Test-Case 'smoke marker parsing evaluates exit codes and expected output' {
  $log = "noise`nDH_SMOKE_BEGIN:interpreter-python3`nDH_OK`nDH_SMOKE_END:interpreter-python3:0`nDH_SMOKE_BEGIN:action-entrypoints`nmissing`nDH_SMOKE_END:action-entrypoints:1`nDH_SMOKE_BEGIN:needs-text`nhello`nDH_SMOKE_END:needs-text:0`n"
  $cases = @(
    [ordered]@{ name = 'interpreter-python3'; expect = [ordered]@{ exitCode = 0; contains = @('DH_OK') } },
    [ordered]@{ name = 'action-entrypoints'; expect = [ordered]@{ exitCode = 0 } },
    [ordered]@{ name = 'needs-text'; expect = [ordered]@{ exitCode = 0; contains = @('world') } },
    [ordered]@{ name = 'absent'; expect = [ordered]@{ exitCode = 0 } }
  )
  $outcomes = @(InModule { param($l, $c) Get-DhSmokeOutcomes -Log $l -Cases $c } @($log, $cases))
  Assert-Equal @('passed', 'failed', 'failed', 'failed') @($outcomes | ForEach-Object { $_.status })
  Assert-Equal @('', 'DH-SMK-001', 'DH-SMK-003', 'DH-SMK-002') @($outcomes | ForEach-Object { $_.code })
}

Test-Case 'build failure classification separates contribution from infrastructure' {
  Assert-Equal 'DH-BLD-002' (InModule { (Get-DhBuildFailureCode -Log 'write /var: no space left on device').code })
  Assert-Equal 'infrastructure' (InModule { (Get-DhBuildFailureCode -Log 'toomanyrequests: rate limit').category })
  Assert-Equal 'DH-BLD-006' (InModule { (Get-DhBuildFailureCode -Log 'failed to resolve source metadata for docker.io/library/python:9.99: not found').code })
  Assert-Equal 'DH-BLD-007' (InModule { (Get-DhBuildFailureCode -Log 'curl: (22) The requested URL returned error: 404').code })
  Assert-Equal 'contribution' (InModule { (Get-DhBuildFailureCode -Log 'RUN pip install x: exit code 1').category })
  Assert-Equal 'infrastructure' (InModule { Get-DhFailureCategory -Status 503 })
  Assert-Equal 'contribution' (InModule { Get-DhFailureCategory -Status 400 -Text 'InvalidToolDefinition' })
}

Test-Case 'ACR task YAML labels, namespaces and smoke steps; run id parsing' {
  $config = New-DhTestConfig
  $yaml = InModule { param($c) $script:Dh.RunId = 'r1'; $script:Dh.GitSha = 'abc'; New-DhAcrTaskYaml -Config $c -Repository 'discovery-github-test/chembl-image' -Tag 'fp-1' -Fingerprint 'fff' -SmokeCases @(@{ name = 'a' }, @{ name = 'b' }) } @($config)
  Assert-Match $yaml 'build: -t \$Registry/discovery-github-test/chembl-image:fp-1 --label discovery-github-test=true --label dgt.fingerprint=fff'
  Assert-Match $yaml '(?s)id: push.*id: smoke-1.*ignoreErrors: true.*id: smoke-2'
  $smokeOnly = InModule { param($c) New-DhAcrTaskYaml -Config $c -Repository 'r' -Tag 't' -Fingerprint 'f' -SmokeCases @(@{ name = 'a' }) -SmokeOnly } @($config)
  Assert-NotMatch $smokeOnly 'id: build'
  Assert-Equal 'cb3' (InModule { Get-DhAcrRunIdFromOutput -Output 'WARNING: x\n{"runId": "cb3", "status": "Queued"}' })
  Assert-Equal 'cb4' (InModule { Get-DhAcrRunIdFromOutput -Output 'Queued a run with ID: cb4' })
  $script = InModule { New-DhSmokeScript -Case @{ name = 'n1'; command = 'python3 -c "print(1)"' } }
  Assert-NotMatch $script "`r"
  Assert-Match $script 'DH_SMOKE_END:n1:\$rc'
}

Test-Case 'catalog bindings, staging parity and default specs on real agents' {
  $config = New-DhTestConfig
  $out = Join-Path ([System.IO.Path]::GetTempPath()) ('dh-unit-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $catalog = InModule { param($c, $r, $o) Initialize-DhRun -Config $c -OutputDir $o -RunId 'u'; Read-DhCatalog -CatalogRoot $r -Agents @('chembl', 'alphafold-db', 'online-researcher', 'rtl-ivlg-linter', 'core-python-agent', 'flowblind-research-teammate-v2', 'aqcat') -OutputDir $o -Config $c } @($config, $repo, $out)
  Assert-Equal 'ChEMBL' $catalog.agents['chembl'].bindings[0].tool
  Assert-Equal 'iverilog-tool' $catalog.agents['rtl-ivlg-linter'].bindings[0].tool
  Assert-Equal 'corepython' $catalog.agents['core-python-agent'].bindings[0].tool
  Assert-Equal @('flowblind-prepare', 'flowblind-run-verify') @($catalog.agents['flowblind-research-teammate-v2'].bindings | ForEach-Object { $_.tool })
  Assert-Equal @('AQ_MCP_CONNECTION', 'AQ_MCP_SERVER_URL') @($catalog.agents['aqcat'].requiredVariables)
  $staged = Get-ChildItem (Join-Path $out 'catalog/agents/core-python-agent') -Recurse -Filter '*.sh' | Select-Object -First 1
  Assert-NotMatch ([System.IO.File]::ReadAllText($staged.FullName)) "`r`n" 'staged shell scripts use LF'
  $chembl = $catalog.agents['chembl']
  $smoke = @(InModule { param($a) Get-DhSmokeCases -Agent $a -Tool $a.tools['ChEMBL'] } @($chembl))
  Assert-Equal 'interpreter-python' $smoke[0].name
  $runPlan = InModule { param($a) Get-DhToolRunCases -Agent $a -Tool $a.tools['ChEMBL'] } @($chembl)
  Assert-Equal 1 @($runPlan.cases).Count
  Assert-Match $runPlan.cases[0].command 'python "/dh/input/dh_check.py"'
  Assert-Match $runPlan.cases[0].command 'DH_RUN_EXIT'
  $afdb = $catalog.agents['alphafold-db']
  Assert-Equal 'DH-RUN-007' (InModule { param($a) (Get-DhToolRunCases -Agent $a -Tool $a.tools['alphafold-db']).untestedCode } @($afdb))
  $actionSmoke = @(InModule { param($a) Get-DhSmokeCases -Agent $a -Tool $a.tools['alphafold-db'] } @($afdb))
  Assert-Match $actionSmoke[0].command 'command -v python3 >/dev/null && test -e /app/entrypoint.py'
  Assert-Equal 'DH-RTP-007' (InModule { param($a) (Get-DhRoundTripPlan -Agent $a).untestedCode } @($afdb))
  Assert-True (InModule { param($a) (Get-DhRoundTripPlan -Agent $a).toolLess } @($catalog.agents['online-researcher']))
  $skeleton = InModule { param($a) New-DhSpecSkeleton -Agent $a } @($afdb)
  $tmp = Join-Path $out 'skeleton.yaml'
  Set-Content -Path $tmp -Value $skeleton
  $doc = InModule { param($p, $c) ConvertFrom-DhYamlFile -Path $p -Config $c } @($tmp, $config)
  Assert-Equal 0 @(InModule { param($d, $a) Test-DhSpec -Spec $d -Agent $a } @($doc, $afdb)).Count 'skeleton validates against the schema'
}

Test-Case 'spec validation catches unknown tools, actions, bad regex and dates' {
  $config = New-DhTestConfig
  $out = Join-Path ([System.IO.Path]::GetTempPath()) ('dh-unit-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $catalog = InModule { param($c, $r, $o) Initialize-DhRun -Config $c -OutputDir $o -RunId 'u'; Read-DhCatalog -CatalogRoot $r -Agents @('alphafold-db') -OutputDir $o -Config $c } @($config, $repo, $out)
  $spec = [ordered]@{
    agent = 'alphafold-db'
    tools = [ordered]@{ 'alphafold-db' = [ordered]@{ toolRun = @([ordered]@{ name = 'x'; action = 'nope'; expect = [ordered]@{ matches = @('([') } }) }; ghost = [ordered]@{} }
    skip = @([ordered]@{ stage = 'tool-run'; reason = 'because reasons'; until = '2026-99-99' })
    extra = 1
  }
  $problems = @(InModule { param($s, $a) Test-DhSpec -Spec $s -Agent $a } @($spec, $catalog.agents['alphafold-db']))
  $joined = $problems -join ' | '
  foreach ($expected in @('schema', 'unknown tool folder: ghost', 'no action nope', 'invalid regex', 'invalid skip.until')) { Assert-Match $joined ([regex]::Escape($expected)) }
}

Test-Case 'committed specs are valid' {
  $specDir = Join-Path $repo '.github/discovery-health/specs'
  $names = @(Get-ChildItem $specDir -Filter '*.yaml' -File | Where-Object { -not $_.Name.StartsWith('_') } | ForEach-Object BaseName)
  if ($names.Count -eq 0) { return }
  $config = New-DhTestConfig
  $out = Join-Path ([System.IO.Path]::GetTempPath()) ('dh-unit-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $catalog = InModule { param($c, $r, $o, $n, $s) Initialize-DhRun -Config $c -OutputDir $o -RunId 'u'; Read-DhCatalog -CatalogRoot $r -Agents $n -SpecRoot $s -OutputDir $o -Config $c } @($config, $repo, $out, $names, $specDir)
  Assert-Equal 0 @($catalog.unknown).Count ('specs for unknown agents: ' + ($catalog.unknown -join ','))
  foreach ($agent in $catalog.agents.Values) {
    $issues = @($agent.issues | Where-Object { $_.code -eq 'DH-SPC-001' })
    Assert-Equal 0 $issues.Count ("$($agent.name): " + (($issues | ForEach-Object { "$($_.params.reason) $($_.detail)" }) -join '; '))
  }
}

Test-Case 'agent payload port: model, HITL, confirmations, multi-tool ids and markers' {
  $doc = [ordered]@{
    kind = 'prompt'; name = 'Demo'; description = 'Demo agent'; model = [ordered]@{ id = '{{CHAT-MODEL}}'; options = [ordered]@{ temperature = 0 } }
    instructions = 'Use {{project}} and keep {{unknownVar}}.'
    discoveryExtensions = [ordered]@{ humanInTheLoop = 'Enabled'; tools = @([ordered]@{ toolId = '{{aToolId}}'; confirmation = 'Enabled' }, [ordered]@{ toolId = '{{bToolId}}' }); knowledgeBases = @('/bookshelves/x/knowledgeBases/y'); disableDataHandlingTools = $false }
  }
  $patched = InModule { param($d) Update-DhAgentDocument -Doc $d -ChatModel 'gpt-x' -ToolIdMap @{ '{{aToolId}}' = '/s/tools/atool'; '{{bToolId}}' = '/s/tools/btool' } } @($doc)
  Assert-Equal 'gpt-x' $patched.model.id
  Assert-Equal 'Disabled' $patched.discoveryExtensions.humanInTheLoop
  Assert-Equal @('/s/tools/atool', '/s/tools/btool') @($patched.discoveryExtensions.tools | ForEach-Object { $_.toolId })
  Assert-Equal @('Disabled', 'Disabled') @($patched.discoveryExtensions.tools | ForEach-Object { $_.confirmation })
  $resolved = InModule { param($d) Resolve-DhTemplateVariables -Value $d -Variables @{ project = 'p1' } } @($patched)
  Assert-Equal 'Use p1 and keep {{unknownVar}}.' $resolved.instructions
  $payload = InModule { param($d) New-DhAgentPayload -Doc $d } @($resolved)
  Assert-Equal 'Disabled' $payload.humanInTheLoop
  Assert-Equal 2 @($payload.tools).Count
  Assert-Equal 1 @($payload.knowledgeBases).Count
  Assert-False ($payload.discoveryExtensions.Contains('tools')) 'tools are lifted out of discoveryExtensions'
  Assert-Equal 'gpt-x' $payload.foundryDetails.definition.model
  Assert-Equal 0 $payload.foundryDetails.definition.temperature
  Assert-Throws { InModule { New-DhAgentPayload -Doc ([ordered]@{ kind = 'workflow'; name = 'w' }) } }
}

Test-Case 'round-trip verdict: approvals, missing tools, failures, receipts, tool-less' {
  $plan = [ordered]@{ toolsCalled = @('t1'); contains = @('42'); matches = @(); receipt = $true; toolLess = $false }
  $prefixes = @{ t1 = @('tool1') }
  $receipt = "Tool execution succeeded`nDISCOVERY_VALIDATION_RESULT={""checks"":[{""name"":""p"",""actual"":42,""expected"":42,""tolerance"":0}],""artifacts"":[{""path"":""/output/x"",""bytes"":2}]}`ndiscovery://storageassets/a"
  $body = @{ status = 'completed'; output = @(@{ type = 'function_call'; call_id = 'c'; name = 'tool1-python' }, @{ type = 'function_call_output'; call_id = 'c'; output = $receipt }, @{ type = 'message'; content = @(@{ text = 'answer 42' }) }) }
  Assert-Equal 'passed' (InModule { param($b, $p, $x) (Get-DhRoundTripVerdict -Body $b -Plan $p -ToolPrefixes $x).status } @($body, $plan, $prefixes))
  $approval = @{ status = 'completed'; discoveryProperties = @{ confirmations = @(@{ status = 'AwaitingUserInput' }) }; output = @() }
  Assert-Equal 'DH-RTP-003' (InModule { param($b, $p, $x) (Get-DhRoundTripVerdict -Body $b -Plan $p -ToolPrefixes $x).code } @($approval, $plan, $prefixes))
  $noTool = @{ status = 'completed'; output = @(@{ type = 'message'; content = @(@{ text = 'I did it without tools: 42' }) }) }
  Assert-Equal 'DH-RTP-002' (InModule { param($b, $p, $x) (Get-DhRoundTripVerdict -Body $b -Plan $p -ToolPrefixes $x).code } @($noTool, $plan, $prefixes))
  $toolError = @{ status = 'completed'; output = @(@{ type = 'function_call'; call_id = 'c'; name = 'tool1-python' }, @{ type = 'function_call_output'; call_id = 'c'; output = 'Tool execution failed: ContainerExitCode 1' }) }
  Assert-Match (InModule { param($b, $p, $x) (Get-DhRoundTripVerdict -Body $b -Plan $p -ToolPrefixes $x).params.reason } @($toolError, $plan, $prefixes)) 'execution error'
  $failed = @{ status = 'failed'; error = @{ message = 'Service Unavailable' }; output = @() }
  Assert-Equal 'infrastructure' (InModule { param($b, $p, $x) (Get-DhRoundTripVerdict -Body $b -Plan $p -ToolPrefixes $x).category } @($failed, $plan, $prefixes))
  $toolLessPlan = [ordered]@{ toolsCalled = @(); contains = @(); matches = @(); receipt = $false; toolLess = $true }
  $smoke = @{ status = 'completed'; output = @(@{ type = 'message'; content = @(@{ text = 'I search literature.' }) }) }
  Assert-Equal 'DH-RTP-006' (InModule { param($b, $p) (Get-DhRoundTripVerdict -Body $b -Plan $p -ToolPrefixes @{}).code } @($smoke, $toolLessPlan))
  $errText = @{ status = 'completed'; output = @(@{ type = 'message'; content = @(@{ text = 'An error occurred.' }) }) }
  Assert-Equal 'failed' (InModule { param($b, $p) (Get-DhRoundTripVerdict -Body $b -Plan $p -ToolPrefixes @{}).status } @($errText, $toolLessPlan))
  Assert-Match (InModule { New-DhInvestigationName -AgentName 'flowblind-research-teammate-v2' }) '^dgt-flowbl-[0-9a-f]+$'
  $a = InModule { New-DhInvestigationName -AgentName 'alphafold' }; $b = InModule { New-DhInvestigationName -AgentName 'alphafold-db' }
  Assert-True ($a.Substring(0, 15) -ne $b.Substring(0, 15)) 'agents sharing a prefix get distinct names'
  Assert-True ((InModule { New-DhInvestigationName -AgentName 'x' }).Length -le 24) 'investigation name length'
}

Test-Case 'nodepool selection honours SKUs and GPU requirements' {
  $config = New-DhTestConfig -Overrides @{ nodePools = @([ordered]@{ id = '/np/cpu'; skus = @('Standard_D4s_v6'); gpu = $false }, [ordered]@{ id = '/np/gpu'; skus = @('Standard_NC24ads_A100_v4'); gpu = $true }) }
  $agent = [ordered]@{ spec = $null }
  Assert-Equal '/np/cpu' (InModule { param($c, $a) (Select-DhNodePool -Config $c -Agent $a -Tool @{ skus = @('Standard_D4s_v6'); gpu = $false }).id } @($config, $agent))
  Assert-Equal '/np/gpu' (InModule { param($c, $a) (Select-DhNodePool -Config $c -Agent $a -Tool @{ skus = @('Standard_NC24ads_A100_v4', 'Standard_D4s_v6'); gpu = $true }).id } @($config, $agent))
  Assert-True ($null -eq (InModule { param($c, $a) Select-DhNodePool -Config $c -Agent $a -Tool @{ skus = @('Standard_NC40ads_H100_v5'); gpu = $true } } @($config, $agent))) 'no H100 pool'
}

Test-Case 'report synthesizes lost results, scores agents and merges history without resets' {
  $config = New-DhTestConfig
  $out = Join-Path ([System.IO.Path]::GetTempPath()) ('dh-rep-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $plan = [ordered]@{ runId = 'r9'; gitSha = 'abcdef0123456789'; stages = @('build', 'image-smoke', 'agent-register'); allAgents = @('a1', 'a2')
    agents = [ordered]@{ a1 = [ordered]@{ expected = @([ordered]@{ tool = 't'; stage = 'build' }, [ordered]@{ tool = 't'; stage = 'image-smoke' }, [ordered]@{ tool = ''; stage = 'agent-register' }) }; a2 = [ordered]@{ expected = @([ordered]@{ tool = ''; stage = 'agent-register' }) } } }
  $results = InModule {
    param($c, $o, $p)
    Initialize-DhRun -Config $c -OutputDir $o -RunId 'r9'
    $r = @(
      (New-DhResult -Agent 'a1' -Tool 't' -Stage 'build' -Status 'passed'),
      (New-DhResult -Agent 'a1' -Tool 't' -Stage 'image-smoke' -Status 'failed' -Category 'contribution' -Code 'DH-SMK-001' -Messages @((New-DhMessage -Level error -Code 'DH-SMK-001' -Params @{ name = 'x'; exit = 1 })))
    )
    $all = @(Add-DhMissingResults -Results $r -Plan $p -RunId 'r9')
    $summaries = Get-DhAgentSummaries -Results $all -Stages $p.stages
    $previous = [ordered]@{ schema = 'discovery-health/state@1'; runs = @([ordered]@{ runId = 'r8'; at = '2026-01-01T00:00:00Z'; agents = @{} }); agents = [ordered]@{ a3 = [ordered]@{ state = 'healthy'; score = 100; history = @() } } }
    $state = Merge-DhState -Previous $previous -Summaries $summaries -RunId 'r9' -GitSha 'abc' -HistoryRuns 5 -CatalogAgents @('a1', 'a2')
    New-DhSite -State $state -Destination (Join-Path $o 'site')
    @{ all = $all; summaries = $summaries; state = $state; md = (New-DhSummaryMarkdown -Results $all -Summaries $summaries -RunId 'r9' -GitSha 'abc' -Title 'T'); junit = (New-DhJUnitXml -Results $all) }
  } @($config, $out, $plan)
  Assert-Equal 4 @($results.all).Count 'two synthesized results'
  Assert-Equal 'inconclusive' @($results.all | Where-Object { $_.agent -eq 'a2' })[0].status
  Assert-Equal 'DH-RPT-001' @($results.all | Where-Object { $_.agent -eq 'a2' })[0].code
  Assert-Equal 'failing' $results.summaries['a1'].state
  Assert-Equal 'inconclusive' $results.summaries['a2'].state
  Assert-True ($results.summaries['a1'].score -gt 0 -and $results.summaries['a1'].score -lt 100) 'partial score'
  Assert-Equal 'removed' $results.state.agents['a3'].state 'agents gone from the catalog are marked removed'
  Assert-Equal @('r9', 'r8') @($results.state.runs | ForEach-Object { $_.runId })
  Assert-True (Test-Path (Join-Path $out 'site/index.html')) 'site index'
  Assert-True (Test-Path (Join-Path $out 'site/badges/a1.json')) 'badge'
  Assert-True (Test-Path (Join-Path $out 'site/history/r8.json')) 'older history regenerated from state'
  Assert-Match $results.md 'All warnings and errors \(3\)'
  [xml]$junit = $results.junit
  Assert-Equal '1' $junit.testsuites.failures
}

Test-Case 'YAML shim isolates bad files and stringifies non-string keys' {
  $dir = Join-Path ([System.IO.Path]::GetTempPath()) ('dh-yaml-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
  New-Item -ItemType Directory -Path $dir | Out-Null
  $dated = Join-Path $dir 'dated.yaml'; Set-Content -Path $dated -Value "changelog:`n  2025-01-01: first release`nversion: 2026-06-01`n"
  $broken = Join-Path $dir 'broken.yaml'; Set-Content -Path $broken -Value "a: [unclosed`n"
  $fine = Join-Path $dir 'fine.yaml'; Set-Content -Path $fine -Value "name: ok`n"
  $config = New-DhTestConfig
  $parsed = InModule { param($paths, $c) ConvertFrom-DhYamlFiles -Paths $paths -Config $c } @(@($dated, $broken, $fine), $config)
  Assert-True $parsed[$dated].ok 'date keys do not abort the batch'
  Assert-Equal 'first release' $parsed[$dated].doc.changelog['2025-01-01']
  Assert-Equal '2026-06-01' $parsed[$dated].doc.version
  Assert-False $parsed[$broken].ok 'broken file reported per file'
  Assert-True $parsed[$fine].ok 'other files unaffected'
}

Test-Case 'warnings on passed results are reported; spec/policy errors never mark agents failing' {
  $config = New-DhTestConfig
  $out = Join-Path ([System.IO.Path]::GetTempPath()) ('dh-rep-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $model = InModule {
    param($c, $o)
    Initialize-DhRun -Config $c -OutputDir $o -RunId 'w1'
    $r = @(
      (New-DhResult -Agent 'aqcat' -Stage 'agent-register' -Status 'passed' -Messages @((New-DhMessage -Level warning -Code 'DH-AGT-004' -Params @{ kinds = 'mcp' }))),
      (New-DhResult -Agent 'b1' -Stage 'discover' -Status 'failed' -Category 'policy' -Code 'DH-SPC-001' -Messages @((New-DhMessage -Level error -Code 'DH-SPC-001' -Params @{ reason = 'typo' }))),
      (New-DhResult -Agent 'b1' -Stage 'agent-register' -Status 'blocked' -Category 'policy' -Code 'DH-DEP-001')
    )
    $s = Get-DhAgentSummaries -Results $r -Stages @('agent-register')
    @{ summaries = $s; md = (New-DhSummaryMarkdown -Results $r -Summaries $s -RunId 'w1' -GitSha 'abc' -Title 'T') }
  } @($config, $out)
  Assert-Match $model.md 'DH-AGT-004'
  Assert-Equal 1 @($model.summaries['aqcat'].messages).Count
  Assert-Equal 'inconclusive' $model.summaries['b1'].state 'maintainer spec errors are not contributor failures'
}

Test-Case 'report refuses to publish when previous state is unavailable unless bootstrapping' {
  $config = New-DhTestConfig
  $out = Join-Path ([System.IO.Path]::GetTempPath()) ('dh-rep-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $missing = Join-Path $out 'missing-state.json'
  $refused = InModule { param($c, $o, $m) Invoke-DhReportCommand -Config $c -ResultsDir @($o) -OutputDir $o -PreviousStatePath $m -PreviousStateUrl 'http://127.0.0.1:9/state.json' -Site } @($config, $out, $missing)
  Assert-Equal 3 $refused.exitCode
  $noSource = InModule { param($c, $o) Invoke-DhReportCommand -Config $c -ResultsDir @($o) -OutputDir ($o + '-nosource') -Site } @($config, $out)
  Assert-Equal 3 $noSource.exitCode 'no configured state source still requires -Bootstrap'
  $boot = InModule { param($c, $o, $m) Invoke-DhReportCommand -Config $c -ResultsDir @($o) -OutputDir $o -PreviousStatePath $m -Site -Bootstrap } @($config, $out, $missing)
  Assert-Equal 0 $boot.exitCode
  Assert-True (Test-Path (Join-Path $out 'site/state.json')) 'bootstrap state written'
}

Complete-DhTestFile
