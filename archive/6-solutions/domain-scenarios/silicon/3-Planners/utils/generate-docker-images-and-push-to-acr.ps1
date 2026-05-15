# Chemistry Tools Docker Image Builder and ACR Uploader (PowerShell)
# This script builds Docker images for all chemistry tools and pushes them to Azure Container Registry
# Compatible with Windows, Linux, and macOS

param(
    [string]$AcrName,
    [switch]$Help
)

# Function to print colored output (cross-platform)
function Write-Status {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARNING] $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# Function to show usage
function Show-Usage {
    Write-Host "Chemistry Tools Docker Image Builder & ACR Uploader" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor White
    Write-Host "  .\generate-docker-images-and-push-to-acr.ps1 [-AcrName <acr-name>] [-Help]" -ForegroundColor White
    Write-Host ""
    Write-Host "Parameters:" -ForegroundColor White
    Write-Host "  -AcrName    Optional. Azure Container Registry name (e.g., myregistry or myregistry.azurecr.io)" -ForegroundColor White
    Write-Host "  -Help       Show this help message" -ForegroundColor White
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor White
    Write-Host "  .\generate-docker-images-and-push-to-acr.ps1" -ForegroundColor White
    Write-Host "  .\generate-docker-images-and-push-to-acr.ps1 -AcrName myregistry" -ForegroundColor White
    Write-Host ""
    Write-Host "Features:" -ForegroundColor White
    Write-Host "  - Cross-platform support (Windows, Linux, macOS)" -ForegroundColor White
    Write-Host "  - Automatic discovery of chemistry tools" -ForegroundColor White
    Write-Host "  - Interactive ACR configuration" -ForegroundColor White
    Write-Host "  - Build progress tracking" -ForegroundColor White
    Write-Host "  - Automatic cleanup of local images" -ForegroundColor White
    Write-Host ""
}

# Check for help parameter
if ($Help) {
    Show-Usage
    exit 0
}

# Global variables for tracking results
$script:PushedImages = @()
$script:FailedBuilds = @()
$script:FailedPushes = @()

# Function to check if Docker is available
function Test-DockerEnvironment {
    Write-Status "Checking Docker environment..."
    
    # Check if Docker command exists
    try {
        $dockerVersion = docker --version 2>$null
        if (-not $dockerVersion) {
            throw "Docker command not found"
        }
    }
    catch {
        Write-Error "Docker is not installed or not in PATH"
        Write-Host "Please install Docker from: https://docs.docker.com/get-docker/" -ForegroundColor Yellow
        return $false
    }
    
    # Check if Docker daemon is running
    try {
        docker info | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Docker daemon not running"
        }
    }
    catch {
        Write-Error "Docker daemon is not running. Please start Docker and try again."
        return $false
    }
    
    Write-Success "Docker environment is available"
    Write-Host "  $dockerVersion" -ForegroundColor Gray
    return $true
}

