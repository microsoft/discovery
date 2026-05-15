# PowerShell script to update tool definition YAML files with ACR name and generate JSON files
# Usage: .\update-tools-and-generate-json.ps1 <acr-name>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$AcrName,
    
    [switch]$Help
)

# Function to print colored output
function Write-Info {
    param([string]$Message)
    Write-Host "$Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "$Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "$Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "$Message" -ForegroundColor Red
}

# Function to show usage
function Show-Usage {
    Write-Host "Usage: .\update-tools-and-generate-json.ps1 <acr-name>" -ForegroundColor White
    Write-Host ""
    Write-Host "This script will:" -ForegroundColor White
    Write-Host "  1. Install Python3 and pip if they are missing (automatic dependency management)" -ForegroundColor White
    Write-Host "  2. Install PyYAML Python package if missing" -ForegroundColor White
    Write-Host "  3. Update all tool definition YAML files with the provided ACR name" -ForegroundColor White
    Write-Host "  4. Generate corresponding JSON files using the definition-content-creator.py script" -ForegroundColor White
    Write-Host "  5. Place the JSON files in jsonFiles\" -ForegroundColor White
    Write-Host ""
    Write-Host "Arguments:" -ForegroundColor White
    Write-Host "  <acr-name>    The name of your Azure Container Registry" -ForegroundColor White
    Write-Host "                Can be just the name (e.g., 'myacr') or the full path (e.g., 'myacr.azurecr.io')" -ForegroundColor White
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor White
    Write-Host "  .\update-tools-and-generate-json.ps1 discoveryacr01" -ForegroundColor White
    Write-Host "  .\update-tools-and-generate-json.ps1 discoveryacr01.azurecr.io" -ForegroundColor White
    Write-Host "  .\update-tools-and-generate-json.ps1 mycompanyacr" -ForegroundColor White
    Write-Host ""
    Write-Host "Dependencies:" -ForegroundColor White
    Write-Host "  - The script will automatically install Python3, pip, and PyYAML if missing" -ForegroundColor White
    Write-Host "  - Requires Windows 10/11 or Windows Server 2016+" -ForegroundColor White
    Write-Host "  - May require Administrator privileges for Python installation" -ForegroundColor White
    Write-Host ""
}

# Check for help parameter
if ($Help) {
    Show-Usage
    exit 0
}

# Validate ACR name parameter
if ([string]::IsNullOrWhiteSpace($AcrName)) {
    Write-Error "ACR name is required"
    Show-Usage
    exit 1
}

# Normalize ACR name - remove .azurecr.io suffix if provided
if ($AcrName.EndsWith('.azurecr.io')) {
    $originalAcrName = $AcrName
    $AcrName = $AcrName -replace '\.azurecr\.io$', ''
    Write-Info "Detected full ACR path '$originalAcrName', using ACR name: $AcrName"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ChemistryToolsDir = Join-Path $ProjectRoot "chemistryTools"
$JsonOutputDir = Join-Path $ProjectRoot "jsonFiles"

Write-Info "Starting tool definition update and JSON generation process..."
Write-Info "ACR Name: $AcrName"
Write-Info "Project Root: $ProjectRoot"
Write-Info "Chemistry Tools Directory: $ChemistryToolsDir"

# Check if we're in the right directory structure
if (-not (Test-Path $ChemistryToolsDir)) {
    Write-Error "Chemistry tools directory not found: $ChemistryToolsDir"
    Write-Error "Please run this script from the utils directory of the discovery-hackathon project"
    exit 1
}

# Check if Python script exists
$PythonScript = Join-Path $ScriptDir "definition-content-creator.py"
if (-not (Test-Path $PythonScript)) {
    Write-Error "Python script not found: $PythonScript"
    exit 1
}

# Function to install Python on Windows
function Install-Python {
    Write-Info "Attempting to install Python3..."
    
    # Check if winget is available (Windows Package Manager)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Info "Installing Python3 using Windows Package Manager (winget)..."
        try {
            winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
            Write-Success "Python3 installed successfully via winget"
            
            # Refresh PATH
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
            return $true
        }
        catch {
            Write-Warning "Failed to install Python via winget: $_"
        }
    }
    
    # Check if Chocolatey is available
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Info "Installing Python3 using Chocolatey..."
        try {
            choco install python3 -y
            Write-Success "Python3 installed successfully via Chocolatey"
            
            # Refresh PATH
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
            return $true
        }
        catch {
            Write-Warning "Failed to install Python via Chocolatey: $_"
        }
    }
    
    # Manual installation guidance
    Write-Warning "Automatic installation failed. Please install Python manually:"
    Write-Info "1. Go to https://www.python.org/downloads/windows/"
    Write-Info "2. Download the latest Python 3.x installer"
    Write-Info "3. Run the installer and make sure to check 'Add Python to PATH'"
    Write-Info "4. Restart your PowerShell session after installation"
    
    return $false
}

