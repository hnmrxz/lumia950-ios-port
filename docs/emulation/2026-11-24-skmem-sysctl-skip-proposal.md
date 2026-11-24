# Proposed change: skip the skmem sysctl publication during bring-up

Status: **not applied**. Written down so the next attempt starts from a reviewable change rather than
another experiment.

## Why

The emulated boot stops at `_skmem_sysctl_init+0x18` with `past_bsd_outcome: stopped` and
`_vfs_mountroot` never reached, in three runs with three different ADTs and boot arguments
(docs/emulation/2026-11-24-skmen-sysctl-fault.md). The store is `sysctls->version`, the pointer comes
from the static `sk_sys_obj`, and `skmem_init` allocates that object and immediately calls this
initialiser -- with a panic if the allocation failed. The fault address moves with the memory map but
the faulting instruction does not, which is what "the region this object lives in has no mapping yet"
looks like.

Nothing in `skywalk_init()` can switch this off: it parses 38 `sk_*` boot arguments and none of them
gates the sysctl publication.

## The change

`bsd/net/skmem_sysctl.c`, at the top of the file:

```c
#include <pexpert/pexpert.h>

static int skmem_sysctl_skip = 0;

static void __attribute__((constructor)) skmem_sysctl_skip_bootarg(void)
{
	(void)PE_parse_boot_argn("skmem_sysctl_skip", &skmem_sysctl_skip,
	    sizeof(skmem_sysctl_skip));
}
```

and in `skmem_sysctl_init()`:

```c
	if (skmem_sysctl_skip) {
		return;
	}
```

## What it costs

The function only publishes skmem counters to the sysctl tree; it takes no part in mounting a root
volume. Skipping it keeps those counters invisible, which is harmless until a userland component looks
for them.

This is a bring-up bypass, not a fix. If the real cause is that the region has no mapping at this
point in BSD initialisation, the bypass hides it and it will resurface the first time anything else
touches that region -- so the note has to stay next to the patch and the patch has to go away once
`vfs_mountroot` is reached and the mapping question can be asked on its own.

## Wiring, which is where this stopped

The xnu differences for this port live in `ci/unixnu-16x.patch`, which patches the framework checkout;
the framework then applies its own xnu patch series while building. At the pinned framework commit the
`profiles/arch/arm64/patches/xnu` directory does not exist (it appears only in later commits, and even
there it holds a `series` file rather than a directory of patches), so there is no established place to
drop one more patch file.

Two ways forward, both small:

1. add the hunk to `ci/unixnu-16x.patch` next to the source-crypto hunk, which means reproducing the
   patch's exact context for this file; or
2. edit the fetched xnu source in the CI step that already edits the framework checkout, before the
   build copies it into its work tree -- cheaper to try, but it depends on the copy happening after
   that step, which is not established.
