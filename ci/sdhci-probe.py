#!/usr/bin/env python3
"""Map the SDHCI window after the VM work and read its identification registers.

M2's first observable question is not "can XNU read blocks" but "does the controller answer at all": a host version and a capabilities word
say whether the window maps, the power domain is up and the register layout is the one the driver expects. This probe answers exactly that
and nothing more -- it issues no command and writes no register.

It is behind the boot argument `lumia-sdhci-probe`, so an ordinary boot is unchanged, and it runs after arm_vm_init where ml_io_map works.
The addresses come from drivers/NativeSdhci/BoardConstants.h, which reads them from the device tree rather than guessing.

    python ci/sdhci-probe.py --root "$UNIXNU_OUT" --apply
    python ci/sdhci-probe.py --root "$UNIXNU_OUT" --check
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

MARKER = "LUMIA_SDHCI_PROBE"
HC_PHYS = 0xF9824900
HC_SIZE = 0x1A0

PROBE = f"""
/* {MARKER}: read the SDHCI identification registers. No command is issued and no register is written. */
#include <machine/machine_routines.h>
static int lumia_sdhci_probe_state = -1;
static unsigned int lumia_sdhci_version;
static unsigned int lumia_sdhci_capabilities;
static unsigned int lumia_sdhci_present;
static int lumia_sdhci_probe(void)
{{
	volatile unsigned char *hc;
	volatile unsigned int *word;

	hc = (volatile unsigned char *)ml_io_map((vm_offset_t){HC_PHYS:#x}ULL, (vm_size_t){HC_SIZE:#x}U);
	if (hc == 0) {{
		return 1;
	}}
	/* Host version is the last two bytes of the window, capabilities at 0x40, present state at 0x24. */
	lumia_sdhci_version = (unsigned int)hc[0xFE] | ((unsigned int)hc[0xFF] << 8);
	word = (volatile unsigned int *)(hc + 0x40);
	lumia_sdhci_capabilities = *word;
	word = (volatile unsigned int *)(hc + 0x24);
	lumia_sdhci_present = *word;
	return (lumia_sdhci_version == 0 && lumia_sdhci_capabilities == 0 && lumia_sdhci_present == 0) ? 2 : 0;
}}
"""

REPORT = """
	{
		extern int lumia_sdhci_probe(void);
		extern int lumia_sdhci_probe_state;
		extern unsigned int lumia_sdhci_version;
		extern unsigned int lumia_sdhci_capabilities;
		extern unsigned int lumia_sdhci_present;
		if (PE_parse_boot_argn("lumia-sdhci-probe", 0, 0)) {
			lumia_sdhci_probe_state = lumia_sdhci_probe();
			kprintf("LUMIA: sdhci probe %d version 0x%x caps 0x%x present 0x%x\\n", lumia_sdhci_probe_state,
			        lumia_sdhci_version, lumia_sdhci_capabilities, lumia_sdhci_present);
		}
	}
"""


def candidates(roots: list[pathlib.Path]) -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(sorted(path for path in root.rglob("arm_init.c") if path.parent.name == "arm"))
    return found


def apply_to(path: pathlib.Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already probes the controller"
    match = re.search(r"(?m)^arm_init\(\s*$", text)
    if match is None:
        return False, "skipped: no arm_init definition"
    start = match.start()
    for token in ("\n__startup_func", "\nvoid"):
        found = text.rfind(token, 0, start)
        if found >= 0:
            start = min(start, found + 1)

    # Insert before the first statement after the VM work rather than after the report line: that anchor exists in the source itself, so this
    # injector does not depend on another injector having run, and it cannot land inside the braced block the report uses.
    anchor = "\tif (debug_boot_arg) {"
    if anchor not in text:
        return False, "skipped: no statement after the VM work to anchor on"
    index = text.index(anchor)
    text = text[:index] + REPORT + text[index:]
    text = text[:start] + PROBE + text[start:]
    path.write_text(text, encoding="utf-8")
    return True, "patched"


def check(path: pathlib.Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        return False, "does not probe the controller"
    if "lumia-sdhci-probe" not in text:
        return False, "the marker is present but the boot argument is not"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=[], type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    roots = args.root or [pathlib.Path.cwd()]
    files = candidates(roots)
    if not files:
        print(f"error: no osfmk/arm/arm_init.c under {', '.join(str(root) for root in roots)}", file=sys.stderr)
        return 2
    ok_count = 0
    for path in files:
        ok, message = apply_to(path) if args.apply else check(path)
        print(f"{'ok  ' if ok else 'FAIL'} {path}: {message}")
        ok_count += 1 if ok else 0
    return 0 if ok_count == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
