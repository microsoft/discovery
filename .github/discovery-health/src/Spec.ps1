# Deterministic test specs: validation, defaults and the Handlebars-lite renderer.
# Nothing here generates content with AI; defaults are fixed templates.

$script:DhReceiptContract = @'
Actually execute the requested validation checks. For code execution, assert
the requested numerical results and verify each required output file exists
and has nonzero size before printing one line in the executed tool's stdout:
DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"check name","actual":2.1,"expected":2.1,"tolerance":1e-8}],"artifacts":[{"path":"/output/result.csv","bytes":123}]}
Replace the example with actual measured values, tolerances, paths and sizes.
Include every requested check and artifact, the executed script, and runtime
session information. Use base language facilities if no JSON package exists.
An assistant-only receipt or a plan is not execution evidence. If approval is
needed, request it explicitly; never bypass approval.
'@

$script:DhToolLessPrompt = 'What can you do? Answer in two or three sentences.'

function Expand-DhTemplate {
  <#
  .SYNOPSIS Renders {{var}} and {{#if var}}...{{else}}...{{/if}} (the constructs used by tool.yaml commands).
  #>
  param([AllowEmptyString()][string]$Template, [System.Collections.IDictionary]$Values = @{})
  $text = [string]$Template
  $pattern = '\{\{#if\s+([\w\-]+)\s*\}\}((?:(?!\{\{#if\s).)*?)\{\{/if\}\}'
  $guard = 0
  while ([regex]::IsMatch($text, $pattern, 'Singleline') -and $guard -lt 100) {
    $guard++
    $text = [regex]::Replace($text, $pattern, {
        param($m)
        $name = $m.Groups[1].Value
        $parts = [regex]::Split($m.Groups[2].Value, '\{\{else\}\}')
        $truthy = $Values.Contains($name) -and (Test-DhTruthy $Values[$name])
        if ($truthy) { return $parts[0] }
        if ($parts.Count -gt 1) { return $parts[1] }
        return ''
      }, 'Singleline')
  }
  return [regex]::Replace($text, '\{\{\{?\s*([\w\-]+)\s*\}?\}\}', {
      param($m)
      $name = $m.Groups[1].Value
      if ($Values.Contains($name) -and $null -ne $Values[$name]) { return [string]$Values[$name] }
      return ''
    })
}

function Test-DhSpec {
  <#
  .SYNOPSIS Returns spec problems (schema + semantic checks against the catalog agent).
  #>
  param([System.Collections.IDictionary]$Spec, [System.Collections.IDictionary]$Agent)
  $problems = [System.Collections.Generic.List[string]]::new()
  $schemaErrors = $null
  $ok = Test-Json -Json (ConvertTo-DhJson $Spec) -SchemaFile (Join-Path $script:DhRoot 'schemas/spec.schema.json') -ErrorAction SilentlyContinue -ErrorVariable schemaErrors
  if (-not $ok) { foreach ($err in @($schemaErrors)) { $problems.Add(('schema: ' + $err.Exception.Message)) } }
  if ($Agent -and [string]$Spec.agent -ne [string]$Agent.name) { $problems.Add(('agent field "{0}" does not match folder' -f $Spec.agent)) }
  $tools = Get-DhValue $Spec 'tools' @{}
  if ($tools -is [System.Collections.IDictionary] -and $Agent) {
    foreach ($toolName in $tools.Keys) {
      if (-not $Agent.tools.Contains($toolName)) { $problems.Add("unknown tool folder: $toolName"); continue }
      $tool = $Agent.tools[$toolName]
      foreach ($case in @(Get-DhValue $tools[$toolName] 'toolRun' @())) {
        if (-not ($case -is [System.Collections.IDictionary])) { continue }
        $action = [string](Get-DhValue $case 'action' '')
        if ($action -and -not (@($tool.actions) | Where-Object { $_.name -eq $action })) { $problems.Add("tool $toolName has no action $action") }
        if (-not $action -and -not $case.Contains('script') -and -not $case.Contains('command')) { $problems.Add("toolRun $($case.name) needs action, script or command") }
        foreach ($regex in @(Get-DhValue $case 'expect.matches' @())) { try { [void][regex]::new([string]$regex) } catch { $problems.Add("invalid regex in $($case.name)") } }
      }
    }
  }
  foreach ($skip in @(Get-DhValue $Spec 'skip' @())) {
    $until = [datetime]::MinValue
    if (-not [datetime]::TryParseExact([string]$skip.until, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture, 'AssumeUniversal', [ref]$until)) { $problems.Add("invalid skip.until $($skip.until)") }
    if ($skip.Contains('tool') -and $Agent -and -not $Agent.tools.Contains([string]$skip.tool)) { $problems.Add("skip references unknown tool $($skip.tool)") }
  }
  foreach ($name in @(Get-DhValue $Spec 'roundTrip.expect.toolsCalled' @())) {
    if ($Agent -and -not $Agent.tools.Contains([string]$name)) { $problems.Add("roundTrip.expect.toolsCalled references unknown tool $name") }
  }
  foreach ($regex in @(Get-DhValue $Spec 'roundTrip.expect.matches' @())) { try { [void][regex]::new([string]$regex) } catch { $problems.Add('invalid regex in roundTrip.expect.matches') } }
  return $problems.ToArray()
}

function Get-DhSpecSkip {
  <#
  .SYNOPSIS Returns @{ active = skip-or-null; expired = list } for a stage (and optional tool).
  #>
  param([System.Collections.IDictionary]$Agent, [string]$Stage, [string]$Tool = '')
  $today = (Get-DhUtcNow).Date
  $active = $null
  $expired = [System.Collections.Generic.List[object]]::new()
  foreach ($skip in @(Get-DhValue $Agent.spec 'skip' @())) {
    if ([string]$skip.stage -ne $Stage) { continue }
    if ($skip.Contains('tool') -and $skip.tool -and [string]$skip.tool -ne $Tool) { continue }
    $until = [datetime]::MinValue
    if (-not [datetime]::TryParseExact([string]$skip.until, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture, 'AssumeUniversal', [ref]$until)) { continue }
    if ($until.ToUniversalTime().Date -ge $today) { $active = $skip } else { $expired.Add($skip) }
  }
  return @{ active = $active; expired = $expired.ToArray() }
}

function Get-DhLanguageInfo {
  param([string]$Language)
  switch -Regex (([string]$Language).ToLowerInvariant()) {
    '^python3$' { return @{ interpreter = 'python3'; ext = 'py'; kind = 'python' } }
    '^python$' { return @{ interpreter = 'python'; ext = 'py'; kind = 'python' } }
    '^r$' { return @{ interpreter = 'Rscript'; ext = 'R'; kind = 'r' } }
    default { return @{ interpreter = $Language; ext = 'txt'; kind = 'other' } }
  }
}

function Get-DhSmokeCases {
  <#
  .SYNOPSIS Image smoke cases (run inside ACR right after the build) for a tool.
  #>
  param([System.Collections.IDictionary]$Agent, [System.Collections.IDictionary]$Tool)
  $cases = [System.Collections.Generic.List[object]]::new()
  $toolSpec = Get-DhValue $Agent.spec ('tools.' + $Tool.name) $null
  $useDefaults = $true
  if ($toolSpec -is [System.Collections.IDictionary] -and $toolSpec.Contains('defaultImageSmoke')) { $useDefaults = [bool]$toolSpec.defaultImageSmoke }
  if ($useDefaults) {
    $seen = @{}
    foreach ($env in @($Tool.codeEnvironments)) {
      $info = Get-DhLanguageInfo ([string]$env.language)
      if ($seen.ContainsKey($info.interpreter)) { continue }
      $seen[$info.interpreter] = $true
      $command = switch ($info.kind) {
        'python' { '{0} -c "print(''DH_OK'')"' -f $info.interpreter }
        'r' { 'Rscript -e "cat(''DH_OK\n'')"' }
        default { '{0} --version && echo DH_OK' -f $info.interpreter }
      }
      $cases.Add([ordered]@{ name = ('interpreter-' + (ConvertTo-DhSafeName $info.interpreter)); command = $command; expect = [ordered]@{ exitCode = 0; contains = @('DH_OK') }; source = 'default' })
    }
    $checks = [System.Collections.Generic.List[string]]::new()
    foreach ($action in @($Tool.actions)) {
      $command = ([string]$action.command).Trim()
      $prefix = ($command -split '\{\{', 2)[0]
      $tokens = @($prefix -split '\s+' | Where-Object { $_ })
      if ($tokens.Count -ge 1 -and $tokens[0] -match '^[A-Za-z0-9_.\-]+$' -and $tokens[0] -notin @('cd', 'export', 'set', 'if', 'for', 'mkdir', 'env', 'exec')) {
        $check = 'command -v {0} >/dev/null' -f $tokens[0]
        if (-not $checks.Contains($check)) { $checks.Add($check) }
      } elseif ($tokens.Count -ge 1 -and $tokens[0] -match '^/[A-Za-z0-9_./\-]+$') {
        $check = 'test -e {0}' -f $tokens[0]
        if (-not $checks.Contains($check)) { $checks.Add($check) }
      }
      if ($tokens.Count -ge 2 -and $tokens[1] -match '^/[A-Za-z0-9_./\-]+$' -and $tokens[1] -notmatch '^/(input|output|tmp|workdir)(/|$)') {
        $check = 'test -e {0}' -f $tokens[1]
        if (-not $checks.Contains($check)) { $checks.Add($check) }
      }
    }
    if ($checks.Count -gt 0) {
      $cases.Add([ordered]@{ name = 'action-entrypoints'; command = (($checks -join ' && ') + ' && echo DH_OK'); expect = [ordered]@{ exitCode = 0; contains = @('DH_OK') }; source = 'default' })
    }
    if ($cases.Count -eq 0) {
      $cases.Add([ordered]@{ name = 'container-starts'; command = 'echo DH_OK'; expect = [ordered]@{ exitCode = 0; contains = @('DH_OK') }; source = 'default' })
    }
  }
  if ($toolSpec -is [System.Collections.IDictionary]) {
    foreach ($case in @(Get-DhValue $toolSpec 'imageSmoke' @())) {
      $expect = Get-DhValue $case 'expect' ([ordered]@{})
      if (-not $expect.Contains('exitCode')) { $expect.exitCode = 0 }
      $cases.Add([ordered]@{ name = [string]$case.name; command = [string]$case.command; expect = $expect; source = 'spec' })
    }
  }
  return $cases.ToArray()
}

function Get-DhDefaultCheckScript {
  param([string]$Kind, [string]$OutputDir)
  if ($Kind -eq 'r') {
    return @"
out_dir <- "$OutputDir"
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
path <- file.path(out_dir, "dh_check.txt")
value <- 6L * 7L
writeLines(as.character(value), path)
size <- as.integer(file.info(path)`$size)
receipt <- sprintf('DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"product","actual":%d,"expected":42,"tolerance":0}],"artifacts":[{"path":"%s","bytes":%d}]}', value, path, size)
writeLines(receipt, file.path(out_dir, "dh_receipt.txt"))
cat("DH_OK\n")
cat(receipt, "\n", sep = "")
"@
  }
  return @"
import json
import os

out_dir = "$OutputDir"
os.makedirs(out_dir, exist_ok=True)
path = os.path.join(out_dir, "dh_check.txt")
value = 6 * 7
with open(path, "w", encoding="utf-8") as handle:
    handle.write(str(value))
size = os.path.getsize(path)
receipt = "DISCOVERY_VALIDATION_RESULT=" + json.dumps({"checks": [{"name": "product", "actual": value, "expected": 42, "tolerance": 0}], "artifacts": [{"path": path, "bytes": size}]})
with open(os.path.join(out_dir, "dh_receipt.txt"), "w", encoding="utf-8") as handle:
    handle.write(receipt + "\n")
print("DH_OK")
print(receipt)
"@
}

function New-DhWrappedCommand {
  param([string]$Inner, [string]$OutputDir)
  $q = $OutputDir
  return ('mkdir -p {0} /dh/input 2>/dev/null; {{ {1} ; }}; rc=$?; if [ -f {0}/logs.out ]; then tail -n 200 {0}/logs.out; fi; if [ -f {0}/dh_receipt.txt ]; then cat {0}/dh_receipt.txt; fi; echo "DH_RUN_EXIT:$rc"; exit $rc' -f $q, $Inner)
}

function Get-DhToolRunCases {
  <#
  .SYNOPSIS Deterministic direct tool-run cases; returns @{ cases; untestedCode }.
  #>
  param([System.Collections.IDictionary]$Agent, [System.Collections.IDictionary]$Tool, [string]$OutputDir = '/tmp/dh/output')
  $cases = [System.Collections.Generic.List[object]]::new()
  $specCases = @(Get-DhValue $Agent.spec ('tools.' + $Tool.name + '.toolRun') @())
  foreach ($case in $specCases) {
    $inline = [System.Collections.Generic.List[object]]::new()
    foreach ($file in @(Get-DhValue $case 'inlineFiles' @())) { $inline.Add([ordered]@{ mountPath = ('/dh/input/' + $file.path); content = [string]$file.content }) }
    $expect = Get-DhValue $case 'expect' ([ordered]@{})
    if (-not $expect.Contains('status')) { $expect.status = 'Succeeded' }
    if (-not $expect.Contains('exitCode')) { $expect.exitCode = 0 }
    $values = [ordered]@{ input_directory = '/dh/input'; output_directory = $OutputDir }
    $inputs = Get-DhValue $case 'inputs' @{}
    foreach ($key in $inputs.Keys) { $values[$key] = $inputs[$key] }
    $inner = ''
    $action = [string](Get-DhValue $case 'action' '')
    if ($action) {
      $definition = @($Tool.actions) | Where-Object { $_.name -eq $action } | Select-Object -First 1
      if (-not $definition) {
        $cases.Add([ordered]@{ name = [string]$case.name; error = 'DH-RUN-011'; action = $action })
        continue
      }
      $inner = Expand-DhTemplate -Template ([string]$definition.command) -Values $values
    } elseif ($case.Contains('script')) {
      $envName = [string](Get-DhValue $case 'codeEnvironment' '')
      $env = @($Tool.codeEnvironments) | Where-Object { -not $envName -or [string]$_.language -eq $envName } | Select-Object -First 1
      $info = Get-DhLanguageInfo $(if ($env) { [string]$env.language } else { 'python3' })
      $scriptPath = 'dh/input/dh_case.' + $info.ext
      $inline.Add([ordered]@{ mountPath = '/' + $scriptPath; content = [string]$case.script })
      $values['scriptName'] = $scriptPath
      $inner = if ($env) { Expand-DhTemplate -Template ([string]$env.command) -Values $values } else { '{0} /{1}' -f $info.interpreter, $scriptPath }
    } else {
      $inner = Expand-DhTemplate -Template ([string]$case.command) -Values $values
    }
    $verify = [string](Get-DhValue $case 'verify' '')
    if ($verify) { $inner = '( {0} ) && ( {1} )' -f $inner, (Expand-DhTemplate -Template $verify -Values $values) }
    $cases.Add([ordered]@{
        name = [string]$case.name; command = (New-DhWrappedCommand -Inner $inner -OutputDir $OutputDir); inlineFiles = $inline.ToArray()
        expect = $expect; timeoutMinutes = [int](Get-DhValue $case 'timeoutMinutes' 0); source = 'spec'
      })
  }
  if ($cases.Count -gt 0) { return @{ cases = $cases.ToArray(); untestedCode = '' } }

  $env = @($Tool.codeEnvironments) | Select-Object -First 1
  if ($env) {
    $info = Get-DhLanguageInfo ([string]$env.language)
    if ($info.kind -in @('python', 'r')) {
      $scriptPath = 'dh/input/dh_check.' + $info.ext
      $values = [ordered]@{ scriptName = $scriptPath; output_directory = $OutputDir; input_directory = '/dh/input' }
      $inner = Expand-DhTemplate -Template ([string]$env.command) -Values $values
      $cases.Add([ordered]@{
          name = 'default-code-env'; command = (New-DhWrappedCommand -Inner $inner -OutputDir $OutputDir)
          inlineFiles = @([ordered]@{ mountPath = '/' + $scriptPath; content = (Get-DhDefaultCheckScript -Kind $info.kind -OutputDir $OutputDir) })
          expect = [ordered]@{ status = 'Succeeded'; exitCode = 0; contains = @('DH_OK'); receipt = $true }; timeoutMinutes = 0; source = 'default'
        })
      return @{ cases = $cases.ToArray(); untestedCode = '' }
    }
  }
  return @{ cases = @(); untestedCode = 'DH-RUN-007' }
}

function Get-DhRoundTripPlan {
  <#
  .SYNOPSIS Deterministic round-trip prompt and programmatic expectations for an agent.
  #>
  param([System.Collections.IDictionary]$Agent)
  $bound = @(Get-DhBoundTools -Agent $Agent)
  $specRt = Get-DhValue $Agent.spec 'roundTrip' $null
  if ($specRt -is [System.Collections.IDictionary]) {
    $expect = Get-DhValue $specRt 'expect' ([ordered]@{})
    $called = @(Get-DhValue $expect 'toolsCalled' @())
    if ($called.Count -eq 0 -and $bound.Count -gt 0) { $called = $bound }
    $prompt = [string]$specRt.prompt
    $receipt = [bool](Get-DhValue $expect 'receipt' $false)
    if ($receipt) { $prompt = $prompt + "`n" + $script:DhReceiptContract }
    return [ordered]@{
      prompt = $prompt; toolsCalled = $called; contains = @(Get-DhValue $expect 'contains' @()); matches = @(Get-DhValue $expect 'matches' @())
      receipt = $receipt; toolLess = ($bound.Count -eq 0); untestedCode = ''; source = 'spec'; timeoutMinutes = [int](Get-DhValue $specRt 'timeoutMinutes' 0)
    }
  }
  if ($bound.Count -eq 0) {
    return [ordered]@{ prompt = $script:DhToolLessPrompt; toolsCalled = @(); contains = @(); matches = @(); receipt = $false; toolLess = $true; untestedCode = ''; source = 'default'; timeoutMinutes = 0 }
  }
  foreach ($toolName in $bound) {
    $tool = $Agent.tools[$toolName]
    $env = @($tool.codeEnvironments) | Select-Object -First 1
    if (-not $env) { continue }
    $info = Get-DhLanguageInfo ([string]$env.language)
    if ($info.kind -notin @('python', 'r')) { continue }
    $language = if ($info.kind -eq 'r') { 'R' } else { 'Python' }
    $prompt = ('Use the {0} tool to run a short {1} script that computes 6 multiplied by 7, writes the result to /output/dh_roundtrip.txt, verifies that the file exists and has nonzero size, and prints the validation receipt. Do not ask for confirmation; this is an automated health check.' -f $tool.defName, $language)
    return [ordered]@{
      prompt = ($prompt + "`n" + $script:DhReceiptContract); toolsCalled = @($toolName); contains = @('42'); matches = @()
      receipt = $true; toolLess = $false; untestedCode = ''; source = 'default'; timeoutMinutes = 0
    }
  }
  return [ordered]@{ prompt = ''; toolsCalled = $bound; contains = @(); matches = @(); receipt = $false; toolLess = $false; untestedCode = 'DH-RTP-007'; source = 'none'; timeoutMinutes = 0 }
}

function ConvertTo-DhYamlScalar {
  param([string]$Value)
  if ($Value -match '^[A-Za-z0-9_./-]+$' -and $Value -notmatch '^(true|false|null|yes|no|on|off|\d+)$') { return $Value }
  return "'" + ($Value -replace "'", "''") + "'"
}

function New-DhSpecSkeleton {
  <#
  .SYNOPSIS Deterministic spec skeleton from tool.yaml action input schemas; maintainers fill values.
  #>
  param([System.Collections.IDictionary]$Agent)
  $lines = [System.Collections.Generic.List[string]]::new()
  $lines.Add("# Deterministic Discovery Health spec for $($Agent.name). Replace every <...> value.")
  $lines.Add('# Schema: .github/discovery-health/schemas/spec.schema.json')
  $lines.Add("agent: $($Agent.name)")
  if ($Agent.tools.Count -gt 0) {
    $lines.Add('tools:')
    foreach ($tool in $Agent.tools.Values) {
      $lines.Add("  $(ConvertTo-DhYamlScalar $tool.name):")
      $lines.Add('    toolRun:')
      $hasCase = $false
      foreach ($action in @($tool.actions)) {
        $hasCase = $true
        $lines.Add("      - name: $(ConvertTo-DhSafeName ([string]$action.name) 40)")
        $lines.Add("        action: $(ConvertTo-DhYamlScalar ([string]$action.name))")
        $props = Get-DhValue $action 'input_schema.properties' @{}
        $required = @(Get-DhValue $action 'input_schema.required' @())
        $inputKeys = @($props.Keys | Where-Object { $_ -notin @('input_directory', 'output_directory') })
        if ($inputKeys.Count -gt 0) {
          $lines.Add('        inputs:')
          foreach ($key in $inputKeys) {
            $marker = if ($key -in $required) { 'required' } else { 'optional' }
            $lines.Add("          $(ConvertTo-DhYamlScalar $key): '<$marker value>'")
          }
        }
        $lines.Add('        expect:')
        $lines.Add("          status: Succeeded")
        $lines.Add("          contains: ['<text that proves the action ran>']")
      }
      if (-not $hasCase -and @($tool.codeEnvironments).Count -gt 0) {
        $lines.Add('      - name: domain-check')
        $lines.Add('        script: |')
        $lines.Add('          print("<deterministic domain check printing a known value>")')
        $lines.Add('        expect:')
        $lines.Add("          contains: ['<known value>']")
      }
    }
  }
  $lines.Add('roundTrip:')
  $lines.Add("  prompt: '<deterministic request that requires calling every bound tool>'")
  $lines.Add('  expect:')
  $bound = @(Get-DhBoundTools -Agent $Agent)
  $lines.Add("    toolsCalled: [$((@($bound | ForEach-Object { ConvertTo-DhYamlScalar $_ })) -join ', ')]")
  $lines.Add("    contains: ['<text that proves the answer used tool output>']")
  return ($lines -join "`n") + "`n"
}
