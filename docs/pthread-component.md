# The pthread component, and why the last link fails

This note records what is established about enabling `CONFIG_XNU_SOURCE_PTHREAD`, so the next
attempt starts from facts rather than from the guesses that were already disproved. Every claim here
was measured (run numbers included); nothing is inferred from documentation.

## What works

- `build-libpthread-kernel.py` from upstream (kept in `ci/libpthread/`) compiles libpthread's three
  kernel sources for this kernel's target, and the pin's version does not (it builds the Darwin 23
  component by construction) — runs 45189693913, 45208025816.
- The Darwin 22 source is `libpthread-519.101.1`; `git ls-remote` shows it is an annotated tag whose
  commit is `ba8e1488a0e6848b710c5daad2e226f66cfed656` (the tag object is `ea29c4ab…`, which is what
  the builder must **not** be given) — settled locally against the public repository.
- With both, the archive is built and the build gets as far as the XNU link.

## What fails, and the two symbols

The link reports exactly two undefined symbols:

```
_corecrypto_kext_start        referenced from _source_corecrypto14_bootstrap in prng_random.o
_native_legacy_display_probe  referenced from _bsd_init in bsd_init.o
```

- `corecrypto_kext_start` is referenced by **this repository's own patch** (`ci/unixnu-16x.patch`,
  the source corecrypto bootstrap). The framework only adds
  `prng_random.o_CFLAGS_ADD=-UXNU_SOURCE_CORECRYPTO14` in `prelinked` crypto mode; this port runs
  `source` mode, so the reference is compiled unconditionally (`build-xnu-4k-baseline.sh` line ~153).
- `native_legacy_display_probe` comes from **upstream's** `offline-component-load-probes.patch`
  calling into `bsd_init.c`; this repository only *defines* the symbol
  (`drivers/NativeLegacyDisplay/NativeLegacyDisplay.cpp`).

The failing link is the **bootstrap pass**, which exists only to leave compile records
(`== kernel: bootstrap pass for the compile records` in run 45213433912). It runs before any builder
and therefore without `CRYPTO_ARCHIVE` (line 546 is guarded by `BOOTSTRAP = 0`) and without the
force-loaded display archive.

## What was disproved

| Hypothesis | Evidence it is wrong |
|---|---|
| the archive list is incomplete | the framework appends everything to one variable; a probe echo would have shown it, and disabling the flag makes the same build succeed |
| the pthread source is the wrong Darwin line | switching to `libpthread-519.101.1` changed nothing about the two symbols (run 45213433912) |
| the builder overwrites `prng_random.o` / `bsd_init.o` | the builder writes `kern_*.o` and `source_pthread_bootstrap.o` into `build/libpthread-kernel/` only |
| the driver can be told to skip the bootstrap pass | an extra `XNU_BOOTSTRAP=1 XNU_CRYPTO_BOOTSTRAP=prelinked` build did not stop the real invocation's own bootstrap pass (run 45215870232) |
| `XNU_EXTRA_LD_ARCHIVES` can feed both passes | it can, but the archives do not exist yet during the bootstrap pass — a timing contradiction, not a flag problem |

## The two remaining ways

1. **Make the bootstrap pass not link.** Its only job is compile records; the link it now does is the
   side effect that fails. This needs a small change to the framework script, carried in
   `ci/unixnu-16x.patch` with the reason written down, and later offered upstream.
2. **Stop the builder depending on compile records.** It reads `prng_random.o.json` only for the
   compiler arguments; the same arguments can be derived from the defconfig and the SDK. This is
   local to `ci/libpthread/build-libpthread-kernel.py` and touches no framework code, at the cost of
   duplicating a little knowledge upstream already encodes.

Neither is attempted here: both need a decision about which side owns the change, and the port has
been building and gating correctly without the pthread component (the emulated boot reaches
`bsd_init` and its pthread panic is recorded in every run).

## The bootstrap pass cannot be given archives at all

EXTRA_MAKE_ARGS+=("LD_KERNEL_ARCHIVES=...") sits at the same indentation as the archive
assignments inside the BOOTSTRAP = 0 branch (lines 546-733 of uild-xnu-4k-baseline.sh), so the
records pass receives no LD_KERNEL_ARCHIVES whatsoever. Two attempts to feed it anyway are
therefore dead ends, and both were measured:

- exporting XNU_EXTRA_LD_ARCHIVES in the job: ignored, the harness sets it from the defconfig
  (run 45219103054);
- appending a weak stub object to the device copy of CONFIG_XNU_EXTRA_LD_ARCHIVES: the list is
  printed with the stub in it, and the link still reports the same two undefined symbols
  (runs 45225163325 and 45226537982).

That leaves exactly the two ways out listed above, and neither is a configuration change.
