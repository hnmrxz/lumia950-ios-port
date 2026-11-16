#!/usr/bin/env python3
"""Enable path-scoped automatic kernel builds in the inherited Lumia 950 workflow."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    path = args.root / '.github' / 'workflows' / 'build.yml'
    if not path.is_file():
        raise SystemExit(f'Missing workflow: {path}')

    text = path.read_text(encoding='utf-8')
    if "      - 'board.toml'\n" not in text:
        old = '  push:\n    branches: [main]\n'
        new = (
            '  push:\n'
            '    branches: [main]\n'
            '    paths:\n'
            "      - 'board.toml'\n"
            "      - 'configs/**'\n"
            "      - 'drivers/**'\n"
            "      - 'scripts/**'\n"
            "      - 'payload/**'\n"
            "      - 'ci/**'\n"
            "      - 'feeds.toml'\n"
            "      - '.github/workflows/build.yml'\n"
        )
        if old not in text:
            raise SystemExit('Cannot patch push path filter: source workflow has changed')
        text = text.replace(old, new, 1)

    old_condition = "if: github.event_name == 'workflow_dispatch' && (inputs.target == 'kernel' || inputs.target == 'both')"
    new_condition = "if: (github.event_name == 'workflow_dispatch' && (inputs.target == 'kernel' || inputs.target == 'both')) || (github.event_name == 'push' && github.ref == 'refs/heads/main')"
    if old_condition in text:
        text = text.replace(old_condition, new_condition, 1)
    elif new_condition not in text:
        raise SystemExit('Cannot patch kernel job condition: source workflow has changed')

    old_runner = 'runs-on: macos-latest'
    new_runner = "runs-on: ${{ vars.MACOS_RUNNER || 'macos-26' }}"
    if old_runner in text:
        text = text.replace(old_runner, new_runner, 1)
    elif new_runner not in text:
        raise SystemExit('Cannot patch macOS runner: source workflow has changed')

    path.write_text(text, encoding='utf-8', newline='\n')
    print('build.yml patched successfully (idempotent).')


if __name__ == '__main__':
    main()
