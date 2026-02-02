<#
.SYNOPSIS
    Exports FOCUS-format billing data from Qumulo storage quotas.

.DESCRIPTION
    Generates FOCUS-compatible CSV files for chargeback and billing systems by reading
    project metadata from .openchargeback.json dot files and querying Qumulo quota/usage data.

    Supports two data collection methods:
    - Qumulo REST API (recommended): Direct API queries for accurate usage data
    - SMB enumeration (fallback): PowerShell directory size calculation

.PARAMETER BillingPeriod
    The billing period in YYYY-MM format. Defaults to the previous month.

.PARAMETER RootPath
    Root path to the research projects share (e.g., \\files.example.edu\research_projects).

.PARAMETER ConfigPath
    Path to the rates configuration JSON file. Defaults to .\config\rates.json.

.PARAMETER OutputDirectory
    Directory for output files. Defaults to .\output.

.PARAMETER Init
    Initialize .openchargeback.json files. Options: 'force' or 'interactive'.
    - force: Create template files in all project directories without prompting
    - interactive: Prompt for metadata for each project directory

.PARAMETER TemplatePath
    Path to the template .openchargeback.json file. Defaults to .\config\template.openchargeback.json.

.PARAMETER UseApi
    Use Qumulo REST API for quota data. Requires -ApiHost and -ApiToken.

.PARAMETER ApiHost
    Qumulo cluster API hostname (e.g., qumulo.example.edu:8000).

.PARAMETER ApiToken
    Qumulo API bearer token. Can also use QUMULO_API_TOKEN environment variable.

.PARAMETER ExcludePattern
    Array of regex patterns for project directories to exclude.
    Defaults to @("^\..*", "^_.*", "^lost\+found$").

.PARAMETER AuditFormat
    Format for audit output: Text, Json, or Splunk. Defaults to Text.

.PARAMETER AuditPath
    Path to append audit log. If not specified, writes to console.

.EXAMPLE
    .\Export-QumuloBilling.ps1 -Init interactive -RootPath "\\files.example.edu\research_projects"
    Initialize metadata files for all project directories interactively.

.EXAMPLE
    .\Export-QumuloBilling.ps1 -Init force -RootPath "\\files.example.edu\research_projects"
    Create template metadata files in all project directories.

.EXAMPLE
    .\Export-QumuloBilling.ps1 -BillingPeriod "2025-01" -RootPath "\\files.example.edu\research_projects"
    Export January 2025 billing data using SMB enumeration.

.EXAMPLE
    .\Export-QumuloBilling.ps1 -BillingPeriod "2025-01" -UseApi -ApiHost "qumulo.example.edu:8000"
    Export using Qumulo REST API (token from QUMULO_API_TOKEN env var).

.NOTES
    File Name  : Export-QumuloBilling.ps1
    Author     : OpenChargeback Contributors
    License    : MIT License
    Requires   : PowerShell 5.1+
#>

#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true, DefaultParameterSetName = 'Export')]
param(
    [Parameter(ParameterSetName = 'Export')]
    [Parameter(ParameterSetName = 'Api')]
    [ValidatePattern('^\d{4}-\d{2}$')]
    [string]$BillingPeriod,

    [Parameter(Mandatory = $true)]
    [string]$RootPath,

    [Parameter()]
    [string]$ConfigPath = '.\config\rates.json',

    [Parameter()]
    [string]$OutputDirectory = '.\output',

    [Parameter(ParameterSetName = 'Init')]
    [ValidateSet('force', 'interactive')]
    [string]$Init,

    [Parameter()]
    [string]$TemplatePath = '.\config\template.openchargeback.json',

    [Parameter(ParameterSetName = 'Api')]
    [switch]$UseApi,

    [Parameter(ParameterSetName = 'Api')]
    [string]$ApiHost,

    [Parameter(ParameterSetName = 'Api')]
    [string]$ApiToken,

    [Parameter()]
    [string[]]$ExcludePattern = @('^\..*', '^_.*', '^lost\+found$'),

    [Parameter()]
    [ValidateSet('Text', 'Json', 'Splunk')]
    [string]$AuditFormat = 'Text',

    [Parameter()]
    [string]$AuditPath
)

