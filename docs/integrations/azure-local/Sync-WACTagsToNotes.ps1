<#
.SYNOPSIS
    Syncs Windows Admin Center (WAC) VM tags to Hyper-V VM Notes fields.

.DESCRIPTION
    Reads VM tags from Windows Admin Center REST API and converts them to JSON
    metadata stored in the Hyper-V VM Notes field. This enables billing metadata
    to be managed through WAC's UI while being consumable by Export-AzureLocalBilling.ps1.

.PARAMETER WACGateway
    The Windows Admin Center gateway URL. Defaults to https://wac.example.edu.

.PARAMETER ClusterName
    The Azure Local cluster name. Defaults to azurelocal.example.edu.

.PARAMETER TierConfigPath
    Path to the tier configuration JSON file for validation. Defaults to .\config\tiers.json.

.PARAMETER Credential
    Credentials for WAC authentication. If not specified, uses current user context.

.PARAMETER OverwriteExisting
    Overwrite existing VM Notes content. By default, VMs with non-empty Notes are skipped.

.PARAMETER AuditFormat
    Format for audit output: Text, Json, or Splunk. Defaults to Text.

.PARAMETER AuditPath
    Path to append audit log. If not specified, writes to console.

.EXAMPLE
    .\Sync-WACTagsToNotes.ps1 -WhatIf -Verbose
    Dry run showing what would be synced without making changes.

.EXAMPLE
    .\Sync-WACTagsToNotes.ps1 -OverwriteExisting -AuditFormat Splunk -AuditPath "\\siem\wac-sync.log"
    Sync all VMs, overwriting existing Notes, with Splunk-format audit logging.

.NOTES
    File Name  : Sync-WACTagsToNotes.ps1
    Author     : Andrew Marx (andrew@xram.net)
    License    : MIT License
    Requires   : PowerShell 5.1+, Hyper-V PowerShell module, Network access to WAC gateway
#>

#Requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [string]$WACGateway = 'https://wac.example.edu',

    [Parameter()]
    [string]$ClusterName = 'azurelocal.example.edu',

    [Parameter()]
    [string]$TierConfigPath = '.\config\tiers.json',

    [Parameter()]
    [PSCredential]$Credential,

    [Parameter()]
    [switch]$OverwriteExisting,

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

Write-Verbose "WAC Gateway: $WACGateway"
Write-Verbose "Cluster: $ClusterName"
Write-Verbose "Overwrite Existing: $OverwriteExisting"
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

# Build valid tier list for validation
$validTiers = @($tierConfig.tiers.PSObject.Properties.Name)
Write-Verbose "Valid tiers: $($validTiers -join ', ')"

# Get field mappings
$vmNotesFields = $tierConfig.fieldMapping.vmNotes
#endregion

#region WAC Tag Field Mapping
# Maps WAC tag names to internal field names
# WAC tags are typically user-friendly names that map to our FinOps* fields
$wacTagMapping = @{
    'PI Email'        = 'piEmail'
    'Project ID'      = 'projectId'
    'Fund/Org'        = 'fundOrg'
    'VM Tier'         = 'vmTier'
    'Subsidy Percent' = 'subsidyPercent'
    'Active'          = 'active'
    # Alternative tag names
    'PIEmail'         = 'piEmail'
    'ProjectID'       = 'projectId'
    'FundOrg'         = 'fundOrg'
    'VMTier'          = 'vmTier'
    'SubsidyPercent'  = 'subsidyPercent'
}
#endregion

#region Connect to WAC
Write-Verbose "Connecting to WAC gateway: $WACGateway"

$wacBaseUrl = $WACGateway.TrimEnd('/')
$invokeParams = @{
    UseBasicParsing = $true
    ContentType     = 'application/json'
}

if ($Credential) {
    $invokeParams['Credential'] = $Credential
}
else {
    $invokeParams['UseDefaultCredentials'] = $true
}

# Test WAC connectivity
try {
    $testUrl = "$wacBaseUrl/api/gateway/status"
    $null = Invoke-RestMethod -Uri $testUrl -Method Get @invokeParams
    Write-Verbose "Successfully connected to WAC gateway"
}
catch {
    throw "Failed to connect to WAC gateway '$WACGateway': $_"
}
#endregion

