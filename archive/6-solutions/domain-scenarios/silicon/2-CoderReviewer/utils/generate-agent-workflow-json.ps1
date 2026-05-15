#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Converts agent and workflow YAML files to JSON format for Microsoft Discovery platform.

.DESCRIPTION
    This PowerShell script processes agent and workflow YAML definition files and converts them
    to JSON format suitable for Microsoft Discovery platform. It leverages the existing Python
    utility definition-content-creator.py to perform the conversion with proper formatting.

.PARAMETER OutputPath
    Output directory for generated JSON files. Defaults to 'jsonFiles'

.PARAMETER Force
    Overwrite existing JSON files without prompting

.EXAMPLE
    ./generate-agent-workflow-json.ps1
    Converts all agent and workflow YAML files to JSON with default settings

.EXAMPLE
    ./generate-agent-workflow-json.ps1 -OutputPath "./output" -Force
    Converts files to custom output directory and overwrites existing files

.NOTES
    Requires Python 3.6+ and PyYAML package to be installed.
    Uses definition-content-creator.py for the actual conversion logic.
#>

param(
    [string]$OutputPath = "jsonFiles",
    [switch]$Force
)

# Set up colored output functions
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    
    $colorMap = @{
        "Red" = [ConsoleColor]::Red
        "Green" = [ConsoleColor]::Green
        "Yellow" = [ConsoleColor]::Yellow
        "Blue" = [ConsoleColor]::Blue
        "Cyan" = [ConsoleColor]::Cyan
        "Magenta" = [ConsoleColor]::Magenta
        "White" = [ConsoleColor]::White
    }
    
    Write-Host $Message -ForegroundColor $colorMap[$Color]
}

function Write-Success {
    param(
        [string]$Message
    )
    Write-ColorOutput "[SUCCESS] $Message" "Green"
}

function Write-Info {
    param([string]$Message)
    Write-ColorOutput "[INFO] $Message" "Blue"
}

function Write-Warning {
    param([string]$Message)
    Write-ColorOutput "[WARNING] $Message" "Yellow"
}

function Write-Error {
    param([string]$Message)
    Write-ColorOutput "[ERROR] $Message" "Red"
}

# Function to check if Python and dependencies are available
function Test-PythonEnvironment {
    Write-Info "Checking Python environment..."
    
    # Check if Python is available
    try {
        $pythonVersion = python3 --version 2>$null
        if (-not $pythonVersion) {
            $pythonVersion = python --version 2>$null
            if (-not $pythonVersion) {
                Write-Error "Python is not installed or not available in PATH"
                Write-Info "Please install Python 3.6+ and ensure it's available in your PATH"
                return $false
            }
            $global:PythonCommand = "python"
        } else {
            $global:PythonCommand = "python3"
        }
        
        Write-Info "Found Python: $pythonVersion"
    }
    catch {
        Write-Error "Failed to check Python version: $_"
        return $false
    }
    
    # Check if PyYAML is installed
    try {
        $yamlCheck = & $global:PythonCommand -c "import yaml; print('PyYAML available')" 2>$null
        if (-not $yamlCheck) {
            Write-Warning "PyYAML is not installed"
            Write-Info "Installing PyYAML..."
            & $global:PythonCommand -m pip install pyyaml
            if ($LASTEXITCODE -ne 0) {
                Write-Error "Failed to install PyYAML"
                return $false
            }
            Write-Success "PyYAML installed successfully"
        } else {
            Write-Info "PyYAML is available"
        }
    }
    catch {
        Write-Error "Failed to check or install PyYAML: $_"
        return $false
    }
    
    return $true
}

# Function to get the base directory (discovery-hackathon root)
function Get-BaseDirectory {
    $currentDir = Get-Location
    $utilsDir = Split-Path -Parent $MyInvocation.ScriptName
    
    # If we're in utils directory, go up one level
    if ((Split-Path -Leaf $utilsDir) -eq "utils") {
        return Split-Path -Parent $utilsDir
    }
    
    # Otherwise, assume we're already in the base directory
    return $currentDir
}

# Function to convert YAML to JSON using the Python utility
function Convert-YamlToJson {
    param(
        [string]$YamlPath,
        [string]$OutputPath,
        [string]$FileType  # "agent" or "workflow"
    )
    
    # Ensure the input path is a file
    if (-not (Test-Path $YamlPath -PathType Leaf)) {
        Write-Warning "$YamlPath is not a valid file. Skipping."
        return $false
    }

    $pythonScript = Join-Path (Split-Path -Parent $MyInvocation.ScriptName) "definition-content-creator.py"

    if (-not (Test-Path $pythonScript)) {
        Write-Error "Python script not found: $pythonScript"
        return $false
    }

    try {
        Write-Info "Converting: $YamlPath"

        # Use the Python script with --json flag for proper JSON formatting
        $result = & $global:PythonCommand $pythonScript $YamlPath --json --output $OutputPath 2>&1

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Generated: $OutputPath"
            return $true
        } else {
            Write-Error "Conversion failed for $YamlPath"
            Write-Error $result
            return $false
        }
    }
    catch {
        Write-Error "Exception during conversion of $YamlPath : $_"
        return $false
    }
}

