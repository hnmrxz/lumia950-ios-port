#!/usr/bin/env python3
"""Render a UniXNU menu configuration from the committed one.

There were two menus. `payload/EFI/UniXNU/unixnu.toml` is the source of truth for the menu stage,
and `scripts/stage-kernel.py` rendered it by replacing one marker line. `scripts/stage-native-
bringup.py` wrote a second, hand-maintained configuration with its own countdown (300 vs 20), its
own title, `logo = false` and its own entry set. A change to the panel layout or an action entry
in the committed file therefore reached one staging path and not the other, and nothing compared
them.

Both stagers render the same file now. The differences that are real -- the countdown, the title,
the arguments, one extra entry, and dropping the firmware action entries a test menu does not
want -- are arguments to `render`, and each one fails loudly if the committed file stops matching
the text it expects. A projection that silently stops projecting is the failure this file exists
to prevent.
"""
from __future__ import annotations

import sys

# The line the kernel entry is inserted at. Kept here so both stagers agree on it.
MARKER = "# stage-kernel.py: kernel entry"

# The two action entries a native test menu does not carry: install-native-bringup.py requires
# exactly [gpu, xnu, exit], so their removal is part of the contract, not an accident.
FIRMWARE_ACTIONS = (
    ("reset entry block",
     '[[entry]]\nid = "reset"\ntitle = "Restart"\ntype = "action"\naction = "reset"\n'),
    ("shutdown entry block",
     '[[entry]]\nid = "shutdown"\ntitle = "Power off"\ntype = "action"\naction = "shutdown"\n'),
)


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def replace_once(text: str, old: str, new: str, what: str) -> str:
    """Exactly one occurrence, or nothing: a projection that quietly matches twice is a guess."""
    if text.count(old) != 1:
        fail(f"the menu configuration no longer has exactly one {what}; update "
             "scripts/menu_render.py with it instead of letting the stage drift")
    return text.replace(old, new)


def render(source: str, *, insert: str, default: str, overrides: tuple = (), drop: tuple = ()) -> str:
    text = replace_once(source, MARKER, insert, "marker line")
    for label, block in drop:
        text = replace_once(text, block, "", label)
    for old, new, what in overrides:
        text = replace_once(text, old, new, what)
    return replace_once(text, 'default = "exit"', f'default = "{default}"', "default entry")
