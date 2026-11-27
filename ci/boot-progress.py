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
EARLY_MAP = (
    "\n\t/* Bring-up marker: draw before the VM work, through the mapping ci/framebuffer-map.py adds. */\n"
    "\t{\n"
    "\t\tconst char *line = args->CommandLine;\n"
    "\t\tconst char *want = \"lumia-early-map\";\n"
    "\t\tint hit = 0;\n"
    "\t\tconst char *p = line;\n"
    "\t\twhile (*p != '\\0' && !hit) {\n"
    "\t\t\tconst char *a = p;\n"
    "\t\t\tconst char *b = want;\n"
    "\t\t\tif (a != line && a[-1] != ' ' && a[-1] != '\\t') { p++; continue; }\n"
    "\t\t\twhile (*a != '\\0' && *b != '\\0' && *a == *b) { a++; b++; }\n"
    "\t\t\tif (*b == '\\0' && (*a == '\\0' || *a == ' ' || *a == '\\t')) { hit = 1; break; }\n"
    "\t\t\tp++;\n"
    "\t\t}\n"
    "\t\tif (hit) {\n"
    "\t\t\tconst unsigned long block = 0x2000000UL;\n"
    "\t\t\tconst unsigned long base = 0xFFFFFFF0E0000000UL;\n"
    "\t\t\tconst unsigned long pa = (unsigned long)args->Video.v_baseAddr;\n"
    "\t\t\tvolatile unsigned int *fb = (volatile unsigned int *)(base + (pa & (block - 1)));\n"
    "\t\t\tconst unsigned long stride = (unsigned long)args->Video.v_rowBytes;\n"
    "\t\t\tconst unsigned long width = (unsigned long)args->Video.v_width;\n"
    "\t\t\tunsigned long row;\n"
    "\t\t\tunsigned long column;\n"
    "\t\t\tfor (row = 120; row < 136; row++) {\n"
    "\t\t\t\tfor (column = 0; column < width; column++) {\n"
    "\t\t\t\t\tfb[(row * stride) / 4 + column] = 0x00E03030u;\n"
    "\t\t\t\t}\n"
    "\t\t\t}\n"
    "\t\t\tfor (row = (120 * stride) / 64; row < (136 * stride) / 64; row++) {\n"
    "\t\t\t\tunsigned long address = (unsigned long)fb + row * 64;\n"
    "\t\t\t\t__asm__ volatile(\"dc civac, %0\" :: \"r\"(address) : \"memory\");\n"
    "\t\t\t}\n"
    "\t\t\t__asm__ volatile(\"dsb sy\" ::: \"memory\");\n"
    "\t\t}\n"
    "\t}\n"
)

STAGE_0 = (
    "\n\t/* Bring-up instrument: remember the panel and draw the first bar before the MMU work. */\n"
    + DECLARATION
    + "\tnative_boot_progress_remember((void *)args->Video.v_baseAddr, args->Video.v_rowBytes, "
    + "args->Video.v_height, args->CommandLine);\n"
    + "\tnative_boot_progress_stage((void *)args->Video.v_baseAddr, args->Video.v_rowBytes, "
    + "args->Video.v_height, args->CommandLine, 0);\n"
)
STAGE_2 = ("\tnative_boot_progress_stage((void *)args->Video.v_baseAddr, args->Video.v_rowBytes, "
           "args->Video.v_height, args->CommandLine, 1);\n")

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


def apply_bsd(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already carries the third stage"
    if BSD_ANCHOR not in text:
        return False, "skipped: no throttle_init() in this copy of bsd_init.c"
    text = text.replace(BSD_ANCHOR, BSD_STAGE + BSD_ANCHOR, 1)
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
