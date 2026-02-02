<#
.SYNOPSIS
    Exports FOCUS-format billing data for Azure Local (Azure Stack HCI) virtual machines.

.DESCRIPTION
    Generates FOCUS-compatible CSV files for chargeback and billing systems by reading
    VM metadata from Hyper-V VM Notes fields and applying tier-based pricing with
    optional proration and subsidies.

.PARAMETER BillingPeriod
    The billing period in YYYY-MM format. Defaults to the previous month.

.PARAMETER ClusterName
    The Azure Local cluster to connect to. Defaults to azurelocal.example.edu.

.PARAMETER TierConfigPath
    Path to the tier pricing configuration JSON file. Defaults to .\config\tiers.json.

.PARAMETER OutputDirectory
    Directory for output files. Defaults to .\output.

.PARAMETER ExcludeVMPattern
    Array of regex patterns for VM names to exclude from billing.
    Defaults to @("^infra-.*", "^template-.*").

.PARAMETER IncludeOffVMs
    Include VMs that are not in Running state. By default, only Running VMs are processed.

.PARAMETER AuditFormat
    Format for audit output: Text, Json, or Splunk. Defaults to Text.

.PARAMETER AuditPath
    Path to append audit log. If not specified, writes to console.

.EXAMPLE
    .\Export-AzureLocalBilling.ps1 -WhatIf -Verbose
    Dry run showing what would be exported without making changes.

.EXAMPLE
    .\Export-AzureLocalBilling.ps1 -BillingPeriod "2025-01" -AuditFormat Json
    Export January 2025 billing data with JSON audit output.

.NOTES
    File Name  : Export-AzureLocalBilling.ps1
    Author     : Andrew Marx (andrew@xram.net)
    License    : MIT License
    Requires   : PowerShell 5.1+, Hyper-V PowerShell module, Failover Clustering module
#>

#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [ValidatePattern('^\d{4}-\d{2}$')]
    [string]$BillingPeriod,

    [Parameter()]
    [string]$ClusterName = 'azurelocal.example.edu',

    [Parameter()]
    [string]$TierConfigPath = '.\config\tiers.json',

    [Parameter()]
    [string]$OutputDirectory = '.\output',

    [Parameter()]
    [string[]]$ExcludeVMPattern = @('^infra-.*', '^template-.*'),

    [Parameter()]
    [switch]$IncludeOffVMs,

    [Parameter()]
    [ValidateSet('Text', 'Json', 'Splunk')]
    [string]$AuditFormat = 'Text',

    [Parameter()]
    [string]$AuditPath
)

# MIT License
# Copyright (c) 2026 Andrew Marx (andrew@xram.net)

#region Script Initialization
$ErrorActionPreference = 'Stop'
$scriptStartTime = Get-Date
$errors = [System.Collections.Generic.List[object]]::new()
$warnings = [System.Collections.Generic.List[object]]::new()

# Calculate billing period dates
if (-not $BillingPeriod) {
    $previousMonth = (Get-Date).AddMonths(-1)
    $BillingPeriod = $previousMonth.ToString('yyyy-MM')
}

$billingYear = [int]$BillingPeriod.Substring(0, 4)
$billingMonth = [int]$BillingPeriod.Substring(5, 2)
$periodStart = Get-Date -Year $billingYear -Month $billingMonth -Day 1
$periodEnd = $periodStart.AddMonths(1).AddDays(-1)
$daysInMonth = [DateTime]::DaysInMonth($billingYear, $billingMonth)

Write-Verbose "Billing Period: $BillingPeriod"
Write-Verbose "Period Start: $($periodStart.ToString('yyyy-MM-dd'))"
Write-Verbose "Period End: $($periodEnd.ToString('yyyy-MM-dd'))"
Write-Verbose "Days in Month: $daysInMonth"
#endregion

#region Load Tier Configuration
Write-Verbose "Loading tier configuration from: $TierConfigPath"

if (-not (Test-Path $TierConfigPath)) {
    throw "Tier configuration file not found: $TierConfigPath"
}

