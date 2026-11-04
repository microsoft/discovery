# Offline fake of ARM / ACR / Discovery data-plane endpoints used by scheduler tests.
# Installed into the DiscoveryHealth module scope; no network or Azure access.

function Install-DhFakeBackend {
  param([hashtable]$Options = @{})
  $module = Get-Module DiscoveryHealth
  & $module {
    param($Options)
    $script:Fake = @{
      calls = [System.Collections.Generic.List[string]]::new(); acrTags = @{}; acrRuns = @{}; tools = @{}; ops = @{}; agents = @{}; responses = @{}
      runCounter = 0; options = $Options; cancelled = [System.Collections.Generic.List[string]]::new(); deleted = [System.Collections.Generic.List[string]]::new()
    }
    function script:Invoke-DhAz {
      param([string[]]$Arguments, [switch]$AsJson)
      $script:Fake.calls.Add('az ' + ($Arguments -join ' '))
      $joined = $Arguments -join ' '
      if ($joined -match '^acr repository show-tags .*--repository (\S+)') {
        $repo = $Matches[1]
        if (-not $script:Fake.acrTags.ContainsKey($repo)) { return @{ exitCode = 1; stdout = ''; stderr = 'repository not found'; json = $null } }
        return @{ exitCode = 0; stdout = ''; stderr = ''; json = @($script:Fake.acrTags[$repo]) }
      }
      return @{ exitCode = 0; stdout = '[]'; stderr = ''; json = @() }
    }
    function script:Start-DhBackgroundCommand {
      param([string]$Command, [string[]]$Arguments)
      $script:Fake.calls.Add('bg ' + ($Arguments -join ' '))
      $context = $Arguments[-1]
      $task = [System.IO.File]::ReadAllText((Join-Path $context '.dh/acr-task.yaml'))
      $script:Fake.runCounter++
      $runId = 'ca{0}' -f $script:Fake.runCounter
      $image = if ($task -match '\$Registry/([^:\s]+):(\S+)') { @{ repo = $Matches[1]; tag = $Matches[2] } } else { @{ repo = 'x'; tag = 'y' } }
      $failBuild = $task -match ' build: ' -and @($script:Fake.options['failBuild']) -contains (($image.repo -split '/')[-1])
      $log = [System.Text.StringBuilder]::new()
      [void]$log.AppendLine('2026/01/01 00:00:00 Executing step ID: build. Timeout(sec): 7200')
      if ($failBuild) {
        [void]$log.AppendLine('ERROR: failed to solve: process "/bin/sh -c pip install nope" did not complete successfully: exit code: 1')
      } else {
        [void]$log.AppendLine("- image:`n  registry: dgttestacr.azurecr.io`n  repository: $($image.repo)`n  tag: $($image.tag)`n  digest: sha256:aaaa`n  runtime-dependency:`n    registry: mcr.microsoft.com`n    repository: azurelinux/base/python`n    tag: 3.12`n    digest: sha256:bbbb")
        foreach ($script in (Get-ChildItem -LiteralPath (Join-Path $context '.dh') -Filter 'smoke-*.sh' | Sort-Object Name)) {
          $text = [System.IO.File]::ReadAllText($script.FullName)
          $name = if ($text -match 'DH_SMOKE_BEGIN:([a-z0-9-]+)') { $Matches[1] } else { 'unknown' }
          $rc = if (@($script:Fake.options['failSmoke']) -contains $name) { 1 } else { 0 }
          [void]$log.AppendLine("DH_SMOKE_BEGIN:$name")
          [void]$log.AppendLine('DH_OK')
          [void]$log.AppendLine("DH_SMOKE_END:${name}:$rc")
        }
      }
      $script:Fake.acrRuns[$runId] = @{ polls = 0; status = $(if ($failBuild) { 'Failed' } else { 'Succeeded' }); log = $log.ToString(); repo = $image.repo; tag = $image.tag }
      return [pscustomobject]@{ State = 'Completed'; FakeResult = [pscustomobject]@{ exitCode = 0; output = ('{{"runId": "{0}", "status": "Queued"}}' -f $runId) } }
    }
    function script:Receive-DhBackgroundCommand { param($Job) return $Job.FakeResult }
    function script:Invoke-DhRest {
      param([string]$Method = 'GET', [string]$Uri, [string]$Audience = 'arm', $Body = $null, [hashtable]$Headers = @{}, [string]$ContentType = '', [int]$TimeoutSec = 60, [int]$MaxAttempts = 4)
      $script:Fake.calls.Add("$Method $Uri")
      $ok = { param($b, $s = 200, $h = @{}) @{ status = $s; body = $b; raw = (ConvertTo-DhJson $b -Compress); headers = $h } }
      if ($Uri -match '/resourcegroups/[^/?]+\?api-version') { return (& $ok @{ name = 'rg'; tags = @{ 'discovery-github-test' = 'true' } }) }
      if ($Uri -match '/registries/[^/?]+\?api-version') { return (& $ok @{ name = 'acr'; tags = @{ 'discovery-github-test' = 'true' } }) }
      if ($Uri -match '/nodepools/[^/?]+\?api-version') { return (& $ok @{ name = 'np' }) }
      if ($Uri -match '/runs/([a-z0-9]+)/cancel') { $script:Fake.cancelled.Add('acr:' + $Matches[1]); return (& $ok @{}) }
      if ($Uri -match '/runs/([a-z0-9]+)/listLogSasUrl') { return (& $ok @{ logLink = "https://fakeblob.example/logs/$($Matches[1])?sig=SECRET" }) }
      if ($Uri -match '^https://fakeblob\.example/logs/([a-z0-9]+)') { if ($script:Fake.options['emptyLogs']) { return @{ status = 403; body = $null; raw = ''; headers = @{} } }; return @{ status = 200; body = $null; raw = $script:Fake.acrRuns[$Matches[1]].log; headers = @{} } }
      if ($Uri -match '/registries/[^/]+/runs/([a-z0-9]+)\?') {
        $run = $script:Fake.acrRuns[$Matches[1]]
        $run.polls++
        if ($script:Fake.options['hangAcr']) { return (& $ok @{ properties = @{ status = 'Running' } }) }
        $status = if ($run.polls -lt 2) { 'Running' } else { $run.status }
        return (& $ok @{ properties = @{ status = $status; outputImages = @(@{ registry = 'dgttestacr.azurecr.io'; repository = $run.repo; tag = $run.tag; digest = 'sha256:cafe' }) } })
      }
      if ($Uri -match '/providers/Microsoft\.Discovery/tools\?api-version') { return (& $ok @{ value = @($script:Fake.tools.Values | ForEach-Object { $_.body }) }) }
      if ($Uri -match '/tools/projects/[^/]+/operations\?api-version') { return (& $ok @{ value = @($script:Fake.options['cleanupOps']) }) }
      if ($Uri -match '/projects/[^/]+/investigations\?api-version') { return (& $ok @{ value = @($script:Fake.options['cleanupInvestigations']) }) }
      if ($Uri -match '/providers/Microsoft\.Discovery/tools/([a-z0-9]+)\?') {
        $name = $Matches[1]
        if ($Method -eq 'PUT') {
          $tags = @{}; foreach ($k in $Body.tags.Keys) { $tags[$k] = $Body.tags[$k] }
          $script:Fake.tools[$name] = @{ polls = 0; body = [ordered]@{ id = "/x/tools/$name"; name = $name; tags = $tags; properties = [ordered]@{ provisioningState = 'Creating'; definitionContent = $Body.properties.definitionContent } } }
          return (& $ok $script:Fake.tools[$name].body 201)
        }
        if ($Method -eq 'DELETE') { $script:Fake.deleted.Add("tool:$name"); $script:Fake.tools.Remove($name); return (& $ok @{} 200) }
        if (-not $script:Fake.tools.ContainsKey($name)) { return @{ status = 404; body = @{ error = @{ code = 'NotFound' } }; raw = 'not found'; headers = @{} } }
        $tool = $script:Fake.tools[$name]
        $tool.polls++
        if ($tool.polls -ge 2) { $tool.body.properties.provisioningState = 'Succeeded' }
        return (& $ok $tool.body)
      }
      if ($Uri -match '/tools/projects/[^/]+:run\?') {
        $id = [guid]::NewGuid().ToString()
        $script:Fake.ops[$id] = @{ polls = 0; payload = $Body }
        return (& $ok @{ id = $id; status = 'Accepted'; result = $null } 202)
      }
      if ($Uri -match '/operations/([0-9a-f-]{36}):cancel') { $script:Fake.cancelled.Add('op:' + $Matches[1]); return (& $ok @{} 202) }
      if ($Uri -match '/tools/projects/[^/]+/operations/([0-9a-f-]{36})\?') {
        $op = $script:Fake.ops[$Matches[1]]
        $op.polls++
        if ($op.polls -lt 2) { return (& $ok @{ id = $Matches[1]; status = 'Running'; result = @{ status = 'Running'; toolReport = @{ logs = '' } } }) }
        $logs = "DH_OK`nDISCOVERY_VALIDATION_RESULT={""checks"":[{""name"":""product"",""actual"":42,""expected"":42,""tolerance"":0}],""artifacts"":[{""path"":""/tmp/dh/output/dh_check.txt"",""bytes"":2}]}`nDH_RUN_EXIT:0"
        return (& $ok @{ id = $Matches[1]; status = 'Succeeded'; result = @{ status = 'Succeeded'; toolReport = @{ logs = $logs; percentageComplete = 100 }; runtimeDetails = 'ok' } })
      }
      if ($Uri -match ':upsertAgent\?') {
        $script:Fake.agents[[string]$Body.name] = $Body
        return @{ status = 202; body = @{ id = $Body.name }; raw = '{}'; headers = @{ 'Operation-Location' = @("https://fakeop.example/agents/$($Body.name)") } }
      }
      if ($Uri -match '^https://fakeop\.example/') { return (& $ok @{ status = 'Succeeded' }) }
      if ($Uri -match '/projects/[^/]+/agents/([^/?]+)\?') {
        if ($Method -eq 'DELETE') { $script:Fake.deleted.Add('agent:' + $Matches[1]); return (& $ok @{} 204) }
        if ($script:Fake.deleted.Contains('agent:' + $Matches[1])) { return @{ status = 404; body = $null; raw = ''; headers = @{} } }
        return (& $ok @{ name = $Matches[1]; provisioningState = 'Succeeded' })
      }
      if ($Uri -match '/projects/[^/]+/agents\?') { return (& $ok @{ value = @($script:Fake.options['cleanupAgents']) }) }
      if ($Uri -match '/investigations/([^/?]+)\?') {
        if ($Method -eq 'DELETE') { $script:Fake.deleted.Add('investigation:' + $Matches[1]) }
        return (& $ok @{ name = $Matches[1] } 201)
      }
      if ($Uri -match '/conversations\?api-version') { return (& $ok @{ name = 'conv-' + [guid]::NewGuid().ToString('N').Substring(0, 6) } 201) }
      if ($Uri -match '/conversations/([^/]+)/openai/v1/responses/([^/?]+)/cancel') { $script:Fake.cancelled.Add('response:' + $Matches[2]); return (& $ok @{}) }
      if ($Uri -match '/conversations/([^/]+)/openai/v1/responses$' -and $Method -eq 'POST') {
        $id = 'resp_' + [guid]::NewGuid().ToString('N').Substring(0, 8)
        $agentName = [string]$Body.agent_reference.name
        $script:Fake.responses[$id] = @{ polls = 0; agent = $agentName; prompt = [string]$Body.input[0].content[0].text }
        return (& $ok @{ id = $id; status = 'in_progress'; output = @() })
      }
      if ($Uri -match '/conversations/([^/]+)/openai/v1/responses/([^/?]+)$') {
        $r = $script:Fake.responses[$Matches[2]]
        $r.polls++
        if ($script:Fake.options['hangResponses'] -or $r.polls -lt 2) { return (& $ok @{ id = $Matches[2]; status = 'in_progress'; output = @() }) }
        $agentKey = ConvertTo-DhAlnum ($r.agent -replace '^dgt-', '')
        $toolFns = @()
        if ($script:Fake.options['toolFunctions']) {
          foreach ($key in $script:Fake.options['toolFunctions'].Keys) { if ((ConvertTo-DhAlnum $key) -eq $agentKey) { $toolFns = @($script:Fake.options['toolFunctions'][$key]) } }
        }
        $output = [System.Collections.Generic.List[object]]::new()
        $i = 0
        foreach ($fn in $toolFns) {
          $i++
          $output.Add(@{ type = 'function_call'; call_id = "c$i"; name = $fn; arguments = '{}' })
          $output.Add(@{ type = 'function_call_output'; call_id = "c$i"; output = "Tool execution succeeded. stdout: 42`nDISCOVERY_VALIDATION_RESULT={""checks"":[{""name"":""product"",""actual"":42,""expected"":42,""tolerance"":0}],""artifacts"":[{""path"":""/output/dh_roundtrip.txt"",""bytes"":2}]}`nOutputs: discovery://storageassets/x/out" })
        }
        $output.Add(@{ type = 'message'; content = @(@{ type = 'output_text'; text = 'Done. The product is 42. I can help with chemistry questions.' }) })
        return (& $ok @{ id = $Matches[2]; status = 'completed'; output = $output.ToArray() })
      }
      return @{ status = 404; body = $null; raw = "unmatched $Method $Uri"; headers = @{} }
    }
    function script:Get-DhAccessToken { param($Audience, [switch]$Refresh) return 'fake-token' }
  } $Options
}
