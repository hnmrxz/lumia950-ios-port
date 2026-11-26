# The flashing toolchain, located but never committed

The binaries this port drives belong to other projects, so none of them is in this repository. What is
committed is where to look, how to override, and what each tool is for:

| tool | source | wrapper |
|---|---|---|
| `WPinternals.exe` | WPinternals, or the copy inside the SJM install | `scripts/phone-modes.py`, `scripts/phone-recover.ps1` |
| `thor2.exe` | Microsoft's emergency/FFU flasher, shipped inside the SJM install | `scripts/phone-thor2.py` |
| `ffutool.exe`, `emmcdl.exe`, `Img2Ffu.exe` | likewise | located by `scripts/phone-tools.py` |

`scripts/phone-tools.py` resolves each name from `PHONE_TOOL_<NAME>`, then from the known install
locations, then from `PATH`, and prints the SHA-256 of what it found. That list is how a future session
knows which copy was used; it is also why nothing here has to ship a binary.

```
python scripts/phone-tools.py                     # table with sizes and hashes
python scripts/phone-tools.py --require thor2     # fail if a needed tool is absent
python scripts/phone-thor2.py devices             # read-only: what thor2 sees
python scripts/phone-thor2.py emergency --hex MPRG8992_fh.ede --edp RM1105_fh.edp --apply
python scripts/phone-thor2.py ffu --file RM1105_....ffu --apply
```

`phone-thor2.py` prints the exact command and refuses both writing modes without `--apply`, so the
emergency path the Chinese utility uses is reproducible from this checkout without any binary being
vendored.

The binaries observed on this machine, with hashes (recorded so a different copy is noticed):

```
thor2        1,129,688 B  sha256 ac97d128fab1e00a...
ffutool         35,056 B  sha256 9b968014fdfca826...
emmcdl         177,152 B  sha256 d0fe3d4d051b5b0e...
img2ffu        127,488 B  sha256 689cd5e362330f9d...
wpinternals  2,264,576 B  sha256 9b8c4509c27ecca6...
```
