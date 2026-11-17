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
**no exception** (ESR 0, no stop symbol) and then it stops progressing without faulting.

The fixture now has two probes for that situation, and they named the blocker:

```
--watch _thread_block   hit:  pc _thread_block, x30 _lck_mtx_sleep+0x78
                        stack _ml_wait_max_cpus+0x64 ... _max_cpus_lock
--watch _fleh_irq       never hit over 45 s
--watch _fleh_fiq       never hit
--read  _max_cpus_initialized   = 2
--read  _real_ncpus             = 1
```

The 2 is not a CPU count: in `osfmk/arm/machine_routines_common.c` the loop is
`while (max_cpus_initialized != MAX_CPUS_SET)` with `MAX_CPUS_SET 0x1` and `MAX_CPUS_WAIT 0x2`, so
the value says "one thread is asleep waiting". It is woken only by `ml_set_max_cpus()`, whose caller
is `IOCPUInterruptController` in `iokit/Kernel/IOCPU.cpp` — the wait is for the platform interrupt
controller to register.

That never happens, and three more watches show why:

```
ArmCpu::start                     hit
ArmCpu::prepareGic                hit
gicv2::Controller::prepareDistributor  hit
gicv2::Controller::prepareLocal   never
gicv2::Controller::enableLocal    never
ArmCpu::enableGic / initCPU       never
```

`prepareGic()` is `mapGic -> prepareDistributor -> prepareLocal` (see `drivers/NativeGicV2/ArmCpu.patch`),
and `||` short-circuits: `prepareDistributor()` returned false, so everything after it — the CPU
interface, the local IRQ enable, the CPU registration — never ran. No CPU interrupt source exists,
so no IRQ is ever delivered, so nothing wakes the sleeping thread, and `bsd_init` is never entered.

`docs/emulation/2026-11-17-local-qemu-max-cpus-block.json` is the trimmed report, with the source
citations for each step.

The next question is therefore narrow: **which condition inside `prepareDistributor()` returns
false.** Its `fail()` and `verify()` helpers are inlined in the kernel build, so they have no
symbols; instead the fixture stops at the instruction after the call (`--break-at`, using the
return address it captured) and reads the controller's own state from `__ZL3gV2`:

```
x0 at the return site          0        (prepareDistributor returned false)
bound                          1
distributed                    0
interrupts                     288      (GICD_TYPER)
distributor PIDR2              0x2b     (GICv2, revision 3)
lastError                      4        (InvalidCpuTarget)
```

So the failing check is the CPU-target probe: it ORs `GICD_ITARGETSR` 0x800..0x81f and rejects a
zero result. QEMU's `hw/intc/arm_gic.c` returns zero for that whole range **only when the machine
has one CPU** ("For uniprocessor GICs these RAZ/WI"); with two or more it reports the CPU mask for
the banked range. The handset GIC is multiprocessor, so the probe is probably right on hardware and
this was an emulator configuration, not a port bug.

That is what `--smp` is for. With `--smp 2` the run goes further than any earlier one:

```
milestones: ... iokit_return, bsd_init_entry
watched:    prepareLocal hit (it was never reached with --smp 1)
stop:       _panic
panic:      "pthread kernel extension not loaded (function table is NULL). @%s:%d"
```

**The kernel enters `bsd_init`** — the last milestone before a root volume is needed — and then
panics because the pthread kext never registered its function table. The linked image does contain
`_pthread_functions`, `_pthread_kext_register` and the kext's symbols, so the gap is startup and
registration, not the link.

`docs/emulation/2026-11-17-local-qemu-bsd-init-panic.json` is the trimmed report.

The next question: **why the pthread kext does not start.** The answer is in the kernel artifact,
not in the emulator: `out/lumia950/kernel/kernel.json` lists exactly the nine components the
prelink merged, and the pthread kext is not one of them.

```
com.apple.AppleFSCompression.AppleFSCompressionTypeZlib  com.apple.driver.AppleEffaceableStorage
com.apple.filesystems.apfs                              com.apple.iokit.CoreAnalyticsFamily
com.apple.iokit.IOCryptoAcceleratorFamily                com.apple.iokit.IOStorageFamily
com.apple.kec.corecrypto                                com.apple.kext.CoreTrust
com.apple.security.AppleImage4
```

`board.toml [kernel.prelink] roots` names four of those, and the prelink adds what they declare as
libraries. The pthread kext is nobody's library dependency, so it is not in the closure, its start
routine never runs, `pthread_kext_register()` is never called, and `_pthread_functions` stays NULL.

The fix is a configuration flag, and the framework names it: `XNU_SOURCE_PTHREAD` builds
`build/libpthread-kernel/libpthread_kernel.a` and, with `patches/xnu/source-pthread-bootstrap.patch`,
registers it through `STARTUP(EARLY_BOOT, STARTUP_RANK_SECOND, source_pthread_bootstrap)`, which
calls `pthread_start()` so the function table is filled before `bsd_init`. `configs/lumia950_defconfig`
did not set it, so the component was never built.

```
image symbols              _pthread_functions, _pthread_kext_register   (the xnu shims)
                           pthread_start, source_pthread_bootstrap      ABSENT
```

`configs/lumia950_defconfig` now sets `CONFIG_XNU_SOURCE_PTHREAD=y`, and
`scripts/test-native-bringup.py::test_the_pthread_provider_must_stay_in_the_configuration` fails if
it disappears. What is not done is the verification: linking the source component needs the macOS
kernel job, so the next real image is the proof, not this repository state.

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