# Function to get agent name from YAML file
function Get-AgentNameFromYaml {
    param([string]$YamlPath)
    
    try {
        $content = Get-Content $YamlPath -Raw
        if ($content -match "name:\s*(.+)") {
            return $matches[1].Trim()
        }
    }
    catch {
        Write-Warning "Could not extract agent name from $YamlPath"
    }
    
    # Fallback to filename without extension
    return [System.IO.Path]::GetFileNameWithoutExtension($YamlPath)
}

# Add support for new agents and workflows
$SupportedAgents = @("CodeReviewer", "Coder", "CoderWithSaveTool")
$SupportedWorkflows = @("CoderWf", "CoderAndReviewerWf", "CoderWithSaveToolWf")

function Test-SupportedDefinitions {
    param (
        [string]$DefinitionName
    )

    if (-not ($DefinitionName -in $SupportedAgents -or $DefinitionName -in $SupportedWorkflows)) {
        Write-ColorOutput -Message "Warning: Unsupported definition $DefinitionName detected." -Color Yellow
    }
}

# Example usage within the script
Test-SupportedDefinitions -DefinitionName "ExampleAgent"

# Function to get all YAML files for agents and workflows
function Get-YamlFiles {
    param(
        [string]$BaseDirectory,
        [string]$SubDirectory,  # Subdirectory for agents
        [string]$FileType       # "agent" or "workflow"
    )

    if ($FileType -eq "agent") {
        # Search recursively in the 'agent-definitions' subdirectory
        $searchPath = Join-Path $BaseDirectory $SubDirectory
        $files = Get-ChildItem -Path $searchPath -Filter "*.yaml" -Recurse -File
        Write-Info "Agent files found: $($files | ForEach-Object { $_.FullName })"
        return $files
    } elseif ($FileType -eq "workflow") {
        # Search only in the current directory for workflows
        $files = Get-ChildItem -Path $BaseDirectory -Filter "*.yaml" -File
        Write-Info "Workflow files found: $($files | ForEach-Object { $_.FullName })"
        return $files
    }

    return @()  # Return an empty array if no files are found
}

# Main execution
Write-Info "Starting Agent and Workflow JSON Generation"
Write-Info "============================================="

# Check Python environment
if (-not (Test-PythonEnvironment)) {
    Write-Error "Python environment check failed. Exiting."
    exit 1
}

# Get the base directory
$BaseDirectory = Get-BaseDirectory
Write-Info "Base directory: $BaseDirectory"

# Get agent and workflow files
$AgentFiles = Get-YamlFiles -BaseDirectory $BaseDirectory -SubDirectory "agent-definitions" -FileType "agent"
$WorkflowFiles = Get-YamlFiles -BaseDirectory $BaseDirectory -SubDirectory "" -FileType "workflow"

Write-Info "Found $($AgentFiles.Count) agent files and $($WorkflowFiles.Count) workflow files to process"

# Ensure output directory exists
$fullOutputPath = Join-Path $BaseDirectory $OutputPath
if (-not (Test-Path $fullOutputPath)) {
    New-Item -ItemType Directory -Path $fullOutputPath -Force | Out-Null
    Write-Info "Created output directory: $fullOutputPath"
}

$successCount = 0
$totalFiles = $AgentFiles.Count + $WorkflowFiles.Count

# Process agent files
Write-Info "\nProcessing Agent Files:\n-----------------------"
foreach ($AgentFile in $AgentFiles) {
    Write-Info "Processing agent file: $($AgentFile.FullName)"
    if (-not (Test-Path $AgentFile.FullName -PathType Leaf)) {
        Write-Warning "$($AgentFile.FullName) is not a valid file. Skipping."
        continue
    }
    $OutputPath = Join-Path $BaseDirectory "jsonFiles" ($AgentFile.BaseName + "-agent-definition.json")
    # Increment success count if conversion is successful
    if (Convert-YamlToJson -YamlPath $AgentFile.FullName -OutputPath $OutputPath -FileType "agent") {
        $successCount++
    }
}

# Process workflow files
Write-Info "\nProcessing Workflow Files:\n---------------------------"
foreach ($WorkflowFile in $WorkflowFiles) {
    Write-Info "Processing workflow file: $($WorkflowFile.FullName)"
    if (-not (Test-Path $WorkflowFile.FullName -PathType Leaf)) {
        Write-Warning "$($WorkflowFile.FullName) is not a valid file. Skipping."
        continue
    }
    $OutputPath = Join-Path $BaseDirectory "jsonFiles" ($WorkflowFile.BaseName + "-workflow-definition.json")
    # Increment success count if conversion is successful
    if (Convert-YamlToJson -YamlPath $WorkflowFile.FullName -OutputPath $OutputPath -FileType "workflow") {
        $successCount++
    }
}

# Summary
Write-Info ""
Write-Info "Conversion Summary:"
Write-Info "==================="
Write-Success "Successfully converted: $successCount/$totalFiles files"
Write-Info "Output directory: $fullOutputPath"

if ($successCount -eq $totalFiles) {
    Write-Success "All files converted successfully!"
} elseif ($successCount -gt 0) {
    Write-Warning "Some files failed to convert. Check the errors above."
} else {
    Write-Error "No files were converted successfully."
    exit 1
}

# List generated files
Write-Info ""
Write-Info "Generated Files:"
Write-Info "----------------"
$jsonFiles = Get-ChildItem -Path $fullOutputPath -Filter "*.json" | Sort-Object Name
foreach ($file in $jsonFiles) {
    Write-Info "  $($file.Name)"
}

Write-Info ""
Write-Success "Agent and Workflow JSON generation completed!"