# MIT License
# Copyright (c) 2026 OpenChargeback Contributors

#region Constants
$METADATA_FILENAME = '.openchargeback.json'
$ADMIN_GROUP = 'DOMAIN\StorageAdmins'  # Customize for your environment
#endregion

#region Script Initialization
$ErrorActionPreference = 'Stop'
$scriptStartTime = Get-Date
$errors = [System.Collections.Generic.List[object]]::new()
$warnings = [System.Collections.Generic.List[object]]::new()

# Resolve script directory for relative paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath = Join-Path $ScriptDir $ConfigPath
}
if (-not [System.IO.Path]::IsPathRooted($TemplatePath)) {
    $TemplatePath = Join-Path $ScriptDir $TemplatePath
}
if (-not [System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $ScriptDir $OutputDirectory
}

Write-Verbose "Script Directory: $ScriptDir"
Write-Verbose "Config Path: $ConfigPath"
Write-Verbose "Template Path: $TemplatePath"
Write-Verbose "Output Directory: $OutputDirectory"
#endregion

#region Helper Functions

function Get-ProjectDirectories {
    <#
    .SYNOPSIS
        Enumerate project directories under the root path.
    #>
    param([string]$Path)

    $directories = Get-ChildItem -Path $Path -Directory -ErrorAction SilentlyContinue

    foreach ($dir in $directories) {
        $excluded = $false
        foreach ($pattern in $ExcludePattern) {
            if ($dir.Name -match $pattern) {
                Write-Debug "Excluding directory '$($dir.Name)': matched pattern '$pattern'"
                $excluded = $true
                break
            }
        }
        if (-not $excluded) {
            $dir
        }
    }
}

function Get-DirectorySize {
    <#
    .SYNOPSIS
        Calculate total size of a directory via SMB enumeration.
    #>
    param([string]$Path)

    try {
        $size = (Get-ChildItem -Path $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
                 Measure-Object -Property Length -Sum -ErrorAction SilentlyContinue).Sum
        if ($null -eq $size) { $size = 0 }
        return $size
    }
    catch {
        Write-Warning "Failed to calculate size for '$Path': $_"
        return $null
    }
}

function Get-QumuloApiUsage {
    <#
    .SYNOPSIS
        Query Qumulo REST API for directory usage.
    #>
    param(
        [string]$ApiHost,
        [string]$ApiToken,
        [string]$Path
    )

    $headers = @{
        'Authorization' = "Bearer $ApiToken"
        'Content-Type'  = 'application/json'
    }

    try {
        # Get quota info for path
        $quotaUrl = "https://$ApiHost/v1/file-system/quota/?path=$([uri]::EscapeDataString($Path))"
        $response = Invoke-RestMethod -Uri $quotaUrl -Headers $headers -Method Get

        if ($response.quotas -and $response.quotas.Count -gt 0) {
            return [long]$response.quotas[0].capacity_usage
        }

        # Fallback to capacity-by-path
        $capacityUrl = "https://$ApiHost/v1/analytics/capacity-by-path/?path=$([uri]::EscapeDataString($Path))"
        $response = Invoke-RestMethod -Uri $capacityUrl -Headers $headers -Method Get

        if ($response.capacity) {
            return [long]$response.capacity
        }

        return $null
    }
    catch {
        Write-Warning "API query failed for '$Path': $_"
        return $null
    }
}

function Set-MetadataFilePermissions {
    <#
    .SYNOPSIS
        Set restrictive permissions on metadata file.
    #>
    param(
        [string]$FilePath,
        [string]$ProjectGroup
    )

    try {
        $acl = Get-Acl $FilePath

        # Remove inheritance and clear existing rules
        $acl.SetAccessRuleProtection($true, $false)
        $acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) } | Out-Null

        # Add Storage Admins - Full Control
        if ($ADMIN_GROUP -ne 'DOMAIN\StorageAdmins') {
            $adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                $ADMIN_GROUP, 'FullControl', 'Allow')
            $acl.AddAccessRule($adminRule)
        }

        # Add project group - Read only (if provided)
        if ($ProjectGroup) {
            $readRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                $ProjectGroup, 'Read', 'Allow')
            $acl.AddAccessRule($readRule)
        }

        # Add SYSTEM - Full Control (required for scheduled tasks)
        $systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            'NT AUTHORITY\SYSTEM', 'FullControl', 'Allow')
        $acl.AddAccessRule($systemRule)

        Set-Acl $FilePath $acl
        Write-Verbose "Set permissions on: $FilePath"
    }
    catch {
        Write-Warning "Failed to set permissions on '$FilePath': $_"
    }
}