try {
    $tierConfig = Get-Content -Path $TierConfigPath -Raw | ConvertFrom-Json
}
catch {
    throw "Failed to parse tier configuration: $_"
}

# Build tier lookup hashtable
$tiers = @{}
foreach ($tierName in $tierConfig.tiers.PSObject.Properties.Name) {
    $tier = $tierConfig.tiers.$tierName
    $tiers[$tierName] = @{
        AnnualCost  = [decimal]$tier.annualCost
        MonthlyCost = [decimal]$tier.annualCost / 12
        Description = $tier.description
    }
}

Write-Verbose "Loaded $($tiers.Count) tiers: $($tiers.Keys -join ', ')"

# Get field mappings
$vmNotesFields = $tierConfig.fieldMapping.vmNotes
$focusTagFields = $tierConfig.fieldMapping.focusTags
$serviceName = $tierConfig.defaults.serviceName
#endregion

#region Enumerate VMs
Write-Verbose "Connecting to cluster: $ClusterName"

try {
    $clusterGroups = Get-ClusterGroup -Cluster $ClusterName | Where-Object { $_.GroupType -eq 'VirtualMachine' }
}
catch {
    throw "Failed to connect to cluster '$ClusterName': $_"
}

Write-Verbose "Found $($clusterGroups.Count) VM cluster groups"

$allVMs = [System.Collections.Generic.List[object]]::new()
$skippedVMs = [System.Collections.Generic.List[object]]::new()

foreach ($group in $clusterGroups) {
    $vmName = $group.Name

    # Check exclusion patterns
    $excluded = $false
    foreach ($pattern in $ExcludeVMPattern) {
        if ($vmName -match $pattern) {
            $skippedVMs.Add(@{
                VMName = $vmName
                Reason = "Matched exclude pattern: $pattern"
            })
            $excluded = $true
            Write-Debug "Skipping VM '$vmName': matched exclude pattern '$pattern'"
            break
        }
    }

    if ($excluded) { continue }

    # Get VM details from the owner node
    try {
        $ownerNode = $group.OwnerNode.Name
        $vm = Get-VM -ComputerName $ownerNode -Name $vmName

        # Check VM state
        if (-not $IncludeOffVMs -and $vm.State -ne 'Running') {
            $skippedVMs.Add(@{
                VMName = $vmName
                Reason = "VM state is '$($vm.State)' (use -IncludeOffVMs to include)"
            })
            Write-Debug "Skipping VM '$vmName': state is $($vm.State)"
            continue
        }

        $allVMs.Add($vm)
    }
    catch {
        $warnings.Add(@{
            VMName  = $vmName
            Warning = "Failed to retrieve VM details: $_"
        })
        Write-Warning "Failed to retrieve VM '$vmName': $_"
    }
}

Write-Verbose "VMs to process: $($allVMs.Count)"
Write-Verbose "VMs skipped: $($skippedVMs.Count)"
#endregion

#region Process VMs and Calculate Costs
$billingRecords = [System.Collections.Generic.List[object]]::new()
$whatIfRecords = [System.Collections.Generic.List[object]]::new()

