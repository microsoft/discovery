#!/usr/bin/env pwsh

# Docker Setup Automation Script for PowerShell (Cross-Platform)
# Ensures Docker is installed, running, and configured for VS Code bash and PowerShell environments
# Supports: macOS, Windows, and Linux

param(
    [switch]$SkipInstall,
    [switch]$SkipVSCodeSettings,
    [switch]$TestOnly,
    [switch]$Verbose
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Enable verbose output if requested
if ($Verbose) {
    $VerbosePreference = "Continue"
}

# Cross-platform compatibility functions
function Get-OperatingSystem {
    if ($PSVersionTable.PSVersion.Major -ge 6) {
        return $PSVersionTable.OS
    } else {
        return "Windows"
    }
}

function Get-OSType {
    $os = Get-OperatingSystem
    if ($os -like "*Windows*") {
        return "Windows"
    } elseif ($os -like "*Darwin*" -or $os -like "*macOS*") {
        return "macOS"
    } elseif ($os -like "*Linux*") {
        return "Linux"
    } else {
        return "Unknown"
    }
}

function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Level = "Info"
    )
    
    $color = switch ($Level) {
        "Success" { "Green" }
        "Warning" { "Yellow" }
        "Error" { "Red" }
        "Info" { "Cyan" }
        default { "White" }
    }
    
    $prefix = switch ($Level) {
        "Success" { "[SUCCESS]" }
        "Warning" { "[WARNING]" }
        "Error" { "[ERROR]" }
        "Info" { "[INFO]" }
        default { "[LOG]" }
    }
    
    Write-Host "$prefix $Message" -ForegroundColor $color
}

function Test-DockerInstalled {
    Write-ColorOutput "Checking Docker installation..." "Info"
    
    try {
        $dockerVersion = docker --version 2>$null
        if ($dockerVersion) {
            Write-ColorOutput "Docker is installed: $dockerVersion" "Success"
            return $true
        }
    }
    catch {
        Write-ColorOutput "Docker command not found" "Warning"
    }
    
    return $false
}

function Test-DockerDesktopInstalled {
    Write-ColorOutput "Checking Docker Desktop installation..." "Info"
    
    $osType = Get-OSType
    $isInstalled = $false
    
    switch ($osType) {
        "Windows" {
            $paths = @(
                "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
                "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
            )
            foreach ($path in $paths) {
                if (Test-Path $path) {
                    Write-ColorOutput "Docker Desktop found at: $path" "Success"
                    $isInstalled = $true
                    break
                }
            }
        }
        "macOS" {
            if (Test-Path "/Applications/Docker.app") {
                Write-ColorOutput "Docker Desktop found at: /Applications/Docker.app" "Success"
                $isInstalled = $true
            }
        }
        "Linux" {
            # Linux typically uses Docker Engine, not Desktop
            if (Get-Command docker -ErrorAction SilentlyContinue) {
                Write-ColorOutput "Docker Engine is installed (Linux)" "Success"
                $isInstalled = $true
            }
        }
    }
    
    if (-not $isInstalled) {
        Write-ColorOutput "Docker Desktop/Engine not found" "Warning"
    }
    
    return $isInstalled
}

