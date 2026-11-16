# 0001 — The log transport for the handset

- **Status:** proposed. No transport exists; `docs/native-checkpoints.json` still says
  `"transport": "undecided"`.
- **Blocks:** `docs/phases/p1-exit.json` P1.1 and P1.4. Without one, a successful XNU entry and a
  hang are the same black screen, so P1 cannot be judged at all.
- **Decided by:** the first handset run that produces or fails to produce a checkpoint marker.

## The problem

The roadmap's P1 exit is "a real-device log proves XNU took control". A Lumia 950 in this
configuration has no accessible serial port and no working storage path from inside XNU yet
(P2 is open). Everything the kernel knows has to leave the phone through something that already
works: the panel, or a region of RAM that survives a reset.

## Option A — GOP framebuffer console after ExitBootServices

Write checkpoint markers as text into the firmware's framebuffer at `0x00400000`, 1080×1920,
BGR, using a bitmap font, and photograph the result.

**Already established.** `docs/hardware/2026-10-26-handoff-v1.json` records raw framebuffer writes
visible after a successful `ExitBootServices`, with the firmware's MMU mappings retained by the
application. So the firmware half of this works on this phone.

**Still unproven.** That XNU's pmap maps that physical range with attributes that make CPU writes
reach the panel, and that DarwinBoot or the platform expert can hand the address and stride to the
console code. The ADT declares the GOP region; nothing has written to it from inside the kernel.

**What implementation needs.** A framebuffer address/stride/format triple carried from the EFI
handoff into the kernel (the ADT is the natural place), a write path that does not need the
display driver (it is rung 1 and publishes no framebuffer), and a font of a few hundred bytes.
Cost is small; the risk is the cache attribute question, which a single test write answers.

## Option B — reserved RAM mailbox plus a diagnostic EFI application

Reserve a page before `ExitBootServices`, have the kernel append markers to it, then power cycle
and read the page back with a small EFI application that dumps it.

**Already established.** Nothing on the handset: this needs a reservation that the firmware will
not hand to the OS, and no measurement of a safe region exists in `docs/hardware/`.

**Still unproven.** That a page outside the memory the firmware reports as conventional can be
taken without colliding with a carve-out, and that its contents survive a reset (RAM contents
after a power cycle are not a given).

**What implementation needs.** A measured reserved region, a reader application, and a physical
power cycle per observation, which makes iterating slow.

## Recommendation

**Option A first**, for two reasons that are evidence rather than preference: the phone has already
shown framebuffer writes surviving `ExitBootServices` in an EFI application, and Option B depends
on a reserved region this project has not measured. Option A also reuses the same panel the menu
already proves works.

Option B stays the fallback if the kernel-side mapping turns out not to reach the panel, or if
Option A's output is unreadable at 1080×1920 in a photograph.

## What would overturn this

- A test write from inside XNU to `0x00400000` that the panel does not show, after the mapping is
  proved correct → Option B.
- Evidence that the firmware's framebuffer is not retained after `ExitBootServices` on a cold
  boot (the handoff record is a warm observation) → Option B.

## Consequence for the plan

This also settles an ordering argument: the GOP framebuffer console is **P1, not P3**. P3 reuses
the firmware framebuffer as a first-screen path for *scanout*; P1 needs it for *text*. Both use the
same region, and P1 needs it first.

When a transport is chosen and implemented, set `transport` in `docs/native-checkpoints.json` to
`gop-framebuffer` or `ram-mailbox`; `scripts/check-checkpoints.py` accepts exactly those values
and `undecided`.
