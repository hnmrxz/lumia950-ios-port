# 2026-11-24 the ADT's DRAM values disagreed with board.toml

`board.toml` states the board's memory as `dram_size = 0xAF600000` at `dram_base = 0`. The ADT this
port has been generating for the emulator and for the handset used `0xC0000000` at `0x80000000`,
which is neither the board's size nor its base.

The emulated report put the `skmem` fault at `0xfffffff0c6a15000`, about 3 GB above the kernel text
base, inside the kernel's address range but far outside the 48 MiB kext window `board.toml` describes
(comment at its prelink section). A memory map that disagrees with the board is exactly the kind of
thing that moves kernel allocations to addresses its pmap never maps, so the ADT is corrected first:

- CI's handset staging step now generates `--dram-size 0xAF600000 --dram-base 0`.
- The same values were used to regenerate the ADT staged for the handset.

This is a correction of a real inconsistency, not yet proof about the `skmem` fault: the next emulated
run with the corrected ADT is what decides that.
