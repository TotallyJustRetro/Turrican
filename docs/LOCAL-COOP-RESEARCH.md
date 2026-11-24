# Mega Turrican local co-op research status

## Safety status

The first RAM-shadow prototype is disabled and must not be reintroduced.

Observed in the generated recomp source:
- The main update loop in `f_156A` calls the native player callback through the pointer at `$FFBC62`.
- The callback installed by `f_19FA` is `f_224C`.
- `f_224C` reads the controller sample at `$FFBC90/$FFBC91` and updates player coordinates at `$FFBD1E/$FFBD20`.
- The same callback also uses state outside the earlier copied window, including `$FFBCC0-$FFBCE5`, `$FFBCF3`, `$FFBCF9`, `$FFBCFC`, and other player/global working fields.
- The earlier prototype copied only `$FFBC70-$FFBD26`, so its second callback execution mixed P2's partial state with P1/shared state. That was not a valid independent actor and resulted in uncontrolled movement and out-of-bounds corruption during user testing.

## Current build policy

- Keep the original single-player path intact.
- Keep the launcher’s independent P1/P2 controller profiles and native port-2 polling as low-level input groundwork.
- Do not show or enable an in-game Multiplayer toggle until a true second actor exists.
- Do not re-run the disabled `patch-local-coop.py` RAM-shadow prototype.

## Next implementation investigation

1. Map the complete player state and every direct/indirect RAM reference used by `f_224C` and its called routines.
2. Trace the player initialization path in `f_19FA` and the alternate setup path in `f_1BDE`, including the source records referenced through `$FFBC50` and child/working context at `$FFBCC4`.
3. Determine whether the game has an existing object-pool path suitable for a player-controlled actor, or whether the native player context must be explicitly virtualized across all referenced state.
4. Identify the actual per-frame dispatch point and ensure the second actor's update, collision, render, animation, damage, and death state are all independently owned.
5. Only then reintroduce a Multiplayer option, initially behind a guarded test build.

No separate lives, shared camera, P2 visuals, or P2 gameplay completion should be claimed until tested in-game.
