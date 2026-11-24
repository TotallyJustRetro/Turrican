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
- The main loop dispatches through seven callback slots: `$FFBC3C`, `$FFBC44`, `$FFBC4C`, `$FFBC1C`, `$FFBC62`, `$FFBC20`, and `$FFBC5E`. `$FFBC62` is the player update callback (`f_224C`); the others are additional setup/update/resource callbacks installed by the descriptor path. These are all part of the main player's callback context, not just one movement function.
- `f_19FA` calls `f_5232`. That routine resets the shared object-pool list heads at `$FFBC28` and `$FFBC30`, then creates a free list of 79 fixed-size records (62-byte stride, beginning at `$FFBF7A`) linked through `$FFBC2C`. It also clears the auxiliary list head at `$FFBC34`.
- `f_5300` removes a record from the free list at `$FFBC2C` and links it into the active list at `$FFBC28`; `f_5382` links a record into the second active list at `$FFBC30`; `f_5400` removes a record and returns it to the free list. These allocators are called from many unrelated game routines, not just the player.
- Within the player update graph, `f_4992` uses `f_5300` to create a secondary object and installs handler `0x49C8` at record offset `+34`. Other callers install other object handlers. The generic pool is therefore a shared secondary-object system (projectiles/effects and other game objects), not a substitute for the main player actor.
- `f_1BDE` also calls `f_5232` and `f_5578`. `f_5578` clears the auxiliary list at `$FFBC34` and resets 79 12-byte records beginning at `$FFD55A`. A second call to the descriptor setup path could therefore disturb shared live objects/resources; we must not simply call `f_19FA` a second time to manufacture P2.
- `f_5D8A` clears 29 four-byte entries beginning at `$FFFFFCE8` and resets the player sprite-state bytes at `$FFBD24/$FFBD25`. The main loop calls `f_5DB2` separately from the movement callback; `f_5DB2` builds the player's multipart sprite from the descriptor/state fields and uses a single fixed scratch area. P2 therefore needs a safe way to contribute its sprite to the shared renderer without overwriting P1's scratch data.
- The generic object pool is also used by the authentic player renderer. `f_5DB2` walks 29 sprite-part entries in the scratch table beginning at `$FFFFFCE8`. For each visible part it calls `f_5300` to allocate a shared render record, then calls `f_5CA4` to install the sprite-part handlers (`0x5CD0` at record offset `+34` and `0x5CFA` at `+30`). Thus the shared pool can hold multipart player sprite records as well as projectiles/effects; it is not a separate main-player actor system.
- This gives us a plausible authentic P2 rendering path: run the original player sprite preparation/render code against a correctly isolated P2 context, so its visible parts are appended to the shared pool. It is not yet safe to invoke twice because the per-player sprite descriptor table and resource callbacks still need to be separated.
- The 79-record shared pool is a real capacity constraint. The renderer may request up to 29 records for one character; two complete characters could request up to 58 before projectiles and effects. We need an allocator high-water/remaining-count check and graceful part/effect omission rather than allowing pool exhaustion to corrupt linked-list state.
- The main player renderer is a strong candidate for reuse once P2's state and scratch inputs are isolated, but the generic object allocator still does not create P2's movement, collision, damage or life state by itself.

## Runtime memory and CPU-context boundary

The generated runtime report shows a potential, more disciplined isolation seam:

- The emulator owns one 64 KB main RAM array, `ram[0x10000]`.
- `rd8_raw` masks the 68000 address to 24 bits, then returns `ram[a & 0xFFFF]` for work-RAM addresses at or above `0xE00000`.
- `bus_rd8` and `bus_rd16` special-case VDP ports, then read ordinary memory through `rd8_raw`.
- `bus_wr8` handles VDP, PSG and Z80 special regions, then writes ordinary work RAM to `ram[a & 0xFFFF]`; `bus_wr16` similarly handles VDP and writes normal RAM bytes.
- This suggests a central banked-RAM translation layer could isolate a *verified set* of P2-owned RAM addresses while leaving stage state, camera, VDP and shared object lists single-copy. This remains a hypothesis until the generated `RD8/RD16/RD32/WR8/WR16/WR32` macros are verified to pass every relevant access through these bus functions, and the direct plus indirect RAM reference sets have been classified.
- The M68K context is not just a program counter: `M68K` stores D0-D7, A0-A7, `ret`, `usp`, X/N/Z/V/C and `sr_sys`. P2 needs its own persistent instance; copying the active P1 registers before every P2 callback is specifically forbidden.
- Generated nested calls also use shared `rt_shadow` / `rt_sp` return bookkeeping. We must inspect how that bookkeeping behaves when callbacks are invoked with a second M68K context, and make it safe for sequential P1/P2 updates.
- Port 2 is sampled independently by the runtime into the emulated controller bytes `$FFBC92/$FFBC93`; the player callback currently reads `$FFBC90/$FFBC91`. A P2 memory-bank pass can potentially present P2's input at those expected addresses without overwriting P1's input state, but this must be implemented at a verified point in the memory-bus context switch.
- A banked P2 pass would also need its own player-local scratch such as the 29-entry sprite descriptor buffer at `$FFFFFCE8), while keeping the shared render-record pool and its list heads single-copy.

The key engineering task is now to classify the full player callback's direct and pointer-indirect memory accesses, then define a narrow P2 RAM view and persistent CPU context. Do not bank the whole 64 KB RAM: many addresses in it are shared world, VDP, audio, object-pool, timer and stage state.
  
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
7. Build a guarded P2 render-only experiment using the original `f_5DB2` path after a P2 context exists, and instrument the shared 79-record pool for capacity/overflow.
8. Then add P2 update/collision using the same callback family under independent context virtualization. Only after that works should we add camera and lives.