# Function to get ACR details from user
function Get-AcrDetails {
    param([string]$ProvidedAcrName)
    
    Write-Host ""
    Write-Status "Configuring Azure Container Registry details..."
    
    $acrName = $ProvidedAcrName
    
    while ([string]::IsNullOrWhiteSpace($acrName)) {
        $acrName = Read-Host "Enter ACR registry name (e.g., myregistry or myregistry.azurecr.io)"
        if ([string]::IsNullOrWhiteSpace($acrName)) {
            Write-Warning "ACR name cannot be empty"
        }
    }
    
    # Clean up the ACR name
    $acrName = $acrName.Trim()
    
    # Remove protocol if provided
    $acrName = $acrName -replace '^https?://', ''
    
    # Add .azurecr.io suffix if not provided (but avoid double suffix)
    if (-not $acrName.EndsWith('.azurecr.io')) {
        # Check if it already has azurecr but is missing .io
        if ($acrName.EndsWith('.azurecr')) {
            $acrName = "$acrName.io"
        } 
        # Check if it has azureacr.io (common typo) and fix it
        elseif ($acrName.EndsWith('.azureacr.io')) {
            $acrName = $acrName -replace '\.azureacr\.io$', '.azurecr.io'
        } 
        # Otherwise add the full suffix
        else {
            $acrName = "$acrName.azurecr.io"
        }
    }
    
    # Ensure ACR name is lowercase (ACR URLs are case-sensitive)
    $acrName = $acrName.ToLower()
    
    Write-Success "Using ACR: $acrName"
    
    # Check ACR authentication using Azure CLI (more reliable than docker search)
    Write-Status "Checking ACR authentication..."
    $acrShortName = $acrName -replace '\.azurecr\.io$', ''
    
    # First check if Azure CLI is available and logged in
    try {
        $azAccount = az account show 2>$null | ConvertFrom-Json
        if ($azAccount) {
            Write-Success "Azure CLI is logged in as: $($azAccount.user.name)"
            
            # Try to check ACR access with timeout
            Write-Status "Verifying ACR access..."
            $job = Start-Job -ScriptBlock {
                param($acrName)
                az acr repository list --name $acrName --output none 2>$null
                return $LASTEXITCODE
            } -ArgumentList $acrShortName
            
            $completed = Wait-Job -Job $job -Timeout 10
            if ($completed) {
                $exitCode = Receive-Job -Job $job
                Remove-Job -Job $job
                if ($exitCode -eq 0) {
                    Write-Success "ACR authentication verified successfully"
                    
                    # Ensure Docker is logged into ACR
                    Write-Status "Configuring Docker authentication to ACR..."
                    $loginResult = az acr login --name $acrShortName 2>&1
                    if ($LASTEXITCODE -eq 0) {
                        Write-Success "Docker successfully authenticated to ACR"
                    } else {
                        Write-Warning "Docker ACR login may have failed: $loginResult"
                    }
                } else {
                    Write-Warning "ACR access verification failed. You may need to run: az acr login --name $acrShortName"
                }
            } else {
                Remove-Job -Job $job -Force
                Write-Warning "ACR access check timed out"
            }
        } else {
            Write-Warning "Azure CLI not logged in"
        }
    }
    catch {
        Write-Warning "Unable to verify ACR authentication using Azure CLI"
    }
    
    # Provide guidance regardless of authentication check result
    Write-Host ""
    Write-Host "If you encounter authentication issues during push, ensure you're properly logged in:" -ForegroundColor Yellow
    Write-Host "  1. az login" -ForegroundColor Cyan
    Write-Host "  2. az acr login --name $acrShortName" -ForegroundColor Cyan
    Write-Host ""
    
    return $acrName
}

# Function to build and push Docker image
function Build-AndPushImage {
    param(
        [string]$ToolPath,
        [string]$ToolName,
        [string]$AcrName
    )
    
    Write-Status "Processing tool: $ToolName"
    
    # Check if Dockerfile exists
    $dockerfilePath = Join-Path $ToolPath "Dockerfile"
    if (-not (Test-Path $dockerfilePath)) {
        Write-Warning "No Dockerfile found in $ToolPath, skipping..."
        return $false
    }
    
    # Generate image name (lowercase)
    $imageName = "$($ToolName.ToLower())"
    $localTag = "$imageName`:latest"
    $acrTag = "$AcrName/$imageName`:latest"
    
    Write-Status "Building Docker image: $localTag"
    
    try {
        # Build the Docker image
        $buildResult = docker build -t $localTag $ToolPath
        if ($LASTEXITCODE -ne 0) {
            throw "Docker build failed"
        }
        
        Write-Success "Successfully built $localTag"
        
        # Tag for ACR
        Write-Status "Tagging image for ACR: $acrTag"
        docker tag $localTag $acrTag
        if ($LASTEXITCODE -ne 0) {
            throw "Docker tag failed"
        }
        
        # Push to ACR
        Write-Status "Pushing image to ACR: $acrTag"
        docker push $acrTag
        if ($LASTEXITCODE -ne 0) {
            throw "Docker push failed"
        }
        
        Write-Success "Successfully pushed $acrTag"
        $script:PushedImages += $acrTag
        
        # Clean up local images to save space
        Write-Status "Cleaning up local images..."
        try {
            docker rmi $localTag $acrTag 2>$null | Out-Null
        }
        catch {
            # Ignore cleanup errors
        }
        
        return $true
    }
    catch {
        if ($_.Exception.Message -eq "Docker build failed") {
            Write-Error "Failed to build Docker image for $ToolName"
            $script:FailedBuilds += $ToolName
        } elseif ($_.Exception.Message -eq "Docker push failed") {
            Write-Error "Failed to push $acrTag"
            $script:FailedPushes += $acrTag
        } else {
            Write-Error "Error processing $ToolName`: $($_.Exception.Message)"
            $script:FailedBuilds += $ToolName
        }
        return $false
    }
}