function Read-MetadataFile {
    <#
    .SYNOPSIS
        Read and validate .openchargeback.json metadata file.
    #>
    param([string]$ProjectPath)

    $metadataPath = Join-Path $ProjectPath $METADATA_FILENAME

    if (-not (Test-Path $metadataPath)) {
        return @{
            Found    = $false
            Path     = $metadataPath
            Error    = 'File not found'
            Metadata = $null
        }
    }

    try {
        $content = Get-Content $metadataPath -Raw -ErrorAction Stop
        $metadata = $content | ConvertFrom-Json

        # Validate required fields
        $missingFields = @()
        if ([string]::IsNullOrWhiteSpace($metadata.pi_email)) { $missingFields += 'pi_email' }
        if ([string]::IsNullOrWhiteSpace($metadata.project_id)) { $missingFields += 'project_id' }
        if ([string]::IsNullOrWhiteSpace($metadata.fund_org)) { $missingFields += 'fund_org' }

        if ($missingFields.Count -gt 0) {
            return @{
                Found    = $true
                Path     = $metadataPath
                Error    = "Missing required fields: $($missingFields -join ', ')"
                Metadata = $metadata
            }
        }

        return @{
            Found    = $true
            Path     = $metadataPath
            Error    = $null
            Metadata = $metadata
        }
    }
    catch {
        return @{
            Found    = $true
            Path     = $metadataPath
            Error    = "Failed to parse JSON: $_"
            Metadata = $null
        }
    }
}

#endregion

#region Init Mode

