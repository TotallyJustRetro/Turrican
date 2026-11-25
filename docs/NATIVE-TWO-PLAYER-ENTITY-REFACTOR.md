# Native Two-Player Entity Refactor

## Current status

This branch preserves the Build616 P2-spawn baseline and adds explicit private ownership for the additional player descriptor and lifecycle state required by a true second actor.

This is a structural step, not a claim that full two-player gameplay is finished. The active prototype still executes the native movement actor (f_224C) with isolated collision preparation and resolution. It does not yet execute every descriptor-selected player callback or the complete death/respawn lifecycle for P2.

## Verified native player frame phases

The generated Mega Turrican frame loop in f_156A contains these important player-local phases:

1. f_3B38: reset per-frame player collision state and descriptor cursor.
2. Descriptor-selected callbacks through BC3C, BC44, and BC4C.
3. f_56CE: rebuild collision candidates from the shared world-object list into player work buffers.
4. f_3D80: resolve this player's collision descriptors and write per-player contact results into their 24-byte result/context records.
5. f_5DB2: build the player's multipart sprite data and append to the shared render queue.
6. BC62: native player actor, normally f_224C.
7. f_3BD8: finalize player contact/collision state.
8. BC20: descriptor-selected post-actor callback.

Other phases in the same frame are world-wide services, not second-player services. In particular, f_5432 updates the shared world-object list, f_552A traverses the shared object/render list, and f_5472 operates on the shared sprite queue and object list. These must not be replayed as though P2 owns a second world.

## Ownership added in this revision

P2 now has private copies for these descriptor/lifecycle fields:

- BC18..BC27: descriptor-selected player state callbacks.
- BC3C..BC43: callback and context pair.
- BC44..BC4B: callback and context pair.
- BC4C..BC53: callback and descriptor pointer.
- BC5A..BC61: dynamic callback and callback context.
- BF0E..BF17: player-specific camera/position snapshot used by the original initialization and lifecycle paths.

The gaps are intentional. BC28..BC3B is the shared world-object list, BC54..BC59 is the shared sprite-output queue pointer/count, DFD4..DFD7 is the shared viewport origin, and BF3A is the global continue counter. These must remain world-owned. The build patch now parses every private-bank range and fails its static ownership checks if any of those shared ranges are banked.

The P2 runtime trace now prints the private callback pointers and lifecycle snapshot, making later callback isolation auditable rather than inferred. One important alignment is enforced at spawn: both the live X coordinate in BD1E and the saved player X in BF12 receive the same +0x10 offset. The native f_1BDE respawn path rebuilds position from the shared viewport origin in BF0E and the saved player position in BF12; leaving BF12 unchanged would make a later P2 respawn collapse back onto P1's saved X. The BD28 descriptor table is copied per player; each descriptor's +8 pointer is redirected to a private 24-byte collision-result context. f_3D80 writes its +11 contact result and +16 candidate pointer there, so P2's collision pass cannot overwrite P1's result context. The F268 candidate buffer it points into is rebuilt from the shared BC28 world-object list, while its output scratch is private.

## Shared-world object interaction path found

The static actor audit now distinguishes collision detection from the actual object-response path:

- P2 runs f_56CE against the same shared BC28 world-object list as P1, building only its own F268/F2A8 candidate buffers.
- During f_224C, the native f_57A6 query follows pointers from those spatial candidates and returns the object-specific state pointer in A2.
- The player actor then writes the hit/response byte at A2+11 and subtracts from the response field at A2+9. Those writes are not directed at the private BD28 collision-result shadows. The target address is classified against the explicit P2 private-bank allowlist by the new runtime trace, so the next in-game run can confirm the actual target memory region and before/after values.
- After movement, f_3BD8 has another P2-local input/contact path. Under its native conditions it calls f_4626, which obtains an object through the shared f_5382 allocator and initializes its fields using P2's BD1E/BD20 coordinates. f_5382 updates the shared allocator links at BC2C/BC30. f_3BD8 can also call f_3D12, which appends its effect through the shared sprite queue at BC54/BC58.

This is strong evidence that the prototype is not a separate simulated copy of the level: P2's native actor can query shared world objects, address their object-owned response state, and invoke the game's shared object allocator with P2's position. It is not yet runtime proof that every enemy type, pickup, projectile, or damage case behaves correctly.

The new file MegaTurrican-coop-shared-hit-trace.txt records the A2 pointer and A2+9/A2+11 values before and after the f_224C writes, along with a private-bank classification for each target byte. A target marked private=0 is outside the P2 private allowlist and is read from shared RAM.

## Camera boundary

P2's native f_3368 computes its own camera candidate into private DFD8/DFDA using P2's position and the shared viewport origin DFD4/DFD6. However, no shared-camera merge has been installed yet. The original post-actor callback f_932A calls f_BCB6, which derives camera movement from global viewport/mode state and may call f_5300 to mutate the shared object list. Running that callback a second time unchanged would duplicate global work. For now the viewport still follows P1; a safe midpoint/dual-player camera policy remains a separate milestone.

## Why the callbacks are not all duplicated yet

The original callback targets observed for this descriptor include 004EE2, 00915A, 000582, 009222, and 00932A. Their bodies are not all pure player-state updates:

- f_915A reads the shared world-view origin and writes through a context pointer.
- f_582 stages data through shared transfer helpers.
- f_9222 touches global mode/state and dynamic callback state.
- f_932A calls f_BCB6, reads shared world bounds, writes camera candidate values to DFD8/DFDA, and updates player callback/lifecycle fields. It also touches global mode and level-state bytes, so its full body cannot be duplicated unchanged.
- f_4EE2 walks a caller-supplied context block and calls transfer helpers. Its writable context has not yet been proven independent of shared rendering/resource state.

Calling these routines twice without first separating their world-wide effects could duplicate resource transfers or overwrite the one shared camera/mode state. They remain a deliberate boundary for the next phase. P2's private collision result records are not yet proof that every enemy-damage or pickup side effect is visible in the shared world; that interaction path still needs explicit validation.

## Initialization and lifecycle boundary

The original f_19FA and f_1BDE initialization paths do more than initialize actor fields. They also call shared renderer/object-pool/resource helpers such as f_5232 and f_5D8A, so they cannot simply be called a second time unchanged.

Likewise, f_156A owns both per-player life state and global continue/game-flow decisions. P2 needs its own life/death/respawn transitions, but it must not consume the shared continue counter or reset the shared world.

## Next implementation milestones

1. Use the new private callback/lifecycle fields to build a per-player initialization routine that mirrors only verified actor-owned state from the original descriptor.
2. Split callback routines into player-state updates and shared world/render/resource effects; execute each half at the correct once-per-player or once-per-world frequency.
3. Implement P2 life, death, respawn, and game-over handling without duplicating global continue flow.
4. Merge P1/P2 camera candidates into one viewport that keeps both actors visible.
5. Validate that both players collide with and affect the same enemies, projectiles, platforms, pickups, and stage state; bridge any player-result-to-world-object effects that remain P1-only.

The working spawn baseline must remain intact throughout these steps.
