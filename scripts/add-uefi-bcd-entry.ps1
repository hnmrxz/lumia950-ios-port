# Add a boot entry for BootShim to the handset's BCD store. Run as Administrator.
#
# The Windows Phone BCD store is not a desktop one: it can lack a display order element, and /copy can
# refuse to clone entries. Step one is therefore to look at what the store holds; this script only
# proceeds when it recognises a manager entry, and it prefers /copy with a /create fallback.
#
#   powershell -ExecutionPolicy Bypass -File scripts\add-uefi-bcd-entry.ps1 -Efiesp R:
#   powershell -ExecutionPolicy Bypass -File scripts\add-uefi-bcd-entry.ps1 -Efiesp R: -EnumerateOnly
#
param(
    [Parameter(Mandatory = $true)][string]$Efiesp,
    [string]$Title = "UniXNU (UEFI.elf via BootShim)",
    [int]$TimeoutSeconds = 10,
    [switch]$EnumerateOnly
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this in an elevated PowerShell: bcdedit needs an administrator token."
    }
}

Assert-Admin

$letter = $Efiesp.TrimEnd(":")
$store = "${letter}:\EFI\Microsoft\BOOT\BCD"
if (-not (Test-Path $store)) { throw "$store is missing; is EFIESP mounted as ${letter}?" }

function Invoke-Bcd {
    param([string[]]$Arguments)
    $output = & bcdedit /store $store @Arguments 2>&1
    return @{ ExitCode = $LASTEXITCODE; Output = $output }
}

Write-Host "=== current store ==="
$enum = Invoke-Bcd @("/enum", "all")
$enum.Output | Out-Host
if ($EnumerateOnly) { exit 0 }
if ($enum.ExitCode -ne 0) { throw "bcdedit /enum failed; the store cannot be opened" }

$text = ($enum.Output -join "`n")
if ($text -notmatch "\{bootmgr\}") {
    throw "this store has no {bootmgr} entry; it is not the store the firmware reads. Stop here and report."
}

# Identify a template entry: prefer {default}, else the first osloader-looking identifier.
$template = $null
if ($text -match "\{default\}") { $template = "{default}" }
else {
    $match = [regex]::Match($text, "\{([0-9a-fA-F\-]{36})\}")
    if ($match.Success) { $template = "{" + $match.Groups[1].Value + "}" }
}

$backup = Join-Path $PSScriptRoot ("BCD-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".bin")
$export = Invoke-Bcd @("/export", $backup)
$export.Output | Out-Host
if ($export.ExitCode -ne 0) {
    Write-Warning "bcdedit /export failed; continuing without a store backup. Do not reboot until the enum output above is saved."
}

$entry = $null
if ($template) {
    Write-Host "=== copying $template ==="
    $copy = Invoke-Bcd @("/copy", $template, "/d", $Title)
    $copy.Output | Out-Host
    $match = [regex]::Match(($copy.Output -join "`n"), "\{([0-9a-fA-F\-]{36})\}|([0-9a-fA-F\-]{36})")
    if ($copy.ExitCode -eq 0 -and $match.Success) {
        $guid = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value }
        $entry = "{" + $guid + "}"
    }
}

if (-not $entry) {
    Write-Host "=== creating a new osloader entry ==="
    $create = Invoke-Bcd @("/create", "/d", $Title, "/application", "osloader")
    $create.Output | Out-Host
    $match = [regex]::Match(($create.Output -join "`n"), "\{([0-9a-fA-F\-]{36})\}|([0-9a-fA-F\-]{36})")
    if ($create.ExitCode -ne 0 -or -not $match.Success) {
        throw "could not create a boot entry; paste the output above when reporting"
    }
    $guid = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value }
    $entry = "{" + $guid + "}"
    Invoke-Bcd @("/set", $entry, "device", "partition=${letter}:") | ForEach-Object { $_.Output | Out-Host }
}

Write-Host "entry: $entry"
Invoke-Bcd @("/set", $entry, "path", "\EFI\boot\BootShim.efi") | ForEach-Object { $_.Output | Out-Host }

# The display order element may not exist on this store; create it first if the add fails.
$order = Invoke-Bcd @("/displayorder", $entry, "/addfirst")
if ($order.ExitCode -ne 0) {
    Write-Host "=== display order missing; creating one ==="
    Invoke-Bcd @("/create", "/d", "Boot Menu", "/application", "bootmgr")
    Invoke-Bcd @("/displayorder", $entry, "/addfirst") | ForEach-Object { $_.Output | Out-Host }
} else { $order.Output | Out-Host }

Invoke-Bcd @("/timeout", "$TimeoutSeconds") | ForEach-Object { $_.Output | Out-Host }
Invoke-Bcd @("/set", "{bootmgr}", "displaybootmenu", "Yes") | ForEach-Object { $_.Output | Out-Host }

Write-Host "=== result ==="
Invoke-Bcd @("/enum", "all") | ForEach-Object { $_.Output | Out-Host }

Write-Host ""
Write-Host "Reboot with the cable detached. The boot menu should offer '$Title' for $TimeoutSeconds s,"
Write-Host "and it should start BootShim, which loads UEFI.elf from the EFIESP root."
Write-Host "If Windows still starts, make the entry the default instead:"
Write-Host "  bcdedit /store $store /default $entry"