#region Get VM Tags from WAC
Write-Verbose "Retrieving VM tags from WAC for cluster: $ClusterName"

try {
    # WAC API endpoint for cluster VMs with tags
    $vmTagsUrl = "$wacBaseUrl/api/nodes/$ClusterName/features/virtualMachines/vms"
    $wacVMs = Invoke-RestMethod -Uri $vmTagsUrl -Method Get @invokeParams
}
catch {
    throw "Failed to retrieve VMs from WAC: $_"
}

Write-Verbose "Found $($wacVMs.Count) VMs in WAC"
#endregion

#region Get VMs from Hyper-V
Write-Verbose "Retrieving VMs from cluster: $ClusterName"

try {
    $clusterGroups = Get-ClusterGroup -Cluster $ClusterName | Where-Object { $_.GroupType -eq 'VirtualMachine' }
}
catch {
    throw "Failed to connect to cluster '$ClusterName': $_"
}

# Build lookup of VMs by name
$vmLookup = @{}
foreach ($group in $clusterGroups) {
    try {
        $ownerNode = $group.OwnerNode.Name
        $vm = Get-VM -ComputerName $ownerNode -Name $group.Name
        $vmLookup[$group.Name] = @{
            VM        = $vm
            OwnerNode = $ownerNode
        }
    }
    catch {
        $warnings.Add(@{
            VMName  = $group.Name
            Warning = "Failed to retrieve VM from Hyper-V: $_"
        })
    }
}

Write-Verbose "Retrieved $($vmLookup.Count) VMs from Hyper-V"
#endregion

#region Process VMs
$processedCount = 0
$updatedCount = 0
$skippedCount = 0
$warningCount = 0
$whatIfRecords = [System.Collections.Generic.List[object]]::new()

