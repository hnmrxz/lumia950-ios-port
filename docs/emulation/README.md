# What the emulation proves, and what it cannot

`scripts/test-native-xnu-entry.py` boots the real linked kernel under QEMU and reads its progress
with GDB breakpoints on real symbols. It is the only way this project can observe the kernel
executing without a handset, and this page is the boundary of that evidence.

## What a passing run means

Run 44003233713 is the reference. The fixture reached, in order:

```
arm_vm_init_entry → arm_vm_init_return
source_crypto_bootstrap_entry → return, status 0 (KERN_SUCCESS)
iokit_entry → iokit_return
kernel_bootstrap_entry
```

with the architectural counter at 19,200,000 Hz (the Lumia device-tree figure), `wfe_event_index`
4, and the report itself stating `emulator_only: true`, `handset_boot_observed: false`,
`ios_userspace_booted: false`. A CI step asserts those three fields, so an emulator result cannot
quietly become a handset claim.

## What it cannot mean

- **Not XNU-entry-tested.** That label needs the handset (`docs/evidence.json`).
- **Not a device.** QEMU's `virt` machine is not MSM8992: no eMMC controller, no MDSS, no Adreno,
  no PMIC, no SPMI, no RPM.
- **Not a boot past the interrupt controller with the phone's ADT.** With the staged bring-up ADT
  the kernel takes a data abort inside `ArmCpu::mapGic()` (ESR `0x96000010`): the ADT points the
  GIC at the Lumia's SoC windows and QEMU has no device there. That is why the fixture has
  `--adt-profile`.

## The qemu ADT profile

`board.toml [payload.adt.profiles.qemu]` keeps the bring-up shape (one CPU, no PSCI conduit, an
ownership bound) and moves the interrupt controller to where the emulated machine put one:
distributor `0x08000000`, CPU interface `0x08010000`.

Rules that keep it honest:

- it exists for the fixture only; both stagers emit no GIC window for `bringup` or `target`, which
  `scripts/test-adt-profile.py` pins;
- the fixture regenerates the ADT inside its temporary ESP copy and never writes into the staged
  artifact, and it runs `check-adt.py --profile qemu` on the result;
- `scripts/test-xnu-entry-adt.py` covers that step without QEMU.

## Reading a report

`out/xnu-entry/report.json` (gate) and `out/xnu-entry-bsd/report.json` (observation). Fields worth
starting from:

| Field | Meaning |
|---|---|
| `milestones` | the ordered sequence actually observed |
| `stop_symbols` | a breakpoint name, or `_fleh_synchronous` when the kernel took an exception |
| `pc_symbol` | the symbol the stop PC falls in, e.g. `_kernel_bootstrap_thread+0x224` |
| `fault_elr_symbol` | the faulting instruction's site, e.g. `__ZN6ArmCpu6mapGicEv+0x444` |
| `fault_far` | the address the faulting access touched |
| `system_registers.esr_el1` | `0x96000010` is a synchronous external abort on a data access |

## The next thing to measure

With the qemu profile the run should pass `mapGic`. Whatever it reports next is the next blocker —
the likely candidate is `vfs_mountroot`, because nothing in the emulated machine is an iOS root
volume. That measurement is what turns "it boots this far" into a plan.
