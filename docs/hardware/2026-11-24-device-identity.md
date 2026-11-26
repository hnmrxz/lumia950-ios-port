# Device identity, and why it does not produce the ADT chip identifier

Recorded by the owner: the handset is an **RM-1105** (Lumia 950, MSM8992), product code 059X4d5.
The IMEI is deliberately **not** written here: this repository is public, and the port's own rules keep
private identifiers out of it.

## What this settles

The model is the one this board describes (`board.toml`: MSM8992, 3 GB DRAM at `0xAF600000`, the 48 MiB
kext window), so the ADT and the linker settings already point at the right hardware.

## What it does not settle

`stage-kernel.py --unique-chip-id` wants the SoC's unique identifier -- a hardware value produced by the
chip itself -- not a product code and not an IMEI. There is no mapping from an IMEI to that value, and
inventing one would put a wrong identifier into the device tree without saying so.

The ADT installed on the phone therefore still carries `0000000000000000`. Two consequences, and one
non-consequence:

- the menu, DarwinBoot and the loading of the kernel on MainOS do not read that field, so the EFI stage
  can be tested as it stands;
- anything that keys off the device identity later (activation, per-device keys) would see the wrong
  value, so a kernel that stops early must not be blamed on the kernel alone;
- how the kernel *starts* does not depend on it, which is why the boot test is still the next step.

## Where the real value would come from

Either the handset's own firmware tooling shows it (WPinternals' device panel is the usual place) or a
runtime reader does once a kernel runs far enough to expose it. Both are later than the boot test that
is still outstanding.
