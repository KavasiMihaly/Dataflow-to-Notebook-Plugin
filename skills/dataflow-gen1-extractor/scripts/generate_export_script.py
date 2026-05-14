"""
Generate a PowerShell script to export all Dataflow Gen1 from a Power BI workspace.

Usage:
    python generate_export_script.py --workspace-id "GUID" --output "path/to/Export-AllDataflows.ps1"
    python generate_export_script.py --workspace-id "GUID" --output "script.ps1" --json-dir "path/to/json/output"
"""

import argparse
import sys
from pathlib import Path

TEMPLATE = r'''<#
.SYNOPSIS
    Exports all Dataflow Gen1 definitions from a Power BI workspace.

.DESCRIPTION
    Connects to Power BI Service using interactive browser authentication,
    lists all Gen1 dataflows in the target workspace, and exports each one
    as a JSON file. Also generates a dataflow_manifest.csv with metadata.

.NOTES
    Requires: MicrosoftPowerBIMgmt PowerShell module
    Auth: Interactive browser login (Connect-PowerBIServiceAccount)
    Run manually - requires user interaction for auth.

.EXAMPLE
    .\Export-AllDataflows.ps1
    .\Export-AllDataflows.ps1 -OutputDir "C:\exports"
    .\Export-AllDataflows.ps1 -UseDeviceCode             # fallback if browser does not open
#>

param(
    [string]$OutputDir = "{json_dir}",

    [switch]$UseDeviceCode
)

# --- Configuration ---
$WorkspaceId = "{workspace_id}"

# --- Resolve output directory ---
if (-not [System.IO.Path]::IsPathRooted($OutputDir)) {{
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $OutputDir = Join-Path $ScriptDir $OutputDir
}}
$ManifestFile = Join-Path $OutputDir "dataflow_manifest.csv"

# --- Ensure output directory exists ---
if (-not (Test-Path $OutputDir)) {{
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    Write-Host "Created output directory: $OutputDir" -ForegroundColor Green
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

# --- List all dataflows in workspace ---
Write-Host "`n=== Listing Dataflows in Workspace ===" -ForegroundColor Cyan
Write-Host "Workspace ID: $WorkspaceId"

try {{
    $ApiUrl = "https://api.powerbi.com/v1.0/myorg/groups/$WorkspaceId/dataflows"
    $Response = Invoke-PowerBIRestMethod -Url $ApiUrl -Method Get | ConvertFrom-Json
    $Dataflows = $Response.value
}}
catch {{
    Write-Host "ERROR: Failed to list dataflows." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Check that you have access to workspace $WorkspaceId" -ForegroundColor Yellow
    exit 1
}}

if (-not $Dataflows -or $Dataflows.Count -eq 0) {{
    Write-Host "No dataflows found in workspace." -ForegroundColor Yellow
    exit 0
}}

Write-Host "Found $($Dataflows.Count) dataflow(s):" -ForegroundColor Green
$Dataflows | ForEach-Object {{
    Write-Host "  - $($_.name) ($($_.objectId))"
}}

# --- Export each dataflow ---
Write-Host "`n=== Exporting Dataflows ===" -ForegroundColor Cyan
$Manifest = @()
$ExportCount = 0
$ErrorCount = 0

foreach ($Df in $Dataflows) {{
    $SafeName = $Df.name -replace '[\\/:*?"<>|]', '_'
    $OutFile = Join-Path $OutputDir "$SafeName.json"

    Write-Host "Exporting: $($Df.name) -> $SafeName.json" -NoNewline

    try {{
        Export-PowerBIDataflow `
            -WorkspaceId $WorkspaceId `
            -Id $Df.objectId `
            -OutFile $OutFile `
            -ErrorAction Stop

        $FileSize = (Get-Item $OutFile).Length
        Write-Host " [OK - $([math]::Round($FileSize / 1KB, 1)) KB]" -ForegroundColor Green
        $ExportCount++

        $Manifest += [PSCustomObject]@{{
            dataflow_name  = $Df.name
            dataflow_id    = $Df.objectId
            file_name      = "$SafeName.json"
            file_size_kb   = [math]::Round($FileSize / 1KB, 1)
            export_date    = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            configured_by  = if ($Df.configuredBy) {{ $Df.configuredBy }} else {{ "unknown" }}
            description    = if ($Df.description) {{ $Df.description }} else {{ "" }}
        }}
    }}
    catch {{
        Write-Host " [FAILED]" -ForegroundColor Red
        Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor Red
        $ErrorCount++

        $Manifest += [PSCustomObject]@{{
            dataflow_name  = $Df.name
            dataflow_id    = $Df.objectId
            file_name      = "EXPORT_FAILED"
            file_size_kb   = 0
            export_date    = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            configured_by  = if ($Df.configuredBy) {{ $Df.configuredBy }} else {{ "unknown" }}
            description    = "EXPORT FAILED: $($_.Exception.Message)"
        }}
    }}
}}

# --- Write manifest CSV ---
$Manifest | Export-Csv -Path $ManifestFile -NoTypeInformation -Encoding UTF8
Write-Host "`n=== Manifest written to: $ManifestFile ===" -ForegroundColor Cyan

# --- Summary ---
Write-Host "`n=== Export Summary ===" -ForegroundColor Cyan
Write-Host "Total dataflows found: $($Dataflows.Count)"
Write-Host "Successfully exported: $ExportCount" -ForegroundColor Green
if ($ErrorCount -gt 0) {{
    Write-Host "Failed exports:        $ErrorCount" -ForegroundColor Red
}}
Write-Host "Output directory:      $OutputDir"
Write-Host "Manifest file:         $ManifestFile"

# --- Disconnect ---
Disconnect-PowerBIServiceAccount -ErrorAction SilentlyContinue
Write-Host "`nDone. Disconnected from Power BI Service." -ForegroundColor Green
'''


def main():
    parser = argparse.ArgumentParser(
        description="Generate PowerShell script to export Dataflow Gen1 from a workspace"
    )
    parser.add_argument(
        "--workspace-id", required=True,
        help="Power BI workspace GUID"
    )
    parser.add_argument(
        "--output", required=True,
        help="Output path for the generated .ps1 script"
    )
    parser.add_argument(
        "--json-dir", default=".",
        help="Directory where exported JSON files will be saved (default: same as script location)"
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    script_content = TEMPLATE.format(
        workspace_id=args.workspace_id,
        json_dir=args.json_dir.replace("\\", "\\\\"),
    )

    output_path.write_text(script_content, encoding="utf-8")
    print(f"Generated: {output_path}")
    print(f"Workspace: {args.workspace_id}")
    print(f"JSON dir:  {args.json_dir}")
    print(f"\nNext: User runs the script in PowerShell (requires interactive auth)")


if __name__ == "__main__":
    main()