foreach ($wacVM in $wacVMs) {
    $vmName = $wacVM.name
    Write-Debug "Processing VM: $vmName"

    # Check if VM exists in Hyper-V
    if (-not $vmLookup.ContainsKey($vmName)) {
        Write-Debug "VM '$vmName' not found in Hyper-V cluster"
        continue
    }

    $vmInfo = $vmLookup[$vmName]
    $vm = $vmInfo.VM
    $ownerNode = $vmInfo.OwnerNode

    # Check existing Notes
    $existingNotes = $vm.Notes
    $hasExistingNotes = -not [string]::IsNullOrWhiteSpace($existingNotes)

    if ($hasExistingNotes -and -not $OverwriteExisting) {
        $skippedCount++
        $whatIfRecords.Add(@{
            VMName         = $vmName
            Status         = 'skipped'
            Reason         = 'Existing Notes present (use -OverwriteExisting to replace)'
            ExistingNotes  = $existingNotes
            ProposedNotes  = $null
        })
        Write-Debug "VM '$vmName': Skipped - has existing Notes"
        continue
    }

    # Extract tags from WAC VM object
    $wacTags = $wacVM.tags
    if ($null -eq $wacTags -or $wacTags.Count -eq 0) {
        $warnings.Add(@{
            VMName  = $vmName
            Warning = "No tags defined in WAC"
        })
        $warningCount++
        Write-Warning "VM '$vmName': No tags defined in WAC"
        continue
    }

    # Build metadata object from tags
    $metadata = @{}
    foreach ($tag in $wacTags.PSObject.Properties) {
        $tagName = $tag.Name
        $tagValue = $tag.Value

        # Map WAC tag name to internal field name
        if ($wacTagMapping.ContainsKey($tagName)) {
            $internalField = $wacTagMapping[$tagName]
            $vmNotesField = $vmNotesFields.$internalField

            if ($vmNotesField) {
                $metadata[$vmNotesField] = $tagValue
            }
        }
    }

    # Validate required fields
    $missingFields = @()
    if (-not $metadata.ContainsKey($vmNotesFields.piEmail)) { $missingFields += 'PI Email' }
    if (-not $metadata.ContainsKey($vmNotesFields.projectId)) { $missingFields += 'Project ID' }
    if (-not $metadata.ContainsKey($vmNotesFields.fundOrg)) { $missingFields += 'Fund/Org' }
    if (-not $metadata.ContainsKey($vmNotesFields.vmTier)) { $missingFields += 'VM Tier' }

    if ($missingFields.Count -gt 0) {
        $warnings.Add(@{
            VMName  = $vmName
            Warning = "Missing required WAC tags: $($missingFields -join ', ')"
        })
        $warningCount++
        Write-Warning "VM '$vmName': Missing required WAC tags: $($missingFields -join ', ')"
        continue
    }

    # Validate tier
    $vmTier = $metadata[$vmNotesFields.vmTier]
    if ($vmTier -notin $validTiers) {
        $warnings.Add(@{
            VMName  = $vmName
            Warning = "Unrecognized tier '$vmTier'. Valid tiers: $($validTiers -join ', ')"
        })
        $warningCount++
        Write-Warning "VM '$vmName': Unrecognized tier '$vmTier'"
        Write-Warning "  Valid tiers: $($validTiers -join ', ')"
    }

    # Apply defaults for optional fields
    if (-not $metadata.ContainsKey($vmNotesFields.subsidyPercent)) {
        $metadata[$vmNotesFields.subsidyPercent] = $tierConfig.defaults.subsidyPercent
    }
    if (-not $metadata.ContainsKey($vmNotesFields.active)) {
        $metadata[$vmNotesFields.active] = $tierConfig.defaults.active
    }

    # Convert subsidy to number if string
    $subsidyValue = $metadata[$vmNotesFields.subsidyPercent]
    if ($subsidyValue -is [string]) {
        $metadata[$vmNotesFields.subsidyPercent] = [int]$subsidyValue
    }

    # Convert active to boolean if string
    $activeValue = $metadata[$vmNotesFields.active]
    if ($activeValue -is [string]) {
        $metadata[$vmNotesFields.active] = $activeValue -eq 'true' -or $activeValue -eq 'yes' -or $activeValue -eq '1'
    }

    # Generate JSON for VM Notes
    $notesJson = $metadata | ConvertTo-Json -Compress

    $whatIfRecords.Add(@{
        VMName        = $vmName
        Status        = 'update'
        ExistingNotes = if ($hasExistingNotes) { $existingNotes } else { $null }
        ProposedNotes = $notesJson
        Metadata      = $metadata
    })

    # Update VM Notes
    if ($PSCmdlet.ShouldProcess("VM '$vmName' on $ownerNode", "Set Notes to: $notesJson")) {
        try {
            Set-VM -ComputerName $ownerNode -Name $vmName -Notes $notesJson
            $updatedCount++
            Write-Verbose "VM '$vmName': Notes updated successfully"
        }
        catch {
            $errors.Add(@{
                VMName = $vmName
                Error  = "Failed to set Notes: $_"
            })
            Write-Error "VM '$vmName': Failed to set Notes: $_"
        }
    }

    $processedCount++
}
#endregion

#region Export WhatIf Output
if ($WhatIfPreference) {
    $outputDirectory = '.\output'
    if (-not (Test-Path $outputDirectory)) {
        New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    }

    $whatIfPath = Join-Path $outputDirectory "wac-sync_$(Get-Date -Format 'yyyy-MM-dd')_whatif.json"

    $whatIfOutput = @{
        metadata = @{
            generatedAt      = (Get-Date).ToString('o')
            wacGateway       = $WACGateway
            clusterName      = $ClusterName
            mode             = 'WhatIf'
            overwriteExisting = $OverwriteExisting.IsPresent
            totalVMs         = $wacVMs.Count
            vmsProcessed     = $processedCount
            vmsToUpdate      = ($whatIfRecords | Where-Object { $_.Status -eq 'update' }).Count
            vmsSkipped       = $skippedCount
        }
        vms      = $whatIfRecords
        warnings = $warnings
    }

    $whatIfJson = $whatIfOutput | ConvertTo-Json -Depth 10
    $whatIfJson | Out-File -FilePath $whatIfPath -Encoding UTF8
    Write-Verbose "WhatIf JSON exported to: $whatIfPath"
}
#endregion

