"""
Generate a PowerShell script that discovers ALL Dataflow Gen1 across every workspace
the authenticated user can see. Use this BEFORE you know which workspace to migrate.

Auth model: uses the `MicrosoftPowerBIMgmt` module's `Connect-PowerBIServiceAccount`.
The script is designed to be run under **Windows PowerShell 5.1** (the
`powershell.exe` host), which uses an in-process WebBrowser COM control for the
OAuth dialog. That code path is more reliable than PowerShell 7's MSAL-based
external-browser launch -- particularly in environments with corporate TLS
interception (Norton, Zscaler, Palo Alto) where the system cert store trusts the
interceptor's root CA but Python-based tools like `az` CLI do not.

Usage:
    python generate_discovery_script.py --output "path/to/Discover-AllDataflows.ps1"
    python generate_discovery_script.py --output "Discover-AllDataflows.ps1" --csv-output "gen1-inventory.csv" --scope Organization
"""

import argparse
import sys
from pathlib import Path

TEMPLATE = r'''<#
.SYNOPSIS
    Discovers all Dataflow Gen1 across every Power BI workspace you can see.

.DESCRIPTION
    Authenticates via Connect-PowerBIServiceAccount (MicrosoftPowerBIMgmt module),
    enumerates workspaces at the chosen scope, lists Gen1 dataflows in each, and
    writes a CSV inventory.

.NOTES
    Run this in Windows PowerShell 5.1 (`powershell.exe -File ...`), NOT pwsh 7.
    PowerShell 5.1 uses an in-process WebBrowser COM control for OAuth that
    works in environments where pwsh 7's external browser launch silently
    hangs (common in pwsh -File / VS Code terminal / remote sessions / corporate
    networks with TLS interception).

    Requires: MicrosoftPowerBIMgmt PowerShell module
              (Install-Module -Name MicrosoftPowerBIMgmt -Scope CurrentUser)
    Auth:     Interactive browser via WebBrowser COM (PS 5.1) or system browser
              (pwsh 7 -- may fail to launch).

.EXAMPLE
    # Recommended invocation (Windows PowerShell 5.1):
    powershell -File .\Discover-AllDataflows.ps1
    powershell -File .\Discover-AllDataflows.ps1 -Scope Organization        # admin-only
    powershell -File .\Discover-AllDataflows.ps1 -CsvOutput "C:\inventory.csv"
#>

param(
    [ValidateSet("Individual", "Organization")]
    [string]$Scope = "{scope}",

    [string]$CsvOutput = "{csv_output}"
)

# --- Resolve CSV output path (relative to script dir if not rooted) ---
if (-not [System.IO.Path]::IsPathRooted($CsvOutput)) {{
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $CsvOutput = Join-Path $ScriptDir $CsvOutput
}}
$CsvDir = Split-Path -Parent $CsvOutput
if ($CsvDir -and -not (Test-Path $CsvDir)) {{
    New-Item -ItemType Directory -Path $CsvDir -Force | Out-Null
}}

Write-Host "PowerShell edition: $($PSVersionTable.PSEdition)  version: $($PSVersionTable.PSVersion)" -ForegroundColor DarkGray

# --- Warn if running under pwsh 7 (more likely to hit browser-launch issues) ---
if ($PSVersionTable.PSEdition -eq "Core") {{
    Write-Host "`n=== WARNING: Running on PowerShell 7 (Core) ===" -ForegroundColor Yellow
    Write-Host "Connect-PowerBIServiceAccount in pwsh 7 launches the default browser via" -ForegroundColor Yellow
    Write-Host "Process.Start(), which can silently hang in pwsh -File contexts, VS Code" -ForegroundColor Yellow
    Write-Host "terminal, remote sessions, and some corporate-network setups." -ForegroundColor Yellow
    Write-Host "" -ForegroundColor Yellow
    Write-Host "If this script hangs at the 'Connecting...' step or no browser opens within" -ForegroundColor Yellow
    Write-Host "~30 seconds, press Ctrl+C and re-run under Windows PowerShell 5.1:" -ForegroundColor Yellow
    Write-Host "  powershell -File `"$PSCommandPath`"" -ForegroundColor DarkYellow
    Write-Host "PS 5.1 uses an in-process COM-hosted auth dialog that works reliably." -ForegroundColor Yellow
}}

# --- Check for MicrosoftPowerBIMgmt module ---
if (-not (Get-Module -ListAvailable -Name MicrosoftPowerBIMgmt)) {{
    Write-Host "ERROR: MicrosoftPowerBIMgmt module is not installed." -ForegroundColor Red
    Write-Host "Install it with: Install-Module -Name MicrosoftPowerBIMgmt -Scope CurrentUser" -ForegroundColor Yellow
    exit 1
}}

# --- Connect to Power BI Service ---
Write-Host "`n=== Connecting to Power BI Service ===" -ForegroundColor Cyan
Write-Host "A browser auth dialog should appear. If it does not, see the WARNING above." -ForegroundColor Yellow
try {{
    Connect-PowerBIServiceAccount -ErrorAction Stop | Out-Null
    Write-Host "Connected successfully." -ForegroundColor Green
}}
catch {{
    Write-Host "ERROR: Failed to connect to Power BI Service." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "`nIf the browser did not open or this hangs, re-run under Windows PowerShell 5.1:" -ForegroundColor Yellow
    Write-Host "  powershell -File `"$PSCommandPath`"" -ForegroundColor DarkYellow
    exit 1
}}

# --- Enumerate workspaces ---
Write-Host "`n=== Enumerating Workspaces (Scope: $Scope) ===" -ForegroundColor Cyan
if ($Scope -eq "Organization") {{
    Write-Host "Note: Organization scope requires Power BI admin rights." -ForegroundColor Yellow
}}

try {{
    $Workspaces = Get-PowerBIWorkspace -All -Scope $Scope -ErrorAction Stop
}}
catch {{
    Write-Host "ERROR: Failed to enumerate workspaces." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($Scope -eq "Organization") {{
        Write-Host "Try again with -Scope Individual if you're not a Power BI admin." -ForegroundColor Yellow
    }}
    exit 1
}}

# --- Filter out personal "My Workspace" and deleted/orphaned workspaces ---
$Workspaces = $Workspaces | Where-Object {{
    $_.Type -ne "PersonalGroup" -and -not $_.State -or $_.State -eq "Active"
}}
Write-Host "Found $($Workspaces.Count) accessible workspace(s)." -ForegroundColor Green

# --- For each workspace, list dataflows ---
Write-Host "`n=== Scanning workspaces for Gen1 dataflows ===" -ForegroundColor Cyan
$Inventory = @()
$WorkspaceCount = 0
$DataflowCount = 0
$SkippedCount = 0

foreach ($Ws in $Workspaces) {{
    $WorkspaceCount++
    Write-Host ("  [{{0,3}}/{{1}}] {{2}}" -f $WorkspaceCount, $Workspaces.Count, $Ws.Name) -NoNewline

    try {{
        $ApiUrl = "https://api.powerbi.com/v1.0/myorg/groups/$($Ws.Id)/dataflows"
        $Response = Invoke-PowerBIRestMethod -Url $ApiUrl -Method Get -ErrorAction Stop | ConvertFrom-Json
        $Dataflows = $Response.value
    }}
    catch {{
        Write-Host " [skip -- no access or no dataflows endpoint]" -ForegroundColor DarkGray
        $SkippedCount++
        continue
    }}

    if (-not $Dataflows -or $Dataflows.Count -eq 0) {{
        Write-Host " [0 dataflows]" -ForegroundColor DarkGray
        continue
    }}

    Write-Host " [$($Dataflows.Count) dataflow(s)]" -ForegroundColor Green
    foreach ($Df in $Dataflows) {{
        $DataflowCount++
        $Inventory += [PSCustomObject]@{{
            workspace_name        = $Ws.Name
            workspace_id          = $Ws.Id
            workspace_type        = if ($Ws.Type) {{ $Ws.Type }} else {{ "" }}
            workspace_capacity_id = if ($Ws.CapacityId) {{ $Ws.CapacityId }} else {{ "" }}
            dataflow_name         = $Df.name
            dataflow_id           = $Df.objectId
            modified_date         = if ($Df.modifiedDateTime) {{ $Df.modifiedDateTime }} else {{ "" }}
            configured_by         = if ($Df.configuredBy) {{ $Df.configuredBy }} else {{ "" }}
            description           = if ($Df.description) {{ $Df.description }} else {{ "" }}
        }}
    }}
}}

# --- Write CSV inventory ---
if ($Inventory.Count -eq 0) {{
    Write-Host "`nNo Gen1 dataflows found in any accessible workspace." -ForegroundColor Yellow
    Write-Host "Check that you have access to workspaces containing Gen1 dataflows." -ForegroundColor Yellow
    Disconnect-PowerBIServiceAccount -ErrorAction SilentlyContinue | Out-Null
    exit 0
}}

$Inventory | Export-Csv -Path $CsvOutput -NoTypeInformation -Encoding UTF8

# --- Summary ---
Write-Host "`n=== Discovery Summary ===" -ForegroundColor Cyan
Write-Host "Workspaces scanned: $WorkspaceCount"
if ($SkippedCount -gt 0) {{
    Write-Host "Workspaces skipped: $SkippedCount  (no access / no dataflows endpoint)" -ForegroundColor DarkGray
}}
Write-Host "Gen1 dataflows found: $DataflowCount" -ForegroundColor Green
Write-Host "Inventory written to: $CsvOutput" -ForegroundColor Green

# --- Console preview (workspace summary) ---
Write-Host "`n=== Workspace Summary ===" -ForegroundColor Cyan
$Inventory | Group-Object workspace_name | Sort-Object Count -Descending | ForEach-Object {{
    $WsRow = $_.Group | Select-Object -First 1
    "{{0,3}}  {{1,-40}}  {{2}}" -f $_.Count, $_.Name, $WsRow.workspace_id | Write-Host
}}

Write-Host "`nPick one or more workspace_id values from the CSV, then re-launch the orchestrator:"
Write-Host '  claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate dataflows from workspace YOUR-WORKSPACE-GUID"' -ForegroundColor Yellow

# --- Disconnect ---
Disconnect-PowerBIServiceAccount -ErrorAction SilentlyContinue | Out-Null
Write-Host "`nDone. Disconnected from Power BI Service." -ForegroundColor Green
'''


