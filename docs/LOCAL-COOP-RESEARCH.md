# Mega Turrican local co-op research status

## Safety status

The first RAM-shadow prototype is disabled and must not be reintroduced.

The user's test confirmed that Player 2 was not controllable, moved out of bounds, corrupted the level, and caused restart crashes.

## Latest safe diagnostics build

- GitHub Actions run `45350837966` completed successfully on 2026-11-24 with the RAM-shadow co-op patch absent and the read-only descriptor/callback trace step enabled.
- The Windows package includes `MegaTurrican.exe` and `MegaTurricanLauncher-1.0.0-x64.exe`. The executable was checked for the trace filename, callback-target trace format, and both-controller input fields.
- A normal single-player launch creates/appends `MegaTurrican-coop-runtime-trace.txt` in the launcher's working directory (the launcher sets this to its own folder). No Multiplayer option is exposed in this build. This package is for safe runtime diagnostics only; it is not a P2 gameplay test build.
- GitHub Actions run: https://github.com/TotallyJustRetro/Turrican/actions/runs/45350837966

## What the generated recomp report confirms

- The main gameplay player/update path is `f_156A`. The game-state routine `f_200` calls it directly at PCs `0x03EE` and `0x040E`, under separate state branches. `f_156A` selects a descriptor through the ROM table at `0x1994`, indexed by `$FFBF1E`, and calls the setup routine `f_19FA`. It conditionally calls `f_1BDE` as a secondary setup/respawn path. The exact cadence of `f_156A` relative to rendered video frames still needs to be proven from the outer game-state flow.
- The game-state routine `f_200` installs `f_468` in the primary callback slot `$FFBC14` at PCs `0x03AA` and `0x044E`. It calls `f_156A` at `0x03EE` and `0x040E` and then continues its own state machine. This is the first confirmed caller chain into the player update path; it means P2 must be scheduled relative to the existing `f_200`/`f_156A` flow, not bolted onto an unrelated end-of-frame hook.
- `f_200` also installs `f_468` into the separate system callback slot `$FFBC14`. `f_468` calls `f_9B908` and `f_D000C` as part of the asynchronous resource/VDP transfer path; it is not one of the player movement callbacks. Keep this system/resource callback distinct from the player callback family when designing P2.
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
- Generated calls share `rt_shadow[65536]` and `rt_sp` for return bookkeeping. Because this is a synchronous LIFO stack, P2 may be able to nest on the existing shadow stack after P1's player callback returns to a known baseline; a second shadow array is not automatically required. The implementation must snapshot the entry `rt_sp`, allow nested P2 calls (and any P1 event/IRQ calls to push above them), and assert that every nested path returns to the same depth. A leaked/mismatched depth must abort the P2 pass before the next game frame.
- A full 64 KB P2 RAM copy is not appropriate: it would duplicate stage state, camera, VDP queues, audio/interrupt state, shared object-pool lists, timers and other global state. The goal is a selective RAM view with a documented address allowlist and a shared fallback for all other work-RAM addresses.
- The P2 candidate input is sampled by the runtime at `$FFBC92/$FFBC93`; the original player callback reads `$FFBC90/$FFBC91`. The bus-view layer could present P2's sample at the player-local input locations without overwriting P1's current sample, but this must be done only during the P2 player pass.
- The callback graph rooted at `f_224C` touches both likely player-local state (for example `$FFBCC0-$FFBCFE` and `$FFBD00-$FFBD22)) and confirmed shared structures: object-pool links `$FFBC28/$FFBC2C), VDP command queue `$FFBCA4/$FFBCA6/$FFD2DA), and camera/scroll fields `$FFDFD4-$FFDFE4). This rules out banking broad contiguous blocks without a byte-level ownership map.
- The renderer uses a fixed 29-entry sprite-part scratch table at `$FFFFFCE8`, then allocates shared draw records. A P2 render pass will need separate scratch storage but must append to the same draw queue, with pool-capacity checks.

## Confirmed coordinate and input semantics

