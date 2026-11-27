#!/usr/bin/env python3
"""Compile the read-only GPT parser into the kernel image.

The parser lives in drivers/Common/GptRead.c and is tested on the host against the reference reader, but "the kernel will use it" is a claim
about the kernel image, not about a host build. The framework compiles a fixed set of sources, so the parser reaches the image the same way
the bring-up markers do: appended to a file the kernel build already compiles.

Everything it adds is inert: the helpers are marked unused so -Wunused-function does not fail the build, and `gpt_parse` is a global so the
linker keeps it. Nothing calls it yet -- the block device that would feed it does not exist -- which is why this buys `kernel-linked` and
nothing more.

    python ci/inject-gpt-parser.py --root "$UNIXNU_OUT" --apply
    python ci/inject-gpt-parser.py --root "$UNIXNU_OUT" --check
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

MARKER = "LUMIA_GPT_PARSER"
ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "drivers" / "Common" / "GptRead.c"
SELF_CHECK = ROOT / "drivers" / "Common" / "GptSelfCheck.c"


def payload() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    # strip the include of the header (its content is prepended below) and the local include block
    body = re.sub(r'^#include "GptRead\.h"\n', "", text, flags=re.M)
    body = re.sub(r"^#include <string\.h>\n", "", body, flags=re.M)
    header = (pathlib.Path(__file__).resolve().parent.parent / "drivers" / "Common" / "GptRead.h").read_text(encoding="utf-8")
    header = re.sub(r"^#ifndef NATIVE_GPT_READ_H\n#define NATIVE_GPT_READ_H\n", "", header, flags=re.M)
    header = re.sub(r"^#endif /\* NATIVE_GPT_READ_H \*/\n", "", header, flags=re.M)
    header = header.replace("#include <stdint.h>\n", "")
    # every helper of the parser is static and nothing calls the parser yet, so mark them unused rather than fail the build
    body = body.replace("static uint32_t gpt_crc32", "static __attribute__((unused)) uint32_t gpt_crc32")
    body = body.replace("static uint32_t load_le32", "static __attribute__((unused)) uint32_t load_le32")
    body = body.replace("static uint64_t load_le64", "static __attribute__((unused)) uint64_t load_le64")
    body = body.replace("static int is_zero_guid", "static __attribute__((unused)) int is_zero_guid")
    body = body.replace("static gpt_type classify", "static __attribute__((unused)) gpt_type classify")
    check = SELF_CHECK.read_text(encoding="utf-8")
    check = re.sub(r'^#include "GptRead\.h"\n', "", check, flags=re.M)
    return (
        f"\n/* {MARKER}: the read-only GPT parser, and an in-kernel self-check that runs it, compiled into the image. */\n"
        "#ifndef LUMIA_GPT_PARSER_INCLUDED\n#define LUMIA_GPT_PARSER_INCLUDED\n"
        + header
        + "\n"
        + body
        + "\n"
        + check
        + "\n#endif /* LUMIA_GPT_PARSER_INCLUDED */\n"
    )


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
        return True, "already carries the parser"
    match = re.search(r"(?m)^arm_init\(\s*$", text)
    if match is None:
        return False, "skipped: no arm_init definition"
    start = match.start()
    for token in ("\n__startup_func", "\nvoid"):
        found = text.rfind(token, 0, start)
        if found >= 0:
            start = min(start, found + 1)
    text = text[:start] + payload() + text[start:]
    path.write_text(text, encoding="utf-8")
    return True, "patched"


def check(path: pathlib.Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        return False, "does not carry the parser"
    if "lumia_gpt_selfcheck" not in text or "gpt_parse(gpt_read_sector" not in text:
        return False, "the marker is present but the function is not"
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
    patched = 0
    for path in files:
        ok, message = apply_to(path) if args.apply else check(path)
        print(f"{'ok  ' if ok else 'FAIL'} {path}: {message}")
        patched += 1 if ok else 0
    return 0 if patched == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
