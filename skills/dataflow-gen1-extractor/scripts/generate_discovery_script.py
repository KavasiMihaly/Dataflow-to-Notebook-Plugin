"""
Generate a PowerShell script that discovers ALL Dataflow Gen1 across every workspace
the authenticated user can see. Use this BEFORE you know which workspace to migrate.

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
    Connects to Power BI Service using interactive browser authentication,
    enumerates every workspace in the chosen scope, lists Gen1 dataflows in
    each, and writes a CSV inventory. Run this BEFORE exporting a specific
    workspace — use the CSV to pick which workspace(s) to migrate.

.NOTES
    Requires: MicrosoftPowerBIMgmt PowerShell module
    Auth:     Interactive browser login (Connect-PowerBIServiceAccount)
    Run manually — requires user interaction for auth.

.EXAMPLE
    .\Discover-AllDataflows.ps1
    .\Discover-AllDataflows.ps1 -Scope Organization        # admin-only
    .\Discover-AllDataflows.ps1 -CsvOutput "C:\inventory.csv"
    .\Discover-AllDataflows.ps1 -UseDeviceCode             # fallback if browser does not open
#>

param(
    [ValidateSet("Individual", "Organization")]
    [string]$Scope = "{scope}",

    [string]$CsvOutput = "{csv_output}",

    [switch]$UseDeviceCode
)

# --- Resolve CSV output path (relative to script dir if not rooted) ---
if (-not [System.IO.Path]::IsPathRooted($CsvOutput)) {{
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $CsvOutput = Join-Path $ScriptDir $CsvOutput
}}

# --- Ensure parent directory exists ---
$CsvDir = Split-Path -Parent $CsvOutput
if ($CsvDir -and -not (Test-Path $CsvDir)) {{
    New-Item -ItemType Directory -Path $CsvDir -Force | Out-Null
}}

# --- Check for MicrosoftPowerBIMgmt module ---
if (-not (Get-Module -ListAvailable -Name MicrosoftPowerBIMgmt)) {{
    Write-Host "ERROR: MicrosoftPowerBIMgmt module is not installed." -ForegroundColor Red
    Write-Host "Install it with: Install-Module -Name MicrosoftPowerBIMgmt -Scope CurrentUser" -ForegroundColor Yellow
    exit 1
}}

# --- Connect to Power BI Service ---
Write-Host "`n=== Connecting to Power BI Service ===" -ForegroundColor Cyan
Write-Host "PowerShell edition: $($PSVersionTable.PSEdition)  version: $($PSVersionTable.PSVersion)" -ForegroundColor DarkGray

if ($UseDeviceCode) {{
    Write-Host "Using device code flow. A code + URL will print below — open the URL in any browser, enter the code, sign in." -ForegroundColor Yellow
}} else {{
    Write-Host "A browser window should open shortly." -ForegroundColor Yellow
    Write-Host "If it does NOT open within ~30 seconds (common in PowerShell 7 / pwsh -File / remote / VS Code terminals), press Ctrl+C and re-run with -UseDeviceCode:" -ForegroundColor Yellow
    Write-Host "  pwsh -File `"$PSCommandPath`" -UseDeviceCode" -ForegroundColor DarkYellow
    Write-Host "Or run in Windows PowerShell 5.1 instead of pwsh 7:" -ForegroundColor Yellow
    Write-Host "  powershell -File `"$PSCommandPath`"" -ForegroundColor DarkYellow
}}

try {{
    if ($UseDeviceCode) {{
        Connect-PowerBIServiceAccount -DeviceCode -ErrorAction Stop | Out-Null
    }} else {{
        Connect-PowerBIServiceAccount -ErrorAction Stop | Out-Null
    }}
    Write-Host "Connected successfully." -ForegroundColor Green
}}
catch {{
    Write-Host "ERROR: Failed to connect to Power BI Service." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    if (-not $UseDeviceCode) {{
        Write-Host "`nTry the device code flow instead:" -ForegroundColor Yellow
        Write-Host "  pwsh -File `"$PSCommandPath`" -UseDeviceCode" -ForegroundColor DarkYellow
    }}
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
        Write-Host " [skip — no access or no dataflows endpoint]" -ForegroundColor DarkGray
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
            workspace_name   = $Ws.Name
            workspace_id     = $Ws.Id
            workspace_type   = if ($Ws.Type) {{ $Ws.Type }} else {{ "" }}
            workspace_capacity_id = if ($Ws.CapacityId) {{ $Ws.CapacityId }} else {{ "" }}
            dataflow_name    = $Df.name
            dataflow_id      = $Df.objectId
            modified_date    = if ($Df.modifiedDateTime) {{ $Df.modifiedDateTime }} else {{ "" }}
            configured_by    = if ($Df.configuredBy) {{ $Df.configuredBy }} else {{ "" }}
            description      = if ($Df.description) {{ $Df.description }} else {{ "" }}
        }}
    }}
}}

# --- Write CSV inventory ---
if ($Inventory.Count -eq 0) {{
    Write-Host "`nNo Gen1 dataflows found in any accessible workspace." -ForegroundColor Yellow
    Write-Host "Check that you have access to workspaces containing Gen1 dataflows." -ForegroundColor Yellow
    Disconnect-PowerBIServiceAccount -ErrorAction SilentlyContinue
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
Write-Host '  claude --agent fabric-dataflow-migration-toolkit:fabric-migration-orchestrator:fabric-migration-orchestrator "Migrate dataflows from workspace <GUID>"' -ForegroundColor Yellow

# --- Disconnect ---
Disconnect-PowerBIServiceAccount -ErrorAction SilentlyContinue
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

    output_path.write_text(script_content, encoding="utf-8")
    print(f"Generated: {output_path}")
    print(f"Default scope: {args.scope}")
    print(f"CSV output (relative to script): {args.csv_output}")
    print(f"\nNext: User runs the script in PowerShell (requires interactive auth).")
    print(f"  pwsh -File \"{output_path}\"")


if __name__ == "__main__":
    main()