- `f_224C` polls the controller bytes at `$FFBC90/$FFBC91`; the SDL runtime separately samples controller 2 into `$FFBC92/$FFBC93`. A P2 pass must expose the second sample at the player-local input location without altering P1's sample.
- `$FFBD1E) and `$FFBD20` are screen-space player coordinates. The movement routine compares and clamps X to `0x128` and Y to `0xE0`; they are not world coordinates.
- The camera/scroll fields `$FFDFD4/$FFDFD6` are read separately by the player logic. Camera values and screen-space player coordinates must never be combined or interpreted as the same coordinate.
- `f_224C` also uses `$FFDFD8/$FFDFDA` through helper `f_3368`, while helpers `f_3430` and `f_3514` access `$FFDFD4/$FFDFD6`. These are shared-camera candidates that must be examined before deciding which writes P2 may perform.
- The callback contains an indirect call through A6 at PC `0x288E`. A6 is loaded with `f_4B58` or `f_4B74` at earlier branch sites; this selection is separate from the `$FFBCC4` state/table value. Both targets allocate from the shared object pool through `f_5300` and install handler `0x4BD0`. Treat this as a player-triggered shared-object path, not as a second private object pool.

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

## Player callback call-graph findings

The depth-six generated-code audit rooted at `f_224C` gives a more specific separation:

- `f_224C` is a large player-local movement/input state machine. Its direct calls include `f_20D2`, `f_2150`, `f_2612`, `f_2640`, `f_26A2`, `f_28A6`, `f_2A18`, `f_2D84), `f_2DE8`, `f_2E34`, `f_31A0`, `f_31E4`, `f_3222`, `f_3284`, `f_3368`, `f_3430`, `f_34DA`, `f_3514`, `f_35D8`, `f_35E4`, `f_3650`, `f_374E), and others. Its dynamic indirect callback at PC `0x288E) must also be retained in a proper P2 context.
- The callback has a substantial per-player data region at `$FFBCBC-$FFBCFE) and `$FFBD00-$FFBD22), with the core screen position at `$FFBD1E/$FFBD20). It also reads/writes player control/condition bytes at `$FFBC84/$FFBC88) and input at `$FFBC90/$FFBC91). These are candidates for P2's private RAM bank, but the full access map and pointers still need reviewing before defining an allowlist.
- The movement graph calls `f_4992`, which allocates through `f_5300`; it also reaches `f_5B02`, which removes a record through the same shared free list. This is the game's native way for player actions to create/retire projectile or related records. P2 should therefore use the same global object lists and allocator so both players' projectiles and effects coexist in one world. Those pool links and free-list metadata must never be copied into P2's private bank.
- The movement graph reaches `f_3430` through `f_26A2`; `f_3430`, `f_34DA`, and `f_34E2` are coordinate-transform/bounds helpers that read global scroll/view values, including `$FFDFD4/$FFDFD6` and `$FFDFDC/$FFDFE4`. The actual player-follow writer identified in the generated code is `f_3368`, called by `f_224C` at PC `0x24BA`. It reads player condition `$FFBC87`, screen coordinates `$FFBD1E/$FFBD20`, and tracking state `$FFBCCE/$FFBCD2/$FFBCD6/$FFBCD7`, then writes the shared view offsets `$FFDFD8/$FFDFDA`. P2 must not independently invoke `f_3368`; the camera needs one combined follow decision based on both players, while the transform helpers continue to read the one shared view.
- This is consistent with the coordinate model: `$FFBD1E/$FFBD20) are screen-space coordinates; the camera is represented separately. The shared-camera condition must be based on both screen-space player positions, not a second copy of world scroll state.
- The callback also touches `$FFBC54/$FFBC58`, `$FFBF20/$FFBF21/$FFBF23), `$FFF226), and `$FFFA00). These fields have mixed cross-routine use, so they remain unclassified; do not bank them merely because they appear under the player call graph.

## Descriptor initialization and player-loop boundary (latest report audit)

The recovery build's runtime-state report provides a narrower, safer scheduling boundary:

- In `f_156A`, the game reads the selector at `$FFBF1E`, scales it by four, reads a longword from the table beginning at ROM address `0x1994`, and passes that selected descriptor pointer to `f_19FA`. The descriptor variants and their exact meaning still need decoding; this does **not** establish that a second table entry is a P2 descriptor.
- `f_19FA` stores that descriptor pointer in `$FFBC50` and uses descriptor fields to populate several player-context callback/resource slots. Confirmed destinations include `$FFBC1C`, `$FFBC20`, `$FFBC24`, `$FFBC3C`, `$FFBC44`, `$FFBC4C`, and `$FFBC5A`. It installs `f_224C` at `$FFBC62`.
- The setup routine also initializes two resource chains using the fixed resource roots `$FFDFCE/$FFDD1E/$FF5C00` and `$FFE002/$FFDE4E/$FF9400`. Their ownership is not yet classified: they may be player-specific resource state, shared VDP/resource state, or a mixture. Do not clone or redirect them until their callback effects are traced.
- A critical detail is now explicit in the initializer body: `f_19FA` calls both `f_5232` and `f_5D8A`. The first rebuilds the shared 79-record object list; the second clears the fixed 29-entry sprite-part scratch table and resets sprite state. A second call to `f_19FA` during a live level would therefore reset shared live state. A future P2 initializer must split player-context setup from one-time shared-pool/sprite initialization rather than simply invoking `f_19FA` twice.
- The conditional `f_1BDE` path is also unsuitable as a P2 constructor: it calls `f_5578`, `f_5232`, and `f_5D8A` before restoring/rebinding state from saved fields. Its role is a secondary setup/restore path for the existing player, not evidence of a second-player slot.
- The actual `f_156A` path is broader than player movement. In its main gameplay sequence it dispatches descriptor-supplied callbacks through `$FFBC3C`, `$FFBC44`, `$FFBC4C`, and `$FFBC1C`; runs shared helper stages; calls `f_5DB2` to append the current player's multipart sprite; reads `$FFBC62` and dispatches `f_224C`; then runs post-player helpers and dispatches `$FFBC20`. A further conditional path dispatches the `$FFBC5E` callback. `$FFBC5A` is not an eighth callback: it is a resource-table pointer passed to `f_5EC`, which copies 32 longwords from that table into the work buffer beginning at `$FFDC9E`; `f_6D6` then polls the associated status. These slots and resource buffers need individual ownership/side-effect classification before any are duplicated.
- The order matters: the existing loop calls `f_5DB2` immediately before the `$FFBC62` movement callback. P2 rendering should be inserted at a deliberately chosen point in this sequence, not by calling all of `f_156A` again.
- `f_224C` reaches player input, movement, collision/state helpers and projectile creation. Its child graph includes `f_3284`, `f_2640`, `f_26A2`, `f_2150`, `f_3222`, and `f_31E4). `f_26A2` reaches the camera helper `f_3430`; `f_4992` allocates from the shared object pool; and `f_5B02` returns objects to that pool. This confirms the required split: duplicate only proven player-local state/logic, while camera, world collision data, object lists, and allocation stay shared.
- `f_2150` selects one of the ROM-side state/table values `0x2230` or `0x223E` and stores it at `$FFBCC4`. Separately, the indirect call at PC `0x288E` in `f_224C` uses A6, which is assigned earlier by control-flow branches directly to either `f_4B58` or `f_4B74` (PCs `0x27D4`, `0x2820`, and `0x2826`). These are two distinct mechanisms; `$FFBCC4` does **not** supply the A6 call target. Both constructors allocate from the shared pool via `f_5300`, install handler `0x4BD0`, and initialize a common object record from the current player state. `f_4B58` copies the current player screen position from `$FFBD1E` and player state `$FFBC86`; `f_4B74` does the same, but first runs `f_D0010` with selector `0x27` and writes different object fields. This is evidence that player-triggered objects can enter the shared world pool, not proof that the constructors are generic player-spawn routines.

