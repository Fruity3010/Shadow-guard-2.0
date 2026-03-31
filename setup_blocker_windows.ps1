#Requires -RunAsAdministrator
# setup_blocker_windows.ps1 - Shadow IT Control Platform (Windows)

# Allow running local scripts for this session
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process -Force

Write-Host "Shadow IT Control Platform" -ForegroundColor Cyan
Write-Host "==========================" -ForegroundColor Cyan
Write-Host "Starting website blocker..." -ForegroundColor Yellow

# ---- Variables ----
$PORT = 8888
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BASE_DIR = if ($env:SHADOWGUARD_BASE_DIR) { $env:SHADOWGUARD_BASE_DIR } else { Join-Path $SCRIPT_DIR ".shadowguard" }
$BLOCKED_HTML = Join-Path $SCRIPT_DIR "templates\blocked.html"
$VENV_DIR = Join-Path $SCRIPT_DIR ".venv"
$CERT_DIR = Join-Path $BASE_DIR "mitmproxy"
$CERT_PATH = Join-Path $CERT_DIR "mitmproxy-ca-cert.pem"
$LOG_DIR = Join-Path $BASE_DIR "logs"
$DASHBOARD_LOG = Join-Path $LOG_DIR "dashboard.log"
$DASHBOARD_ERR_LOG = Join-Path $LOG_DIR "dashboard_err.log"
$PROXY_REG_PATH = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"

$PYTHON = Join-Path $VENV_DIR "Scripts\python.exe"
$PIP = Join-Path $VENV_DIR "Scripts\pip.exe"
$MITMDUMP = Join-Path $VENV_DIR "Scripts\mitmdump.exe"
$DASHBOARD_SCRIPT = Join-Path $SCRIPT_DIR "dashboard.py"