function Install-DockerDesktop {
    if ($SkipInstall) {
        Write-ColorOutput "Skipping Docker installation (SkipInstall flag set)" "Info"
        return $false
    }
    
    Write-ColorOutput "Installing Docker Desktop..." "Info"
    $osType = Get-OSType
    
    try {
        switch ($osType) {
            "Windows" {
                if (Get-Command winget -ErrorAction SilentlyContinue) {
                    Write-ColorOutput "Installing Docker Desktop via winget..." "Info"
                    winget install Docker.DockerDesktop
                    Write-ColorOutput "Docker Desktop installed via winget" "Success"
                } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
                    Write-ColorOutput "Installing Docker Desktop via Chocolatey..." "Info"
                    choco install docker-desktop -y
                    Write-ColorOutput "Docker Desktop installed via Chocolatey" "Success"
                } else {
                    Write-ColorOutput "No package manager found. Please install Docker Desktop manually from:" "Error"
                    Write-ColorOutput "https://www.docker.com/products/docker-desktop/" "Error"
                    return $false
                }
            }
            "macOS" {
                if (Get-Command brew -ErrorAction SilentlyContinue) {
                    Write-ColorOutput "Installing Docker Desktop via Homebrew..." "Info"
                    brew install --cask docker
                    Write-ColorOutput "Docker Desktop installed via Homebrew" "Success"
                } else {
                    Write-ColorOutput "Homebrew not found. Please install Docker Desktop manually from:" "Error"
                    Write-ColorOutput "https://www.docker.com/products/docker-desktop/" "Error"
                    return $false
                }
            }
            "Linux" {
                Write-ColorOutput "Installing Docker Engine via apt/yum..." "Info"
                if (Get-Command apt-get -ErrorAction SilentlyContinue) {
                    sudo apt-get update
                    sudo apt-get install -y docker.io
                    sudo systemctl start docker
                    sudo systemctl enable docker
                    Write-ColorOutput "Docker Engine installed via apt" "Success"
                } elseif (Get-Command yum -ErrorAction SilentlyContinue) {
                    sudo yum install -y docker
                    sudo systemctl start docker
                    sudo systemctl enable docker
                    Write-ColorOutput "Docker Engine installed via yum" "Success"
                } else {
                    Write-ColorOutput "Please install Docker manually for your Linux distribution" "Error"
                    return $false
                }
            }
            default {
                Write-ColorOutput "Unsupported operating system: $osType" "Error"
                return $false
            }
        }
        return $true
    }
    catch {
        Write-ColorOutput "Failed to install Docker: $($_.Exception.Message)" "Error"
        return $false
    }
}
function Start-DockerDesktop {
    Write-ColorOutput "Starting Docker Desktop..." "Info"
    $osType = Get-OSType
    
    try {
        switch ($osType) {
            "Windows" {
                $dockerPath = Get-ChildItem -Path "$env:ProgramFiles\Docker\Docker", "${env:ProgramFiles(x86)}\Docker\Docker" -Filter "Docker Desktop.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($dockerPath) {
                    Start-Process -FilePath $dockerPath.FullName -WindowStyle Hidden
                    Write-ColorOutput "Docker Desktop is starting..." "Info"
                } else {
                    Write-ColorOutput "Docker Desktop executable not found" "Error"
                    return $false
                }
            }
            "macOS" {
                if (Test-Path "/Applications/Docker.app") {
                    Start-Process -FilePath "open" -ArgumentList "-a", "Docker" -Wait
                    Write-ColorOutput "Docker Desktop is starting..." "Info"
                } else {
                    Write-ColorOutput "Docker Desktop not found at /Applications/Docker.app" "Error"
                    return $false
                }
            }
            "Linux" {
                sudo systemctl start docker
                Write-ColorOutput "Docker service started" "Info"
            }
        }
        
        # Wait for Docker daemon to be ready
        Write-ColorOutput "Waiting for Docker daemon to be ready..." "Info"
        $retries = 0
        $maxRetries = 30
        
        do {
            Start-Sleep -Seconds 2
            $retries++
            Write-Host "." -NoNewline
            
            try {
                $null = docker info 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host ""
                    Write-ColorOutput "Docker daemon is ready" "Success"
                    return $true
                }
            }
            catch {
                # Continue waiting
            }
        } while ($retries -lt $maxRetries)
        
        Write-Host ""
        Write-ColorOutput "Docker daemon failed to start within expected time" "Error"
        return $false
    }
    catch {
        Write-ColorOutput "Failed to start Docker Desktop: $($_.Exception.Message)" "Error"
        return $false
    }
}

function Test-DockerRunning {
    Write-ColorOutput "Checking if Docker daemon is running..." "Info"
    
    try {
        $null = docker info 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-ColorOutput "Docker daemon is running" "Success"
            return $true
        }
    }
    catch {
        # Fall through to warning
    }
    
    Write-ColorOutput "Docker daemon is not running" "Warning"
    return $false
}

