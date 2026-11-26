# Restoring the handset from raw partition images, 2026-11-25

## Why this exists

Every failed boot experiment on this phone ends the same way: Windows starts, the two gears appear, and
the phone reboots instead of reaching the OS. In that state **mass storage mode is unreachable** -- the
owner's report, repeated across a day of attempts, is that only flash mode (the panel showing a single
`!`) can be entered. The vendor utility restores mass storage, but each cycle costs a full image write
plus an unlock.

## What was captured

The phone appears in mass storage mode as a USB disk (`MSFT Phone MMC Stor`, 29.12 GB) and its volumes
can be read through their device handles without an elevated token, so the two partitions the unlock
patches live on were dumped as raw images **in the unlocked state**:

| image | bytes | sha256 |
|---|---|---|
| `out/phone-backups/unlocked-efiesp.img` | 16,777,216 | `1e9b2ff31601769b7ddd3749ac24c444f64213767d66874512bbd09a140f71e9` |
| `out/phone-backups/unlocked-mainos.img` | 2,999,971,840 | `64955e166a1752db5117b8cf30eb90f2a68e65e75fe139d0c0a1487e4deffb8a` |

Both were produced by `scripts/phone-image.py dump`, which reads `\\.\R:` / `\\.\F:` and prints the hash
as it goes.

## The restore that matches the failure mode

`-FlashPartition` works in **flash mode**, which is the only mode available after a failure:

```
# phone on the "!" screen, cable attached
python scripts/phone-image.py restore --partition EFIESP --image out/phone-backups/unlocked-efiesp.img --apply
python scripts/phone-image.py restore --partition MainOS --image out/phone-backups/unlocked-mainos.img --apply
```

**Both partitions must be restored together.** A single-partition restore is what produced the longest
loop of the day: the factory EFIESP image was written back while MainOS still carried the unlock patch,
and the mismatch (stock boot files beside a patched OS) put the phone straight back into the gears loop.
The images above are a matched pair by construction -- they were taken from the same booted, unlocked
phone minutes apart.

## What is still unproven

The write direction of this pair has not been exercised yet. `-FlashPartition EFIESP` was used earlier
with the factory image and returned exit 0 with the phone booting afterwards, so the mechanism works; the
images here are the same size and shape, but the claim "restoring both images returns the phone to the
unlocked state without the vendor utility" stays **unverified** until one restore cycle has been done.

Until then the fallback remains the full FFU flash (`scripts/phone-recover.ps1`), which needs the vendor
utility for the unlock afterwards.

## Related limits

- `\\.\PhysicalDrive1` needs an elevated token, so a disk-level image (and therefore a homemade FFU via
  the vendor's `Img2Ffu.exe`) is not available from this session.
- The vendor install ships `thor2.exe`, `ffutool.exe`, `emmcdl.exe` and `Img2Ffu.exe`;
  `scripts/phone-tools.py` locates them and `scripts/phone-thor2.py` drives thor2's emergency and FFU
  modes with a dry run by default.
