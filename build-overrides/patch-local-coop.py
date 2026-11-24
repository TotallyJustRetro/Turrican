#!/usr/bin/env python3
"""
The experimental Mega Turrican second-player RAM-shadow patch is disabled.

The copied RAM window ($FFBC70-$FFBD26) includes the callback's direct
$FFBCC0-$FFBCE5 fields, so those addresses were not missing from the byte copy.
The actual problem is deeper: the callback uses pointers stored in that window
(e.g. $FFBCC4) to reach other working structures, and copying pointer values
does not duplicate or rebase their targets. The prototype also reused a fresh
copy of P1's M68K register context for P2 every frame instead of preserving an
independent P2 execution context. This is not a valid second actor and caused
uncontrolled movement/state corruption in testing.

This script is deliberately fail-closed. Do not re-enable it until a real actor
with independently allocated/rebased working memory and persistent CPU state
has been implemented and verified.
"""

raise SystemExit(
    "Local co-op actor patch is disabled: the old RAM-shadow prototype reused "
    "P1 pointer targets and CPU context. Use the normal single-player runtime "
    "while the native actor model is being researched."
)
