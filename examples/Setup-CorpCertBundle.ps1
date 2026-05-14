<#
.SYNOPSIS
    Augments Python's certifi CA bundle with corporate root CAs from the Windows
    certificate store, then sets REQUESTS_CA_BUNDLE so az CLI, fab CLI, and any
    other Python tool that uses `requests` / `certifi` trusts the corporate proxy.

.DESCRIPTION
    Run this ONCE on a Windows machine that has corporate TLS interception
    (Norton, Zscaler, Palo Alto, etc.). It:

    1. Detects every root CA currently installed in the Windows trust store.
    2. Exports them all to PEM format.
    3. Locates the bundled certifi CA file used by your Python installation.
    4. Concatenates the Windows roots onto a copy of that bundle.
    5. Sets the REQUESTS_CA_BUNDLE environment variable (per-user, permanent via
       setx) to point at the augmented bundle.
    6. Tests that az CLI now works against a Microsoft endpoint.

    After this completes, restart your shell and az / fab / pip / requests-based
    tooling will trust the corporate proxy's intercepting root CA, the same way
    your browser already does.

.NOTES
    Required: Python with certifi installed (any version; certifi ships with pip).
              Windows PowerShell 5.1 or pwsh 7. Run from any shell.
    Effect:   Per-user environment variable. No admin rights needed.
    Reverse:  Set REQUESTS_CA_BUNDLE to empty or delete it from User env vars
              (System Properties → Environment Variables).

.EXAMPLE
    powershell -File .\Setup-CorpCertBundle.ps1
    powershell -File .\Setup-CorpCertBundle.ps1 -BundlePath "C:\certs\corp-cacert.pem"

.LINK
    See plugin README "Corporate environment setup" section for context.
    See _Documentation/plugin_learnings.md N12 for the root-cause explanation.
#>

param(
    # Where to write the augmented CA bundle. Default is in the user profile.
    [string]$BundlePath = "$env:USERPROFILE\corp-augmented-cacert.pem",

    # Python executable to use for locating certifi. Default: first python on PATH.
    [string]$PythonExe = "python",

    # Skip the post-install test (useful in environments where az isn't installed).
    [switch]$SkipTest
)

$ErrorActionPreference = "Stop"

Write-Host "`n=== Corporate cert bundle setup ===" -ForegroundColor Cyan
Write-Host "Bundle will be written to: $BundlePath" -ForegroundColor DarkGray

# --- Step 1: Verify Python + certifi ---
Write-Host "`n--- Step 1: locate certifi bundle ---" -ForegroundColor Cyan
try {
    $certifiPath = & $PythonExe -c "import certifi; print(certifi.where())" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $certifiPath) {
        throw "python returned no certifi path"
    }
}
catch {
    Write-Host "ERROR: Could not import certifi via '$PythonExe'." -ForegroundColor Red
    Write-Host "Either Python is not on PATH or certifi is not installed. Install with:" -ForegroundColor Yellow
    Write-Host "  pip install certifi" -ForegroundColor DarkYellow
    Write-Host "Or pass a different Python via -PythonExe (e.g. -PythonExe py)." -ForegroundColor Yellow
    exit 1
}
$certifiPath = $certifiPath.Trim()
if (-not (Test-Path $certifiPath)) {
    Write-Host "ERROR: certifi reported '$certifiPath' but file does not exist." -ForegroundColor Red
    exit 1
}
$certifiSize = (Get-Item $certifiPath).Length
Write-Host "Found certifi bundle: $certifiPath  ($([math]::Round($certifiSize / 1KB, 1)) KB)" -ForegroundColor Green

# --- Step 2: Export Windows trusted roots ---
Write-Host "`n--- Step 2: export Windows trusted roots ---" -ForegroundColor Cyan
$winRoots = Get-ChildItem -Path Cert:\LocalMachine\Root -ErrorAction SilentlyContinue
$currentUserRoots = Get-ChildItem -Path Cert:\CurrentUser\Root -ErrorAction SilentlyContinue
$allRoots = @($winRoots) + @($currentUserRoots)
$allRoots = $allRoots | Sort-Object Thumbprint -Unique