## Updated implementation sequence

1. Finish the per-slot audit for `$FFBC3C/$FFBC44/$FFBC4C/$FFBC1C/$FFBC62/$FFBC20/$FFBC5E`: identify each target, all reads/writes, whether it runs once or conditionally, and which side effects are shared.
2. Decode the descriptor table at `0x1994` and every field consumed by `f_19FA`; identify which pieces are immutable ROM resources, player-local state, and shared resource/VDP state.
3. Resolve the A6 indirect call at `0x288E` and all pointer-indirect accesses beneath `f_224C`. The direct-address list alone is not sufficient for a safe RAM allowlist.
4. Produce a byte/word-level RAM ownership map and reserve an independent P2 stack/context. Do not choose a synthetic RAM region until all fixed and pointer-derived uses of that region have been checked.
5. Split one-time shared initialization from player-context initialization. Keep `f_5232`, `f_5578`, and the shared reset part of `f_5D8A` single-instance; give P2 an isolated sprite-part scratch table and append its parts to the common object/render queue with overflow guards.
6. Add a guarded P2 render-only pass only after its context, resource references, and scratch storage are valid. Then add movement/collision while gating the camera-advance side effect and keeping the global `f_156A`/continue flow single-instance.
7. Add lives/continue and the requested extra-life sharing rules only after both actors survive gameplay, death, respawn, and level transitions.

## ROM descriptor selector behavior

The selector at `$FFBF1E` is not simply copied as a character ID. The initializer feeds it through several ROM-table helpers before installing its callbacks:

- `f_B0A` multiplies D0 by four, selects a longword through the table rooted at ROM `0xB1C+12`, then follows another offset table and reads a word.
- `f_B38` similarly indexes a longword table rooted at ROM `0xB3E-34`, follows the selected pointer, and copies a count-controlled block.
- `f_AD2` preserves A0, computes D0=`selector*4`, computes D1 as an eight-byte stride, indexes the table rooted at ROM `0xB1C`, follows a second offset table, loads register data, and restores A0.
- `f_19FA` uses the resulting values to populate the first nested callback/resource structure and calls the selected target at `0x1AF0`. The direct `descriptor+2` bytes are therefore not enough to identify that callback; the target recorded at phase `101` is the correct value.
- The second nested chain and the descriptor `+38` callback are also captured after their actual runtime setup at phases `102` and `103`. This avoids treating raw descriptor fields as callable pointers when the game performs additional indexed lookup first.

