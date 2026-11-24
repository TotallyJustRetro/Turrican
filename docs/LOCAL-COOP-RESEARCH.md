# Mega Turrican local co-op research status

## Safety status

The first RAM-shadow prototype is disabled and must not be reintroduced.

The generated recomp report shows:
- The main update loop in `f_156A` calls the native player callback through the pointer at `$FFBC62`.
- The callback installed by `f_19FA` is `f_224C`.
- `f_224C` reads the controller sample at `$FFBC90/$FFBC91` and updates player coordinates at `$FFBD1E/$FFBD20`.
- The previous prototype copied `$FFBC70-$FFBD26`. This range does include the callback's direct `$FFBCC0-$FFBCE5` fields; those bytes were not missing from the copy.
- The deeper problem is that the copied block contains pointer values used by the callback. For example, `f_224C` loads the pointer at `$FFBCC4` into A0 and follows it to other working data. Copying that pointer does not duplicate its target or rebase it to P2-owned storage. P2 therefore reused P1's pointed-to structures.
- The prototype also declared `M68K coop_player_call_entry` as a non-static local in `f_156A` and populated it from P1's current CPU context before running P2. It did not preserve a persistent, independent P2 register context between frames.

Those two assumptions invalidated the shadow-player design. The user observed P2 moving out of bounds, corrupting the level, and failing to respond to controller 2.

## Current build policy

- Keep the original single-player path intact.
- Keep the launcher’s independent P1/P2 controller profiles and native port-2 polling as low-level input groundwork.
- Do not show or enable an in-game Multiplayer toggle until a true second actor exists.
- Do not re-run the disabled `patch-local-coop.py` RAM-shadow prototype.

## Next implementation investigation

1. Trace the complete pointer graph rooted in `$FFBCC4` and any other player-owned pointers used by `f_224C` and its child routines.
2. Trace the player initialization path in `f_19FA` and the alternate setup path in `f_1BDE`, including the ROM records referenced through `$FFBC50`.
3. Determine how to allocate and rebase P2-owned working structures rather than copying pointer values.
4. Preserve an independent P2 M68K register context across frames; never refresh it from P1's registers every frame.
5. Identify the actual per-frame dispatch point and ensure update, collision, render, animation, damage, and death state are all independently owned.
6. Only then reintroduce a Multiplayer option, initially behind a guarded test build.

No separate lives, shared camera, P2 visuals, or P2 gameplay completion should be claimed until tested in-game.