if (-not $allRoots -or $allRoots.Count -eq 0) {
    Write-Host "ERROR: No root CAs found in Windows certificate store." -ForegroundColor Red
    exit 1
}
Write-Host "Found $($allRoots.Count) unique root CA(s) in Windows store." -ForegroundColor Green

# Identify likely interceptor roots so we can call them out
$interceptorPatterns = @(
    "Norton",
    "Symantec Endpoint",
    "Zscaler",
    "Palo Alto",
    "Forcepoint",
    "Sophos",
    "NetSkope",
    "Check Point",
    "Cisco Umbrella",
    "BlueCoat",
    "Fortinet",
    "Trend Micro",
    "ESET",
    "Avast",
    "AVG",
    "BitDefender",
    "Kaspersky",
    "McAfee Web Gateway"
)
$detected = @()
foreach ($cert in $allRoots) {
    foreach ($p in $interceptorPatterns) {
        if ($cert.Subject -match $p -or $cert.Issuer -match $p) {
            $detected += $cert.Subject
            break
        }
    }
}
if ($detected.Count -gt 0) {
    Write-Host "TLS interceptor root(s) detected — these are exactly what need to be trusted by Python:" -ForegroundColor Yellow
    foreach ($d in $detected | Select-Object -Unique) {
        Write-Host "  $d" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "No obvious TLS-interceptor patterns detected. This machine may not need this fix, but it's safe to apply." -ForegroundColor DarkGray
}

# --- Step 3: Build the augmented bundle ---
Write-Host "`n--- Step 3: build augmented bundle ---" -ForegroundColor Cyan
$bundleDir = Split-Path -Parent $BundlePath
if ($bundleDir -and -not (Test-Path $bundleDir)) {
    New-Item -ItemType Directory -Path $bundleDir -Force | Out-Null
}
Copy-Item -Path $certifiPath -Destination $BundlePath -Force
$exportedCount = 0
foreach ($cert in $allRoots) {
    try {
        $pemBody = [Convert]::ToBase64String($cert.RawData, [Base64FormattingOptions]::InsertLineBreaks)
        $pemBlock = "`n# Subject: $($cert.Subject)`n# Issuer:  $($cert.Issuer)`n# Thumbprint: $($cert.Thumbprint)`n-----BEGIN CERTIFICATE-----`n$pemBody`n-----END CERTIFICATE-----`n"
        Add-Content -Path $BundlePath -Value $pemBlock -Encoding ASCII
        $exportedCount++
    }
    catch {
        Write-Host "  Warning: could not export $($cert.Subject): $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}
Write-Host "Wrote $exportedCount certificate(s) into augmented bundle: $BundlePath" -ForegroundColor Green
$newSize = (Get-Item $BundlePath).Length
Write-Host "Augmented bundle size: $([math]::Round($newSize / 1KB, 1)) KB (was $([math]::Round($certifiSize / 1KB, 1)) KB)" -ForegroundColor DarkGray

# --- Step 4: Set REQUESTS_CA_BUNDLE env var (per-user, permanent) ---
Write-Host "`n--- Step 4: set REQUESTS_CA_BUNDLE env var ---" -ForegroundColor Cyan
[Environment]::SetEnvironmentVariable("REQUESTS_CA_BUNDLE", $BundlePath, "User")
[Environment]::SetEnvironmentVariable("CURL_CA_BUNDLE", $BundlePath, "User")
# Also set for the current process so the post-install test below sees them.
$env:REQUESTS_CA_BUNDLE = $BundlePath
$env:CURL_CA_BUNDLE = $BundlePath
Write-Host "Set REQUESTS_CA_BUNDLE = $BundlePath  (User scope, persists across reboots)" -ForegroundColor Green
Write-Host "Set CURL_CA_BUNDLE     = $BundlePath" -ForegroundColor Green

# --- Step 5: Optional post-install test ---
if (-not $SkipTest) {
    Write-Host "`n--- Step 5: verify with a Microsoft HTTPS probe ---" -ForegroundColor Cyan
    $azExe = Get-Command az -ErrorAction SilentlyContinue
    if ($azExe) {
        Write-Host "Testing: az login --use-device-code --tenant <your-tenant>" -ForegroundColor DarkGray
        Write-Host "(Skipping the actual login. Run `az login --use-device-code` yourself to confirm.)" -ForegroundColor DarkGray
        Write-Host "If az CLI worked here previously and now still fails with cert errors, the bundle may be missing your specific interceptor's root." -ForegroundColor DarkGray
    } else {
        Write-Host "(az CLI not found on PATH; skipping az probe. Install az CLI to use Stages 10-12.)" -ForegroundColor DarkGray
    }

    Write-Host "`nDirect Python requests probe to https://api.fabric.microsoft.com/ ..." -ForegroundColor DarkGray
    $probeCmd = @"
import os, sys
try:
    import requests
except ImportError:
    print('requests not installed; pip install requests', file=sys.stderr)
    sys.exit(2)
try:
    r = requests.head('https://api.fabric.microsoft.com/', timeout=10)
    print(f'HTTP {r.status_code}')
    sys.exit(0)
except requests.exceptions.SSLError as e:
    print(f'SSL ERROR: {e}', file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f'OTHER ERROR: {e}', file=sys.stderr)
    sys.exit(3)
"@
    $tmpProbe = Join-Path $env:TEMP "tls-probe-$([guid]::NewGuid().ToString('N').Substring(0,8)).py"
    Set-Content -Path $tmpProbe -Value $probeCmd -Encoding UTF8
    $probeOutput = & $PythonExe $tmpProbe 2>&1
    $probeExit = $LASTEXITCODE
    Remove-Item $tmpProbe -Force -ErrorAction SilentlyContinue

    switch ($probeExit) {
        0 {
            Write-Host "SUCCESS: Python + requests can now reach api.fabric.microsoft.com via TLS." -ForegroundColor Green
            Write-Host "Response: $probeOutput" -ForegroundColor DarkGray
        }
        1 {
            Write-Host "FAIL: SSL error persists after augmenting the bundle." -ForegroundColor Red
            Write-Host $probeOutput -ForegroundColor Red
            Write-Host "Your interceptor's root may not be in the Windows store. Add it manually." -ForegroundColor Yellow
        }
        2 {
            Write-Host "SKIP: requests package not installed in this Python." -ForegroundColor Yellow
            Write-Host "Install with: pip install requests   (then re-run this script with -SkipTest:`$false)" -ForegroundColor DarkYellow
        }
        default {
            Write-Host "UNEXPECTED: probe returned exit $probeExit" -ForegroundColor Yellow
            Write-Host $probeOutput -ForegroundColor DarkGray
        }
    }
}

# --- Final reminder ---
Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host "REQUESTS_CA_BUNDLE is set at User scope. Existing shells will NOT pick this up automatically." -ForegroundColor Yellow
Write-Host "Close and reopen your terminal (and Claude Code, if running) before running az / fab / pip." -ForegroundColor Yellow
Write-Host ""
Write-Host "To verify after restart:" -ForegroundColor DarkGray
Write-Host '  echo $env:REQUESTS_CA_BUNDLE   # PowerShell' -ForegroundColor DarkGray
Write-Host '  echo %REQUESTS_CA_BUNDLE%      # cmd.exe' -ForegroundColor DarkGray
Write-Host ""
Write-Host "To revert (rare):" -ForegroundColor DarkGray
Write-Host '  [Environment]::SetEnvironmentVariable("REQUESTS_CA_BUNDLE", $null, "User")' -ForegroundColor DarkGray
