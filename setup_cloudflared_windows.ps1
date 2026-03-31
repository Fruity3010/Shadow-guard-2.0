#Requires -RunAsAdministrator
param(
    [Parameter(Mandatory = $true)]
    [string]$MachineName,

    [Parameter(Mandatory = $true)]
    [string]$HostnameSuffix,

    [string]$TunnelName = "",
    [string]$BaseDir = "",
    [string]$CloudflaredDir = "",
    [string]$CloudflaredExe = "",
    [string]$CloudflaredConfigDir = "",
    [int]$AgentPort = 5555,
    [switch]$InstallCloudflared,
    [switch]$CreateTunnel,
    [switch]$RouteDns,
    [switch]$InstallService
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step($message) {
    Write-Host "[ShadowGuard Cloudflare] $message" -ForegroundColor Cyan
}

function Resolve-CloudflaredExe {
    param([string]$CandidateExe, [string]$BaseDir)

    if ($CandidateExe -and (Test-Path $CandidateExe)) {
        return (Resolve-Path $CandidateExe).Path
    }

    $defaultExe = Join-Path $BaseDir "cloudflared.exe"
    if (Test-Path $defaultExe) {
        return (Resolve-Path $defaultExe).Path
    }

    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    return $null
}

function Install-CloudflaredIfNeeded {
    param([string]$CandidateExe, [string]$BaseDir)

    $resolved = Resolve-CloudflaredExe -CandidateExe $CandidateExe -BaseDir $BaseDir
    if ($resolved) {
        return $resolved
    }

    Write-Step "cloudflared was not found. Attempting automatic install."

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "cloudflared.exe was not found and winget is not available for automatic install."
    }

    Write-Step "Installing cloudflared with winget"
    $null = & $winget.Source install --id Cloudflare.cloudflared --exact --source winget --accept-package-agreements --accept-source-agreements --silent

    Start-Sleep -Seconds 3
    $resolved = Resolve-CloudflaredExe -CandidateExe $CandidateExe -BaseDir $BaseDir
    if ($resolved) {
        return $resolved
    }

    $programFilesMatch = "C:\Program Files\cloudflared\cloudflared.exe"
    if (Test-Path $programFilesMatch) {
        return (Resolve-Path $programFilesMatch).Path
    }

    $programFilesX86Match = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if (Test-Path $programFilesX86Match) {
        return (Resolve-Path $programFilesX86Match).Path
    }

    $wingetPackagesRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $wingetPackagesRoot) {
        $match = Get-ChildItem -Path $wingetPackagesRoot -Recurse -Filter "cloudflared.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($match) {
            return $match.FullName
        }
    }

    Ensure-Directory -PathValue $BaseDir
    $downloadPath = Join-Path $BaseDir "cloudflared.exe"
    $downloadUrl = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") {
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-arm64.exe"
    } else {
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    }

    Write-Step "winget completed but cloudflared.exe was not discoverable. Falling back to direct download."
    $null = Invoke-WebRequest -Uri $downloadUrl -OutFile $downloadPath
    return (Resolve-Path $downloadPath).Path
}

function Ensure-Directory {
    param([string]$PathValue)
    if (-not (Test-Path $PathValue)) {
        New-Item -ItemType Directory -Path $PathValue -Force | Out-Null
    }
}

function Get-BaseDirectory {
    param([string]$ConfiguredDir)

    $candidate = if ($ConfiguredDir) {
        $ConfiguredDir
    } elseif ($env:SHADOWGUARD_BASE_DIR) {
        $env:SHADOWGUARD_BASE_DIR
    } else {
        Join-Path $PSScriptRoot ".shadowguard"
    }

    Ensure-Directory -PathValue $candidate
    return (Resolve-Path $candidate).Path
}

function Get-ConfigDirectory {
    param([string]$ConfiguredDir, [string]$RuntimeBaseDir)
    if ($ConfiguredDir) {
        Ensure-Directory -PathValue $ConfiguredDir
        return (Resolve-Path $ConfiguredDir).Path
    }

    $defaultDir = Join-Path $RuntimeBaseDir "cloudflared"
    Ensure-Directory -PathValue $defaultDir
    return (Resolve-Path $defaultDir).Path
}

function Get-CredentialSearchDirectories {
    param([string]$PrimaryConfigDir)

    $directories = [System.Collections.Generic.List[string]]::new()
    $directories.Add($PrimaryConfigDir)

    $legacyDir = Join-Path $env:USERPROFILE ".cloudflared"
    if ($legacyDir -ne $PrimaryConfigDir -and (Test-Path $legacyDir)) {
        $directories.Add((Resolve-Path $legacyDir).Path)
    }

    return $directories
}