foreach ($dir in @($BASE_DIR, $CERT_DIR, $LOG_DIR)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

$env:SHADOWGUARD_BASE_DIR = $BASE_DIR

# Check templates
if (-not (Test-Path $BLOCKED_HTML)) {
    Write-Host "WARNING: blocked.html not found at $BLOCKED_HTML" -ForegroundColor Yellow
    Write-Host "WARNING: Using default blocking page" -ForegroundColor Yellow
}

# ---- Load WinINet for proxy refresh ----
$signature = @"
[DllImport("wininet.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern bool InternetSetOption(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int dwBufferLength);
"@
$wininet = Add-Type -MemberDefinition $signature -Name "WinINet" -Namespace "PInvoke" -PassThru

function Refresh-ProxySettings {
    # Signals all running WinINet-based apps (Edge, Chrome, etc.) to reload proxy settings immediately
    $wininet::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) | Out-Null  # INTERNET_OPTION_SETTINGS_CHANGED
    $wininet::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) | Out-Null  # INTERNET_OPTION_REFRESH
}

# ---- Cleanup function ----
function Invoke-Cleanup {
    Write-Host "`nCleaning up..." -ForegroundColor Yellow

    # Disable system proxy
    Set-ItemProperty -Path $PROXY_REG_PATH -Name "ProxyEnable" -Value 0 -Type DWord
    Refresh-ProxySettings
    Write-Host "System proxy disabled." -ForegroundColor Green

    # Stop mitmdump
    Get-Process -Name "mitmdump" -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "mitmdump stopped." -ForegroundColor Green

    # Stop dashboard
    if ($null -ne $script:dashboardProcess -and -not $script:dashboardProcess.HasExited) {
        Write-Host "Stopping dashboard..." -ForegroundColor Yellow
        $script:dashboardProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Cleanup complete. Proxy and dashboard disabled!" -ForegroundColor Green
}

# ---- Kill existing mitmdump processes ----
Write-Host "Stopping any existing mitmdump processes..." -ForegroundColor Yellow
Get-Process -Name "mitmdump" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

# ---- Virtual environment setup ----
Write-Host "Setting up Python virtual environment..." -ForegroundColor Yellow

if (Test-Path $VENV_DIR) {
    Write-Host "Using existing virtual environment" -ForegroundColor Green
} else {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv $VENV_DIR
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create virtual environment. Is Python installed and in PATH?" -ForegroundColor Red
        exit 1
    }
}

# Activate venv
$ACTIVATE = Join-Path $VENV_DIR "Scripts\Activate.ps1"
& $ACTIVATE

# Install dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
& $PIP install -r (Join-Path $SCRIPT_DIR "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install failed." -ForegroundColor Red
    exit 1
}

# ---- Start dashboard in background ----
Write-Host "Starting dashboard server..." -ForegroundColor Yellow
$script:dashboardProcess = Start-Process `
    -FilePath $PYTHON `
    -ArgumentList "-u `"$DASHBOARD_SCRIPT`"" `
    -RedirectStandardOutput $DASHBOARD_LOG `
    -RedirectStandardError $DASHBOARD_ERR_LOG `
    -WorkingDirectory $SCRIPT_DIR `
    -PassThru `
    -WindowStyle Hidden

Start-Sleep -Seconds 2

if (-not $script:dashboardProcess.HasExited) {
    Write-Host "Dashboard running at http://localhost:5555" -ForegroundColor Green
    Write-Host "Open http://localhost:5555 in your browser to view statistics" -ForegroundColor Cyan
} else {
    Write-Host "WARNING: Dashboard failed to start. Check $DASHBOARD_LOG" -ForegroundColor Yellow
}

# ---- Generate mitmproxy certificates ----
Write-Host "Setting up certificates..." -ForegroundColor Yellow
$certGenProcess = Start-Process `
    -FilePath $MITMDUMP `
    -ArgumentList "--listen-port", $PORT, "--set", "confdir=$CERT_DIR" `
    -PassThru `
    -WindowStyle Hidden

Start-Sleep -Seconds 3
$certGenProcess | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "Certificate generation complete." -ForegroundColor Green

# ---- Install certificate into Windows Root CA store ----
# NOTE: Windows 11 will show a UAC trust prompt — click Yes when asked
if (Test-Path $CERT_PATH) {
    Write-Host "Installing mitmproxy certificate into Windows Root CA store..." -ForegroundColor Yellow

    $certResult = & certutil -addstore -f "Root" $CERT_PATH 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Certificate installed successfully." -ForegroundColor Green
    } else {
        # Fallback to PowerShell Import-Certificate
        Write-Host "Trying Import-Certificate fallback..." -ForegroundColor Yellow
        try {
            Import-Certificate -FilePath $CERT_PATH -CertStoreLocation "Cert:\LocalMachine\Root" | Out-Null
            Write-Host "Certificate installed successfully." -ForegroundColor Green
        } catch {
            Write-Host "WARNING: Certificate installation failed: $_" -ForegroundColor Yellow
            Write-Host "HTTPS sites may show security warnings." -ForegroundColor Yellow
            Write-Host "NOTE: Firefox requires manual cert import via about:preferences#privacy" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "WARNING: Certificate not found at $CERT_PATH" -ForegroundColor Yellow
    Write-Host "HTTPS sites may show security warnings." -ForegroundColor Yellow
}

# ---- Configure system proxy ----
Write-Host "Configuring Windows system proxy..." -ForegroundColor Yellow
Set-ItemProperty -Path $PROXY_REG_PATH -Name "ProxyEnable" -Value 1 -Type DWord
Set-ItemProperty -Path $PROXY_REG_PATH -Name "ProxyServer" -Value "127.0.0.1:$PORT" -Type String
# Bypass proxy for localhost so the dashboard at http://localhost:5555 stays accessible
Set-ItemProperty -Path $PROXY_REG_PATH -Name "ProxyOverride" -Value "localhost;127.0.0.1;<local>" -Type String
Refresh-ProxySettings
Write-Host "System proxy set to 127.0.0.1:$PORT" -ForegroundColor Green

# ---- Feature display ----
Write-Host ""
Write-Host "Ready!" -ForegroundColor Green
Write-Host "Features Active:" -ForegroundColor Cyan
Write-Host "  - Local machine agent API for remote policy control"
Write-Host "  - Method-specific blocking (GET, POST, etc.)"
Write-Host "  - Real-time statistics and monitoring"
Write-Host "Dashboard:   http://localhost:5555"
Write-Host "Machine API: http://localhost:5555/agent/blocked-sites"
Write-Host "Remote admin is hosted separately and should call this machine agent."
Write-Host "WARNING: Firefox requires manual cert import - see about:preferences#privacy" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop"
Write-Host "----------------------------------------"

# ---- Run proxy (try/finally ensures cleanup on Ctrl+C and normal exit) ----
try {
    & $MITMDUMP -s (Join-Path $SCRIPT_DIR "simple_blocker.py") --listen-port $PORT --set confdir=$CERT_DIR
} finally {
    Invoke-Cleanup
}
