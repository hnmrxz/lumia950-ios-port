# 2026-11-24 - the emulated kernel now stops inside `skmem_sysctl_init`

Run 45314032032 (branch `probe/pthread-darwin22`) is the first run whose image links the pthread
component; its archived report (`lumia950-xnu-entry`) records:

```
"past_bsd_outcome": "stopped",
"watched": { "_vfs_mountroot": false },
"fault_elr_symbol": "_skmem_sysctl_init+0x18",
"fault_far": "0xfffffff0c6a15000"
```

`bsd_init` therefore returned (the report is `stopped`, not `panicked` on the pthread provider), the
kernel brought up `dlil_init`, and it then took a data abort inside `skmem_sysctl_init` -- before
`vfs_mountroot` was ever reached, which is why that watch stayed false.

`0xfffffff0c6a15000` is outside this kernel's VA window (text base `0xfffffff007004000`), so the
fault is a dereference of a pointer that was never valid, not an unmapped-but-plausible address.

## What this changes about "next"

The next blocker toward a root volume is no longer the pthread component: it is this sysctl
initialisation. Two candidates to check, in order:

1. the `skmem` tunables this kernel registers are expected to be backed by a provider that the
   emulated device tree does not describe (`SK[0]: skmem_region_init ...` is the last dmesg line);
2. a Darwin 22/23 structure difference in the same area the pthread component needed two adaptations
   for.

## What the source says

`bsd/net/skmem_sysctl.c` (xnu-8796.141.3) is 57 lines, and its whole init is:

`` 
skmem_sysctl *sysctls = skmem_get_sysctls_obj(NULL);
sysctls->version = SKMEM_SYSCTL_VERSION;
`` 

`skmem_get_sysctls_obj` in `bsd/skywalk/mem/skmem.c` returns the static `sk_sys_obj`, which `skmem_init(void)` sets. Nothing in that path checks the pointer, so the store faults when the object is absent -- which is what the report's `_skmem_sysctl_init+0x18` and a FAR outside the kernel VA window describe. The two candidates therefore collapse into one: this kernel reaches the sysctl initialiser with `sk_sys_obj` unset, so either `skmem_init` did not run (the dmesg line `SK[0]: skmem_region_init` is not proof that it finished) or it ran after it. The next experiment is to make that ordering visible in the fixture rather than patch Apple code blind.
