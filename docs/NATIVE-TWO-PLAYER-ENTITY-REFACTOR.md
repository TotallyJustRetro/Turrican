# Native Two-Player Entity Refactor

## Current status

This branch preserves the Build616 P2-spawn baseline and adds explicit private ownership for the additional player descriptor and lifecycle state required by a true second actor.

This is a structural step, not a claim that full two-player gameplay is finished. The active prototype still executes the native movement actor (f_224C) with isolated collision preparation and resolution. It does not yet execute every descriptor-selected player callback or the complete death/respawn lifecycle for P2.

## Verified native player frame phases

The generated Mega Turrican frame loop in f_156A contains these important player-local phases:

1. f_3B38: reset per-frame player collision state and descriptor cursor.
2. Descriptor-selected callbacks through BC3C, BC44, and BC4C.
3. f_56CE: rebuild collision candidates from the shared world-object list into player work buffers.
4. f_3D80: resolve this player's collision descriptors and mutate collision targets.
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

The gaps are intentional. BC54..BC59 contains the shared sprite-output queue pointer/count and must remain world-owned. The patch must not accidentally bank that queue while separating callback state.

The P2 runtime trace now prints the private callback pointers and lifecycle snapshot, making later callback isolation auditable rather than inferred.

## Why the callbacks are not all duplicated yet

The original callback targets observed for this descriptor include 004EE2, 00915A, 000582, 009222, and 00932A. Their bodies are not all pure player-state updates:

- f_915A reads the shared world-view origin and writes through a context pointer.
- f_582 stages data through shared transfer helpers.
- f_9222 touches global mode/state and dynamic callback state.
- f_932A calls f_BCB6, reads shared world bounds, and writes camera candidate values to DFD8/DFDA; some paths also create or update shared world/render objects.
- f_4EE2 walks a caller-supplied context block and calls transfer helpers. Its writable context has not yet been proven independent of shared rendering/resource state.

Calling these routines twice without first separating their world-wide effects could duplicate object creation, resource transfers, or camera mutations. They remain a deliberate boundary for the next phase.

## Initialization and lifecycle boundary

The original f_19FA and f_1BDE initialization paths do more than initialize actor fields. They also call shared renderer/object-pool/resource helpers such as f_5232 and f_5D8A, so they cannot simply be called a second time unchanged.

Likewise, f_156A owns both per-player life state and global continue/game-flow decisions. P2 needs its own life/death/respawn transitions, but it must not consume the shared continue counter or reset the shared world.

## Next implementation milestones

1. Use the new private callback/lifecycle fields to build a per-player initialization routine that mirrors only verified actor-owned state from the original descriptor.
2. Split callback routines into player-state updates and shared world/render/resource effects; execute each half at the correct once-per-player or once-per-world frequency.
3. Implement P2 life, death, respawn, and game-over handling without duplicating global continue flow.
4. Merge P1/P2 camera candidates into one viewport that keeps both actors visible.
5. Validate that both players collide with and affect the same enemies, projectiles, platforms, pickups, and stage state.

The working spawn baseline must remain intact throughout these steps.