# Function to install pip (usually comes with Python on Windows)
function Install-Pip {
    Write-Info "Attempting to install pip..."
    
    try {
        # Try to bootstrap pip
        python -m ensurepip --upgrade
        Write-Success "pip installed/upgraded successfully"
        return $true
    }
    catch {
        Write-Warning "Failed to install pip via ensurepip: $_"
    }
    
    # Try downloading get-pip.py
    try {
        $getPipPath = Join-Path $env:TEMP "get-pip.py"
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipPath
        python $getPipPath
        Remove-Item $getPipPath -Force
        Write-Success "pip installed successfully via get-pip.py"
        return $true
    }
    catch {
        Write-Warning "Failed to install pip via get-pip.py: $_"
    }
    
    Write-Error "Failed to install pip automatically"
    Write-Info "Please install pip manually: https://pip.pypa.io/en/stable/installation/"
    return $false
}

# Check and install Python dependencies
Write-Info "Checking and installing Python dependencies..."

# Check if Python is available
$pythonCommand = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCommand = "python3"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
}

if (-not $pythonCommand) {
    Write-Warning "Python is not installed or not in PATH"
    if (-not (Install-Python)) {
        Write-Error "Failed to install Python automatically"
        exit 1
    }
    
    # Re-check for Python after installation
    Start-Sleep -Seconds 2
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $pythonCommand = "python"
    } elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
        $pythonCommand = "python3"
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $pythonCommand = "py"
    } else {
        Write-Error "Python installation verification failed"
        exit 1
    }
}

$pythonVersion = & $pythonCommand --version
Write-Success "Python is available: $pythonVersion"

# Check if pip is available
$pipCommand = $null
if (Get-Command pip -ErrorAction SilentlyContinue) {
    $pipCommand = "pip"
} elseif (Get-Command pip3 -ErrorAction SilentlyContinue) {
    $pipCommand = "pip3"
}

if (-not $pipCommand) {
    Write-Warning "pip is not installed or not in PATH"
    if (-not (Install-Pip)) {
        Write-Error "Failed to install pip automatically"
        exit 1
    }
    
    # Re-check for pip after installation
    if (Get-Command pip -ErrorAction SilentlyContinue) {
        $pipCommand = "pip"
    } elseif (Get-Command pip3 -ErrorAction SilentlyContinue) {
        $pipCommand = "pip3"
    } else {
        Write-Error "pip installation verification failed"
        exit 1
    }
}

$pipVersion = & $pipCommand --version
Write-Success "pip is available: $pipVersion"

# Check and install PyYAML
try {
    & $pythonCommand -c "import yaml" 2>$null
    Write-Success "PyYAML is already available"
}
catch {
    Write-Warning "PyYAML is not installed. Installing it now..."
    try {
        & $pipCommand install pyyaml
        Write-Success "PyYAML installed successfully"
    }
    catch {
        Write-Error "Failed to install PyYAML automatically: $_"
        Write-Info "Please install PyYAML manually with: $pipCommand install pyyaml"
        exit 1
    }
}

# Create JSON output directory if it doesn't exist
if (-not (Test-Path $JsonOutputDir)) {
    New-Item -ItemType Directory -Path $JsonOutputDir -Force | Out-Null
}
Write-Info "Created/verified JSON output directory: $JsonOutputDir"