The selector may distinguish character or animation/resource variants, but that meaning is not proven yet. The runtime capture will reveal the exact selector and the callable targets for the title/level state we test.

## Exact runtime callback trace points

The diagnostic hook now records the actual 68000 target address immediately before each selected indirect call. Phase IDs are fixed in the trace output:

- `101`, `102`, `103`: the three dynamic calls inside `f_19FA` at PCs `0x1AF0`, `0x1B32`, and `0x1B56`. These capture the selected target after the descriptor-selection logic has finished, so they are authoritative; the nested descriptor raw bytes are supplementary only.
- `201`, `202`, `203`: the three dynamic calls inside `f_1BDE` at PCs `0x1C60`, `0x1CA2`, and `0x1CAC`. These capture the restore/setup callback targets after `f_1BDE` has read the saved descriptor and callback fields.
- `301`, `302`, `303`, `304`: the recurring player-frame callback targets in `f_156A` at PCs `0x1620`, `0x162A`, `0x1630`, and `0x163E`, corresponding to the four descriptor-supplied callbacks in slots `$FFBC3C`, `$FFBC44`, `$FFBC4C`, and `$FFBC1C`.
- `305`: the active player update callback in `$FFBC62` at PC `0x1660` (normally `f_224C`).
- `306`: the post-update callback in `$FFBC20` at PC `0x166E`.
- `307`: the optional callback loaded from `$FFBC5E` at PC `0x1746`; the trace will show whether it is present and which target is actually used.

The trace records the descriptor pointer, actual indirect target, 68000 D/A registers, active selector, player state, current P1 input bytes, player screen coordinates, and shared view offsets. Calls are de-duplicated by descriptor/target/phase, so the file should remain small even though the player loop runs every frame. These hooks only append diagnostic text; they do not alter emulated registers, RAM, callback targets, or game control flow.

## Runtime actor-context and event/interrupt rules

The runtime audit confirms that the P2 execution context must be isolated at the emulator layer, not only by copying game RAM:

- `M68K` contains D0-D7, A0-A7, `ret`, `usp`, condition flags, and `sr_sys`. The runtime currently owns one static CPU in `md_boot` and exposes it through the global `CPU` pointer. P2 requires a second persistent `M68K` instance with an independent valid A7 stack; copying P1's registers each frame is not acceptable.
- Generated code accesses memory through `RD8/RD16/RD32` and `WR8/WR16/WR32`, which route through `bus_rd8/bus_rd16/bus_wr8/bus_wr16`. However, `vdp_dma_read` calls `rd8_raw` directly. The actor-aware work-RAM view must therefore be applied in `rd8_raw` as well as the bus writers, or DMA reads during P2 would see the wrong memory.
- `RT_POLL` decrements the single global `rt_budget`; if it goes negative it calls `rt_event(c)`, and if an IRQ is pending it calls `rt_irq_service(c)`. `rt_event` advances the VDP line, renders, advances sound, and can call `md_frame_hook`. `rt_irq_service` dispatches interrupt handlers using the exact `M68K *c` passed to it. A P2 callback must never accidentally service the game's VBlank/HBlank handlers on P2's CPU state.
- The call/return repair path also relies on one global `rt_shadow[65536]` and `rt_sp`. Treat this as a nested shared stack until tests prove otherwise: enter P2 only at a known P1 depth, preserve the existing P1 entries below it, and require every P2/nested event path to unwind to its entry depth. Only add a second shadow stack if the generated runtime violates this LIFO nesting model.
- A robust actor switch should preserve the P2 CPU, sparse player-local RAM view, and actor tag while keeping the global `rt_shadow/rt_sp` stack nested and balanced. When `RT_POLL` needs a VDP event or IRQ during a P2 pass, temporarily restore the shared RAM view and dispatch the event/interrupt on the primary P1 CPU context; any temporary return entries must be pushed above the still-active P2 entries and unwound before P2 resumes. This keeps DMA, frame hooks, and interrupts on the single shared system context without skipping frame time.
- Simply setting `rt_budget` to a huge value and deferring all events/IRQs is not the preferred final solution: it would make P2 execution effectively free in the frame budget and delay interrupts. The event/IRQ wrapper should charge P2's poll count to the same budget and service any resulting events on P1.
- The global `rt_trace/rt_ti` and shared `rt_shadow/rt_sp` can remain single-instance if the nested-depth invariant holds. P2's save-state data must eventually include its persistent CPU context, private actor bytes, sprite scratch, and actor-bank selector; the existing save-state structure serializes only the single `CPU`, main RAM, and one shadow stack, so co-op save/load still needs an explicit dual-actor extension.