function Get-DockerPath {
    try {
        $dockerPath = Get-Command docker -ErrorAction SilentlyContinue
        if ($dockerPath) {
            return $dockerPath.Source
        }
    }
    catch {
        # Return empty if not found
    }
    return ""
}

function Update-ShellProfiles {
    Write-ColorOutput "Updating shell profiles for Docker PATH..." "Info"
    
    $dockerPath = Get-DockerPath
    if (-not $dockerPath) {
        Write-ColorOutput "Docker path not found" "Error"
        return $false
    }
    
    $dockerBinDir = Split-Path $dockerPath -Parent
    $osType = Get-OSType
    
    # Update bash/zsh profiles (macOS/Linux)
    if ($osType -ne "Windows") {
        $profileFiles = @(
            "$env:HOME/.bash_profile",
            "$env:HOME/.bashrc", 
            "$env:HOME/.zshrc"
        )
        
        foreach ($profileFile in $profileFiles) {
            if ((Test-Path $profileFile) -or ($profileFile -like "*/.zshrc")) {
                $content = ""
                if (Test-Path $profileFile) {
                    $content = Get-Content $profileFile -Raw
                }
                
                if ($content -notlike "*$dockerBinDir*") {
                    Add-Content -Path $profileFile -Value "`n# Docker PATH configuration"
                    Add-Content -Path $profileFile -Value "export PATH=`"$dockerBinDir`:`$PATH`""
                    Write-ColorOutput "Updated $profileFile with Docker PATH" "Success"
                } else {
                    Write-ColorOutput "$profileFile already contains Docker PATH" "Info"
                }
            }
        }
    }
    
    return $true
}

function Update-PowerShellProfile {
    Write-ColorOutput "Configuring PowerShell profile for Docker..." "Info"
    
    $dockerPath = Get-DockerPath
    if (-not $dockerPath) {
        Write-ColorOutput "Docker path not found" "Error"
        return $false
    }
    
    $dockerBinDir = Split-Path $dockerPath -Parent
    $osType = Get-OSType
    
    # Determine PowerShell profile path
    $profilePath = $PROFILE.CurrentUserAllHosts
    if (-not $profilePath) {
        $profilePath = $PROFILE
    }
    
    $profileDir = Split-Path $profilePath -Parent
    if (-not (Test-Path $profileDir)) {
        New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
    }
    
    # Determine path separator
    $pathSeparator = if ($osType -eq "Windows") { ";" } else { ":" }
    
    # PowerShell profile content
    $profileContent = @"
# Docker PATH configuration for PowerShell on $osType
# Ensure Docker is available in PowerShell sessions

# Add Docker binary directory to PATH if not already present
`$dockerPath = "$dockerBinDir"
if (`$env:PATH -notlike "*`$dockerPath*") {
    `$env:PATH = `$dockerPath + "$pathSeparator" + `$env:PATH
}

# Function to check Docker status
function Test-Docker {
    try {
        `$dockerVersion = docker --version 2>`$null
        if (`$dockerVersion) {
            Write-Host "Docker is available: `$dockerVersion" -ForegroundColor Green
            
            # Check if Docker daemon is running
            `$dockerInfo = docker info 2>`$null
            if (`$LASTEXITCODE -eq 0) {
                Write-Host "Docker daemon is running" -ForegroundColor Green
                return `$true
            } else {
                Write-Host "Docker daemon is not running. Start Docker Desktop." -ForegroundColor Yellow
                return `$false
            }
        }
    }
    catch {
        Write-Host "Docker is not available in PATH" -ForegroundColor Red
        return `$false
    }
}

# Function to start Docker Desktop
function Start-DockerDesktop {
    try {
        Write-Host "Starting Docker Desktop..." -ForegroundColor Blue
        `$osType = "$osType"
        switch (`$osType) {
            "Windows" {
                `$dockerExe = Get-ChildItem -Path "`$env:ProgramFiles\Docker\Docker", "`${env:ProgramFiles(x86)}\Docker\Docker" -Filter "Docker Desktop.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
                if (`$dockerExe) {
                    Start-Process -FilePath `$dockerExe.FullName -WindowStyle Hidden
                }
            }
            "macOS" {
                & open -a Docker
            }
            "Linux" {
                sudo systemctl start docker
            }
        }
        Write-Host "Docker Desktop is starting. Please wait for initialization." -ForegroundColor Blue
    }
    catch {
        Write-Host "Failed to start Docker Desktop: `$(`$_.Exception.Message)" -ForegroundColor Red
    }
}

# Display Docker status when profile loads (optional)
# Test-Docker
"@

    Set-Content -Path $profilePath -Value $profileContent -Force
    Write-ColorOutput "Created PowerShell profile at $profilePath" "Success"
    return $true
}

function Update-VSCodeSettings {
    if ($SkipVSCodeSettings) {
        Write-ColorOutput "Skipping VS Code settings update (SkipVSCodeSettings flag set)" "Info"
        return $true
    }
    
    Write-ColorOutput "Configuring VS Code terminal settings..." "Info"
    
    $dockerPath = Get-DockerPath
    if (-not $dockerPath) {
        Write-ColorOutput "Docker path not found" "Error"
        return $false
    }
    
    $dockerBinDir = Split-Path $dockerPath -Parent
    $osType = Get-OSType
    
    # Determine VS Code settings path
    $settingsPath = switch ($osType) {
        "Windows" { "$env:APPDATA\Code\User\settings.json" }
        "macOS" { "$env:HOME/Library/Application Support/Code/User/settings.json" }
        "Linux" { "$env:HOME/.config/Code/User/settings.json" }
    }
    
    $settingsDir = Split-Path $settingsPath -Parent
    if (-not (Test-Path $settingsDir)) {
        New-Item -ItemType Directory -Path $settingsDir -Force | Out-Null
    }
    
    # Create or update settings.json
    $settings = @{}
    if (Test-Path $settingsPath) {
        try {
            $existingContent = Get-Content $settingsPath -Raw
            if ($existingContent.Trim()) {
                $settings = $existingContent | ConvertFrom-Json -AsHashtable
            }
        }
        catch {
            Write-ColorOutput "Could not parse existing VS Code settings, creating backup..." "Warning"
            Copy-Item $settingsPath "$settingsPath.backup" -Force
            $settings = @{}
        }
    }
    
    # Determine path separator for VS Code
    $pathSeparator = if ($osType -eq "Windows") { ";" } else { ":" }
    
    # Add Docker PATH to terminal settings
    $osKey = switch ($osType) {
        "Windows" { "windows" }
        "macOS" { "osx" }
        "Linux" { "linux" }
    }
    
    # Update terminal integrated profiles
    if (-not $settings.ContainsKey("terminal.integrated.profiles.$osKey")) {
        $settings["terminal.integrated.profiles.$osKey"] = @{}
    }
    
    $terminalProfiles = $settings["terminal.integrated.profiles.$osKey"]
    
    # Configure profiles based on OS
    switch ($osType) {
        "Windows" {
            $terminalProfiles["PowerShell"] = @{
                "source" = "PowerShell"
                "env" = @{
                    "PATH" = "$dockerBinDir$pathSeparator`${env:PATH}"
                }
            }
            $terminalProfiles["Command Prompt"] = @{
                "path" = @("${env:windir}\System32\cmd.exe")
                "env" = @{
                    "PATH" = "$dockerBinDir$pathSeparator`${env:PATH}"
                }
            }
        }
        default {
            $terminalProfiles["bash"] = @{
                "path" = "/bin/bash"
                "args" = @("-l")
                "env" = @{
                    "PATH" = "$dockerBinDir$pathSeparator`${env:PATH}"
                }
            }
            $terminalProfiles["zsh"] = @{
                "path" = "/bin/zsh"
                "args" = @("-l")
                "env" = @{
                    "PATH" = "$dockerBinDir$pathSeparator`${env:PATH}"
                }
            }
            if (Get-Command pwsh -ErrorAction SilentlyContinue) {
                $pwshPath = (Get-Command pwsh).Source
                $terminalProfiles["pwsh"] = @{
                    "path" = $pwshPath
                    "env" = @{
                        "PATH" = "$dockerBinDir$pathSeparator`${env:PATH}"
                    }
                }
            }
        }
    }
    
    # Update global terminal environment
    $settings["terminal.integrated.env.$osKey"] = @{
        "PATH" = "$dockerBinDir$pathSeparator`${env:PATH}"
    }
    
    # Save settings
    try {
        $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath -Force
        Write-ColorOutput "Updated VS Code settings at $settingsPath" "Success"
    }
    catch {
        Write-ColorOutput "Failed to update VS Code settings: $($_.Exception.Message)" "Error"
        return $false
    }
    
    return $true
}

function Test-DockerEnvironments {
    Write-ColorOutput "Testing Docker availability in different environments..." "Info"
    $osType = Get-OSType
    
    Write-Host ""
    Write-ColorOutput "=== Testing Current PowerShell Session ===" "Info"
    try {
        $version = docker --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-ColorOutput "Docker works in current PowerShell session: $version" "Success"
        } else {
            Write-ColorOutput "Docker not available in current PowerShell session" "Error"
        }
    }
    catch {
        Write-ColorOutput "Docker not available in current PowerShell session" "Error"
    }
    
    if ($osType -ne "Windows") {
        Write-Host ""
        Write-ColorOutput "=== Testing Bash Environment ===" "Info"
        try {
            $result = bash -l -c "docker --version" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-ColorOutput "Docker works in bash: $result" "Success"
            } else {
                Write-ColorOutput "Docker not available in bash" "Error"
            }
        }
        catch {
            Write-ColorOutput "Docker not available in bash" "Error"
        }
        
        Write-Host ""
        Write-ColorOutput "=== Testing Zsh Environment ===" "Info"
        try {
            $result = zsh -l -c "docker --version" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-ColorOutput "Docker works in zsh: $result" "Success"
            } else {
                Write-ColorOutput "Docker not available in zsh" "Error"
            }
        }
        catch {
            Write-ColorOutput "Docker not available in zsh" "Error"
        }
    }
    
    Write-Host ""
    Write-ColorOutput "=== Testing PowerShell (No Profile) ===" "Info"
    try {
        $result = pwsh -NoProfile -Command "docker --version" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-ColorOutput "Docker works in PowerShell (no profile): $result" "Success"
        } else {
            Write-ColorOutput "Docker not available in PowerShell (no profile)" "Error"
        }
    }
    catch {
        Write-ColorOutput "Docker not available in PowerShell (no profile)" "Error"
    }
    
    Write-Host ""
    Write-ColorOutput "=== Testing PowerShell (With Profile) ===" "Info"
    try {
        $result = pwsh -Command "docker --version" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-ColorOutput "Docker works in PowerShell (with profile): $result" "Success"
        } else {
            Write-ColorOutput "Docker not available in PowerShell (with profile)" "Error"
        }
    }
    catch {
        Write-ColorOutput "Docker not available in PowerShell (with profile)" "Error"
    }
}

