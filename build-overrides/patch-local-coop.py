#!/usr/bin/env python3
"""
The earlier RAM-shadow prototype for a second Mega Turrican player was unsafe.

It copied only $FFBC70-$FFBD26, while the native player callback also reads and
writes additional state including $FFBCC0-$FFBCE5 and other shared globals.
Running that callback against a partial copy caused uncontrolled movement and
invalid game state. The patch is intentionally disabled until a complete,
independently initialized player actor is implemented and verified.
"""

raise SystemExit(
    "Local co-op actor patch is disabled: the previous RAM-shadow prototype "
    "caused out-of-bounds movement and state corruption. Use the normal "
    "single-player runtime while the native actor model is being researched."
)