function Initialize-MetadataFiles {
    <#
    .SYNOPSIS
        Create .openchargeback.json files in project directories.
    #>
    param(
        [ValidateSet('force', 'interactive')]
        [string]$Mode
    )

    # Load template
    if (-not (Test-Path $TemplatePath)) {
        throw "Template file not found: $TemplatePath"
    }

    $templateContent = Get-Content $TemplatePath -Raw
    $template = $templateContent | ConvertFrom-Json

    Write-Host "`nInitializing metadata files in: $RootPath" -ForegroundColor Cyan
    Write-Host "Mode: $Mode`n" -ForegroundColor Cyan

    $projectDirs = @(Get-ProjectDirectories -Path $RootPath)
    Write-Host "Found $($projectDirs.Count) project directories`n"

    $created = 0
    $skipped = 0
    $updated = 0

    foreach ($dir in $projectDirs) {
        $metadataPath = Join-Path $dir.FullName $METADATA_FILENAME
        $projectId = $dir.Name

        Write-Host "[$($created + $skipped + $updated + 1)/$($projectDirs.Count)] $projectId" -ForegroundColor White

        # Check if file already exists
        $existingMetadata = $null
        if (Test-Path $metadataPath) {
            try {
                $existingMetadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
                Write-Host "  Existing metadata found" -ForegroundColor Yellow
            }
            catch {
                Write-Host "  Invalid existing metadata (will overwrite)" -ForegroundColor Red
            }
        }

        if ($Mode -eq 'force') {
            # Force mode: create template with project_id pre-filled
            $newMetadata = $template.PSObject.Copy()
            $newMetadata.project_id = $projectId

            # Preserve existing values if file exists
            if ($existingMetadata) {
                if ($existingMetadata.pi_email) { $newMetadata.pi_email = $existingMetadata.pi_email }
                if ($existingMetadata.fund_org) { $newMetadata.fund_org = $existingMetadata.fund_org }
                if ($existingMetadata.cost_center) { $newMetadata.cost_center = $existingMetadata.cost_center }
                if ($existingMetadata.reference_1) { $newMetadata.reference_1 = $existingMetadata.reference_1 }
                if ($existingMetadata.reference_2) { $newMetadata.reference_2 = $existingMetadata.reference_2 }
                if ($existingMetadata.end_date) { $newMetadata.end_date = $existingMetadata.end_date }
                if ($existingMetadata.reconciliation_end) { $newMetadata.reconciliation_end = $existingMetadata.reconciliation_end }
                if ($null -ne $existingMetadata.active) { $newMetadata.active = $existingMetadata.active }
                if ($null -ne $existingMetadata.free_gb) { $newMetadata.free_gb = $existingMetadata.free_gb }
                if ($null -ne $existingMetadata.subsidy_percent) { $newMetadata.subsidy_percent = $existingMetadata.subsidy_percent }
                if ($null -ne $existingMetadata.daily_credit) { $newMetadata.daily_credit = $existingMetadata.daily_credit }
                if ($existingMetadata.notes) { $newMetadata.notes = $existingMetadata.notes }
                $updated++
                Write-Host "  Updated (preserved existing values)" -ForegroundColor Green
            }
            else {
                $created++
                Write-Host "  Created template" -ForegroundColor Green
            }

            $newMetadata | ConvertTo-Json -Depth 10 | Set-Content $metadataPath -Encoding UTF8
            Set-MetadataFilePermissions -FilePath $metadataPath
        }
        elseif ($Mode -eq 'interactive') {
            # Interactive mode: prompt for each field
            Write-Host ""

            $newMetadata = [PSCustomObject]@{
                pi_email           = ''
                project_id         = $projectId
                fund_org           = ''
                cost_center        = ''
                reference_1        = ''
                reference_2        = ''
                end_date           = ''
                reconciliation_end = ''
                active             = $true
                free_gb            = $template.free_gb
                subsidy_percent    = $template.subsidy_percent
                daily_credit       = $template.daily_credit
                notes              = ''
            }

            # Pre-fill from existing if available
            if ($existingMetadata) {
                $newMetadata.pi_email = $existingMetadata.pi_email
                $newMetadata.fund_org = $existingMetadata.fund_org
                $newMetadata.cost_center = $existingMetadata.cost_center
                $newMetadata.reference_1 = $existingMetadata.reference_1
                $newMetadata.reference_2 = $existingMetadata.reference_2
                $newMetadata.end_date = $existingMetadata.end_date
                $newMetadata.reconciliation_end = $existingMetadata.reconciliation_end
                if ($null -ne $existingMetadata.active) { $newMetadata.active = $existingMetadata.active }
                if ($null -ne $existingMetadata.free_gb) { $newMetadata.free_gb = $existingMetadata.free_gb }
                if ($null -ne $existingMetadata.subsidy_percent) { $newMetadata.subsidy_percent = $existingMetadata.subsidy_percent }
                if ($null -ne $existingMetadata.daily_credit) { $newMetadata.daily_credit = $existingMetadata.daily_credit }
                if ($existingMetadata.notes) { $newMetadata.notes = $existingMetadata.notes }
            }

            # Required fields
            $piEmail = Read-Host "  PI Email [$($newMetadata.pi_email)]"
            if ($piEmail) { $newMetadata.pi_email = $piEmail }

            $fundOrg = Read-Host "  Fund/Org Code [$($newMetadata.fund_org)]"
            if ($fundOrg) { $newMetadata.fund_org = $fundOrg }

            # Recommended fields
            $costCenter = Read-Host "  Cost Center [$($newMetadata.cost_center)]"
            if ($costCenter) { $newMetadata.cost_center = $costCenter }

            # Custom reference fields
            $ref1 = Read-Host "  Reference 1 (e.g., grant number) [$($newMetadata.reference_1)]"
            if ($ref1) { $newMetadata.reference_1 = $ref1 }

            $ref2 = Read-Host "  Reference 2 (e.g., request ID) [$($newMetadata.reference_2)]"
            if ($ref2) { $newMetadata.reference_2 = $ref2 }

            # Lifecycle dates
            $endDate = Read-Host "  End Date (YYYY-MM-DD) [$($newMetadata.end_date)]"
            if ($endDate) { $newMetadata.end_date = $endDate }

            $reconEnd = Read-Host "  Reconciliation End (YYYY-MM-DD) [$($newMetadata.reconciliation_end)]"
            if ($reconEnd) { $newMetadata.reconciliation_end = $reconEnd }

            # Optional subsidy fields
            $changeSubsidy = Read-Host "  Modify subsidy settings? (y/N)"
            if ($changeSubsidy -eq 'y' -or $changeSubsidy -eq 'Y') {
                $freeGb = Read-Host "    Free GB allocation [$($newMetadata.free_gb)]"
                if ($freeGb -match '^\d+$') { $newMetadata.free_gb = [int]$freeGb }

                $subsidyPct = Read-Host "    Subsidy percent (0-100) [$($newMetadata.subsidy_percent)]"
                if ($subsidyPct -match '^\d+$') { $newMetadata.subsidy_percent = [int]$subsidyPct }

                $dailyCredit = Read-Host "    Daily credit amount [$($newMetadata.daily_credit)]"
                if ($dailyCredit -match '^\d+\.?\d*$') { $newMetadata.daily_credit = [decimal]$dailyCredit }
            }

            $notes = Read-Host "  Notes [$($newMetadata.notes)]"
            if ($notes) { $newMetadata.notes = $notes }

            # Confirm
            Write-Host ""
            Write-Host "  Summary:" -ForegroundColor Cyan
            Write-Host "    PI Email: $($newMetadata.pi_email)"
            Write-Host "    Project ID: $($newMetadata.project_id)"
            Write-Host "    Fund/Org: $($newMetadata.fund_org)"
            Write-Host "    Cost Center: $($newMetadata.cost_center)"
            Write-Host "    Reference 1: $($newMetadata.reference_1)"
            Write-Host "    Reference 2: $($newMetadata.reference_2)"
            Write-Host "    End Date: $($newMetadata.end_date)"
            Write-Host "    Free GB: $($newMetadata.free_gb)"
            Write-Host "    Subsidy %: $($newMetadata.subsidy_percent)"

            $confirm = Read-Host "  Save? (Y/n/skip)"
            if ($confirm -eq 'skip' -or $confirm -eq 's') {
                Write-Host "  Skipped" -ForegroundColor Yellow
                $skipped++
                continue
            }
            elseif ($confirm -ne 'n' -and $confirm -ne 'N') {
                $newMetadata | ConvertTo-Json -Depth 10 | Set-Content $metadataPath -Encoding UTF8
                Set-MetadataFilePermissions -FilePath $metadataPath

                if ($existingMetadata) {
                    $updated++
                    Write-Host "  Updated" -ForegroundColor Green
                }
                else {
                    $created++
                    Write-Host "  Created" -ForegroundColor Green
                }
            }
            else {
                Write-Host "  Not saved" -ForegroundColor Yellow
                $skipped++
            }

            Write-Host ""
        }
    }

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "Initialization Complete" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Created: $created"
    Write-Host "Updated: $updated"
    Write-Host "Skipped: $skipped"
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Edit metadata files to add PI emails and fund/org codes"
    Write-Host "  2. Run export: .\Export-QumuloBilling.ps1 -BillingPeriod YYYY-MM -RootPath '$RootPath'"
    Write-Host ""
}