function Install-PowerShellIfNeeded {
    $osType = Get-OSType
    
    if ($osType -eq "Windows") {
        # Windows usually has PowerShell built-in
        return $true
    }
    
    if (-not (Get-Command pwsh -ErrorAction SilentlyContinue)) {
        Write-ColorOutput "PowerShell is not installed. Installing..." "Info"
        
        try {
            switch ($osType) {
                "macOS" {
                    if (Get-Command brew -ErrorAction SilentlyContinue) {
                        brew install --cask powershell
                        Write-ColorOutput "PowerShell installed via Homebrew" "Success"
                    } else {
                        Write-ColorOutput "Homebrew not available. Please install PowerShell manually" "Warning"
                        return $false
                    }
                }
                "Linux" {
                    Write-ColorOutput "Please install PowerShell manually for your Linux distribution" "Warning"
                    Write-ColorOutput "Visit: https://docs.microsoft.com/en-us/powershell/scripting/install/installing-powershell-core-on-linux" "Info"
                    return $false
                }
            }
        }
        catch {
            Write-ColorOutput "Failed to install PowerShell: $($_.Exception.Message)" "Error"
            return $false
        }
    } else {
        Write-ColorOutput "PowerShell is already installed" "Success"
    }
    
    return $true
}

function Show-Summary {
    $osType = Get-OSType
    
    Write-Host ""
    Write-ColorOutput "=== Docker Setup Summary ===" "Info"
    Write-Host ""
    
    Write-ColorOutput "Operating System: $osType" "Info"
    Write-ColorOutput "Docker Installed: $(if (Test-DockerInstalled) { 'Yes' } else { 'No' })" "Info"
    Write-ColorOutput "Docker Desktop Installed: $(if (Test-DockerDesktopInstalled) { 'Yes' } else { 'No' })" "Info"
    Write-ColorOutput "Docker Running: $(if (Test-DockerRunning) { 'Yes' } else { 'No' })" "Info"
    
    $dockerPath = Get-DockerPath
    if ($dockerPath) {
        Write-ColorOutput "Docker Path: $dockerPath" "Info"
    }
    
    Write-Host ""
    Write-ColorOutput "Next steps:" "Info"
    Write-Host "1. Restart VS Code to pick up new terminal settings"
    Write-Host "2. Ensure Docker Desktop is running before using Docker commands"
    Write-Host "3. Test Docker in VS Code terminals"
    
    if ($osType -ne "Windows") {
        Write-Host "4. Source your shell profile or restart terminal: source ~/.zshrc (or ~/.bash_profile)"
    }
    
    Write-Host ""
    Write-ColorOutput "To test Docker manually:" "Info"
    if ($osType -ne "Windows") {
        Write-Host "  - Bash/Zsh: docker --version"
    }
    Write-Host "  - PowerShell: Test-Docker"
    Write-Host "  - Current session: docker --version"
    Write-Host ""
}

