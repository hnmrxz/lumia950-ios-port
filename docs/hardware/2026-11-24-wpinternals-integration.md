# Driving WPinternals from the checkout

`scripts/phone-modes.py` forwards the switches the tool already implements (upstream
`WPinternals/CommandLine.cs`), so switching modes no longer means clicking through the window.

```
python scripts/phone-modes.py info              # ShowPhoneInfo, read-only
python scripts/phone-modes.py mass-storage --apply
python scripts/phone-modes.py unlock --apply
python scripts/phone-modes.py root --apply
python scripts/phone-modes.py fix-boot --apply
python scripts/phone-modes.py uefi-dump --out out/uefi --apply
```

The wrapper prints the exact command line it runs, and refuses every switch that changes the phone
unless `--apply` is given. The default tool path is
`C:\Users\Administrator\Downloads\win-x64\WPinternals.exe`; `--tool` overrides it.

## Why the switches are these

The upstream command parser accepts: `ShowPhoneInfo`, `SwitchToMassStorageMode`, `UnlockBootloader`,
`EnableRootAccess`, `FixBootAfterUnlockingBootloader`, `DumpUEFI`, `FlashFFU`, `FlashCustomROM`,
`Rewritepartitionsfrommassstorage`, `Restoregptusingmassstorage`, the GPT group
(`ReadGPT`/`BackupGPT`/`RestoreGPT`/`MergeGPT`/`ConvertGPT`), `DumpFFU`, **`AddFFU`** (adds an FFU to the
reference repository the unlock patch resolves against), and a few diagnostics. Only the ones this port needs
are exposed, so a typo cannot reach a destructive switch.

The switch spellings are the case labels of `CommandLine.cs` in the upstream project (`case "flashffu"`,
`case "addffu"`, ...), so the invocation is case-insensitive: `-AddFFU` and `-addffu` reach the same handler.
`scripts/phone-recover.ps1` uses `AddFFU` for the donor image, which is checkable against that file rather
than against this list.

## What it does not solve

`SwitchToMassStorageMode` needs the phone connected and already past the point where the tool can talk
to it; if the phone sits on the firmware's service prompt, that prompt itself accepts a key press to
shut down, and the next power-on with USB detached is what the boot test actually needs.

## How it is integrated

- `scripts/phone-modes.py` is the only place that runs the tool; `scripts/test-phone-modes.py` covers it and `scripts/run-tests.py` runs that test in the self-contained set (24/24 pass).
- The binary is **not** committed: it is 136 MB and not this project's to redistribute. Its location comes from `--tool`, then `WPINTERNALS_EXE`, then the default install path, then PATH.
- Only the switches this port needs are exposed. The destructive ones (FlashFFU, FlashCustomROM, the GPT group, RestoreGPT) stay out of the wrapper on purpose.

