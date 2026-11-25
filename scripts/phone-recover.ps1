# One command back to a bootable phone: flash the factory FFU, unlock, switch to mass storage.
#
# This is the path that works when the phone only reaches flash mode -- i.e. when the panel shows the
# Windows logo and reboots, or the firmware's service prompt. It is the same sequence used by hand
# earlier: FlashFFU (about 3 minutes for the 2.6 GB image), UnlockBootloader, SwitchToMassStorageMode.
#
#   powershell -ExecutionPolicy Bypass -File scripts\phone-recover.ps1 -Ffu "C:\path\to\RM1105_....ffu"
#   powershell -ExecutionPolicy Bypass -File scripts\phone-recover.ps1 -Ffu ... -SkipFlash
#
# The phone must be in flash mode before the flash step; the script says so and stops otherwise.
#
param(
    [Parameter(Mandatory = $true)][string]$Ffu,
    [string]$Tool = "C:\Users\Administrator\Downloads\win-x64\WPinternals.exe",
    [switch]$SkipFlash,
    [switch]$SkipUnlock
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Tool)) { throw "WPinternals.exe not found at $Tool" }
if (-not $SkipFlash -and -not (Test-Path $Ffu)) { throw "FFU not found at $Ffu" }

function Phone-Present {
    $lines = & pnputil /enum-devices /connected 2>&1
    return [bool]($lines | Select-String -Pattern 'Lumia BootMgr|Lumia_Flash|WinUsb' -Quiet)
}

function Wait-ForVolumes {
    param([int]$Seconds = 60)
    for ($i = 0; $i -lt $Seconds; $i += 5) {
        $volumes = Get-Volume | Where-Object { $_.FileSystemLabel -in @('EFIESP', 'MainOS') }
        if ($volumes) { return $volumes }
        Start-Sleep -Seconds 5
    }
    return $null
}

Write-Host "=== 1/3 factory image ==="
if ($SkipFlash) {
    Write-Host "skipped (-SkipFlash)"
} else {
    if (-not (Phone-Present)) { throw "the phone is not in flash mode; enter it before running this" }
    Write-Host "flashing $Ffu (this takes a few minutes)"
    $p = Start-Process -FilePath $Tool -ArgumentList @('-FlashFFU', "`"$Ffu`"") -PassThru -Wait
    Write-Host "FlashFFU exit: $($p.ExitCode)"
    if ($p.ExitCode -ne 0) { throw "FlashFFU failed; stop here and report the exit code" }
}

Write-Host "=== 2/3 unlock ==="
if ($SkipUnlock) {
    Write-Host "skipped (-SkipUnlock)"
} else {
    $p = Start-Process -FilePath $Tool -ArgumentList '-UnlockBootloader' -PassThru -Wait
    Write-Host "UnlockBootloader exit: $($p.ExitCode)"
}

Write-Host "=== 3/3 mass storage ==="
$p = Start-Process -FilePath $Tool -ArgumentList '-SwitchToMassStorageMode' -PassThru -Wait
Write-Host "SwitchToMassStorageMode exit: $($p.ExitCode)"

$volumes = Wait-ForVolumes
if ($volumes) {
    $volumes | Select-Object DriveLetter, FileSystemLabel | Format-Table -AutoSize | Out-Host
    Write-Host "done: the phone is back and its volumes are mounted"
} else {
    Write-Warning "no volumes appeared within a minute; the phone may need one power cycle"
}