# Function to update ACR path in YAML file
function Update-AcrInYaml {
    param(
        [string]$YamlFile,
        [string]$AcrName
    )
    
    Write-Info "Processing: $YamlFile"
    
    # Create backup
    $backupFile = "$YamlFile.backup"
    Copy-Item $YamlFile $backupFile
    
    try {
        # Read the file content
        $content = Get-Content $YamlFile -Raw
        
        # Find the ACR line using regex - use capturing group instead of lookbehind
        $acrPattern = 'acr:\s+(.+)'
        $match = [regex]::Match($content, $acrPattern)
        
        if (-not $match.Success) {
            Write-Warning "No ACR line found in $YamlFile"
            Remove-Item $backupFile -Force
            return $false
        }
        
        $currentAcrPath = $match.Groups[1].Value.Trim()
        
        # Extract image name (everything after the last '/')
        $imageName = $currentAcrPath -replace '.*/', ''
        
        if ([string]::IsNullOrWhiteSpace($imageName)) {
            Write-Warning "Could not extract image name from $YamlFile"
            Remove-Item $backupFile -Force
            return $false
        }
        
        # Create new ACR path
        $newAcrPath = "$AcrName.azurecr.io/$imageName"
        
        # Replace the ACR path in content
        $newContent = $content -replace "acr:\s+.*", "acr: $newAcrPath"
        
        # Write back to file
        Set-Content -Path $YamlFile -Value $newContent -NoNewline
        
        # Clean up backup
        Remove-Item $backupFile -Force
        
        Write-Success "Updated ACR path to: $newAcrPath"
        return $true
    }
    catch {
        # Restore backup on failure
        if (Test-Path $backupFile) {
            Move-Item $backupFile $YamlFile -Force
        }
        Write-Error "Failed to update ACR path in $YamlFile`: $_"
        return $false
    }
}

# Function to generate JSON from YAML
function Generate-JsonFromYaml {
    param(
        [string]$YamlFile,
        [string]$ToolName
    )
    
    Write-Info "Generating JSON from: $YamlFile"
    
    # Generate output filename
    $jsonFilename = "$ToolName-tool-definition.json"
    $jsonOutput = Join-Path $JsonOutputDir $jsonFilename
    
    try {
        # Use Python script to convert YAML to JSON
        & $pythonCommand $PythonScript $YamlFile --json --output $jsonOutput
        Write-Success "Generated JSON: $jsonOutput"
        return $true
    }
    catch {
        Write-Error "Failed to generate JSON from $YamlFile`: $_"
        return $false
    }
}

# Find all YAML files in the chemistry tools directory
Write-Info "Searching for tool definition YAML files..."

$processedCount = 0
$failedCount = 0

# Find all YAML files in 1-Tool directories
$yamlFiles = Get-ChildItem -Path $ChemistryToolsDir -Recurse -Filter "*.yaml" | Where-Object { $_.Directory.Name -eq "1-Tool" }

foreach ($yamlFile in $yamlFiles) {
    # Extract tool name from path (parent directory of 1-Tool)
    $toolName = $yamlFile.Directory.Parent.Name
    
    Write-Info "Found tool: $toolName"
    Write-Info "YAML file: $($yamlFile.FullName)"
    
    # Update ACR path
    if (Update-AcrInYaml -YamlFile $yamlFile.FullName -AcrName $AcrName) {
        # Generate JSON
        if (Generate-JsonFromYaml -YamlFile $yamlFile.FullName -ToolName $toolName) {
            $processedCount++
            Write-Success "Successfully processed $toolName"
        } else {
            $failedCount++
            Write-Error "Failed to generate JSON for $toolName"
        }
    } else {
        $failedCount++
        Write-Error "Failed to update ACR path for $toolName"
    }
    
    Write-Host ""  # Add blank line for readability
}

# Summary
Write-Host "==========================================" -ForegroundColor Cyan
Write-Info "Processing Summary:"
Write-Success "Successfully processed: $processedCount tools"
if ($failedCount -gt 0) {
    Write-Error "Failed to process: $failedCount tools"
}

if ($processedCount -gt 0) {
    Write-Success "JSON files generated in: $JsonOutputDir"
    Write-Info "You can now use these JSON files for your Microsoft Discovery deployment"
}

# List generated JSON files
if (Test-Path $JsonOutputDir) {
    $jsonFiles = Get-ChildItem -Path $JsonOutputDir -Filter "*.json"
    if ($jsonFiles.Count -gt 0) {
        Write-Info "Generated JSON files:"
        foreach ($jsonFile in $jsonFiles) {
            Write-Host "  📄 $($jsonFile.Name)" -ForegroundColor White
        }
    }
}

# Clean up any remaining backup files
Write-Info "Cleaning up backup files..."
$backupFiles = Get-ChildItem -Path $ChemistryToolsDir -Recurse -Filter "*.backup"
$backupFilesCleanedCount = 0

foreach ($backupFile in $backupFiles) {
    try {
        Remove-Item $backupFile.FullName -Force
        $backupFilesCleanedCount++
    }
    catch {
        Write-Warning "Failed to remove backup file: $($backupFile.FullName)"
    }
}

if ($backupFilesCleanedCount -gt 0) {
    Write-Success "Cleaned up $backupFilesCleanedCount backup files"
}

Write-Info "Script completed!"

# Exit with error if any files failed to process
if ($failedCount -gt 0) {
    exit 1
}
