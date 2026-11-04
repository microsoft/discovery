#Requires -Version 7.2
# End-to-end scheduler tests against the offline fake backend (real catalog content, fake Azure).
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'TestHelpers.ps1')
. (Join-Path $PSScriptRoot 'FakeBackend.ps1')
$module = Get-DhTestModule
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path

function New-DhTestOutDir { return (Join-Path ([System.IO.Path]::GetTempPath()) ('dh-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))) }

function ConvertTo-DhResultMap {
  param([object[]]$Results)
  $byKey = @{}
  foreach ($r in @($Results)) { $byKey[('{0}|{1}|{2}' -f $r.agent, $r.tool, $r.stage)] = $r }
  return $byKey
}

function Invoke-DhFakeRun {
  param([string[]]$Agents, [hashtable]$Options = @{}, [hashtable]$ConfigOverrides = @{}, [string[]]$Stages = @('all'), [string]$SpecRoot = '', [switch]$Untrusted, [string]$OutDir = '')
  Install-DhFakeBackend -Options $Options
  $config = New-DhTestConfig -Overrides $ConfigOverrides
  $out = if ($OutDir) { $OutDir } else { New-DhTestOutDir }
  $result = & $module {
    param($config, $repo, $Agents, $Stages, $out, $SpecRoot, $Untrusted)
    Invoke-DhRunCommand -Config $config -CatalogRoot $repo -Ref 'HEAD' -Source 'git' -Agents $Agents -Stages $Stages -SpecRoot $SpecRoot -OutputDir $out -PlanPath '' -Shard 0 -RunId 'test-run' -Untrusted:$Untrusted
  } $config $repo $Agents $Stages $out $SpecRoot ([bool]$Untrusted)
  return @{ results = (ConvertTo-DhResultMap $result.results); out = $out; fake = (& $module { $script:Fake }) }
}

$toolFunctions = @{ chembl = @('chembl-python'); aizynthfinder = @('aizynthfinder-python3'); 'online-researcher' = @() }

Test-Case 'full pipeline passes for a code-environment agent and a tool-less agent' {
  $run = Invoke-DhFakeRun -Agents @('chembl', 'online-researcher') -Options @{ toolFunctions = $toolFunctions }
  $r = $run.results
  foreach ($stage in @('build', 'image-smoke', 'tool-register', 'tool-run')) { Assert-Equal 'passed' $r["chembl|ChEMBL|$stage"].status "chembl $stage $($r["chembl|ChEMBL|$stage"].messages | ConvertTo-Json -Depth 5 -Compress)" }
  Assert-Equal 'passed' $r['chembl||agent-register'].status
  Assert-Equal 'passed' $r['chembl||round-trip'].status ($r['chembl||round-trip'].messages | ConvertTo-Json -Depth 5)
  Assert-Equal 'warning' $r['online-researcher||agent-register'].status 'web_search top-level tool is surfaced as DH-AGT-004'
  Assert-Equal 'passed' $r['online-researcher||round-trip'].status
  Assert-Equal 'DH-RTP-006' $r['online-researcher||round-trip'].code
  Assert-Match ([string]$r['chembl|ChEMBL|build'].data.imageTag) '^[0-9a-f]{12}-\d{12}$'
  Assert-False ($r['chembl|ChEMBL|build'].data.Contains('imageRef')) 'registry name never appears in public results'
  $agent = $run.fake.agents['dgt-chembl']
  Assert-True ($null -ne $agent) 'agent deployed with dgt- prefix'
  Assert-Match ([string]$agent.foundryDetails.description) '\[discovery-github-test test-run\]$'
  Assert-Equal 'Disabled' $agent.humanInTheLoop
  Assert-Match ([string]$agent.tools[0].toolId) '/providers/Microsoft\.Discovery/tools/chembl$'
  Assert-Equal 'gpt-test' $agent.foundryDetails.definition.model
  $tool = $run.fake.tools['chembl']
  Assert-Equal 'true' $tool.body.tags['discovery-github-test']
  Assert-Match ([string]$tool.body.properties.definitionContent.infra[0].image.acr) 'discovery-github-test/chembl-image:'
  Assert-True (@($run.fake.deleted | Where-Object { $_ -like 'investigation:dgt-*' }).Count -ge 1) 'passing investigations deleted'
  Assert-True (Test-Path (Join-Path $run.out 'operations')) 'operation registry written'
  Assert-True (@(Get-ChildItem (Join-Path $run.out 'evidence') -Recurse -File).Count -gt 5) 'private evidence written'
}

Test-Case 'build failure blocks dependents but never the sibling tool or other agents' {
  $run = Invoke-DhFakeRun -Agents @('flowblind-research-teammate-v2', 'chembl') -Options @{ failBuild = @('flowblind-prepare'); toolFunctions = $toolFunctions } -Stages @('build', 'tool-register', 'agent-register')
  $r = $run.results
  Assert-Equal 'failed' $r['flowblind-research-teammate-v2|flowblind-prepare|build'].status
  Assert-Equal 'contribution' $r['flowblind-research-teammate-v2|flowblind-prepare|build'].category
  Assert-Equal 'blocked' $r['flowblind-research-teammate-v2|flowblind-prepare|tool-register'].status
  Assert-Equal 'blocked' $r['flowblind-research-teammate-v2|flowblind-prepare|image-smoke'].status
  Assert-Equal 'passed' $r['flowblind-research-teammate-v2|flowblind-run-verify|build'].status
  Assert-Equal 'passed' $r['flowblind-research-teammate-v2|flowblind-run-verify|tool-register'].status
  Assert-Equal 'blocked' $r['flowblind-research-teammate-v2||agent-register'].status
  Assert-Equal 'passed' $r['chembl||agent-register'].status
}

Test-Case 'action tool without spec is untested (needs spec) and does not block other stages' {
  $run = Invoke-DhFakeRun -Agents @('alphafold-db') -Options @{ toolFunctions = @{} }
  $r = $run.results
  Assert-Equal 'passed' $r['alphafold-db|alphafold-db|image-smoke'].status
  Assert-Equal 'untested' $r['alphafold-db|alphafold-db|tool-run'].status
  Assert-Equal 'DH-RUN-007' $r['alphafold-db|alphafold-db|tool-run'].code
  Assert-Equal 'passed' $r['alphafold-db||agent-register'].status
  Assert-Equal 'untested' $r['alphafold-db||round-trip'].status
  Assert-Equal 'DH-RTP-007' $r['alphafold-db||round-trip'].code
}

Test-Case 'missing image blocks registration; no matching nodepool marks runs untested for capacity' {
  $run = Invoke-DhFakeRun -Agents @('alphafold') -Options @{ toolFunctions = @{} } -Stages @('tool-register', 'tool-run', 'agent-register', 'round-trip')
  Assert-Equal 'blocked' $run.results['alphafold|alphafold|tool-register'].status 'no image for fingerprint yet'
  Assert-Equal 'DH-REG-005' $run.results['alphafold|alphafold|tool-register'].code
  $run2 = Invoke-DhFakeRun -Agents @('aizynthfinder') -Options @{ toolFunctions = $toolFunctions } -ConfigOverrides @{ nodePools = @() }
  Assert-Equal 'untested' $run2.results['aizynthfinder|aizynthfinder|tool-run'].status
  Assert-Equal 'DH-RUN-006' $run2.results['aizynthfinder|aizynthfinder|tool-run'].code
  Assert-Equal 'untested' $run2.results['aizynthfinder||round-trip'].status
  Assert-Equal 'DH-RUN-006' $run2.results['aizynthfinder||round-trip'].code
}

Test-Case 'unchanged fingerprint reuses the image and ledger smoke results' {
  $ledger = Join-Path (New-DhTestOutDir) 'ledger'
  $first = Invoke-DhFakeRun -Agents @('chembl') -Options @{ toolFunctions = $toolFunctions } -Stages @('build') -ConfigOverrides @{ ledgerDir = $ledger }
  $tag = [string]$first.results['chembl|ChEMBL|build'].data.imageTag
  Install-DhFakeBackend -Options @{ toolFunctions = $toolFunctions }
  & $module { param($tag) $script:Fake.acrTags['discovery-github-test/chembl-image'] = @(@{ name = $tag; createdTime = (Get-Date).ToUniversalTime().ToString('o'); digest = 'sha256:cafe' }) } $tag
  $config = New-DhTestConfig -Overrides @{ ledgerDir = $ledger }
  $out = New-DhTestOutDir
  $result = & $module { param($config, $repo, $out) Invoke-DhRunCommand -Config $config -CatalogRoot $repo -Ref 'HEAD' -Source 'git' -Agents @('chembl') -Stages @('build') -SpecRoot '' -OutputDir $out -RunId 'test-run-2' } $config $repo $out
  $byKey = ConvertTo-DhResultMap $result.results
  Assert-Equal 'cached' $byKey['chembl|ChEMBL|build'].status
  Assert-Equal 'cached' $byKey['chembl|ChEMBL|image-smoke'].status
  Assert-Equal 0 @((& $module { $script:Fake.calls }) | Where-Object { $_ -like 'bg *' }).Count 'no new ACR run'
}

Test-Case 'budget exhaustion skips work instead of failing' {
  $run = Invoke-DhFakeRun -Agents @('chembl') -Options @{ toolFunctions = $toolFunctions } -ConfigOverrides @{ budgets = [ordered]@{ maxAcrBuilds = 0; maxToolRuns = 10; maxGpuToolRuns = 0; maxRoundTrips = 0 } } -Stages @('build', 'round-trip')
  Assert-Equal 'skipped' $run.results['chembl|ChEMBL|build'].status
  Assert-Equal 'DH-DEP-002' $run.results['chembl|ChEMBL|build'].code
  Assert-Equal 'skipped' $run.results['chembl||round-trip'].status
}

Test-Case 'deadline cancels in-flight remote operations and records inconclusive results' {
  Install-DhFakeBackend -Options @{ hangAcr = $true; toolFunctions = $toolFunctions }
  $config = New-DhTestConfig
  $out = New-DhTestOutDir
  $results = & $module {
    param($config, $repo, $out)
    Initialize-DhRun -Config $config -OutputDir $out -RunId 'deadline'
    $catalog = Read-DhCatalog -CatalogRoot $repo -Agents @('chembl') -OutputDir $out -Config $config
    $graph = New-DhGraph -Catalog $catalog -Stages @('build', 'image-smoke', 'tool-register') -Config $config
    $reason = Invoke-DhScheduler -Graph $graph -DeadlineUtc ((Get-DhUtcNow).AddSeconds(8))
    @{ reason = $reason; results = @(Read-DhResults -Directories @($out)) }
  } $config $repo $out
  Assert-Equal 'deadline' $results.reason
  $map = ConvertTo-DhResultMap $results.results
  Assert-Equal 'inconclusive' $map['chembl|ChEMBL|build'].status
  Assert-Equal 'DH-DEP-004' $map['chembl|ChEMBL|build'].code
  Assert-True (@((& $module { $script:Fake.cancelled }) | Where-Object { $_ -like 'acr:*' }).Count -ge 1) 'ACR run cancelled'
  Assert-Equal 'inconclusive' $map['chembl|ChEMBL|tool-register'].status
  $ops = @(Get-ChildItem (Join-Path $out 'operations') -File | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json })
  Assert-Equal 'cancelled' $ops[0].status
}

Test-Case 'unknown agents and spec skips are reported without stopping the run' {
  $specs = New-DhTestOutDir
  New-Item -ItemType Directory -Path $specs | Out-Null
  $until = (Get-Date).AddDays(10).ToString('yyyy-MM-dd')
  Set-Content -Path (Join-Path $specs 'chembl.yaml') -Value "agent: chembl`nskip:`n  - stage: round-trip`n    reason: model quota is exhausted`n    until: '$until'`n"
  $run = Invoke-DhFakeRun -Agents @('chembl', 'does-not-exist') -Options @{ toolFunctions = $toolFunctions } -SpecRoot $specs -Stages @('agent-register', 'round-trip', 'tool-register', 'build')
  Assert-Equal 'failed' $run.results['does-not-exist||discover'].status
  Assert-Equal 'skipped' $run.results['chembl||round-trip'].status
  Assert-Equal 'DH-SPC-003' $run.results['chembl||round-trip'].code
  Assert-Equal 'passed' $run.results['chembl||agent-register'].status
}

Test-Case 'agents needing trusted variables are untested in untrusted runs' {
  $vars = @{ templateVariables = [ordered]@{ AQ_MCP_CONNECTION = 'conn'; AQ_MCP_SERVER_URL = 'https://mcp.example' } }
  $pr = Invoke-DhFakeRun -Agents @('aqcat') -Stages @('agent-register') -ConfigOverrides $vars -Untrusted
  Assert-Equal 'untested' $pr.results['aqcat||agent-register'].status
  Assert-Equal 'DH-AGT-005' $pr.results['aqcat||agent-register'].code
  $main = Invoke-DhFakeRun -Agents @('aqcat') -Stages @('agent-register') -ConfigOverrides $vars
  Assert-Equal 'warning' $main.results['aqcat||agent-register'].status 'warnings downgrade passed results'
  Assert-Equal 'warning' @($main.results['aqcat||agent-register'].messages | Where-Object { $_.code -eq 'DH-AGT-004' })[0].level
}

Test-Case 'multi-tool agent binds every tool id and round trip requires each expected tool' {
  $specs = New-DhTestOutDir
  New-Item -ItemType Directory -Path $specs | Out-Null
  Set-Content -Path (Join-Path $specs 'flowblind-research-teammate-v2.yaml') -Value "agent: flowblind-research-teammate-v2`nroundTrip:`n  prompt: 'Prepare and verify the sample flow end to end.'`n  expect:`n    toolsCalled: [flowblind-prepare, flowblind-run-verify]`n"
  $fns = @{ 'flowblind-research-teammate-v2' = @('flowblindprepare-run') }
  $run = Invoke-DhFakeRun -Agents @('flowblind-research-teammate-v2') -Options @{ toolFunctions = $fns } -SpecRoot $specs -Stages @('build', 'tool-register', 'agent-register', 'round-trip')
  $agent = $run.fake.agents['dgt-FlowBlindResearchTeammateV2']
  Assert-True ($null -ne $agent) 'deployed name uses agent.yaml name with prefix'
  $ids = @($agent.tools | ForEach-Object { ($_.toolId -split '/')[-1] })
  Assert-Equal @('flowblindprepare', 'flowblindrunverify') $ids
  Assert-Equal 'failed' $run.results['flowblind-research-teammate-v2||round-trip'].status
  Assert-Equal 'DH-RTP-002' $run.results['flowblind-research-teammate-v2||round-trip'].code
}

Test-Case 'agent-register alone uses existing tagged tools or blocks instead of deploying placeholders' {
  $run = Invoke-DhFakeRun -Agents @('chembl') -Stages @('agent-register') -Options @{ toolFunctions = $toolFunctions }
  Assert-Equal 'blocked' $run.results['chembl||agent-register'].status
  Assert-Equal 'DH-RUN-009' $run.results['chembl||agent-register'].code
  Assert-Equal 0 $run.fake.agents.Count 'no upsert with unresolved placeholders'
  Install-DhFakeBackend -Options @{ toolFunctions = $toolFunctions }
  & $module { $script:Fake.tools['chembl'] = @{ polls = 5; body = [ordered]@{ id = '/x/tools/chembl'; name = 'chembl'; tags = @{ 'discovery-github-test' = 'true' }; properties = [ordered]@{ provisioningState = 'Succeeded' } } } }
  $config = New-DhTestConfig
  $out = New-DhTestOutDir
  $result = & $module { param($config, $repo, $out) Invoke-DhRunCommand -Config $config -CatalogRoot $repo -Agents @('chembl') -Stages @('agent-register') -OutputDir $out -RunId 'reuse' } $config $repo $out
  $map = ConvertTo-DhResultMap $result.results
  Assert-Equal 'passed' $map['chembl||agent-register'].status
  $payload = (& $module { $script:Fake.agents })['dgt-chembl']
  Assert-Match ([string]$payload.tools[0].toolId) '/providers/Microsoft\.Discovery/tools/chembl$'
}

Test-Case 'unavailable ACR logs are inconclusive and never cached as smoke failures' {
  $ledger = Join-Path (New-DhTestOutDir) 'ledger'
  $run = Invoke-DhFakeRun -Agents @('chembl') -Stages @('build') -Options @{ emptyLogs = $true } -ConfigOverrides @{ ledgerDir = $ledger }
  Assert-Equal 'passed' $run.results['chembl|ChEMBL|build'].status
  Assert-Equal 'inconclusive' $run.results['chembl|ChEMBL|image-smoke'].status
  Assert-Equal 'DH-SMK-006' $run.results['chembl|ChEMBL|image-smoke'].code
  $entry = Get-ChildItem $ledger -Recurse -Filter '*.json' | Select-Object -First 1 | ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json }
  Assert-True ($null -eq $entry.smoke) 'no smoke results cached from an unavailable log'
}

Test-Case 'changed smoke cases invalidate cached smoke results' {
  $ledger = Join-Path (New-DhTestOutDir) 'ledger'
  $first = Invoke-DhFakeRun -Agents @('chembl') -Stages @('build') -ConfigOverrides @{ ledgerDir = $ledger }
  $tag = [string]$first.results['chembl|ChEMBL|build'].data.imageTag
  $specs = New-DhTestOutDir
  New-Item -ItemType Directory -Path $specs | Out-Null
  Set-Content -Path (Join-Path $specs 'chembl.yaml') -Value "agent: chembl`ntools:`n  ChEMBL:`n    imageSmoke:`n      - name: extra-check`n        command: echo extra`n"
  Install-DhFakeBackend -Options @{}
  & $module { param($tag) $script:Fake.acrTags['discovery-github-test/chembl-image'] = @(@{ name = $tag; createdTime = (Get-Date).ToUniversalTime().ToString('o'); digest = 'sha256:cafe' }) } $tag
  $config = New-DhTestConfig -Overrides @{ ledgerDir = $ledger }
  $out = New-DhTestOutDir
  $result = & $module { param($config, $repo, $out, $specs) Invoke-DhRunCommand -Config $config -CatalogRoot $repo -Agents @('chembl') -Stages @('build') -SpecRoot $specs -OutputDir $out -RunId 'spec-change' } $config $repo $out $specs
  $map = ConvertTo-DhResultMap $result.results
  Assert-Equal 'cached' $map['chembl|ChEMBL|build'].status
  Assert-Equal 'passed' $map['chembl|ChEMBL|image-smoke'].status 'smoke re-ran instead of reusing stale ledger results'
  $smokeRuns = @((& $module { $script:Fake.calls }) | Where-Object { $_ -like 'bg *' })
  Assert-Equal 1 $smokeRuns.Count 'one smoke-only ACR run'
  Assert-Equal @('extra-check', 'interpreter-python') @(@($map['chembl|ChEMBL|image-smoke'].data.cases) | ForEach-Object { $_.name } | Sort-Object)
}

Test-Case 'budgets split exactly across shards' {
  $config = New-DhTestConfig -Overrides @{ budgets = [ordered]@{ maxAcrBuilds = 10; maxToolRuns = 4; maxGpuToolRuns = 2; maxRoundTrips = 0 } }
  $split = foreach ($i in 1..3) { & $module { param($c, $i) (New-DhGraph -Catalog ([ordered]@{ agents = [ordered]@{} }) -Stages @() -Config $c -ShardCount 3 -ShardIndex $i).budgets } $config $i }
  Assert-Equal 10 (($split | ForEach-Object { $_.maxAcrBuilds }) | Measure-Object -Sum).Sum
  Assert-Equal 4 (($split | ForEach-Object { $_.maxToolRuns }) | Measure-Object -Sum).Sum
  Assert-Equal @(1, 1, 0) @($split | ForEach-Object { $_.maxGpuToolRuns })
  Assert-Equal 0 (($split | ForEach-Object { $_.maxRoundTrips }) | Measure-Object -Sum).Sum
}

Test-Case 'cleanup deletes only marked test resources in dependency order' {
  $old = (Get-Date).ToUniversalTime().AddDays(-60).ToString('o')
  $taggedId = '/subscriptions/00000000-1111-2222-3333-444444444444/resourceGroups/rg-dgt-test/providers/Microsoft.Discovery/tools/removedtool'
  Install-DhFakeBackend -Options @{
    cleanupAgents = @(
      @{ name = 'dgt-removed-agent'; description = 'x [discovery-github-test r1]' },
      @{ name = 'dgt-CorePythonAgent'; description = 'y [discovery-github-test r1]' },
      @{ name = 'dgt-unmarked'; description = 'someone else' },
      @{ name = 'production-agent'; description = 'z [discovery-github-test r1]' }
    )
    cleanupInvestigations = @(
      @{ name = 'dgt-old-marked'; displayName = 'discovery-github-test chembl'; createdAt = $old },
      @{ name = 'dgt-old-unmarked'; displayName = 'my investigation'; createdAt = $old },
      @{ name = 'dgt-no-date'; displayName = 'discovery-github-test x' }
    )
    cleanupOps = @(
      @{ id = '11111111-1111-1111-1111-111111111111'; status = 'Running'; toolId = $taggedId; createdAt = $old },
      @{ id = '22222222-2222-2222-2222-222222222222'; status = 'Running'; toolId = '/subscriptions/x/resourceGroups/prod/providers/Microsoft.Discovery/tools/real'; createdAt = $old }
    )
  }
  & $module {
    param($taggedId)
    $script:Fake.tools['removedtool'] = @{ polls = 5; body = [ordered]@{ id = $taggedId; name = 'removedtool'; tags = @{ 'discovery-github-test' = 'true'; 'dgt-agent' = 'gone-agent' }; properties = [ordered]@{ provisioningState = 'Succeeded' } } }
    $script:Fake.tools['chembl'] = @{ polls = 5; body = [ordered]@{ id = '/x/tools/chembl'; name = 'chembl'; tags = @{ 'discovery-github-test' = 'true'; 'dgt-agent' = 'chembl' }; properties = [ordered]@{ provisioningState = 'Succeeded' } } }
    $script:Fake.tools['prodtool'] = @{ polls = 5; body = [ordered]@{ id = '/x/tools/prodtool'; name = 'prodtool'; tags = @{}; properties = [ordered]@{ provisioningState = 'Succeeded' } } }
  } $taggedId
  $config = New-DhTestConfig
  $out = New-DhTestOutDir
  $result = & $module { param($c, $o, $r) Invoke-DhCleanupCommand -Config $c -OutputDir $o -CatalogRoot $r } $config $out $repo
  $deleted = @(& $module { $script:Fake.deleted })
  $cancelled = @(& $module { $script:Fake.cancelled })
  Assert-Equal 0 $result.exitCode
  Assert-True ($deleted -contains 'agent:dgt-removed-agent') 'stale marked agent deleted'
  Assert-False ($deleted -contains 'agent:dgt-CorePythonAgent') 'catalog agent kept'
  Assert-False ($deleted -contains 'agent:dgt-unmarked') 'agent without marker kept'
  Assert-False ($deleted -contains 'agent:production-agent') 'agent without prefix kept'
  Assert-True ($deleted -contains 'investigation:dgt-old-marked') 'old marked investigation deleted'
  Assert-False ($deleted -contains 'investigation:dgt-old-unmarked') 'unmarked investigation kept'
  Assert-False ($deleted -contains 'investigation:dgt-no-date') 'undated investigation kept'
  Assert-True ($cancelled -contains 'op:11111111-1111-1111-1111-111111111111') 'stale run on tagged tool cancelled'
  Assert-False ($cancelled -contains 'op:22222222-2222-2222-2222-222222222222') 'run on production tool untouched'
  Assert-True ($deleted -contains 'tool:removedtool') 'tool of removed agent deleted'
  Assert-False ($deleted -contains 'tool:chembl') 'tool of catalog agent kept'
  Assert-False ($deleted -contains 'tool:prodtool') 'untagged tool kept'
  $agentIndex = [array]::IndexOf($deleted, 'agent:dgt-removed-agent')
  $toolIndex = [array]::IndexOf($deleted, 'tool:removedtool')
  Assert-True ($agentIndex -lt $toolIndex) 'agents are deleted before tools'
}

Complete-DhTestFile
