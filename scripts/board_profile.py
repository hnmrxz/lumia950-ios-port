#!/usr/bin/env python3
"""Resolve board.toml's ADT profile into the values the two stagers hand the generator.

Two scripts stage an ADT for the same phone: `scripts/stage-kernel.py` from a CI artifact, and
`scripts/stage-native-bringup.py` from a local source build. They used to answer the same
questions differently -- six CPUs and a PSCI/HVC conduit in one, one CPU and no conduit in the
other -- so the tree CI validated and the tree the phone ran were not the same tree.

board.toml carries the answer once, as named profiles, and both stagers read it here. The
bring-up profile is the only one that may reach the phone, and it is checked here rather than
trusted: one boot CPU, no PSCI node, and an explicit ownership window.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

PROFILES = ("bringup", "target", "qemu", "qemu-relative")


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def resolve_profile(board_path: Path, profile: str | None = None) -> dict:
    path = Path(board_path)
    if not path.is_file():
        fail(f"{path} is missing; run from the device repository")
    board = tomllib.loads(path.read_text())
    payload = board.get("payload") or {}
    adt = payload.get("adt") or {}

    tool = adt.get("tool")
    if not tool:
        fail(f"{path} [payload.adt] has no tool; it is the ADT generator for this SoC")
    if payload.get("dram_size") is None:
        fail(f"{path} [payload] has no dram_size; the ADT's /memory node needs the figure the "
             "firmware reports, not the marketing one")

    if profile is None:
        profile = adt.get("profile")
    if profile not in PROFILES:
        fail(f"{path} [payload.adt] profile is {profile!r}; the stagers need one of "
             f"{', '.join(PROFILES)} so they cannot disagree about the CPU count")
    values = (adt.get("profiles") or {}).get(profile) or {}
    if not values:
        fail(f"{path} has no [payload.adt.profiles.{profile}]; the profile {profile!r} is "
             "selected but describes nothing")

    resolved = {
        "profile": profile,
        "tool": tool,
        "dram_size": int(payload["dram_size"]),
        "dram_base": payload.get("dram_base"),
        "chip_id": adt.get("chip_id"),
        "cpu_regs": values.get("cpu_regs"),
        "psci_method": values.get("psci_method"),
        "owned_memory_size": values.get("owned_memory_size"),
        # Only an emulated profile names these; the phone's machine has them fixed in the generator.
        "gic_distributor": values.get("gic_distributor"),
        "gic_cpu_interface": values.get("gic_cpu_interface"),
        "soc_base": values.get("soc_base"),
    }
    for key in ("cpu_regs", "psci_method"):
        if resolved[key] in (None, ""):
            fail(f"{path} [payload.adt.profiles.{profile}] has no {key}")
    for key in ("dram_base", "chip_id", "owned_memory_size"):
        if resolved[key] is not None:
            resolved[key] = int(resolved[key])

    cpus = [part for part in str(resolved["cpu_regs"]).split(",") if part.strip()]
    if profile in ("bringup", "qemu", "qemu-relative"):
        # Both conditions are hardware facts this port has not established, and the ADT is what
        # the kernel believes. Claiming either one moves the failure from "one CPU came up" to
        # "something in the boot chain lied", which is not a debuggable state. The qemu profile is
        # the bring-up shape placed on an emulated machine, so the same rules apply to it.
        if len(cpus) != 1:
            fail(f"{path} [payload.adt.profiles.{profile}] lists {len(cpus)} CPUs; no secondary-CPU "
                 "path has been qualified on this SoC, so this profile stages the boot CPU alone")
        if resolved["psci_method"] != "none":
            fail(f"{path} [payload.adt.profiles.{profile}] sets psci_method "
                 f"{resolved['psci_method']!r}; no PSCI/HVC conduit has been qualified "
                 "(docs/native-bringup.md), so this profile publishes none")
        if resolved["owned_memory_size"] is None:
            fail(f"{path} [payload.adt.profiles.{profile}] has no owned_memory_size; DarwinBoot "
                 "needs an ownership bound to clamp the firmware memory map to")
    return resolved
