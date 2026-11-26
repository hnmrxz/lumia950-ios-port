# Create the BootShim entry and make it the boot manager's default. Run as Administrator.
#
# The store on this handset (read with -EnumerateOnly first) looks like this:
#
#   {bootmgr}   device partition=R:  path \efi\boot\bootarm.efi  default {default}  timeout 0
#   {default}   Windows Loader       device partition=F:         path \windows\system32\boot\winload.efi
#   {01de5a27…} Mobile Startup App   device partition=R:         path \windows\system32\boot\mobilestartup.efi
#
# There is no display order and the manager boots a sequence, so the reliable way to start something new
# is to point the manager's `default` at it. That is all this script changes:
#
#   1. creates an osloader entry whose path is \EFI\boot\BootShim.efi on EFIESP;
#   2. sets that entry as {bootmgr} default, with a 10 s timeout and the boot menu on;
#   3. prints the store afterwards.
#
# Restore with:  bcdedit /store R:\EFI\Microsoft\BOOT\BCD /default {default}
# and if that is not reachable, reflash the FFU: the handset recovers from that.
#
param(
    [Parameter(Mandatory = $true)][string]$Efiesp,
    [string]$Title = "BootShim (UEFI.elf)",
    [int]$TimeoutSeconds = 10,
    [switch]$Restore
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this in an elevated PowerShell."
}

$letter = $Efiesp.TrimEnd(":")
$store = "${letter}:\EFI\Microsoft\BOOT\BCD"
if (-not (Test-Path $store)) { throw "$store is missing" }

function Bcd { param([string[]]$Arguments) & bcdedit /store $store @Arguments 2>&1 }

if ($Restore) {
    Bcd @("/default", "{default}") | Out-Host
    Bcd @("/timeout", "0") | Out-Host
    Bcd @("/set", "{bootmgr}", "displaybootmenu", "No") | Out-Host
    Bcd @("/enum", "{bootmgr}") | Out-Host
    Write-Host "restored: the manager boots Windows again"
    exit 0
}

# An existing entry for the shim would otherwise be created twice.
$enum = (Bcd @("/enum", "all")) -join "`n"
$existing = [regex]::Matches($enum, "\{([0-9a-fA-F\-]{36})\}[^\{]*?BootShim") |
    ForEach-Object { "{" + $_.Groups[1].Value + "}" } | Select-Object -First 1

if ($existing) {
    $entry = $existing
    Write-Host "reusing existing BootShim entry $entry"
} else {
    $create = (Bcd @("/create", "/d", $Title, "/application", "osloader")) -join "`n"
    Write-Host $create
    $match = [regex]::Match($create, "\{([0-9a-fA-F\-]{36})\}")
    if (-not $match.Success) { throw "bcdedit did not report a new identifier; paste the output above" }
    $entry = "{" + $match.Groups[1].Value + "}"
    Write-Host "created $entry"
}

Bcd @("/set", $entry, "device", "partition=${letter}:") | Out-Host
Bcd @("/set", $entry, "path", "\EFI\boot\BootShim.efi") | Out-Host
Bcd @("/set", $entry, "description", $Title) | Out-Host

Bcd @("/set", "{bootmgr}", "default", $entry) | Out-Host
Bcd @("/set", "{bootmgr}", "displaybootmenu", "Yes") | Out-Host
Bcd @("/timeout", "$TimeoutSeconds") | Out-Host

Write-Host "=== result ==="
Bcd @("/enum", "{bootmgr}") | Out-Host
Bcd @("/enum", $entry) | Out-Host

Write-Host ""
Write-Host "Reboot with the cable detached. The manager should start $entry -> \EFI\boot\BootShim.efi,"
Write-Host "which loads UEFI.elf from the EFIESP root."
Write-Host "Restore Windows booting with: -Restore"