## Descriptor initializer: three dynamic callback phases

The newest expanded report shows that `f_19FA` has three distinct indirect calls. The full initializer therefore cannot be treated as one generic player-state constructor:

- At PC `0x1AF0`, it calls the function pointer obtained from the structure at descriptor offset `+2`. The same pointer is saved in `$FFBC40`. The call is prepared with resource/transfer roots `$FFDFCE`, `$FFBC94`, `$FFDD1E`, and `$FF5C00` in A6/A4/A3/A1 respectively. This strongly suggests the first resource setup phase, but the exact callback target and side effects still depend on the runtime descriptor contents.
- At PC `0x1B32`, it calls the function pointer obtained from the nested structure reached through descriptor offset `+6`; the pointer is saved in `$FFBC48`. This call is prepared with a second resource chain: A6=`$FFE002`, A4=`$FFBC96`, A3=`$FFDE4E`, A2=`0x2000`, and A1=`$FF9400`. Treat this as a separate resource/setup phase until its target is resolved.
- Immediately after the second call, `f_19FA` invokes `f_5232` and `f_5D8A`. `f_5232` resets the global 79-record object lists and auxiliary record list; `f_5D8A` clears the single 29-part renderer scratch list and sprite phase bytes. These are explicit shared one-instance side effects.
- At PC `0x1B56`, it calls the longword stored at descriptor offset `+38`. This happens after those resets. It then snapshots shared view state `$FFDFD4` into `$FFBF0E`, copies the current player position `$FFBD1E` into `$FFBF12`, copies player size/state `$FFBD22/$FFBC87` into `$FFBF17/$FFBF16`, resets/sets player flags, and installs `f_224C` at `$FFBC62`. This is the strongest candidate for the descriptor's player-specific runtime initialization callback, but its target still must be read from the real descriptor.
- The alternate `f_1BDE` setup/restore path also has three indirect calls. It walks existing active-list state, runs `f_5578`, `f_5232`, and `f_5D8A`, then invokes descriptor-derived callbacks. It is therefore not a safe shortcut for creating P2 either.
- A plausible future split is: resolve and share immutable character/animation resources from the first two phases; run player-specific setup separately for P1 and P2; and run shared list/scratch resets exactly once. This remains a design hypothesis until the live descriptor callback addresses and the effects of each target are captured.


## Expanded generated-callgraph and ownership audit

The extended report now traces the direct player update graph to depth six instead of relying only on the top-level callback body:

- `f_224C` reaches 41 generated functions in the audited direct-call graph. Its own body references 52 distinct RAM addresses; the deeper graph exposes additional player, sprite, allocator, VDP-command, and camera/view state. It also has one indirect call site, the A6 action dispatch at PC `0x288E`, whose selected code targets were separately resolved to `f_4B58` and `f_4B74`.
- The camera-writer caller scan finds two callers for `f_3368`: `f_224C` at PC `0x24BA` and a second generated player-state entry `f_2E94` at the same PC. `f_2E94` shares the movement tail at `0x244E-0x2610`, reads the active player's input at `$FFBC90`, updates sprite/state selection at `$FFBCC0` based on `$FFBF1E`, updates player position/status fields, and calls the same camera-follow writer. Its external dispatch/callback source still needs to be identified, so it must be included in the dynamic entry audit rather than assumed to be a direct child of `f_224C`.
- The movement graph's obvious player-state candidates include control/status fields around `$FFBC84-$FFBC91`, movement/animation fields across `$FFBCBC-$FFBCFE`, and position/actor fields across `$FFBD00-$FFBD22`. `$FFBC54/$FFBC58`, `$FFBF1E/$FFBF20/$FFBF23`, and several status/resource fields have mixed use across setup, rendering, and movement; they are not yet approved for a blind private-bank allowlist.
- The graph also touches shared list heads and records through `$FFBC28/$FFBC2C/$FFBC30` and `$FFBF3C`; these belong to the global object system. The allocator's free records begin at `$FFBF7A` and use a 62-byte stride for 79 entries. Player projectiles, effects, and multipart sprite parts must all continue to use this one allocator.
- The player graph reaches the VDP command queue through `f_6DE -> f_6E6 -> f_71C`, which reads/writes `$FFBCA4/$FFBCA6` and `$FFD2DA`. Resource transfer state around `$FFBC94/$FFBC96/$FFBCA8-$FFBCB4/$FFDC9E`, plus descriptor-linked DMA roots `$FFDFCE/$FFE002`, is also shared or mixed. These must not be copied into P2's local view.
- The `f_5DB2` renderer graph contains eight functions. It reads player sprite/resource state, the 29-entry scratch area `$FFFFFCE8`, the shared view offset `$FFDFD8`, and camera transform fields; then it allocates from the shared object pool. Its helper `f_2660` also touches animation/status flags, so a render-only pass still needs more than just independent X/Y coordinates.
- The theoretical maximum is 29 sprite-part records per character. Two fully populated characters could reserve up to 58 of the 79 shared records before enemies, player-fired objects, and effects. This is a capacity warning, not a claim that every frame consumes all 29; the eventual renderer needs a measured high-water mark and an overflow-safe fallback.
- The `f_156A` root reaches 103 functions in the same depth-six audit and contains the descriptor setup, shared transfers, sprite preparation, player update, and post-update phases. Its two direct callers are both in `f_200` under separate game-state branches. This reinforces the boundary: duplicate a classified player context and its player-owned phases, never the entire `f_156A` entry.
- The current audit is still not a complete ownership proof: direct-call graph limits do not resolve every pointer-indirect read, runtime callback value, DMA access, or nested event/interrupt. Until those are classified, no RAM range should be called a safe P2 bank.

