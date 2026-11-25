# Restore Windows booting, or retarget the entry the manager actually starts. Run as Administrator.
#
# What the handset's store holds (read from the owner's `bcdedit /enum all`):
#
#   {bootmgr}   device R:  path \efi\boot\bootarm.efi  default {default}  bootsequence {01de5a27…}
#   {default}   Windows Loader        device F:  path \windows\system32\boot\winload.efi
#   {01de5a27…} Mobile Startup App    device R:  path \windows\system32\boot\mobilestartup.efi
#
# Pointing {default} at BootShim produced "Windows logo -> gears -> reboot", i.e. the manager fell back
# to its boot sequence and the phone's own reset flow took over. So:
#
#   -Restore        put {default} back on the Windows loader and stop the loop
#   -RetargetStart  keep {default} as Windows but aim the *start app* at BootShim instead, which is the
#                   entry the boot sequence runs; -RevertStart puts mobilestartup.efi back
#
param(
    [Parameter(Mandatory = $true)][string]$Efiesp,
    [switch]$Restore,
    [switch]$RetargetStart,
    [switch]$RevertStart
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

$startApp = "{01de5a27-8705-40db-bad6-96fa5187d4a6}"

if ($Restore) {
    Bcd @("/set", "{default}", "device", "partition=F:") | Out-Host
    Bcd @("/set", "{default}", "path", "\windows\system32\boot\winload.efi") | Out-Host
    Bcd @("/set", "{default}", "osdevice", "partition=F:") | Out-Host
    Bcd @("/set", "{default}", "systemroot", "\windows") | Out-Host
    Bcd @("/set", "{default}", "description", "Windows Loader") | Out-Host
    Bcd @("/timeout", "0") | Out-Host
    Bcd @("/set", "{bootmgr}", "displaybootmenu", "No") | Out-Host
    Write-Host "=== restored ==="
    Bcd @("/enum", "{default}") | Out-Host
    exit 0
}

if ($RetargetStart) {
    Bcd @("/set", $startApp, "path", "\EFI\boot\BootShim.efi") | Out-Host
    Write-Host "start app now points at BootShim; the Windows loader entry is untouched"
    Bcd @("/enum", $startApp) | Out-Host
    exit 0
}

if ($RevertStart) {
    Bcd @("/set", $startApp, "path", "\windows\system32\boot\mobilestartup.efi") | Out-Host
    Bcd @("/enum", $startApp) | Out-Host
    exit 0
}

Write-Host "nothing to do: pass -Restore, -RetargetStart or -RevertStart"
