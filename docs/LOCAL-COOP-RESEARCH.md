# Mega Turrican local co-op research status

## Safety status

The first RAM-shadow prototype is disabled and must not be reintroduced.

The user's test confirmed that Player 2 was not controllable, moved out of bounds, corrupted the level, and caused restart crashes.

## What the generated recomp report confirms

- The main gameplay loop is `f_156A`. It selects a descriptor through the ROM table at `0x1994`, indexed by `$FFBF1E`, and calls the setup routine `f_19FA`. It conditionally calls `f_1BDE` as a secondary setup path.
- `f_19FA` saves the descriptor pointer at `$FFBC50`, reads the descriptor's fields, and initializes a group of lower player-context slots including `$FFBC1C`, `$FFBC20`, `$FFBC24`, `$FFBC3C`, `$FFBC40`, `$FFBC44`, `$FFBC48`, `$FFBC4C`, and `$FFBC5A`.
- `f_19FA` installs the player update callback pointer `0x224C` at `$FFBC62`. The main loop later reads that slot and dispatches through it with `rt_call_addr`.
- `f_1BDE` is a conditional secondary setup path that also reads the descriptor at `$FFBC50` and writes the callback slot at `$FFBC62`. It is not established to be a second-player initializer.
- `f_224C` is the active player update callback. The main loop separately calls `f_5DB2` for the player's native sprite/render work.
- The prior prototype copied only `$FFBC70-$FFBD26`. That left out the lower `$FFBC00-$FFBC6F` setup/context area, including the descriptor pointer, callback slot, and function/resource pointers prepared by `f_19FA`. This is a confirmed major flaw in the old design, but it is not yet a complete list of everything that must be independent.
- `$FFBCC4` is followed by `f_224C` as a ROM-side state/table address. The current code path sets it to values such as `0x2230` or `0x223E`; it should not be described as a pointer to a separate mutable heap allocation.
- The generated report shows `f_5300` being called by ordinary object constructors which then install handlers in object records. The dedicated player update path through `$FFBC62` is separate in the code we have traced so far. It is not yet proven that the generic object pool can host a player.

## Why the previous attempt was unsafe

The old prototype copied P1's upper player RAM window but did not initialize P2 through the game's own descriptor/setup path. It also copied P1's live CPU register context before each P2 callback instead of preserving an independent P2 execution context. That mixed state and caused the observed out-of-bounds movement and corruption.

## Current build policy

- Keep the original single-player path intact.
- Keep independent P1/P2 launcher controller profiles and native port-2 polling as low-level input groundwork.
- Do not expose or enable an in-game Multiplayer toggle until a valid second actor exists.
- Keep `build-overrides/patch-local-coop.py` fail-closed and do not re-run the RAM-shadow prototype.
- Do not claim separate lives, shared camera, P2 visuals, or P2 gameplay until implemented and tested in-game.

## Next implementation investigation

1. Build a direct-call and indirect-call graph rooted at `f_156A`, `f_19FA`, `f_1BDE`, `f_224C`, and `f_2150`.
2. Resolve the ROM descriptor table at `0x1994` and the descriptor fields consumed by `f_19FA`.
3. Identify the purpose and ownership of the pointer-driven buffers and routines referenced by the lower player context.
4. Inspect the separate object-pool allocator and renderer to determine whether it can represent a player actor without bypassing the real movement/collision path.
5. Design a P2 context with independently initialized data and persistent M68K register/stack state; never refresh P2's registers from P1 each frame.
6. Only after these pieces are mapped should we implement a guarded proof-of-concept, initially limited to P2 spawn, movement and collision before adding camera, visuals and lives.