foreach ($vm in $allVMs) {
    $vmName = $vm.Name
    Write-Debug "Processing VM: $vmName"

    # Parse VM Notes JSON
    $notesJson = $vm.Notes

    if ([string]::IsNullOrWhiteSpace($notesJson)) {
        $warnings.Add(@{
            VMName  = $vmName
            Warning = "VM Notes field is empty - cannot determine billing metadata"
        })
        Write-Warning "VM '$vmName': Notes field is empty"
        continue
    }

    try {
        $metadata = $notesJson | ConvertFrom-Json
    }
    catch {
        $warnings.Add(@{
            VMName  = $vmName
            Warning = "Failed to parse VM Notes as JSON: $_"
        })
        Write-Warning "VM '$vmName': Failed to parse Notes as JSON"
        continue
    }

    # Extract fields using configured field names
    $piEmail = $metadata.$($vmNotesFields.piEmail)
    $projectId = $metadata.$($vmNotesFields.projectId)
    $fundOrg = $metadata.$($vmNotesFields.fundOrg)
    $vmTier = $metadata.$($vmNotesFields.vmTier)
    $subsidyPercent = $metadata.$($vmNotesFields.subsidyPercent)
    $active = $metadata.$($vmNotesFields.active)

    # Apply defaults
    if ($null -eq $subsidyPercent) { $subsidyPercent = $tierConfig.defaults.subsidyPercent }
    if ($null -eq $active) { $active = $tierConfig.defaults.active }

    # Check if VM is active for billing
    if (-not $active) {
        $whatIfRecords.Add(@{
            VMName         = $vmName
            Tier           = $vmTier
            PiEmail        = $piEmail
            ProjectId      = $projectId
            FundOrg        = $fundOrg
            CreationDate   = $vm.CreationTime.ToString('yyyy-MM-dd')
            ProrationDays  = $null
            ProrationFactor = $null
            SubsidyPercent = $subsidyPercent
            ListCost       = $null
            BilledCost     = $null
            Status         = 'skipped'
            SkipReason     = 'FinOpsActive is false'
        })
        Write-Debug "VM '$vmName': Skipped (FinOpsActive = false)"
        continue
    }

    # Validate required fields
    $missingFields = @()
    if ([string]::IsNullOrWhiteSpace($piEmail)) { $missingFields += $vmNotesFields.piEmail }
    if ([string]::IsNullOrWhiteSpace($projectId)) { $missingFields += $vmNotesFields.projectId }
    if ([string]::IsNullOrWhiteSpace($fundOrg)) { $missingFields += $vmNotesFields.fundOrg }
    if ([string]::IsNullOrWhiteSpace($vmTier)) { $missingFields += $vmNotesFields.vmTier }

    if ($missingFields.Count -gt 0) {
        $warnings.Add(@{
            VMName  = $vmName
            Warning = "Missing required fields: $($missingFields -join ', ')"
        })
        Write-Warning "VM '$vmName': Missing required fields: $($missingFields -join ', ')"
        continue
    }

    # Validate tier
    if (-not $tiers.ContainsKey($vmTier)) {
        $warnings.Add(@{
            VMName  = $vmName
            Warning = "Unrecognized tier '$vmTier'. Valid tiers: $($tiers.Keys -join ', ')"
        })
        Write-Warning "VM '$vmName': Unrecognized tier '$vmTier'. Valid tiers: $($tiers.Keys -join ', ')"
        continue
    }

    # Calculate proration
    $creationDate = $vm.CreationTime.Date
    $prorationDays = $daysInMonth
    $prorationFactor = 1.0

    if ($creationDate -gt $periodStart -and $creationDate -le $periodEnd) {
        # VM was created during this billing period
        $prorationDays = ($periodEnd - $creationDate).Days + 1
        $prorationFactor = [decimal]$prorationDays / $daysInMonth
        Write-Debug "VM '$vmName': Prorated - created $($creationDate.ToString('yyyy-MM-dd')), $prorationDays days active"
    }
    elseif ($creationDate -gt $periodEnd) {
        # VM was created after this billing period
        $whatIfRecords.Add(@{
            VMName          = $vmName
            Tier            = $vmTier
            PiEmail         = $piEmail
            ProjectId       = $projectId
            FundOrg         = $fundOrg
            CreationDate    = $creationDate.ToString('yyyy-MM-dd')
            ProrationDays   = 0
            ProrationFactor = 0
            SubsidyPercent  = $subsidyPercent
            ListCost        = 0
            BilledCost      = 0
            Status          = 'skipped'
            SkipReason      = "VM created after billing period ($($creationDate.ToString('yyyy-MM-dd')))"
        })
        Write-Debug "VM '$vmName': Skipped - created after billing period"
        continue
    }

    # Calculate costs
    $monthlyCost = $tiers[$vmTier].MonthlyCost
    $listCost = [Math]::Round($monthlyCost * $prorationFactor, 2)
    $billedCost = [Math]::Round($listCost * (1 - [decimal]$subsidyPercent / 100), 2)

    Write-Debug "VM '$vmName': Tier=$vmTier, Monthly=$monthlyCost, Proration=$prorationFactor, List=$listCost, Billed=$billedCost"

    # Build FOCUS Tags JSON
    $tagsObject = @{
        $focusTagFields.piEmail   = $piEmail
        $focusTagFields.projectId = $projectId
        $focusTagFields.fundOrg   = $fundOrg
    }
    $tagsJson = $tagsObject | ConvertTo-Json -Compress

    # Create billing record
    $billingRecord = [PSCustomObject]@{
        BillingPeriodStart = $periodStart.ToString('yyyy-MM-dd')
        BillingPeriodEnd   = $periodEnd.ToString('yyyy-MM-dd')
        ChargePeriodStart  = $periodStart.ToString('yyyy-MM-dd')
        ChargePeriodEnd    = $periodEnd.ToString('yyyy-MM-dd')
        ListCost           = $listCost
        BilledCost         = $billedCost
        ResourceId         = $vmName
        ResourceName       = $vmName
        ServiceName        = $serviceName
        Tags               = $tagsJson
    }

    $billingRecords.Add($billingRecord)

    # WhatIf record
    $whatIfRecords.Add(@{
        VMName          = $vmName
        Tier            = $vmTier
        PiEmail         = $piEmail
        ProjectId       = $projectId
        FundOrg         = $fundOrg
        CreationDate    = $creationDate.ToString('yyyy-MM-dd')
        ProrationDays   = $prorationDays
        ProrationFactor = $prorationFactor
        SubsidyPercent  = $subsidyPercent
        ListCost        = $listCost
        BilledCost      = $billedCost
        Status          = 'processed'
    })
}
#endregion