# Main execution function
function Main {
    param($Arguments)
    
    Write-ColorOutput "Starting Docker setup automation for $(Get-OSType)..." "Info"
    Write-Host ""
    
    # If TestOnly flag is set, just run tests
    if ($TestOnly) {
        Test-DockerEnvironments
        Show-Summary
        return
    }
    
    # Check if Docker Desktop is installed
    if (-not (Test-DockerDesktopInstalled)) {
        if (-not $SkipInstall) {
            $response = Read-Host "Docker Desktop/Engine is not installed. Would you like to install it? (y/n)"
            if ($response -match '^[Yy]') {
                if (-not (Install-DockerDesktop)) {
                    Write-ColorOutput "Failed to install Docker. Exiting." "Error"
                    exit 1
                }
            } else {
                Write-ColorOutput "Docker is required. Exiting." "Error"
                exit 1
            }
        } else {
            Write-ColorOutput "Docker not installed and installation skipped" "Warning"
        }
    }
    
    # Check if Docker command is available
    if (-not (Test-DockerInstalled)) {
        Write-ColorOutput "Docker command not found. Please restart your terminal or check installation." "Error"
        exit 1
    }
    
    # Check if Docker daemon is running
    if (-not (Test-DockerRunning)) {
        $response = Read-Host "Docker daemon is not running. Would you like to start Docker Desktop? (y/n)"
        if ($response -match '^[Yy]') {
            if (-not (Start-DockerDesktop)) {
                Write-ColorOutput "Failed to start Docker. Please start it manually." "Warning"
            }
        } else {
            Write-ColorOutput "Docker daemon needs to be running for proper functionality" "Warning"
        }
    }
    
    # Install PowerShell if needed (non-Windows systems)
    Install-PowerShellIfNeeded
    
    # Update shell profiles and VS Code settings
    Update-ShellProfiles
    Update-PowerShellProfile
    Update-VSCodeSettings
    
    # Test Docker in different environments
    Test-DockerEnvironments
    
    # Show summary
    Show-Summary
    
    Write-ColorOutput "Docker setup automation completed!" "Success"
}

# Script entry point
if ($MyInvocation.InvocationName -ne '.') {
    Main $args
}
