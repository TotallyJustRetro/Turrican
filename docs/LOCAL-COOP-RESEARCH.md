# Mega Turrican local co-op research status

## Safety status

The first RAM-shadow prototype is disabled and must not be reintroduced.

The user's test confirmed that Player 2 was not controllable, moved out of bounds, corrupted the level, and caused restart crashes.

## What the generated recomp report confirms

- The main gameplay player/update path is `f_156A`. The game-state routine `f_200` calls it directly at PCs `0x03EE` and `0x040E`, under separate state branches. `f_156A` selects a descriptor through the ROM table at `0x1994`, indexed by `$FFBF1E`, and calls the setup routine `f_19FA`. It conditionally calls `f_1BDE` as a secondary setup/respawn path. The exact cadence of `f_156A` relative to rendered video frames still needs to be proven from the outer game-state flow.
- The game-state routine `f_200` installs `f_468` in the primary callback slot `$FFBC14` at PCs `0x03AA` and `0x044E`. It calls `f_156A` at `0x03EE` and `0x040E` and then continues its own state machine. This is the first confirmed caller chain into the player update path; it means P2 must be scheduled relative to the existing `f_200`/`f_156A` flow, not bolted onto an unrelated end-of-frame hook.
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

The generated recomp report establishes a central work-RAM access path:

- The emulator owns one 64 KB main RAM array, `ram[0x10000]`.
- `rd8_raw` masks the 68000 address to 24 bits, returns ROM for ROM addresses, and returns `ram[a & 0xFFFF]` for work-RAM addresses at or above `0xE00000`.
- `bus_rd8` and `bus_rd16` special-case VDP ports. Ordinary RAM reads pass through `rd8_raw`; `bus_rd16` composes two `rd8_raw` reads.
- `bus_wr8` handles VDP, PSG, Z80 and controller ports, then writes normal work RAM to `ram[a & 0xFFFF]`.
- `bus_wr16` special-cases VDP, then writes the two bytes directly into `ram[]` for work-RAM addresses. It does not call `bus_wr8` for normal RAM.
- `m68k_rt.h` defines `RD8/RD16/RD32` through `bus_rd8/bus_rd16` and `bus_rd32`; `WR8/WR16/WR32` similarly route through `bus_wr8/bus_wr16` and `bus_wr32`. This is a viable interception point for ordinary recompiled 68000 accesses, provided both the byte-read and both write widths are handled.
- There is an important exception to keep in mind: `vdp_dma_read` calls `rd8_raw` directly. A global P2 RAM-view switch would also affect DMA reads if a video event runs while the P2 view is active. The DMA/video path must be forced to the shared RAM view, or the context switch must be deferred safely around that work.
- `RT_POLL` can call `rt_event(c)` when the shared `rt_budget` is exhausted and calls `rt_irq_service(c)` when an interrupt is pending. Therefore a P2 callback can yield into video/audio/interrupt processing while a P2 memory view is active. It is not safe to add a bank switch without explicitly handling this nested event/interrupt boundary.
- The CPU context is `M68K`, containing D0-D7, A0-A7, `ret`, `usp`, X/N/Z/V/C and `sr_sys`. P2 needs a persistent independent instance, including its own valid A7 stack. Copying P1's live CPU registers before each P2 callback is forbidden.
- Generated calls share `rt_shadow[65536]` and `rt_sp` for return bookkeeping. A sequential P2 call might reuse this machinery only if it enters/exits at a known stack baseline and all nested calls unwind; this needs a runtime assertion and explicit nested-event handling.
- A full 64 KB P2 RAM copy is not appropriate: it would duplicate stage state, camera, VDP queues, audio/interrupt state, shared object-pool lists, timers and other global state. The goal is a selective RAM view with a documented address allowlist and a shared fallback for all other work-RAM addresses.
- The P2 candidate input is sampled by the runtime at `$FFBC92/$FFBC93`; the original player callback reads `$FFBC90/$FFBC91`. The bus-view layer could present P2's sample at the player-local input locations without overwriting P1's current sample, but this must be done only during the P2 player pass.
- The callback graph rooted at `f_224C` touches both likely player-local state (for example `$FFBCC0-$FFBCFE` and `$FFBD00-$FFBD22)) and confirmed shared structures: object-pool links `$FFBC28/$FFBC2C), VDP command queue `$FFBCA4/$FFBCA6/$FFD2DA), and camera/scroll fields `$FFDFD4-$FFDFE4). This rules out banking broad contiguous blocks without a byte-level ownership map.
- The renderer uses a fixed 29-entry sprite-part scratch table at `$FFFFFCE8`, then allocates shared draw records. A P2 render pass will need separate scratch storage but must append to the same draw queue, with pool-capacity checks.