$resolvedBaseDir = Get-BaseDirectory -ConfiguredDir $BaseDir
$resolvedCloudflaredDir = if ($CloudflaredDir) { $CloudflaredDir } else { Join-Path $resolvedBaseDir "cloudflared\bin" }
Ensure-Directory -PathValue $resolvedCloudflaredDir
$env:SHADOWGUARD_BASE_DIR = $resolvedBaseDir
$resolvedTunnelName = if ($TunnelName) { $TunnelName } else { $MachineName }
$resolvedHostname = "$MachineName.$HostnameSuffix"
$resolvedExe = Install-CloudflaredIfNeeded -CandidateExe $CloudflaredExe -BaseDir $resolvedCloudflaredDir
$resolvedConfigDir = Get-ConfigDirectory -ConfiguredDir $CloudflaredConfigDir -RuntimeBaseDir $resolvedBaseDir

Write-Step "Using machine hostname $resolvedHostname"
Write-Step "Using tunnel name $resolvedTunnelName"
Write-Step "Using base directory $resolvedBaseDir"
Write-Step "Using cloudflared at $resolvedExe"
Write-Step "Using config directory $resolvedConfigDir"

if ($CreateTunnel) {
    Write-Step "Logging into Cloudflare. A browser window may open."
    & $resolvedExe tunnel login

    Write-Step "Creating named tunnel $resolvedTunnelName"
    & $resolvedExe tunnel create $resolvedTunnelName
}

$credFiles = @()
foreach ($directory in Get-CredentialSearchDirectories -PrimaryConfigDir $resolvedConfigDir) {
    $credFiles += @(Get-ChildItem -Path $directory -Filter "*.json" -ErrorAction SilentlyContinue)
}

if (-not $credFiles) {
    throw "No tunnel credential JSON file was found in $resolvedConfigDir. Run cloudflared tunnel login and cloudflared tunnel create first, or use -CreateTunnel."
}

$credentialFile = $null
if (@($credFiles).Count -eq 1) {
    $credentialFile = $credFiles[0].FullName
} else {
    $credentialFile = ($credFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
    Write-Step "Multiple tunnel credential files found. Using the newest one: $credentialFile"
}

if ((Split-Path -Parent $credentialFile) -ne $resolvedConfigDir) {
    $copiedCredentialFile = Join-Path $resolvedConfigDir (Split-Path -Leaf $credentialFile)
    Copy-Item -Path $credentialFile -Destination $copiedCredentialFile -Force
    $credentialFile = (Resolve-Path $copiedCredentialFile).Path
    Write-Step "Copied tunnel credentials into $resolvedConfigDir"
}

$tunnelId = [System.IO.Path]::GetFileNameWithoutExtension($credentialFile)
$configPath = Join-Path $resolvedConfigDir "config.yml"
$yaml = @"
tunnel: $tunnelId
credentials-file: $credentialFile

ingress:
  - hostname: $resolvedHostname
    service: http://127.0.0.1:$AgentPort
  - service: http_status:404
"@

Set-Content -Path $configPath -Value $yaml -Encoding ASCII
Write-Step "Wrote config to $configPath"

if ($RouteDns) {
    Write-Step "Creating Cloudflare DNS route for $resolvedHostname"
    & $resolvedExe tunnel route dns $resolvedTunnelName $resolvedHostname
}

if ($InstallService) {
    Write-Step "Installing cloudflared as a Windows service"
    Push-Location (Split-Path -Parent $resolvedExe)
    try {
        & $resolvedExe service install
    } finally {
        Pop-Location
    }

    Start-Sleep -Seconds 2
    Start-Service cloudflared -ErrorAction SilentlyContinue
    Write-Step "cloudflared service installed. If it was already installed, restart it after config changes."
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Machine hostname: https://$resolvedHostname" -ForegroundColor Green
Write-Host "Tunnel config: $configPath" -ForegroundColor Green
Write-Host "Credential file: $credentialFile" -ForegroundColor Green
Write-Host ""
Write-Host "Suggested cloud admin settings:" -ForegroundColor Yellow
Write-Host "  SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE=https://{machine}.$HostnameSuffix"
Write-Host "  SHADOWGUARD_DEFAULT_MACHINE=$MachineName"