## Preliminary life, resource, and continue-counter ownership

The current static evidence separates at least two counters that must not be conflated:

- `$FFBF3A` is the strongest continue-stock candidate. The main setup path initializes it to `3` when `$FFBC69` is at least `2`, otherwise initializes it to `0xFF`; later game-state logic reads it and subtracts one using BCD `SBCD`, writing the result back. The existing `md_infinite_continues_enabled` patch is specifically at the subtract instruction at PC `0x192C`. Treat `$FFBF3A` as the current shared continue counter pending one runtime sample, not as an individual P1 life counter.
- `$FFBD0D` is not the life counter. Setup writes `3` to it; the pickup/resource path caps it at `3`; and the player object-spawn routine `f_4992` checks it before creating an object with handler `0x49C8`, then decrements it. This is a limited player resource/ammunition count and must be preserved separately from lives.
- `$FFBF32` and `$FFBF38` are cleared by `f_1944` and later manipulated through BCD arithmetic by `f_5FE6` and `f_6566`. Their exact gameplay meaning is not established; do not repurpose these fields as lives or continues.
- The real player-life field remains unresolved. The next audit needs the exact death/respawn call path and its callers, rather than inferring life stock from a nearby 0–3 counter. The requested co-op rules still require separate lives, an individual out-of-lives state, and a shared continue gate controlled only by P1 after both players are out.

## Shared camera-follow writer

The camera audit has now found the player-driven shared write path, which is more specific than the earlier scroll-helper hypothesis:

- `f_224C` calls `f_3368` at PC `0x24BA`, after updating the player's position and movement state.
- `f_3368` reads the player condition byte `$FFBC87`, screen coordinates `$FFBD1E/$FFBD20`, and tracking/control state `$FFBCCE/$FFBCD2/$FFBCD6/$FFBCD7`.
- It writes `$FFDFD8/$FFDFDA`, the global view offsets used by many world/object routines. This is the concrete per-player camera-follow side effect that cannot be run independently by both player contexts.
- The exact tracking dead zones are now visible in the helper body: horizontal follow reacts outside X=`0x6E` (110) to X=`0xB2` (178); vertical follow reacts outside Y=`0x20` (32) to Y=`0x70` (112). The player update passes its horizontal/vertical movement deltas in D0/D1; `f_3368` carries them in D6/D7, adjusts per-player 32-bit targets `$FFBCCE/$FFBCD2`, tracks per-axis flags `$FFBCD6/$FFBCD7`, and emits the signed 16-bit candidates at `$FFDFD8/$FFDFDA`.
- This gives us the candidate-merge shape: preserve `$FFBCCE/$FFBCD2/$FFBCD6/$FFBCD7` in each actor's private context; intercept only the two final writes from `f_3368` into P1/P2 camera candidates; then choose the candidate that makes less progress in the current scroll direction for the shared view. Opposite-direction candidates should hold the current shared offset until the direction rule is established. The thresholds and easing remain the game's own code.
- The camera audit also finds writes to `$FFDFD8/$FFDFDA` from stage/transition paths including `f_932A`, `f_99FE`, `f_A080`, `f_A18A`, `f_A194`, and `f_BCB6`. These must remain ordinary shared writes. Camera interception must be scoped to `f_3368` while an actor update is active, not applied globally to every write to those RAM addresses.
- `f_3430` calls `f_34DA`, and `f_34DA` calls `f_34E2`; these transform coordinates using shared scroll/view parameters such as `$FFDFD4/$FFDFD6/$FFDFDC/$FFDFE4`. The inspected bodies do not write `$FFDFD8/$FFDFDA`; they are transform helpers, not the follow writer.
- Stage/setup functions also initialize `$FFDFD4-$FFDFDA`, but those are not the recurring player-follow update. For local co-op, preserve the original `f_3368` behavior for each active player, but capture its writes to `$FFDFD8/$FFDFDA` into separate candidate offsets rather than letting either actor overwrite the shared camera immediately.
- After both actor updates, merge the two candidates into one shared view. For a forward-moving horizontal camera, choose the candidate that advances the view less; for reverse movement, choose the corresponding conservative candidate in the opposite direction. The sign/direction rules must be confirmed from level traces before coding the merge. If one player is dead/out of the world, ignore that player's candidate so the surviving player can continue alone. Vertical view can initially remain on the existing shared rule until its two-player behavior is understood.