def main():
    parser = argparse.ArgumentParser(
        description="Generate PowerShell script to discover all Dataflow Gen1 across every accessible Power BI workspace"
    )
    parser.add_argument(
        "--output", required=True,
        help="Output path for the generated .ps1 script"
    )
    parser.add_argument(
        "--csv-output", default="gen1-dataflow-inventory.csv",
        help="Path inside the generated script where the CSV inventory will be written (default: gen1-dataflow-inventory.csv next to the .ps1)"
    )
    parser.add_argument(
        "--scope", choices=["Individual", "Organization"], default="Individual",
        help="Default workspace scope baked into the script. Individual = workspaces the user is a member of; Organization = all workspaces in the tenant (admin only). User can override via -Scope at runtime. (default: Individual)"
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    script_content = TEMPLATE.format(
        scope=args.scope,
        csv_output=args.csv_output.replace("\\", "\\\\"),
    )

    # Write with UTF-8 BOM so PowerShell 5.1 correctly recognizes UTF-8 encoding.
    # Without a BOM, PS 5.1 falls back to the OS code page (typically Windows-1252)
    # and misinterprets any multi-byte UTF-8 sequence -- e.g. an em-dash (U+2014)
    # becomes 3 chars including a right-double-quote that prematurely terminates
    # string literals, cascading into "missing terminator" parse errors.
    output_path.write_text(script_content, encoding="utf-8-sig")
    print(f"Generated: {output_path}")
    print(f"Default scope: {args.scope}")
    print(f"CSV output (relative to script): {args.csv_output}")
    print(f"\nNext: Run in Windows PowerShell 5.1 (NOT pwsh 7):")
    print(f"  powershell -File \"{output_path}\"")


if __name__ == "__main__":
    main()