#region Audit Output
$scriptEndTime = Get-Date
$duration = $scriptEndTime - $scriptStartTime

$auditData = @{
    eventType     = 'WACTagsToNotesSync'
    timestamp     = $scriptEndTime.ToString('o')
    user          = "$env:USERDOMAIN\$env:USERNAME"
    computer      = $env:COMPUTERNAME
    parameters    = @{
        wacGateway        = $WACGateway
        clusterName       = $ClusterName
        overwriteExisting = $OverwriteExisting.IsPresent
        mode              = if ($WhatIfPreference) { 'WhatIf' } else { 'Production' }
    }
    results       = @{
        duration     = $duration.ToString('hh\:mm\:ss')
        vmsProcessed = $processedCount
        vmsUpdated   = $updatedCount
        vmsSkipped   = $skippedCount
        errors       = $errors.Count
        warnings     = $warningCount
    }
}

$auditOutput = switch ($AuditFormat) {
    'Text' {
        @"
=== WAC Tags to Notes Sync - Audit Log ===
Timestamp: $($auditData.timestamp)
User: $($auditData.user)
Computer: $($auditData.computer)
WACGateway: $($auditData.parameters.wacGateway)
ClusterName: $($auditData.parameters.clusterName)
OverwriteExisting: $($auditData.parameters.overwriteExisting)
Mode: $($auditData.parameters.mode)
Duration: $($auditData.results.duration)
VMsProcessed: $($auditData.results.vmsProcessed)
VMsUpdated: $($auditData.results.vmsUpdated)
VMsSkipped: $($auditData.results.vmsSkipped)
Errors: $($auditData.results.errors)
Warnings: $($auditData.results.warnings)
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
            "wacGateway=`"$($auditData.parameters.wacGateway)`""
            "clusterName=`"$($auditData.parameters.clusterName)`""
            "overwriteExisting=$($auditData.parameters.overwriteExisting)"
            "mode=`"$($auditData.parameters.mode)`""
            "duration=`"$($auditData.results.duration)`""
            "vmsProcessed=$($auditData.results.vmsProcessed)"
            "vmsUpdated=$($auditData.results.vmsUpdated)"
            "vmsSkipped=$($auditData.results.vmsSkipped)"
            "errors=$($auditData.results.errors)"
            "warnings=$($auditData.results.warnings)"
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

#region Summary Output
Write-Host ""
Write-Host "WAC Tags to Notes Sync Complete" -ForegroundColor Green
Write-Host "================================"
Write-Host "VMs Processed: $processedCount"
Write-Host "VMs Updated: $updatedCount"
Write-Host "VMs Skipped: $skippedCount"
Write-Host "Warnings: $warningCount"
Write-Host "Errors: $($errors.Count)"
Write-Host ""
#endregion

#region Error Log
if ($errors.Count -gt 0) {
    $errorLogPath = '.\Logs\sync-errors.log'
    $errorLogDir = Split-Path $errorLogPath -Parent

    if (-not (Test-Path $errorLogDir)) {
        New-Item -ItemType Directory -Path $errorLogDir -Force | Out-Null
    }

    $errorLog = @"
========================================
WAC Tags to Notes Sync - Error Log
========================================
Script Start: $($scriptStartTime.ToString('yyyy-MM-dd HH:mm:ss'))
Script End: $($scriptEndTime.ToString('yyyy-MM-dd HH:mm:ss'))
Duration: $($duration.ToString('hh\:mm\:ss'))
Total Errors: $($errors.Count)
========================================

"@

    foreach ($error in $errors) {
        $errorLog += "[$($scriptEndTime.ToString('yyyy-MM-dd HH:mm:ss'))] [ERROR] VM '$($error.VMName)': $($error.Error)`n"
    }

    $errorLog | Out-File -FilePath $errorLogPath -Encoding UTF8
    Write-Verbose "Error log written to: $errorLogPath"
}
#endregion
