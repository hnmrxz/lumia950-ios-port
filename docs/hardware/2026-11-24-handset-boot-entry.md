# Boot entry and menu wait, 2026-11-24

The first handset boot went into Windows instead of the UniXNU menu. Two causes were found, both on
the EFI partition:

1. **The firmware still launched the stock loader.** `EFI\boot\bootarm.efi` was the 911,304-byte
   Microsoft boot manager; the payload had been installed beside it as `EFI\BOOT\BOOTAA64.EFI` and was
   never invoked. The stock loader was copied to `EFI\boot\bootarm.efi.stock` and `bootarm.efi` now
   holds `BOOTAA64.EFI` (verified: both files hash the same after the copy).
2. **The menu wait was short and its default entry exits.** `EFI\UniXNU\unixnu.toml` had
   `timeout = 20`, `fallback_timeout = 10`, `default = "exit"`, which hands control back to the
   firmware after 20 s. Both waits are 30 now, so the panel stays long enough to be read.

Still missing for a kernel boot: the configuration has no kernel entry yet (its marker line
`# stage-kernel.py: kernel entry` is untouched, because the tree came straight from the payload
artifact), while `EFI\UniXNU\Payloads\kernel.macho` and its `.adt` are present on MainOS. Producing
that entry locally needs `scripts/stage-kernel.py --unique-chip-id`, a per-handset value that is not
recorded here, so it was not guessed.

Rollback: write `EFI\boot\bootarm.efi.stock` back over `EFI\boot\bootarm.efi`; the original tree also
sits in `backups/efiesp-2026-11-24/`.