#endregion

#region Export Mode

function Export-BillingData {
    <#
    .SYNOPSIS
        Export FOCUS-format billing CSV.
    #>

    # Calculate billing period dates
    if (-not $BillingPeriod) {
        $previousMonth = (Get-Date).AddMonths(-1)
        $BillingPeriod = $previousMonth.ToString('yyyy-MM')
    }

    $billingYear = [int]$BillingPeriod.Substring(0, 4)
    $billingMonth = [int]$BillingPeriod.Substring(5, 2)
    $periodStart = Get-Date -Year $billingYear -Month $billingMonth -Day 1
    $periodEnd = $periodStart.AddMonths(1).AddDays(-1)

    Write-Verbose "Billing Period: $BillingPeriod"
    Write-Verbose "Period Start: $($periodStart.ToString('yyyy-MM-dd'))"
    Write-Verbose "Period End: $($periodEnd.ToString('yyyy-MM-dd'))"

    # Load rates configuration
    if (-not (Test-Path $ConfigPath)) {
        throw "Rates configuration not found: $ConfigPath"
    }

    $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $serviceName = $config.serviceName
    $monthlyRatePerGB = [decimal]$config.monthlyRatePerGB
    $annualRate = $monthlyRatePerGB * 12
    $dailyRate = $annualRate / 365
    $defaultFreeGB = if ($null -ne $config.defaultFreeGB) { $config.defaultFreeGB } else { 500 }

    Write-Verbose "Service Name: $serviceName"
    Write-Verbose "Monthly Rate: `$$monthlyRatePerGB/GB"
    Write-Verbose "Daily Rate: `$$([math]::Round($dailyRate, 6))/GB"
    Write-Verbose "Default Free GB: $defaultFreeGB"

    # Get API token from parameter or environment
    if ($UseApi -and -not $ApiToken) {
        $ApiToken = $env:QUMULO_API_TOKEN
        if (-not $ApiToken) {
            throw "API token required. Provide -ApiToken or set QUMULO_API_TOKEN environment variable."
        }
    }

    # Enumerate project directories
    Write-Verbose "Scanning: $RootPath"
    $projectDirs = @(Get-ProjectDirectories -Path $RootPath)
    Write-Verbose "Found $($projectDirs.Count) project directories"

    $billingRecords = [System.Collections.Generic.List[object]]::new()
    $skippedProjects = [System.Collections.Generic.List[object]]::new()

    foreach ($dir in $projectDirs) {
        $projectPath = $dir.FullName
        $projectName = $dir.Name

        Write-Debug "Processing: $projectName"

        # Read metadata
        $metadataResult = Read-MetadataFile -ProjectPath $projectPath

        if (-not $metadataResult.Found) {
            $warnings.Add(@{
                Project = $projectName
                Warning = "Missing $METADATA_FILENAME"
            })
            $skippedProjects.Add(@{
                Project = $projectName
                Path    = $projectPath
                Reason  = "Missing $METADATA_FILENAME"
            })
            Write-Warning "Skipping '$projectName': Missing $METADATA_FILENAME"
            continue
        }

        if ($metadataResult.Error) {
            $warnings.Add(@{
                Project = $projectName
                Warning = $metadataResult.Error
            })
            $skippedProjects.Add(@{
                Project = $projectName
                Path    = $projectPath
                Reason  = $metadataResult.Error
            })
            Write-Warning "Skipping '$projectName': $($metadataResult.Error)"
            continue
        }

        $metadata = $metadataResult.Metadata

        # Check if active
        $active = if ($null -ne $metadata.active) { $metadata.active } else { $true }
        if (-not $active) {
            $skippedProjects.Add(@{
                Project = $projectName
                Path    = $projectPath
                Reason  = 'Project marked inactive'
            })
            Write-Debug "Skipping '$projectName': inactive"
            continue
        }

        # Get usage
        $usageBytes = $null
        if ($UseApi) {
            $usageBytes = Get-QumuloApiUsage -ApiHost $ApiHost -ApiToken $ApiToken -Path $projectPath
        }
        else {
            $usageBytes = Get-DirectorySize -Path $projectPath
        }

        if ($null -eq $usageBytes) {
            $warnings.Add(@{
                Project = $projectName
                Warning = 'Failed to determine storage usage'
            })
            $skippedProjects.Add(@{
                Project = $projectName
                Path    = $projectPath
                Reason  = 'Failed to determine storage usage'
            })
            continue
        }

        $usageGB = [math]::Round($usageBytes / 1GB, 2)

        # Get subsidy settings
        $freeGB = if ($null -ne $metadata.free_gb) { $metadata.free_gb } else { $defaultFreeGB }
        $subsidyPercent = if ($null -ne $metadata.subsidy_percent) { $metadata.subsidy_percent } else { 0 }
        $dailyCredit = if ($null -ne $metadata.daily_credit) { $metadata.daily_credit } else { 0 }

        # Calculate costs
        $listCost = [math]::Round($usageGB * $monthlyRatePerGB, 2)

        # Apply free allocation
        $billableGB = [math]::Max(0, $usageGB - $freeGB)
        $costAfterFree = $billableGB * $monthlyRatePerGB

        # Apply subsidy percentage
        $costAfterSubsidy = $costAfterFree * (1 - ($subsidyPercent / 100))

        # Apply daily credits (converted to monthly: daily * days in month)
        $monthlyCredit = $dailyCredit * [DateTime]::DaysInMonth($billingYear, $billingMonth)
        $billedCost = [math]::Max(0, [math]::Round($costAfterSubsidy - $monthlyCredit, 2))

        Write-Debug "  Usage: $usageGB GB, List: `$$listCost, Billed: `$$billedCost"

        # Build Tags JSON
        $tagsObject = @{
            pi_email   = $metadata.pi_email
            project_id = $metadata.project_id
            fund_org   = $metadata.fund_org
        }

        # Add optional fields if present
        if ($metadata.cost_center) { $tagsObject.cost_center = $metadata.cost_center }
        if ($metadata.reference_1) { $tagsObject.reference_1 = $metadata.reference_1 }
        if ($metadata.reference_2) { $tagsObject.reference_2 = $metadata.reference_2 }
        if ($metadata.end_date) { $tagsObject.end_date = $metadata.end_date }
        if ($metadata.reconciliation_end) { $tagsObject.reconciliation_end = $metadata.reconciliation_end }

        $tagsJson = $tagsObject | ConvertTo-Json -Compress

        # Create billing record
        $billingRecord = [PSCustomObject]@{
            BillingPeriodStart = $periodStart.ToString('yyyy-MM-dd')
            BillingPeriodEnd   = $periodEnd.ToString('yyyy-MM-dd')
            ChargePeriodStart  = $periodStart.ToString('yyyy-MM-dd')
            ChargePeriodEnd    = $periodEnd.ToString('yyyy-MM-dd')
            ListCost           = $listCost
            BilledCost         = $billedCost
            ResourceId         = "$($metadata.project_id)-storage"
            ResourceName       = "$($metadata.project_id) Storage"
            ServiceName        = $serviceName
            Tags               = $tagsJson
        }

        $billingRecords.Add($billingRecord)
    }

    # Calculate totals
    $totalListCost = ($billingRecords | Measure-Object -Property ListCost -Sum).Sum
    $totalBilledCost = ($billingRecords | Measure-Object -Property BilledCost -Sum).Sum
    $totalSubsidyAmount = $totalListCost - $totalBilledCost

    if ($null -eq $totalListCost) { $totalListCost = 0 }
    if ($null -eq $totalBilledCost) { $totalBilledCost = 0 }
    if ($null -eq $totalSubsidyAmount) { $totalSubsidyAmount = 0 }

    Write-Verbose "Total List Cost: `$$totalListCost"
    Write-Verbose "Total Billed Cost: `$$totalBilledCost"
    Write-Verbose "Total Subsidy: `$$totalSubsidyAmount"

    # Export CSV
    if (-not (Test-Path $OutputDirectory)) {
        New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    }

    $outputBaseName = "qumulo_$BillingPeriod"
    $csvPath = Join-Path $OutputDirectory "$outputBaseName.csv"

    if ($billingRecords.Count -gt 0) {
        if ($PSCmdlet.ShouldProcess($csvPath, 'Export FOCUS CSV')) {
            $billingRecords | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8
            Write-Verbose "FOCUS CSV exported to: $csvPath"
        }
    }
    else {
        Write-Warning "No billing records to export"
    }

    # Return summary for audit
    return @{
        BillingPeriod      = $BillingPeriod
        ProjectsProcessed  = $billingRecords.Count
        ProjectsSkipped    = $skippedProjects.Count
        TotalListCost      = $totalListCost
        TotalBilledCost    = $totalBilledCost
        TotalSubsidyAmount = $totalSubsidyAmount
        OutputFile         = $csvPath
        SkippedProjects    = $skippedProjects
    }
}

