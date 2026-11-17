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

## Running it locally (no CI, no Mac)

The fixture also runs on a plain Windows host, which is how the measurements below were taken
while the repository's Actions runs were unavailable:

```powershell
winget install --id SoftwareFreedomConservancy.QEMU -e
gh run download <RUN_ID> --repo hnmrxz/lumia950-ios-port -n lumia950-kernel -D out\kernel
gh run download <RUN_ID> --repo hnmrxz/lumia950-ios-port -n lumia950-stage  -D out\stage
python scripts\test-native-xnu-entry.py `
    --kernel "out\kernel\out\lumia950\tree\build\xnu\ios-obj\DEVELOPMENT_ARM64_BCM2837\mach.development.bcm2837.unstripped" `
    --esp out\stage --firmware "C:\Program Files\qemu\share\edk2-aarch64-code.fd" `
    --qemu "C:\Program Files\qemu\qemu-system-aarch64.exe" `
    --output out\local-qemu --timeout 240 --crypto-post --finish-iokit --adt-profile qemu
```

Windows has no emulator-side unix socket here, so the fixture speaks GDB over loopback TCP
(`--gdb-transport auto` picks it: tcp on Windows, unix on POSIX). A gate run takes about ten
seconds on TCG.

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

## What the profile changed (local, 2026-11-17)

With the bring-up ADT the kernel data-aborted inside `ArmCpu::mapGic()` (ESR `0x96000010`). With
the qemu profile the same kernel gets past it: the run reaches all seven milestones —
`arm_vm_init`, `kernel_bootstrap`, the source crypto POST returning 0, `PE_init_iokit` — with
**no exception** (ESR 0, no stop symbol) and then, instead of a fault, **the boot CPU goes idle**:

```
pc            _ml_get_speculative_timebase+0x14
stack         _processor_idle+0x170 → _idle_thread+0x3c → _Call_continuation+0x40
gdb           T02 (the fixture's own interrupt at the 240 s deadline)
bsd_init      never entered
```

So the next blocker is not a fault but a scheduling one: after IOKit the boot CPU runs the idle
thread and the bootstrap thread does not reach `bsd_init`. The obvious candidate is the timer and
interrupt path — `ArmCpu` programs the GIC and the timer, and the idle loop waits for an interrupt
that may never arrive in this machine. That is the next thing to measure: a breakpoint or counter
on the timer interrupt, and a check of whether the bootstrap thread is runnable at all.

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

The qemu profile answered one question and opened another: `mapGic` is behind us, and the boot CPU
now idles instead of faulting. What to measure next:

1. whether the timer interrupt is delivered at all in this machine (a breakpoint or a counter read
   on the interrupt entry path);
2. whether the bootstrap thread is runnable — `_bsd_init` is never entered, so either the thread is
   not scheduled or it is blocked before `bsd_init`;
3. only after that does the root volume question (`vfs_mountroot`) come up, because nothing in the
   emulated machine is an iOS root volume.

Each of those is a fixture change plus a run, not a hardware question.
