#!/usr/bin/env python3
"""The merged image must never be uploaded from a public repository.

The workflow stages and uploads `lumia950-prelinked`, which carries extensions merged out of an Apple kernelcache. The branch
conditions that gated it ('probe/pthread-darwin22' or 'main' or the input) are also true for a public copy of this repository,
so run 45925374030 published that image from a public repo. The guard has to name the repository's visibility, not the branch.

The source-built kernel and its unstripped image stay public on purpose: they are this repository's own compile of open-source
XNU, and the handset smoke test needs them.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "build.yml"

PUBLIC_SAFE_STEPS = {
    "Stage the source-built kernel for a handset smoke test",
    "Upload the source-built kernel",
    "Upload the unstripped kernel the gates booted",
}


def steps() -> list[dict]:
    text = WORKFLOW.read_text(encoding="utf-8")
    found = []
    for match in re.finditer(r"^(\s*)- name: (.+)$", text, re.M):
        indent, name = match.group(1), match.group(2).strip()
        start = match.end()
        following = text[start:].split("\n")
        guard = next((line.strip() for line in following if line.strip().startswith("if:")), "")
        found.append({"name": name, "guard": guard})
    return found


class PrelinkedArtifactGuardTests(unittest.TestCase):
    @staticmethod
    def _publishers() -> list[dict]:
        # only the steps that move the merged image somewhere it can be downloaded
        return [step for step in steps()
                if step["name"].startswith(("Stage the prelinked", "Upload the prelinked"))]

    def test_the_merged_image_is_private_only(self):
        for step in self._publishers():
            self.assertIn("github.event.repository.private", step["guard"],
                          f"'{step['name']}' must require a private repository")

    def test_the_source_builds_stay_public(self):
        by_name = {step["name"]: step for step in steps()}
        for name in PUBLIC_SAFE_STEPS:
            self.assertIn(name, by_name, f"missing step: {name}")
            self.assertNotIn("github.event.repository.private", by_name[name]["guard"],
                             f"'{name}' is this repository's own XNU build and must stay downloadable")

    def test_no_step_guards_on_the_branch_alone_for_apple_content(self):
        for step in self._publishers():
            self.assertNotEqual(
                step["guard"],
                "if: github.ref_name == 'probe/pthread-darwin22' || github.ref_name == 'main' || inputs.handset_artifact",
                f"'{step['name']}' is gated on the branch alone")


if __name__ == "__main__":
    unittest.main()