#endregion

#region Audit Output

function Write-AuditLog {
    param(
        [hashtable]$Summary
    )

    $scriptEndTime = Get-Date
    $duration = $scriptEndTime - $scriptStartTime

    $auditData = @{
        eventType  = 'QumuloBillingExport'
        timestamp  = $scriptEndTime.ToString('o')
        user       = "$env:USERDOMAIN\$env:USERNAME"
        computer   = $env:COMPUTERNAME
        parameters = @{
            billingPeriod = $Summary.BillingPeriod
            rootPath      = $RootPath
            mode          = if ($Init) { "Init-$Init" } elseif ($UseApi) { 'API' } else { 'SMB' }
        }
        results    = @{
            duration           = $duration.ToString('hh\:mm\:ss')
            projectsProcessed  = $Summary.ProjectsProcessed
            projectsSkipped    = $Summary.ProjectsSkipped
            totalListCost      = $Summary.TotalListCost
            totalBilledCost    = $Summary.TotalBilledCost
            totalSubsidyAmount = $Summary.TotalSubsidyAmount
            errors             = $errors.Count
            warnings           = $warnings.Count
        }
        outputFile = $Summary.OutputFile
    }

    $auditOutput = switch ($AuditFormat) {
        'Text' {
            @"
=== Qumulo Storage Billing Export - Audit Log ===
Timestamp: $($auditData.timestamp)
User: $($auditData.user)
Computer: $($auditData.computer)
BillingPeriod: $($auditData.parameters.billingPeriod)
RootPath: $($auditData.parameters.rootPath)
Mode: $($auditData.parameters.mode)
Duration: $($auditData.results.duration)
ProjectsProcessed: $($auditData.results.projectsProcessed)
ProjectsSkipped: $($auditData.results.projectsSkipped)
TotalListCost: $($auditData.results.totalListCost)
TotalBilledCost: $($auditData.results.totalBilledCost)
TotalSubsidyAmount: $($auditData.results.totalSubsidyAmount)
Errors: $($auditData.results.errors)
Warnings: $($auditData.results.warnings)
OutputFile: $($auditData.outputFile)
"@
        }
        'Json' {
            $auditData | ConvertTo-Json -Depth 5
        }
        'Splunk' {
            $parts = @(
                "timestamp=`"$($auditData.timestamp)`""
                "eventType=`"$($auditData.eventType)`""
                "user=`"$($auditData.user)`""
                "computer=`"$($auditData.computer)`""
                "billingPeriod=`"$($auditData.parameters.billingPeriod)`""
                "rootPath=`"$($auditData.parameters.rootPath)`""
                "mode=`"$($auditData.parameters.mode)`""
                "duration=`"$($auditData.results.duration)`""
                "projectsProcessed=$($auditData.results.projectsProcessed)"
                "projectsSkipped=$($auditData.results.projectsSkipped)"
                "totalListCost=$($auditData.results.totalListCost)"
                "totalBilledCost=$($auditData.results.totalBilledCost)"
                "totalSubsidyAmount=$($auditData.results.totalSubsidyAmount)"
                "errors=$($auditData.results.errors)"
                "warnings=$($auditData.results.warnings)"
                "outputFile=`"$($auditData.outputFile)`""
            )
            $parts -join ' '
        }
    }

    if ($AuditPath) {
        $auditOutput | Out-File -FilePath $AuditPath -Append -Encoding UTF8
    }
    else {
        Write-Output $auditOutput
    }
}

#endregion

#region Main

if ($Init) {
    Initialize-MetadataFiles -Mode $Init
}
else {
    $summary = Export-BillingData
    Write-AuditLog -Summary $summary
}

#endregion
