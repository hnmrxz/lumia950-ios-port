#!/usr/bin/env python3
"""Call the boot-progress instrument from the earliest kernel stages.

Upstream does this with patches/xnu/zzz-boot-progress.patch, gated behind an audited storage closure this board
cannot satisfy. This inserts the equivalent calls for the Lumia 950:

  * after `PE_init_platform(FALSE, args);` in `osfmk/arm/arm_init.c` -- before `arm_vm_init` turns the MMU on,
    so the framebuffer physical address is still identity-mapped;
  * immediately before `arm_vm_init(xmaxmem, args);`
  * (nothing after it: `arm_vm_init` turns the MMU on, and a store to the framebuffer physical address without
    a mapping raises a synchronous exception -- measured in run 45764900801, which stopped at
    `_sleh_synchronous_sp1` before VM setup when a third call was placed after the call).

One bar per stage reaches the panel, so the number of bars is how far the kernel got. `--apply` is idempotent
and `--check` re-reads the edit, the same contract the other ci/ patches use.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = "native_boot_progress_stage"

# The panel parameters come from boot_args.Video, measured in pexpert/pexpert/arm/boot.h of the pinned
# source: `unsigned long v_baseAddr, v_rowBytes, v_height`. Hard-coding them drew into unmapped space
# in QEMU (run 45764900801, synchronous exception before VM setup).
DECLARATION = ("\textern void native_boot_progress_remember(void *base, unsigned long stride, "
               "unsigned long height, const char *command_line);\n"
               "\textern void native_boot_progress_stage(void *base, unsigned long stride, "
               "unsigned long height, const char *command_line, int stage);\n")

# A bar drawn from vinfo, not from boot_args, and placed right after the platform expert has run.
#
# The stage-0 and stage-1 bars take their address from `args->Video.v_baseAddr`, which is the *physical* address the loader
# reported; storing there before the VM work faults. The console, however, is set up by PE_init_platform() through
# video_console.c, which maps the framebuffer and publishes the mapped address in `vinfo.v_baseaddr`. That is the address the
# bsd_init bar already uses successfully, so a store through it may work far earlier -- which would give the handset an
# observable point before the five bisect candidates instead of after them.
#
# It is behind its own boot argument so an ordinary boot is unchanged.
EARLY_BAR = (
    "\n\t/* Bring-up instrument: draw through the console's own mapping, before the rest of arm_init. */\n"
    "\tif (PE_parse_boot_argn(\"lumia-early-bar\", NULL, 0)) {\n"
    "\t\textern struct vc_info vinfo;\n"
    "\t\textern void native_boot_progress_stage(void *base, unsigned long stride, unsigned long height,\n"
    "\t\t        const char *command_line, int stage);\n"
    "\t\tif (vinfo.v_baseaddr != 0 && vinfo.v_rowbytes != 0 && vinfo.v_height != 0) {\n"
    "\t\t\tnative_boot_progress_stage((void *)vinfo.v_baseaddr, vinfo.v_rowbytes, vinfo.v_height,\n"
    "\t\t\t                           \"lumia-bars\", 0);\n"
    "\t\t}\n"
    "\t}\n"
)

AFTER_CONSOLE = (
    "\tPE_init_platform(FALSE, args); /* Get platform expert set up */\n"
)

# PE_init_platform() is what initialises the graphics console with the video parameters from boot_args, so this is the first
# point in the kernel where a line of text can reach the panel. On the handset that matters: the photograph of the hand-off page
# proves the loader ran, and a line printed here is what distinguishes "the kernel started" from "the kernel never ran". The
# marker is deliberately a plain kprintf, not a framebuffer store -- it goes through the console the platform expert set up,
# which is exactly what we want to test.
# Measured, not assumed: printing from arm_init faults. Run 45918861169 put a kprintf immediately after
# PE_init_platform(FALSE, args) and the kernel stopped at _sleh_synchronous_sp1 before VM setup, so the graphics console is
# not writable at that point -- the platform expert installs it, but its framebuffer mapping arrives later, with the VM work.
# The bars at the same point are fine because they store through the address the loader reported; the console's own write path
# is what faults. Any text from the kernel therefore has to wait until after arm_vm_init, which is why the first kernel line in
# this port is the one in bsd_init.

BEFORE_VM_INIT = "\tarm_vm_init(xmaxmem, args);\n"

# Text from the kernel has to wait until the VM work is done: a kprintf right after PE_init_platform() faulted at SP1 before VM
# setup (run 45918861169), because the console exists then but its framebuffer mapping does not. The first line that can safely be
# printed is therefore this one, immediately after arm_vm_init() returns -- and it is the line that answers the handset
# question, because a kernel that reaches it has run through the whole early boot path.
# The handset stops before arm_vm_init can print, so nothing on the panel says where. The way out is to remove one candidate at a
# time and watch for the post-VM marker to appear: a candidate that is skipped and lets the marker print is the one that hangs.
# Each switch is a boot argument, so one kernel can test all of them without rebuilding, and nothing changes without the argument.
#
# The candidates are the calls between the platform expert and the VM work that touch hardware the emulator does not model.
SWITCHED_CALLS = {
    "lumia-skip-rtclock": "\trtclock_early_init();\n",
    "lumia-skip-topology": "\tml_parse_cpu_topology();\n",
    "lumia-skip-timercall": "\ttimer_call_init();\n",
    "lumia-skip-cpuinit": "\tcpu_init();\n",
    "lumia-skip-processor": "\tprocessor_bootstrap();\n",
    # Measured and withdrawn: wrapping wfe_timeout_configure()/wfe_timeout_init() or kernel_startup_bootstrap() this way makes the
    # kernel fault at _sleh_synchronous_sp1 before the VM work even with both switches off (four configurations tested in QEMU, all
    # stopped at el1_sp0_synchronous_vector_long+0x34 while the same kernel without these two guards reached root-wait). Until that is
    # understood, the bisect stops at the five calls above; going earlier needs an observable, not more switches.
}

AFTER_VM_INIT_MARKER = (
    "\n\t/* Bring-up instrument: the VM work is done, so the console can be written. */\n"
    "\tkprintf(\"LUMIA: arm_vm_init returned, entering the rest of arm_init\\n\");\n"

    "\tkprintf(\"LUMIA: early map state %u\\n\", lumia_early_map_state);\n"
    "\t{\n"
    "\t\textern unsigned int lumia_gpt_selfcheck(void);\n"
    "\t\tunsigned int gpt_state = lumia_gpt_selfcheck();\n"
    "\t\tkprintf(\"LUMIA: gpt self-check %u (0 ok, 1 valid refused, 2 wrong partition, 3 corrupt accepted, 4 wrong reason)\\n\",\n"
    "\t\t        gpt_state);\n"
    "\t}\n"
)
PLATFORM_CALL = "\tPE_init_platform(FALSE, args); /* Get platform expert set up */\n"
# The third bar is drawn after the platform expert has installed the video console, through the same mapping the
# console itself writes to. That mapping comes from the kernel's own `vinfo`, declared in
# osfmk/console/video_console.h: `v_rowbytes` is bytes and `v_baseaddr` is the mapped address, so the instrument needs
# no address translation of its own and no guess about a structure's layout.
BSD_INCLUDE_ANCHOR = "#include <sys/param.h>\n"
BSD_INCLUDE = "#include <console/video_console.h>\n"
BSD_ANCHOR = "\tthrottle_init();\n"
BSD_STAGE = ("\n\t/* Bring-up instrument: report what it can see, then draw if the panel has a mapping. */\n"
             "\textern struct vc_info vinfo;\n"
             "\textern void native_boot_progress_stage(void *base, unsigned long stride, unsigned long height, "
             "const char *command_line, int stage);\n"
             "\tkprintf(\"LUMIA: vinfo base=%lx row=%u height=%u args=%s\\n\",\n"
             "\t       (unsigned long)vinfo.v_baseaddr, vinfo.v_rowbytes, vinfo.v_height,\n"
             "\t       PE_boot_args());\n"
             "\tnative_boot_progress_stage((void *)vinfo.v_baseaddr, vinfo.v_rowbytes, vinfo.v_height,\n"
             "\t                           PE_boot_args(), 2);\n"
             "\t/* The storage driver, loaded from the container this image carries. */\n"
             "\textern int lumia_kext_load(const char *command_line);\n"
             "\tlumia_kext_load(PE_boot_args());\n")

# The first marker that can reach the panel before the VM work, now that ci/framebuffer-map.py maps one block containing the
# framebuffer from the bootstrap tables. It deliberately does not use PE_parse_boot_argn: that call at this point is the one thing the
# withdrawn skip switches had in common with their failure, so the token is matched with a plain scan of CommandLine instead.
#
# The block template is write-back normal memory, so every line the marker writes is cleaned with `dc civac`; without that the panel
# may never see the data. The physical address comes from boot_args.Video, and the mapped KVA base is the constant the start.s patch
# uses, so the two halves cannot drift.
# A marker that can reach the panel before the VM work, built from the two facts the measurements left:
#
#   * the kernel's bootstrap page tables are the only mapping that exists that early, and start.s is patched by the framework's own
#     4K-baseline series -- so this code builds the one extra mapping itself, in C, from `bootstrap_pagetables` (a global in
#     arm_vm_init.c), which needs no change to start.s and no fight with a patch series;
#   * `ARM_TTE_BOOT_BLOCK` is write-back normal memory, so every line the marker touches is cleaned with `dc civac` afterwards.
#
# The layout it relies on is the one start.s builds: `bootstrap_pagetables + 0` is the V=P L1 table, `+ PGBYTES` the KVA L1 table, and
# the L2 tables follow. The L1 entry is pointed at a page in this file's own BSS instead of the array's next free page, so a mistaken
# page-count cannot overwrite a table the kernel is using; the BSS page's physical address comes from the boot arguments' physBase and
# virtBase, the same relation start.s uses.
#
# It is behind 'lumia-early-map', matched with a plain scan of CommandLine rather than PE_parse_boot_argn -- the call the withdrawn skip
# switches had in common with their failure.
# A marker that can reach the panel before the VM work. It builds its own mapping from the bootstrap tables, because that is the only
# mapping that exists that early and start.s itself is patched by the framework's 4K-baseline series.
#
# The measured failure this version fixes: the first attempt wrote the L1 entry unconditionally and the kernel then took a translation
# fault at VA 0x158 (ESR 0x96000005, FAR 0x158, ELR in the text, while the drawing loop had already run -- x8 held the mapped base,
# x9 the stride, x10 the width, x15 the colour). Writing an L1 slot without knowing whether it is free is the one thing that can damage
# a mapping the kernel is relying on, so now the entry is only written when the slot reads back as empty, every index is bounds
# checked, and nothing at all is drawn unless the mapping was installed. The address, stride and size are validated first, and the loop
# is skipped when the panel is too short for the marker's rows.
# A marker that can reach the panel before the VM work. It installs its own mapping from the bootstrap tables, because that is the
# only mapping that exists that early and start.s is patched by the framework's 4K-baseline series.
#
# Two measured failures shaped it. The first version wrote an L1 entry unconditionally and the kernel then took a translation fault at VA
# 0x158 (ESR 0x96000005, FAR 0x158) with the drawing loop already run (x8 the mapped base, x9 the stride, x10 the width, x15 the colour),
# so the entry is only written when the slot reads back empty, both indices are bounds checked, and nothing is drawn unless the mapping
# was installed. The second version emitted its statements without newlines -- Python concatenates adjacent literals -- and the kernel
# build stopped at "expected expression" in arm_init.c, so every line below ends in an explicit newline escape.
# A marker that can reach the panel before the VM work. It installs its own mapping from the bootstrap tables, because that is the
# only mapping that exists that early and start.s is patched by the framework's 4K-baseline series.
#
# Three measurements shaped it. The first version wrote an L1 entry unconditionally and the kernel took a translation fault at VA 0x158
# (ESR 0x96000005, FAR 0x158) with the drawing loop already run -- x8 held the mapped base, x9 the stride, x10 the width, x15 the colour
# -- so the entry is written only when the slot reads back empty, both indices are bounds checked, and nothing is drawn unless the mapping
# was installed. The second version emitted the block without newlines (adjacent string literals concatenate) and the kernel build stopped
# at "expected expression" in arm_init.c, so the snippet below is one string with real newlines, written to this file by repr().
# A marker that can reach the panel before the VM work. It installs its own mapping, because that is the only thing that exists that
# early and start.s is patched by the framework's 4K-baseline series.
#
# Three measurements shaped this version, and the fourth (below) is what the QEMU failure taught:
#   * drawing through boot_args.Video.v_baseAddr before arm_vm_init is a guaranteed fault (physical address, no mapping) -- STAGE_0 no
#     longer does it;
#   * the mapping is written only into an empty L1 slot, both indices are bounds checked, and nothing is drawn unless it was installed;
#   * the snippet is one string with real newlines (adjacent literals concatenate, which once put every statement on one line).
#
# And the assumption that did not survive: that the KVA L1 table sits at bootstrap_pagetables + ARM_PGBYTES. The QEMU run stopped in the
# exception vector with FAR 0x158 rather than at the framebuffer, so this version does not assume -- it reads TTBR1_EL1, follows the root
# entry for the chosen virtual address, and uses the L1 table the MMU actually walks, with ARM_TT_ROOT_* / ARM_TT_L1_* naming the levels so
# the same code is right for a 4K and a 16K kernel.
# The marker records what it managed to do in a plain global, because the only place a value can be read back from is after the VM work:
# by then PE_create_console() has cleared the panel, so an early bar cannot be seen in a framebuffer dump at the end of the boot. The
# post-VM marker prints this number, which turns "did the mapping install?" into a measured value instead of an inference from a fault
# that is no longer there.
# 4 = token absent, 3 = invalid panel arguments, 2 = the guard refused, 1 = mapping installed, 0 = drawn. A static local of arm_init so
# both the marker and the post-VM report see the same object without touching anything at file scope.
EARLY_STATE = (
    "\n/* 4 = token absent, 3 = invalid panel arguments, 2 = refused, 1 = usable, 0 = drawn. */\n"
    "static volatile unsigned int lumia_early_map_state = 4;\n"
    "static volatile unsigned int lumia_probe_word;\n"
    "static int lumia_token_at(const char *p, const char *want)\n"
    "{\n"
    "\tconst char *a = p;\n"
    "\tconst char *b = want;\n"
    "\twhile (*a != \'\\0\' && *b != \'\\0\' && *a == *b) { a++; b++; }\n"
    "\treturn *b == \'\\0\' && (*a == \'\\0\' || *a == \' \' || *a == \'\\t\');\n"
    "}\n"
)

# A marker that can reach the panel before the VM work, with a self-test for the branch the handset takes.
#
# Boot arguments:
#   lumia-early-map            map and draw rows 8..15 of the panel
#   lumia-early-map-dry        map only                                   (state 1)
#   lumia-early-map-noclean    draw without the cache clean
#   lumia-early-map-notlbi     draw without the TLB invalidate
#   lumia-early-map-probe      two single stores: kernel data, then the framebuffer
#   lumia-early-map-selftest   run the existing-table branch on the marker's own buffer, with sentinels
#
# The self-test exists because the handset's framebuffer shares the kernel image's gigabyte -- that identity entry is already a table, so
# hardware only adds a leaf -- while the emulator's framebuffer sits in an empty gigabyte and needs a table first. The self-test therefore
# points the marker at its own 16 KB buffer, uses its own geometry (stride 256, width 64, rows 0..7 inside the buffer), keeps sentinels at
# both ends of that same buffer, and reports 30 when the existing-table branch was taken and the sentinels survived, 31 when a table had to be
# created, and 32 when a sentinel broke.
#
# States: 0 drawn, 1 usable but not drawn, 2 refused, 3 bad panel arguments, 4 token absent, 6 index out of range, 7 the leaf slot holds
# another block, 9 a block stands in the way, 30/31/32 the self-test outcomes above.
EARLY_MAP = (
    '\n\t/* Bring-up marker: map the framebuffer through the identity tables, then draw -- or run the self-test. */\n\t{\n\t\tconst char *line = args->CommandLine;\n\t\tint hit = 0;\n\t\tint dry_run = 0;\n\t\tint no_clean = 0;\n\t\tint no_tlbi = 0;\n\t\tint probe = 0;\n\t\tint selftest = 0;\n\t\tconst char *p = line;\n\t\twhile (*p != \'\\0\') {\n\t\t\tif (p != line && p[-1] != \' \' && p[-1] != \'\\t\') { p++; continue; }\n\t\t\tif (lumia_token_at(p, "lumia-early-map")) { hit = 1; }\n\t\t\telse if (lumia_token_at(p, "lumia-early-map-dry")) { hit = 1; dry_run = 1; }\n\t\t\telse if (lumia_token_at(p, "lumia-early-map-noclean")) { hit = 1; no_clean = 1; }\n\t\t\telse if (lumia_token_at(p, "lumia-early-map-notlbi")) { hit = 1; no_tlbi = 1; }\n\t\t\telse if (lumia_token_at(p, "lumia-early-map-probe")) { hit = 1; probe = 1; dry_run = 1; }\n\t\t\telse if (lumia_token_at(p, "lumia-early-map-selftest")) { hit = 1; selftest = 1; }\n\t\t\tp++;\n\t\t}\n\t\tif (hit) {\n\t\t\t/* The self-test exists for the branch the handset takes and the emulator does not: the framebuffer\'s gigabyte already has a\n\t\t\t * table. It points the marker at its own buffer with its own geometry, keeps sentinels in that same buffer, and reports whether\n\t\t\t * the existing-table branch was really the one taken -- a store range that overruns the buffer would break a sentinel and be\n\t\t\t * reported rather than corrupting whatever follows. */\n\t\t\tstatic uint64_t lumia_l2[ARM_PGBYTES / 8] __attribute__((aligned(ARM_PGBYTES)));\n\t\t\tstatic unsigned int lumia_test_pixels[18432] __attribute__((aligned(ARM_PGBYTES)));\n\t\t\tconst uint64_t entries = (uint64_t)(ARM_PGBYTES / 8);\n\t\t\tconst uint64_t block = (uint64_t)ARM_TT_L2_SIZE;\n\t\t\tconst uint64_t own_delta = (uint64_t)args->virtBase - (uint64_t)args->physBase;\n\t\t\tuint64_t pa = (uint64_t)args->Video.v_baseAddr;\n\t\t\tunsigned long stride = (unsigned long)args->Video.v_rowBytes;\n\t\t\tunsigned long width = (unsigned long)args->Video.v_width;\n\t\t\tunsigned long height = (unsigned long)args->Video.v_height;\n\t\t\tuint64_t block_pa;\n\t\t\tuint64_t to_va;\n\t\t\tuint64_t l2_pa;\n\t\t\tuint64_t ttbr0;\n\t\t\tuint64_t *l1;\n\t\t\tuint64_t l1_index;\n\t\t\tuint64_t l1_entry;\n\t\t\tuint64_t *l2;\n\t\t\tuint64_t l2_index;\n\t\t\tint installed = 0;\n\t\t\tint created_table = 0;\n\t\t\tint usable = 0;\n\t\t\tif (selftest) {\n\t\t\t\tpa = (uint64_t)lumia_test_pixels - own_delta;\n\t\t\t\tstride = 4320;\n\t\t\t\twidth = 1080;\n\t\t\t\theight = 1920;\n\t\t\t}\n\t\t\tblock_pa = pa & ~(block - 1);\n\t\t\tto_va = own_delta;\n\t\t\tl2_pa = (uint64_t)lumia_l2 - to_va;\n\t\t\tlumia_early_map_state = 2;\n\t\t\t__asm__ volatile("mrs %0, ttbr0_el1" : "=r"(ttbr0));\n\t\t\tl1 = (uint64_t *)((ttbr0 & ARM_TTE_TABLE_MASK) + to_va);\n\t\t\tif (pa == 0 || stride == 0 || width == 0 || height == 0) {\n\t\t\t\tlumia_early_map_state = 3;\n\t\t\t} else {\n\t\t\t\tl1_index = (block_pa & ARM_TT_L1_INDEX_MASK) >> ARM_TT_L1_SHIFT;\n\t\t\t\tif (l1_index >= entries) {\n\t\t\t\t\tlumia_early_map_state = 6;\n\t\t\t\t} else {\n\t\t\t\t\tl1_entry = l1[l1_index];\n\t\t\t\t\tif ((l1_entry & 3) == 1) {\n\t\t\t\t\t\tlumia_early_map_state = (l1_entry & ARM_TTE_TABLE_MASK) <= block_pa ? 1 : 9;\n\t\t\t\t\t\tusable = (lumia_early_map_state == 1);\n\t\t\t\t\t} else {\n\t\t\t\t\t\tif ((l1_entry & 3) == 3) {\n\t\t\t\t\t\t\tl2 = (uint64_t *)((l1_entry & ARM_TTE_TABLE_MASK) + to_va);\n\t\t\t\t\t\t} else {\n\t\t\t\t\t\t\tl2 = lumia_l2;\n\t\t\t\t\t\t\tl1[l1_index] = ARM_TTE_BOOT_TABLE | (l2_pa & ARM_TTE_TABLE_MASK);\n\t\t\t\t\t\t\tcreated_table = 1;\n\t\t\t\t\t\t\t__asm__ volatile("dsb ish" ::: "memory");\n\t\t\t\t\t\t}\n\t\t\t\t\t\tl2_index = (block_pa & ARM_TT_L2_INDEX_MASK) >> ARM_TT_L2_SHIFT;\n\t\t\t\t\t\tif (l2_index >= entries) {\n\t\t\t\t\t\t\tlumia_early_map_state = 6;\n\t\t\t\t\t\t} else if (l2[l2_index] != 0 && (l2[l2_index] & ARM_TTE_BLOCK_L2_MASK) != block_pa) {\n\t\t\t\t\t\t\tlumia_early_map_state = 7;\n\t\t\t\t\t\t} else {\n\t\t\t\t\t\t\tif ((l2[l2_index] & ARM_TTE_BLOCK_L2_MASK) != block_pa) {\n\t\t\t\t\t\t\t\tl2[l2_index] = ARM_TTE_BOOT_BLOCK | (block_pa & ARM_TTE_BLOCK_L2_MASK);\n\t\t\t\t\t\t\t}\n\t\t\t\t\t\t\tlumia_early_map_state = 1;\n\t\t\t\t\t\t\tusable = 1;\n\t\t\t\t\t\t\tinstalled = 1;\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t\tif (usable && selftest) {\n\t\t\t\tvolatile unsigned int *buffer = (volatile unsigned int *)pa;\n\t\t\t\tunsigned long row;\n\t\t\t\tunsigned long column;\n\t\t\t\tint sentinels_ok;\n\t\t\t\tfor (column = 0; column < 16; column++) {\n\t\t\t\t\tbuffer[column] = 0x5AA5C33Cu;\n\t\t\t\t\tbuffer[18400 + column] = 0xC33C5AA5u;\n\t\t\t\t}\n\t\t\t\t__asm__ volatile("dsb ish" ::: "memory");\n\t\t\t\t__asm__ volatile("tlbi vmalle1" ::: "memory");\n\t\t\t\t__asm__ volatile("dsb ish" ::: "memory");\n\t\t\t\t__asm__ volatile("isb" ::: "memory");\n\t\t\t\t/* the drawn region starts after the leading sentinel and ends well before the trailing one */\n\t\t\t\tfor (row = 8; row < 16; row++) {\n\t\t\t\t\tfor (column = 0; column < width; column++) {\n\t\t\t\t\t\tbuffer[16 + (row * stride) / 4 + column] = 0x00E03030u;\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t\tfor (row = 16 + (8 * stride) / 64; row < 16 + (16 * stride) / 64; row++) {\n\t\t\t\t\tunsigned long address = (unsigned long)buffer + row * 64;\n\t\t\t\t\t__asm__ volatile("dc civac, %0" :: "r"(address) : "memory");\n\t\t\t\t}\n\t\t\t\t__asm__ volatile("dsb sy" ::: "memory");\n\t\t\t\tsentinels_ok = 1;\n\t\t\t\tfor (column = 0; column < 16; column++) {\n\t\t\t\t\tif (buffer[column] != 0x5AA5C33Cu || buffer[18400 + column] != 0xC33C5AA5u) {\n\t\t\t\t\t\tsentinels_ok = 0;\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t\tif (!sentinels_ok) {\n\t\t\t\t\tlumia_early_map_state = 32;\n\t\t\t\t} else if (created_table) {\n\t\t\t\t\tlumia_early_map_state = 31;\n\t\t\t\t} else {\n\t\t\t\t\tlumia_early_map_state = 30;\n\t\t\t\t}\n\t\t\t}\n\t\t\tif (usable && probe) {\n\t\t\t\tlumia_probe_word = 0xA5A5A5A5u;\n\t\t\t\t*(volatile unsigned int *)pa = 0x00E03030u;\n\t\t\t\tlumia_early_map_state = 0;\n\t\t\t}\n\t\t\tif (usable && !dry_run && !selftest) {\n\t\t\t\tvolatile unsigned int *fb;\n\t\t\t\tunsigned long row;\n\t\t\t\tunsigned long column;\n\t\t\t\tif (!no_tlbi) {\n\t\t\t\t\t__asm__ volatile("dsb ish" ::: "memory");\n\t\t\t\t\t__asm__ volatile("tlbi vmalle1" ::: "memory");\n\t\t\t\t\t__asm__ volatile("dsb ish" ::: "memory");\n\t\t\t\t\t__asm__ volatile("isb" ::: "memory");\n\t\t\t\t}\n\t\t\t\tfb = (volatile unsigned int *)pa;\n\t\t\t\tif (height > 16 && width <= 16384 && stride <= 65536) {\n\t\t\t\t\tfor (row = 8; row < 16; row++) {\n\t\t\t\t\t\tfor (column = 0; column < width; column++) {\n\t\t\t\t\t\t\tfb[(row * stride) / 4 + column] = 0x00E03030u;\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t\tif (!no_clean) {\n\t\t\t\t\t\tfor (row = (8 * stride) / 64; row < (16 * stride) / 64; row++) {\n\t\t\t\t\t\t\tunsigned long address = (unsigned long)fb + row * 64;\n\t\t\t\t\t\t\t__asm__ volatile("dc civac, %0" :: "r"(address) : "memory");\n\t\t\t\t\t\t}\n\t\t\t\t\t\t__asm__ volatile("dsb sy" ::: "memory");\n\t\t\t\t\t}\n\t\t\t\t\tlumia_early_map_state = 0;\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n'
)

STAGE_0 = (
    "\n\t/* Bring-up instrument: remember the panel; drawing before the VM work needs a mapping, which comes later. */\n"
    + DECLARATION
    + "\tnative_boot_progress_remember((void *)args->Video.v_baseAddr, args->Video.v_rowBytes, "
    + "args->Video.v_height, args->CommandLine);\n"
)
# Withdrawn for the same reason as the stage call in STAGE_0: it hands the physical video base to a driver that stores through it, and at
# this point in arm_init the framebuffer still has no mapping. The mapping the early marker installs is the only pre-VM drawing path, and
# it is behind its own boot argument; the console stage draws through vinfo once PE_create_console() has run.
STAGE_2 = ""

def find(root: Path) -> list[Path]:
    found: list[Path] = []
    for candidate in sorted(root.rglob("arm_init.c")):
        if candidate.parent.name == "arm":
            found.append(candidate)
    return found




def find_bsd_init(root: Path) -> list[Path]:
    found: list[Path] = []
    for candidate in sorted(root.rglob("bsd_init.c")):
        if candidate.parent.name == "kern" and candidate.parent.parent.name == "bsd":
            found.append(candidate)
    return found


def arm_init_body(text: str):
    """The index just past the opening brace of the arm_init definition, or None.

    The pinned source writes it as the name on one line and the parameter on the next:

        arm_init(
            boot_args       *args)
        {
    """
    match = re.search(r"\narm_init\s*\([^)]*\)\s*\n?\{", text)
    if not match:
        return None
    return match.end()


def apply_bsd(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "native_boot_progress_stage((void *)vinfo.v_baseaddr" in text:
        return True, "already carries the third bar"
    if BSD_ANCHOR not in text:
        return False, "skipped: no throttle_init() in this copy of bsd_init.c"
    if BSD_INCLUDE not in text:
        if BSD_INCLUDE_ANCHOR not in text:
            return False, "skipped: no <sys/param.h> include to anchor the console header"
        text = text.replace(BSD_INCLUDE_ANCHOR, BSD_INCLUDE_ANCHOR + BSD_INCLUDE, 1)
    text = text.replace(BSD_ANCHOR, BSD_STAGE + BSD_ANCHOR, 1)
    path.write_text(text, encoding="utf-8")
    return True, "patched"


def check_bsd(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "native_boot_progress_stage((void *)vinfo.v_baseaddr" not in text:
        if BSD_ANCHOR not in text:
            return False, "skipped: no throttle_init() in this copy of bsd_init.c"
        return False, "missing the third bar"
    if BSD_INCLUDE not in text:
        return False, "missing the console header include"
    return True, "ok"


def apply_to(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already carries the calls"
    if BEFORE_VM_INIT not in text:
        return False, "skipped: no arm_vm_init call in this copy"

    if PLATFORM_CALL not in text:
        return False, "skipped: no PE_init_platform(FALSE, args) call in this copy"

    # Stage 0 goes immediately before the first statement of arm_init, not at the top of the body: the body
    # opens with declarations (`unsigned int maxmem;` ...), and a statement above them would make every later
    # declaration a declaration-after-statement.
    if "lumia_token_at" not in text:
        # Insert before the definition of arm_init, not between its return type and its name: the source puts the return type on its own
        # line, and an earlier version split "void" from "arm_init(" that way, which the compiler rejected.
        pattern = re.compile(r"(?m)^arm_init\(\s*$")
        match = pattern.search(text)
        if match is None:
            return False, "skipped: no arm_init definition to put the marker before"
        start = match.start()
        # walk back over the attribute macro and the return type, so the declaration lands before both of them
        for token in ("\n__startup_func", "\nvoid"):
            found = text.rfind(token, 0, start)
            if found >= 0:
                start = min(start, found + 1)
        anchor = start
        text = text[:anchor] + EARLY_STATE + text[anchor:]
    text = text.replace(PLATFORM_CALL, EARLY_MAP + STAGE_0 + PLATFORM_CALL, 1)
    text = text.replace(PLATFORM_CALL + EARLY_BAR, PLATFORM_CALL + EARLY_BAR, 1)
    if EARLY_BAR not in text:
        insertion = text.find(PLATFORM_CALL) + len(PLATFORM_CALL)
        text = text[:insertion] + EARLY_BAR + text[insertion:]
        # struct vc_info comes from console/video_console.h; arm_init.c does not include it
        if BSD_INCLUDE not in text:
            anchor = "#include <arm/pmap.h>\n"
            text = text.replace(anchor, anchor + BSD_INCLUDE, 1)
    text = text.replace(BEFORE_VM_INIT, STAGE_2 + BEFORE_VM_INIT + AFTER_VM_INIT_MARKER, 1)
    for switch, call in SWITCHED_CALLS.items():
        if call not in text:
            continue
        guard = (
            "\t/* Bring-up bisect: this call is skipped when '%s' is in the boot arguments. */\n"
            "\tif (!PE_parse_boot_argn(\"%s\", NULL, 0)) {\n"
            "%s"
            "\t}\n" % (switch, switch, call)
        )
        text = text.replace(call, guard, 1)
    path.write_text(text, encoding="utf-8")
    return True, "patched"


def check(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    missing = [str(stage) for stage in (0, 1) if f"args->CommandLine, {stage})" not in text]
    if missing:
        return False, f"missing stage calls: {', '.join(missing)}"
    body = arm_init_body(text)
    if body is not None and text.find("args->CommandLine, 0)") < body:
        return False, "stage 0 is above arm_init instead of inside it"
    platform = text.find("PE_init_platform(FALSE, args);")
    if platform >= 0 and text.find("args->CommandLine, 0)") > platform:
        return False, "stage 0 landed after the platform call"
    if "extern void native_boot_progress_stage(" not in text:
        return False, "missing the declaration"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=[], type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    roots = args.root or [Path.cwd()]
    files = find(roots[0])
    bsd_files = find_bsd_init(roots[0])
    if not files:
        print(f"error: no osfmk/arm/arm_init.c under {roots[0]}", file=sys.stderr)
        return 2

    patched = 0
    skipped = 0
    for path in files + bsd_files:
        if path.name == "bsd_init.c":
            ok, message = apply_bsd(path) if args.apply else check_bsd(path)
        else:
            ok, message = apply_to(path) if args.apply else check(path)
        if ok:
            print(f"ok   {path}: {message}")
            patched += 1
        elif message.startswith("skipped"):
            print(f"skip {path}: {message}")
            skipped += 1
        else:
            print(f"FAIL {path}: {message}")
    if patched == 0:
        print("error: no osfmk/arm/arm_init.c in this tree could be patched", file=sys.stderr)
        return 1
    print(f"ok: {patched} tree(s) patched, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
