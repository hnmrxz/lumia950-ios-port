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

    "\tkprintf(\"LUMIA: early map state %u (0 installed and drawn, 1 installed not drawn, 2 refused, 3 bad panel,\\n\"\n"
    "\t        \" 4 token absent, 5 no root entry, 6 index out of range, 7 L1 slot taken)\\n\", lumia_early_map_state);\n"
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
EARLY_STATE = "\n\tstatic volatile unsigned int lumia_early_map_state = 4;\n"

# A marker that can reach the panel before the VM work. It installs its own mapping, because that is the only thing that exists that
# early and start.s is patched by the framework's 4K-baseline series.
#
# It reports what it did in the same value the post-VM kprintf prints: 0 mapping installed and drawn, 1 installed but not drawn, 2 refused by
# the guard, 3 invalid panel arguments, 4 boot argument absent, 5 no root entry for the chosen address, 6 index out of range, 7 the L1 slot
# was already taken. The last QEMU run reported 2, which is why the address now shares the kernel's root entry: the previous one,
# 0xFFFFFFF0E0000000, had no root entry at all, and this marker may not create intermediate levels.
EARLY_MAP = (
    '\n\t/* Bring-up marker: install one framebuffer mapping, then draw before the VM work. */\n\t{\n\t\tconst char *line = args->CommandLine;\n\t\tconst char *want = "lumia-early-map";\n\t\tint hit = 0;\n\t\tconst char *p = line;\n\t\twhile (*p != \'\\0\' && !hit) {\n\t\t\tconst char *a = p;\n\t\t\tconst char *b = want;\n\t\t\tif (a != line && a[-1] != \' \' && a[-1] != \'\\t\') { p++; continue; }\n\t\t\twhile (*a != \'\\0\' && *b != \'\\0\' && *a == *b) { a++; b++; }\n\t\t\tif (*b == \'\\0\' && (*a == \'\\0\' || *a == \' \' || *a == \'\\t\')) { hit = 1; break; }\n\t\t\tp++;\n\t\t}\n\t\tif (hit) {\n\t\t\t/* The virtual address has to live under a root entry the kernel already uses, because creating intermediate table\n\t\t\t * levels is not something this marker may do. So it shares the kernel\'s root entry and takes a mid-table L1 slot,\n\t\t\t * which is empty in every build so far. */\n\t\t\tstatic uint64_t lumia_table[ARM_PGBYTES / 8] __attribute__((aligned(ARM_PGBYTES)));\n\t\t\tconst uint64_t entries = (uint64_t)(ARM_PGBYTES / 8);\n\t\t\tconst uint64_t block = (uint64_t)ARM_TT_L2_SIZE;\n\t\t\tconst uint64_t pa = (uint64_t)args->Video.v_baseAddr;\n\t\t\tconst uint64_t block_pa = pa & ~(block - 1);\n\t\t\tconst uint64_t kernel_va = (uint64_t)args->virtBase;\n\t\t\tconst uint64_t va = (kernel_va & ARM_TT_ROOT_INDEX_MASK) | ((entries / 2) << ARM_TT_L1_SHIFT);\n\t\t\tconst uint64_t to_va = (uint64_t)args->virtBase - (uint64_t)args->physBase;\n\t\t\tconst uint64_t table_pa = (uint64_t)lumia_table - to_va;\n\t\t\tuint64_t ttbr1;\n\t\t\tuint64_t *root;\n\t\t\tuint64_t root_index;\n\t\t\tuint64_t l1_pa;\n\t\t\tuint64_t *l1;\n\t\t\tuint64_t l1_index;\n\t\t\tuint64_t l2_index;\n\t\t\tint installed = 0;\n\t\t\tlumia_early_map_state = 2;\n\t\t\t__asm__ volatile("mrs %0, ttbr1_el1" : "=r"(ttbr1));\n\t\t\troot = (uint64_t *)((ttbr1 & ARM_TTE_TABLE_MASK) + to_va);\n\t\t\troot_index = (va & ARM_TT_ROOT_INDEX_MASK) >> ARM_TT_ROOT_SHIFT;\n\t\t\tif ((root[root_index] & 3) != 3) {\n\t\t\t\tlumia_early_map_state = 5;\n\t\t\t} else {\n\t\t\t\tl1_pa = root[root_index] & ARM_TTE_TABLE_MASK;\n\t\t\t\tl1 = (uint64_t *)(l1_pa + to_va);\n\t\t\t\tl1_index = (va & ARM_TT_L1_INDEX_MASK) >> ARM_TT_L1_SHIFT;\n\t\t\t\tif (l1_index >= entries) {\n\t\t\t\t\tlumia_early_map_state = 6;\n\t\t\t\t} else if (l1[l1_index] != 0) {\n\t\t\t\t\tlumia_early_map_state = 7;\n\t\t\t\t} else if (pa == 0 || args->Video.v_rowBytes == 0 || args->Video.v_width == 0 || args->Video.v_height == 0) {\n\t\t\t\t\tlumia_early_map_state = 3;\n\t\t\t\t} else {\n\t\t\t\t\tl2_index = (va & ARM_TT_L2_INDEX_MASK) >> ARM_TT_L2_SHIFT;\n\t\t\t\t\tif (l2_index >= entries) {\n\t\t\t\t\t\tlumia_early_map_state = 6;\n\t\t\t\t\t} else {\n\t\t\t\t\t\tl1[l1_index] = ARM_TTE_BOOT_TABLE | (table_pa & ARM_TTE_TABLE_MASK);\n\t\t\t\t\t\tlumia_table[l2_index] = ARM_TTE_BOOT_BLOCK | (block_pa & ARM_TTE_BLOCK_L2_MASK);\n\t\t\t\t\t\tinstalled = 1;\n\t\t\t\t\t\tlumia_early_map_state = 1;\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t\tif (installed) {\n\t\t\t\tvolatile unsigned int *fb;\n\t\t\t\tunsigned long stride = (unsigned long)args->Video.v_rowBytes;\n\t\t\t\tunsigned long width = (unsigned long)args->Video.v_width;\n\t\t\t\tunsigned long height = (unsigned long)args->Video.v_height;\n\t\t\t\tunsigned long row;\n\t\t\t\tunsigned long column;\n\t\t\t\t__asm__ volatile("dsb ish" ::: "memory");\n\t\t\t\t__asm__ volatile("tlbi vmalle1" ::: "memory");\n\t\t\t\t__asm__ volatile("dsb ish" ::: "memory");\n\t\t\t\t__asm__ volatile("isb" ::: "memory");\n\t\t\t\tfb = (volatile unsigned int *)(va + (pa - block_pa));\n\t\t\t\tif (height > 136 && width <= 16384 && stride <= 65536) {\n\t\t\t\t\tfor (row = 120; row < 136; row++) {\n\t\t\t\t\t\tfor (column = 0; column < width; column++) {\n\t\t\t\t\t\t\tfb[(row * stride) / 4 + column] = 0x00E03030u;\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t\tfor (row = (120 * stride) / 64; row < (136 * stride) / 64; row++) {\n\t\t\t\t\t\tunsigned long address = (unsigned long)fb + row * 64;\n\t\t\t\t\t\t__asm__ volatile("dc civac, %0" :: "r"(address) : "memory");\n\t\t\t\t\t}\n\t\t\t\t\t__asm__ volatile("dsb sy" ::: "memory");\n\t\t\t\t\tlumia_early_map_state = 0;\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n'
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
    text = text.replace(PLATFORM_CALL, EARLY_STATE + EARLY_MAP + STAGE_0 + PLATFORM_CALL, 1)
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
