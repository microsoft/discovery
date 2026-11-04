# YAML parsing through a single batched python call (PyYAML safe_load).

function ConvertFrom-DhYamlFiles {
  <#
  .SYNOPSIS Parses many YAML files in one python process. Returns path -> @{ ok; doc; error }.
  #>
  param([string[]]$Paths, [System.Collections.IDictionary]$Config)
  $result = @{}
  $list = @($Paths | Where-Object { $_ } | Select-Object -Unique)
  if ($list.Count -eq 0) { return $result }
  $python = Get-DhPythonCommand -Config $Config
  $script = Join-Path $script:DhRoot 'src/yaml_to_json.py'
  $raw = ($list -join "`n") | & $python $script 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw ('YAML shim failed (is PyYAML installed?): {0}' -f (($raw | Out-String).Trim()))
  }
  $parsed = ConvertFrom-DhJson (($raw | Where-Object { $_ -is [string] }) -join "`n")
  foreach ($key in $parsed.Keys) { $result[$key] = $parsed[$key] }
  return $result
}

function ConvertFrom-DhYamlFile {
  param([Parameter(Mandatory)][string]$Path, [System.Collections.IDictionary]$Config)
  $all = ConvertFrom-DhYamlFiles -Paths @($Path) -Config $Config
  $entry = $all[$Path]
  if (-not $entry -or -not $entry.ok) { throw ('Invalid YAML {0}: {1}' -f $Path, $entry.error) }
  return $entry.doc
}