#region Calculate Totals
$totalListCost = ($billingRecords | Measure-Object -Property ListCost -Sum).Sum
$totalBilledCost = ($billingRecords | Measure-Object -Property BilledCost -Sum).Sum
$totalSubsidyAmount = $totalListCost - $totalBilledCost

if ($null -eq $totalListCost) { $totalListCost = 0 }
if ($null -eq $totalBilledCost) { $totalBilledCost = 0 }
if ($null -eq $totalSubsidyAmount) { $totalSubsidyAmount = 0 }

Write-Verbose "Total List Cost: $totalListCost"
Write-Verbose "Total Billed Cost: $totalBilledCost"
Write-Verbose "Total Subsidy Amount: $totalSubsidyAmount"
#endregion

#region Export Outputs
if (-not (Test-Path $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}

$outputBaseName = "azure-local_$BillingPeriod"
$csvPath = Join-Path $OutputDirectory "$outputBaseName.csv"
$whatIfPath = Join-Path $OutputDirectory "${outputBaseName}_whatif.json"

if ($WhatIfPreference) {
    # WhatIf mode - export JSON only
    $whatIfOutput = @{
        metadata = @{
            generatedAt     = (Get-Date).ToString('o')
            billingPeriod   = $BillingPeriod
            clusterName     = $ClusterName
            mode            = 'WhatIf'
            tierConfigPath  = $TierConfigPath
            totalVMs        = $allVMs.Count + $skippedVMs.Count
            vmsProcessed    = $billingRecords.Count
            vmsSkipped      = $skippedVMs.Count + ($whatIfRecords | Where-Object { $_.Status -eq 'skipped' }).Count
        }
        vms      = $whatIfRecords
        skipped  = $skippedVMs
        warnings = $warnings
        totals   = @{
            totalListCost     = $totalListCost
            totalBilledCost   = $totalBilledCost
            totalSubsidyAmount = $totalSubsidyAmount
        }
    }

    $whatIfJson = $whatIfOutput | ConvertTo-Json -Depth 10

    if ($PSCmdlet.ShouldProcess($whatIfPath, 'Export WhatIf JSON')) {
        $whatIfJson | Out-File -FilePath $whatIfPath -Encoding UTF8
        Write-Verbose "WhatIf JSON exported to: $whatIfPath"
    }
}
else {
    # Production mode - export CSV
    if ($billingRecords.Count -gt 0) {
        if ($PSCmdlet.ShouldProcess($csvPath, 'Export FOCUS CSV')) {
            $billingRecords | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8
            Write-Verbose "FOCUS CSV exported to: $csvPath"
        }
    }
    else {
        Write-Warning "No billing records to export"
    }
}
#endregion

#region Audit Output
$scriptEndTime = Get-Date
$duration = $scriptEndTime - $scriptStartTime

$auditData = @{
    eventType     = 'AzureLocalBillingExport'
    timestamp     = $scriptEndTime.ToString('o')
    user          = "$env:USERDOMAIN\$env:USERNAME"
    computer      = $env:COMPUTERNAME
    parameters    = @{
        billingPeriod = $BillingPeriod
        clusterName   = $ClusterName
        mode          = if ($WhatIfPreference) { 'WhatIf' } else { 'Production' }
    }
    results       = @{
        duration        = $duration.ToString('hh\:mm\:ss')
        vmsProcessed    = $billingRecords.Count
        vmsSkipped      = $skippedVMs.Count
        totalListCost   = $totalListCost
        totalBilledCost = $totalBilledCost
        errors          = $errors.Count
        warnings        = $warnings.Count
    }
    outputFile    = if ($WhatIfPreference) { $whatIfPath } else { $csvPath }
}

$auditOutput = switch ($AuditFormat) {
    'Text' {
        @"
=== Azure Local Billing Export - Audit Log ===
Timestamp: $($auditData.timestamp)
User: $($auditData.user)
Computer: $($auditData.computer)
BillingPeriod: $($auditData.parameters.billingPeriod)
ClusterName: $($auditData.parameters.clusterName)
Mode: $($auditData.parameters.mode)
Duration: $($auditData.results.duration)
VMsProcessed: $($auditData.results.vmsProcessed)
VMsSkipped: $($auditData.results.vmsSkipped)
TotalListCost: $($auditData.results.totalListCost)
TotalBilledCost: $($auditData.results.totalBilledCost)
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
            "clusterName=`"$($auditData.parameters.clusterName)`""
            "mode=`"$($auditData.parameters.mode)`""
            "duration=`"$($auditData.results.duration)`""
            "vmsProcessed=$($auditData.results.vmsProcessed)"
            "vmsSkipped=$($auditData.results.vmsSkipped)"
            "totalListCost=$($auditData.results.totalListCost)"
            "totalBilledCost=$($auditData.results.totalBilledCost)"
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
#endregion

#region Error Log
if ($errors.Count -gt 0 -or $warnings.Count -gt 0) {
    $errorLogPath = Join-Path (Split-Path $OutputDirectory -Parent) 'Logs\export-errors.log'
    $errorLogDir = Split-Path $errorLogPath -Parent

    if (-not (Test-Path $errorLogDir)) {
        New-Item -ItemType Directory -Path $errorLogDir -Force | Out-Null
    }

    $errorLog = @"
========================================
Azure Local Billing Export - Error Log
========================================
Script Start: $($scriptStartTime.ToString('yyyy-MM-dd HH:mm:ss'))
Script End: $($scriptEndTime.ToString('yyyy-MM-dd HH:mm:ss'))
Duration: $($duration.ToString('hh\:mm\:ss'))
Total Errors: $($errors.Count)
Total Warnings: $($warnings.Count)
========================================

"@

    foreach ($error in $errors) {
        $errorLog += "[$($scriptEndTime.ToString('yyyy-MM-dd HH:mm:ss'))] [ERROR] VM '$($error.VMName)': $($error.Error)`n"
    }

    foreach ($warning in $warnings) {
        $errorLog += "[$($scriptEndTime.ToString('yyyy-MM-dd HH:mm:ss'))] [WARNING] VM '$($warning.VMName)': $($warning.Warning)`n"
    }

    $errorLog | Out-File -FilePath $errorLogPath -Encoding UTF8
    Write-Verbose "Error log written to: $errorLogPath"
}
#endregion