## Confirmed coordinate and input semantics

- `f_224C` polls the controller bytes at `$FFBC90/$FFBC91`; the SDL runtime separately samples controller 2 into `$FFBC92/$FFBC93`. A P2 pass must expose the second sample at the player-local input location without altering P1's sample.
- `$FFBD1E) and `$FFBD20` are screen-space player coordinates. The movement routine compares and clamps X to `0x128` and Y to `0xE0`; they are not world coordinates.
- The camera/scroll fields `$FFDFD4/$FFDFD6` are read separately by the player logic. Camera values and screen-space player coordinates must never be combined or interpreted as the same coordinate.
- `f_224C` also uses `$FFDFD8/$FFDFDA` through helper `f_3368`, while helpers `f_3430` and `f_3514` access `$FFDFD4/$FFDFD6`. These are shared-camera candidates that must be examined before deciding which writes P2 may perform.
- The callback contains a computed call through A6 at PC `0x288E`, in addition to its direct calls. Its dynamic target is part of the player's per-frame behavior and must be preserved in P2's initialized context.

## Frame/event scheduling constraints

The runtime helper bodies add another critical constraint:

- `RT_POLL` decrements the shared `rt_budget`; when it drops below zero, it calls `rt_event(c)`. It then calls `rt_irq_service(c)` if an interrupt is pending.
- `rt_event` advances one VDP line, renders that line, advances audio, updates VBlank/HBlank pending state, and after a full frame calls `md_frame_hook()`.
- `md_frame_hook` polls SDL events, handles pause/title UI and gameplay options, then refreshes `md_live_mask` from controller 1 and `md_player2_live_mask` from controller 2. It also renders/presents the frame.
- `rt_irq_service(c)` dispatches VBlank/HBlank handlers using the exact `M68K *c` passed by the generated callback. If a future P2 CPU context enters a nested event with a normal interrupt mask, the interrupt handler would run against P2's registers and the currently selected P2 memory view. P2's interrupt semantics therefore need explicit handling.
- An isolated P2 update must not accidentally advance a second video/audio frame or run the launcher/game frame hook mid-callback. One possible design is to save `rt_budget`, run the P2 per-player callbacks under a bounded no-yield guard, and restore the budget afterwards; this is only a proposal until the exact callback duration and IRQ behavior are tested.
- If event/yield behavior is retained during P2 execution, the event path must temporarily select the shared RAM view and dispatch game interrupts only on the primary CPU context. VDP DMA reads through `rd8_raw`, and `md_frame_hook` performs UI/input work, so leaving the P2 view globally selected during an event is unsafe.
- The P2 controller mask is refreshed by `md_frame_hook`, not continuously by the SDL callback itself. A P2 pass should latch `md_player2_live_mask` at a stable point before entering the player callback and expose it through P2's local view at `$FFBC90/$FFBC91`.

The memory bus is therefore a useful *mechanism*, not an ownership map. Before implementing it, we still need to classify every direct and pointer-indirect player access, isolate event/interrupt execution onto the shared view, and reserve a safe P2 stack.

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