# Function to find and process all chemistry tools
function Invoke-ChemistryToolsProcessing {
    param([string]$AcrName)
    
    # Get script directory more reliably
    $scriptDir = if ($PSScriptRoot) {
        $PSScriptRoot
    } elseif ($MyInvocation.MyCommand.Path) {
        Split-Path -Parent $MyInvocation.MyCommand.Path
    } else {
        Get-Location
    }
    
    $chemistryToolsDir = Join-Path (Split-Path -Parent $scriptDir) "chemistryTools"
    
    Write-Status "Looking for chemistry tools in: $chemistryToolsDir"
    
    if (-not (Test-Path $chemistryToolsDir)) {
        Write-Error "Chemistry tools directory not found: $chemistryToolsDir"
        return $false
    }
    
    # Reset tracking arrays
    $script:PushedImages = @()
    $script:FailedBuilds = @()
    $script:FailedPushes = @()
    
    # Find all subdirectories in chemistryTools
    $toolDirs = Get-ChildItem -Path $chemistryToolsDir -Directory
    
    if ($toolDirs.Count -eq 0) {
        Write-Warning "No tool directories found in $chemistryToolsDir"
        return $false
    }
    
    foreach ($toolDir in $toolDirs) {
        $toolName = $toolDir.Name
        $toolDockerfileDir = Join-Path $toolDir.FullName "1-Tool"
        
        Write-Status "Found tool directory: $toolName"
        
        if (Test-Path $toolDockerfileDir) {
            Build-AndPushImage -ToolPath $toolDockerfileDir -ToolName $toolName -AcrName $AcrName
        } else {
            Write-Warning "No 1-Tool directory found for $toolName, skipping..."
        }
    }
    
    return $true
}

# Function to display summary
function Show-Summary {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Status "Build and Push Summary"
    Write-Host "============================================" -ForegroundColor Cyan
    
    if ($script:PushedImages.Count -gt 0) {
        Write-Success "Successfully pushed images ($($script:PushedImages.Count)):"
        foreach ($image in $script:PushedImages) {
            Write-Host "  ✅ $image" -ForegroundColor Green
        }
    }
    
    if ($script:FailedBuilds.Count -gt 0) {
        Write-Error "Failed builds ($($script:FailedBuilds.Count)):"
        foreach ($tool in $script:FailedBuilds) {
            Write-Host "  ❌ $tool" -ForegroundColor Red
        }
    }
    
    if ($script:FailedPushes.Count -gt 0) {
        Write-Error "Failed pushes ($($script:FailedPushes.Count)):"
        foreach ($image in $script:FailedPushes) {
            Write-Host "  ❌ $image" -ForegroundColor Red
        }
    }
    
    Write-Host "============================================" -ForegroundColor Cyan
    
    if ($script:FailedBuilds.Count -eq 0 -and $script:FailedPushes.Count -eq 0) {
        Write-Success "All operations completed successfully!"
        return $true
    } else {
        Write-Warning "Some operations failed. Please check the logs above."
        return $false
    }
}

# Main execution function
function Invoke-Main {
    param([string]$AcrName)
    
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "Chemistry Tools Docker Image Builder & ACR Uploader" -ForegroundColor Cyan
    Write-Host "Cross-Platform PowerShell Version" -ForegroundColor Gray
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    
    # Display platform information
    $platform = if ($IsWindows) { "Windows" } 
                elseif ($IsLinux) { "Linux" } 
                elseif ($IsMacOS) { "macOS" } 
                else { "Unknown" }
    Write-Host "Running on: $platform" -ForegroundColor Gray
    Write-Host "PowerShell Version: $($PSVersionTable.PSVersion)" -ForegroundColor Gray
    Write-Host ""
    
    # Check Docker environment
    if (-not (Test-DockerEnvironment)) {
        exit 1
    }
    
    # Get ACR details
    $acrName = Get-AcrDetails -ProvidedAcrName $AcrName
    if (-not $acrName) {
        exit 1
    }
    
    # Process all chemistry tools
    if (-not (Invoke-ChemistryToolsProcessing -AcrName $acrName)) {
        exit 1
    }
    
    # Display summary and exit with appropriate code
    $success = Show-Summary
    if (-not $success) {
        exit 1
    }
}

# Run main function
try {
    Invoke-Main -AcrName $AcrName
}
catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}