## Descriptor, frame-phase, and sprite-path details

The generated code exposes a more precise split than the earlier broad RAM-window notes:

- At the start of the setup branch, `f_156A` reads `$FFBF1E`, doubles it twice (a four-byte table stride), loads a longword from the ROM table at `0x1994`, and passes that pointer to `f_19FA`. This confirms the descriptor lookup mechanism; the semantic meaning and valid alternate entries for this selector are not yet established.
- `f_19FA` stores the descriptor pointer at `$FFBC50`. It loads descriptor offsets `+30`, `+34`, and `+42` into `$FFBC1C`, `$FFBC20`, and `$FFBC24`; `+22` into `$FFBC4C`; `+4` into `$FFBC3C`; `+18` into `$FFBC5A`; and `+26` into `$FFBC18`. It also follows the pointer at descriptor offset `+6` to obtain the values used for `$FFBC44` and `$FFBC48`. These are not all equivalent: some are dispatched callback targets, while others are resource/state pointers.
- `$FFBC5A` is a resource pointer, not one of the seven main-loop callback slots. The seven dispatched slots are `$FFBC3C`, `$FFBC44`, `$FFBC4C`, `$FFBC1C`, `$FFBC62`, `$FFBC20`, and optional `$FFBC5E`. `$FFBC62` is explicitly set to `f_224C`; `$FFBC5E` is initially cleared and later called only when nonzero.
- `f_156A`'s recurring player sequence dispatches `$FFBC3C`, `$FFBC44`, and `$FFBC4C`; then dispatches `$FFBC1C`; runs additional shared helpers; calls `f_5DB2` to prepare and enqueue the current player's sprite parts; dispatches `$FFBC62` (`f_224C`); runs `f_5472` and `f_3BD8`; then dispatches `$FFBC20`. The optional `$FFBC5E` callback is handled in a separate conditional block with resource-transfer/status work. This order is important and is a more reliable insertion guide than calling `f_156A` again.
- `f_5D8A` clears exactly 29 four-byte sprite-part entries at `$FFFFFCE8` and resets the two renderer state bytes `$FFBD24/$FFBD25`. It does not reset the global object pool. The global pool reset is in `f_5232`, which sets up the pool heads and free records; `f_5578` resets the auxiliary list and its separate 79-record area. The setup and restore paths call these shared reset routines, so they must remain single-instance.
- `f_5DB2` is not a pure draw call. It reads the selected sprite-part index from `$FFBCC0`, position from `$FFBD1E/$FFBD20`, size/flags from `$FFBD22` and `$FFBC86`, and animation state at `$FFBD24/$FFBD25`; it also uses `$FFBC54/$FFBC58` and shared camera/scroll state at `$FFDFD4-$FFDFE4`. It transforms each part against the current camera, allocates records from the shared object pool through `f_5300`, and configures the multipart sprite handlers with `f_5CA4`. A P2 render pass therefore needs isolated sprite-part scratch and player renderer fields, but should append to the same global render/object pool with a checked remaining-capacity guard.
- The sprite transform helper `f_34E2` explicitly adds the global scroll values at `$FFDFD4/$FFDFD6` and uses map/scroll data under `$FFDFD8-$FFDFE4`. That confirms that rendering two players must not advance or duplicate the camera; P2's sprite records must be transformed against the one shared camera.
- At PCs `0x27D4`, `0x2820`, and `0x2826`, `f_224C` selects action constructors by loading their code addresses directly into A6. The call at `0x288E` invokes that selected target. `f_4B58` and `f_4B74` both allocate from the shared 79-record pool, but initialize different record fields; the latter also calls `f_D0010` with selector `0x27`. These are likely different player-triggered object types, so the exact weapon/action conditions still need tracing before P2 fire can be considered covered.
- The descriptor/resource fields, player-state bytes, sprite-part scratch, object pools, renderer queue, DMA/VDP resources, and camera are distinct layers. A valid P2 architecture must virtualize only the first two player-owned layers, allocate a separate sprite scratch area, and leave the shared layers intact. The current report does not yet prove a safe P2 RAM address range or fully decode the resource chains.

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


