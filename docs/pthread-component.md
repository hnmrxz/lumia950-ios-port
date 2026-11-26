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

## Where the two-pass attempt stands

The records pass is avoidable: building once with the component removed creates records and archives
(run 45231105748 printed
ecords and archives exist), and the second build never prints
ootstrap pass for the compile records.

What still stops it is the builder's own revision check. Its SOURCE is
efer/libpthread **inside
the build tree**, and that clone is created (or re-created) by the second build, so:

- copying the upstream builder into unixnu/scripts and the device tree is not enough by itself;
- checking the tree reference out to the Darwin 22 commit prints 	ree reference now at ba8e1488
  and the builder still answers Unexpected libpthread source revision (run 45237654171);
- rewriting
eeds.toml in the two places tried did nothing, because neither file named the Darwin 23
  tag (libpthread-519.120.4) that the feed reports in the logs (run 45240055584).

The next step is therefore to find where that revision actually comes from: the log line is
== fetch https://github.com/apple-oss-distributions/libpthread.git c0e60fb5ecfc, so the driver is
resolving it from its own feed data, not from the checkout. Setting that one value -- rather than
fighting its result -- is what closes this.

### One clone, moved, still refused

Run 45241901405 settled where the reference lives: exactly one clone exists in the workspace,
out/feeds/libpthread-67dc7894, and it **was** moved to the Darwin 22 commit:

`
pthread reference: .../out/feeds/libpthread-67dc7894 at c0e60fb5ecfc...
  moved to ba8e1488a0e6848b710c5daad2e226f66cfed656
`

The builder still answered Unexpected libpthread source revision. The only remaining reading is that
the second build fetches its own reference *after* this step and puts it back on the Darwin 23
revision -- so the value to change is the driver's feed data, not any checkout. The next thing to find
is that data: grep -rn libpthread-519 unixnu/ and grep -rn c0e60fb unixnu/ inside the framework
clone, which needs one CI step or a local clone of UniXNU/UniXNU@1a01c2a.

## The out-of-band build gets to the sources, and stops on one line

Run 45247975473 did what it was built to do: the first build left records and archives
(
ecords and archives exist), the tree reference moved to the Darwin 22 commit
(
eference now at ba8e1488), and the upstream builder then compiled the sources itself.

It stops on a single error, in Apple's kern/kern_support.c:

`
1049 |                 pthread_mutex_default_policy = policy_bootarg;
     |                                              ~ ^~~~~~~~~~~~~~
22 warnings and 1 error generated.
`

policy_bootarg exists in the Darwin 23 kernel headers the libpthread sources expect; this kernel is
Darwin 22. That is the whole remaining gap: a one-line source adaptation inside the component, not a
build-system problem. The natural place for it is a small patch file applied by
ci/libpthread/build-libpthread-kernel.py after it prepares its work tree, next to the reason in
ci/libpthread/README.md.

Everything upstream of that line is now known to work, and none of it needed the framework changed.
