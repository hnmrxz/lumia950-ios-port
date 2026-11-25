# One command back to a bootable, unlocked phone: factory image, donor FFU in the repository, unlock,
# then mass storage.
#
# The unlock patch (SecureBootHack-V2-EFIESP / -MainOS) resolves its reference version from the FFUs in
# WPinternals' repository, and for the Lumia 950 those reference versions come from the **950 XL**
# image -- which is why the Chinese flashing tool insists on a 950 XL FFU for every model. Without that
# donor the unlock is incomplete and the phone later falls into the Windows reset flow (the two gears)
# whenever the boot chain is touched.
#
#   powershell -ExecutionPolicy Bypass -File scripts\phone-recover.ps1 `
#       -Ffu   "C:\Users\Administrator\Downloads\RM1105_1078.0053.10586.13169.12716.035044_retail_prod_signed(1).ffu" `
#       -DonorFfu "C:\Users\Administrator\Downloads\RM1085_1078.0053.10586.13169.11302.034DF6_retail_prod_signed.ffu"
#
# Switches: -SkipFlash, -SkipUnlock, -NoWait
#
param(
    [Parameter(Mandatory = $true)][string]$Ffu,
    [string]$DonorFfu,
    [string]$Tool = "C:\Users\Administrator\Downloads\win-x64\WPinternals.exe",
    [switch]$SkipFlash,
    [switch]$SkipUnlock,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Tool)) { throw "WPinternals.exe not found at $Tool" }
if (-not $SkipFlash -and -not (Test-Path $Ffu)) { throw "FFU not found at $Ffu" }
if ($DonorFfu -and -not (Test-Path $DonorFfu)) { throw "donor FFU not found at $DonorFfu" }

function Run-Tool {
    param([string[]]$Arguments, [string]$What)
    Write-Host "> $What"
    $process = Start-Process -FilePath $Tool -ArgumentList $Arguments -PassThru -Wait
    Write-Host "  exit: $($process.ExitCode)"
    return $process.ExitCode
}

function Phone-Present {
    $devices = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.FriendlyName -match 'Lumia' }
    return [bool]$devices
}

function Wait-ForVolumes {
    param([int]$Seconds = 90)
    for ($i = 0; $i -lt $Seconds; $i += 5) {
        $volumes = Get-Volume | Where-Object { $_.FileSystemLabel -in @('EFIESP', 'MainOS') }
        if ($volumes) { return $volumes }
        Start-Sleep -Seconds 5
    }
    return $null
}

Write-Host "=== 0/4 preflight ==="
Write-Host "phone enumerated: $(Phone-Present)"
Write-Host "device FFU: $Ffu"
Write-Host "donor FFU : $(if ($DonorFfu) { $DonorFfu } else { '(none given)' })"

Write-Host "=== 1/4 repository ==="
if ($DonorFfu) {
    # The donor is what makes the unlock patch resolve; add it before any unlock attempt.
    $code = Run-Tool @('-AddFFU', "`"$DonorFfu`"") "AddFFU (950 XL donor)"
    if ($code -ne 0) { throw "AddFFU failed; the unlock would be incomplete without this donor" }
} else {
    Write-Warning "no donor FFU given: the unlock will only succeed if the repository already holds one"
}

Write-Host "=== 2/4 factory image ==="
if ($SkipFlash) {
    Write-Host "skipped (-SkipFlash)"
} else {
    if (-not (Phone-Present)) { throw "the phone is not in flash mode; hold Volume Down and power on" }
    $code = Run-Tool @('-FlashFFU', "`"$Ffu`"") "FlashFFU"
    if ($code -ne 0) { throw "FlashFFU failed; stop and report the exit code" }
}

Write-Host "=== 3/4 unlock ==="
if ($SkipUnlock) {
    Write-Host "skipped (-SkipUnlock)"
} else {
    $code = Run-Tool @('-UnlockBootloader') "UnlockBootloader"
    if ($code -ne 0) { throw "UnlockBootloader failed; the phone stays locked rather than half-unlocked" }
}

Write-Host "=== 4/4 mass storage ==="
if ($NoWait) { exit 0 }
$code = Run-Tool @('-SwitchToMassStorageMode') "SwitchToMassStorageMode"
$volumes = Wait-ForVolumes
if ($volumes) {
    $volumes | Select-Object DriveLetter, FileSystemLabel | Format-Table -AutoSize | Out-Host
    Write-Host "done: volumes are mounted; snapshot them before changing anything"
    Write-Host "  python scripts/phone-snapshot.py save --efiesp <EFIESP letter>:"
} else {
    Write-Warning "no volumes appeared within 90 s; the phone may need one power cycle"
}