## First successful runtime trace of the second controller (2026-11-24)

A user-supplied trace from the updated diagnostics build confirms that the second physical controller is detected and that the game's second Genesis port receives input. This separates controller plumbing from the still-unimplemented second character.

- The run used the diagnostic build from GitHub Actions run [#550](https://github.com/TotallyJustRetro/Turrican/actions/runs/45354062167), commit `1292e1a98708b740c338e2cded3c12f6e920d288`. The run succeeded; its Windows package artifact ID is `14902330571`.
- At every input sample, `p2_connected=1`: SDL kept a valid second controller handle.
- The sampled P2 live mask changed from `00000000` (idle) to `00000020`, `000000A0`, and `00000028` while the user operated the second controller. It returned to zero when released.
- The second controller's emulated active-low input bytes at `$FFBC92/$FFBC93` changed in response (for example `FFFF` to `EFFF`, `6FFF`, and `E7FF`). The P1 bytes at `$FFBC90/$FFBC91` remained `FFFF` during this capture, consistent with P1 being idle.
- Emulated Genesis port-read counters increased continuously for both ports. At the last sample they reached 11,660 reads for port index 0 and 11,464 for port index 1. The stable difference in the counters is an initial offset; both continued advancing throughout the trace.
- This confirms the physical P2 controller -> SDL P2 mapping -> P2 live mask -> Genesis port-2 active-low RAM bytes -> emulated game port-read chain. Do not spend another diagnostic pass on basic P2 detection or port wiring unless later evidence contradicts this trace.
- It does **not** confirm a second game actor. The log still contains one player descriptor (`$008E5E`, selector `0000`) and one main player-update callback (`f_224C` at `$00224C`). No second descriptor or second actor update was observed.
- The next engineering task is therefore inside the game actor model: determine whether the original game has a dormant second-player descriptor/path or implement a true second actor with independently owned player state and CPU context. The old RAM-shadow prototype remains disabled; port-2 availability is not permission to re-enable it.


## Source boundary and next descriptor investigation (2026-11-24)

The available Windows build source is not the original developers' high-level PC gameplay source. The encrypted build kit contains `recomp_gen.c` (generated C for the original Mega Drive 68000 program), the C runtime/harness, and the Electron launcher. This is still modifiable game logic, but it means player creation must be implemented at the static-recomp/game-runtime boundary; there is no verified native PC `Player` class or engine entity-spawn API to call.

### Second-controller path is verified

The user's updated runtime trace confirms the full input chain:

- SDL reports the second physical controller connected.
- P2's live button mask changes when the user presses/releases buttons.
- The P2 active-low bytes at `$FFBC92/$FFBC93` change in sync.
- The game's Genesis port-2 read counter advances continuously.

Therefore the second-controller plumbing is no longer the blocker. Do not request another controller detection test unless new evidence contradicts this trace. The game still initializes and updates only one player.

### Important correction: selector base 0x1994 overlaps generated code

The player setup path in `f_156A` reads a longword from `0x1994 + ($FFBF1E * 4)` and passes the result to `f_19FA`. The runtime trace for selector 0 logged `0x00008E5E`, which resolves to the active player descriptor at ROM address `0x008E5E`.

However, the static recomp also has a generated code entry named `f_1994` at address `0x1994`, whose body contains executable instructions at that address. This suggests the selector data may be deliberately overlaid with code, or that this address is being interpreted through a non-obvious code/data overlap. It is not yet safe to call it an ordinary standalone descriptor table, and we must not infer that selectors 1-7 are second-player descriptors.

### New read-only selector dump

The trace patch now dumps the first eight raw longwords at `0x1994, 0x1998, ... 0x19B0` once per game run. For any candidate address that points to at least 64 bytes inside the loaded ROM, it also records those 64 bytes. The output is labeled as raw/unclassified candidates to avoid treating arbitrary instruction bytes as valid descriptors. This instrumentation does not alter game RAM, CPU registers, player state, or input.

Next decision after the dump:

1. Validate whether selector values 0-7 resolve to coherent descriptor records, including their nested resource/callback pointers.
2. If only selector 0 is valid, close the dormant-descriptor hypothesis and implement P2 as a separate actor context using the translated game logic.
3. If another selector is valid, determine whether it is merely an alternate animation/weapon/resource descriptor or a complete second character definition before reusing it.

No gameplay co-op code has been enabled. The unsafe RAM-shadow prototype remains disabled, and the normal P1 code path remains unchanged.
