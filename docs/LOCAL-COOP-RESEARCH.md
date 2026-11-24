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
- The main loop dispatches through seven callback slots: `$FFBC3C`, `$FFBC44`, `$FFBC4C`, `$FFBC1C`, `$FFBC62`, `$FFBC20`, and `$FFBC5E`. `$FFBC62` is the player update callback (`f_224C)); the others are additional setup/update/resource callbacks installed by the descriptor path. These are all part of the main player's callback context, not just one movement function.
- `f_19FA` calls `f_5232`. That routine resets the shared object-pool list heads at `$FFBC28` and `$FFBC30`, then creates a free list of 79 fixed-size records (62-byte stride, beginning at `$FFBF7A`) linked through `$FFBC2C`. It also clears the auxiliary list head at `$FFBC34`.
- `f_5300` removes a record from the free list at `$FFBC2C` and links it into the active list at `$FFBC28`; `f_5382` links a record into the second active list at `$FFBC30`; `f_5400` removes a record and returns it to the free list. These allocators are called from many unrelated game routines, not just the player.
- Within the player update graph, `f_4992` uses `f_5300` to create a secondary object and installs handler `0x49C8` at record offset `+34`. Other callers install other object handlers. The generic pool is therefore a shared secondary-object system (projectiles/effects and other game objects), not a substitute for the main player actor.
- `f_1BDE` also calls `f_5232` and `f_5578`. `f_5578` clears the auxiliary list at `$FFBC34` and resets 79 12-byte records beginning at `$FFD55A`. A second call to the descriptor setup path could therefore disturb shared live objects/resources; we must not simply call `f_19FA` a second time to manufacture P2.
- `f_5D8A` clears 29 four-byte entries beginning at `$FFFFFCE8` and resets the player sprite-state bytes at `$FFBD24/$FFBD25`. The main loop calls `f_5DB2` separately from the movement callback; `f_5DB2` builds the player's multipart sprite from the descriptor/state fields and uses a single fixed scratch area. P2 therefore needs a safe way to contribute its sprite to the shared renderer without overwriting P1's scratch data.
- The general object pool can still be useful for P2-owned projectiles/effects only after the main player context is properly separated. It does not create an independently controllable main player by itself.

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
3. Map every callback slot and every descriptor field to the initializer that fills it; distinguish player-owned state from shared stage, object-pool, VDP, and renderer state.
4. Trace the fixed buffers and resource callbacks used by `f_19FA` and `f_1BDE`, especially the two resource chains rooted at `$FFDFCE/$FFDD1E/$FF5C00` and `$FFE002/$FFDE4E/$FF9400`.
5. Design per-player RAM virtualization only for state proven to belong to the player. Keep the shared object pools and world state single-copy, and give P2 an independent persistent M68K register context and stack.
6. Extend the sprite path so P2's `f_5DB2` output is appended safely to the shared render queue with separate scratch storage.
7. Only after those pieces are mapped should we implement a guarded proof-of-concept, initially limited to P2 spawn, movement and collision before adding camera, visuals and lives.
