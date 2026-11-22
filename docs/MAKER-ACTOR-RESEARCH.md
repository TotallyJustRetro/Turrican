# Mega Turrican Reborn — Maker actor and asset research

Branch: `feature/level-builder-maker-ui-vdp`

## Safety / entry-point status

- Build #295 added a live gameplay snapshot writer when the Level Builder was opened. That experiment was removed after the user reported a crash.
- The snapshot writer function and its call site are removed from the build patches.
- Level Builder has been removed from the in-game pause menu. It remains reachable from the title/creation menu.
- Build #299 compiled successfully with those safety corrections. Do not ask the user to repeat the Build #295 capture procedure.

## What the current code actually contains

The native harness loads the user's Mega Drive ROM as a runtime byte array (`md_load_rom` reads the external ROM file into `rom` / `romlen`). The generated C contains recompiled 68000 routines, but the artwork is not currently packaged as a named PC-side sprite/enemy/boss library. The cartridge's graphics data is loaded from the ROM and transferred through the emulated VDP into VRAM/CRAM.

The Build #303 source report confirmed the precise VDP DMA paths:

- `dma_run()` reads the transfer mode from VDP register 23 and the byte/word count from registers 19–20.
- Mode 3 performs VRAM-to-VRAM copy; mode 2 performs fill; the other DMA path derives a 24-bit source from registers 21–23 and reads words via `vdp_dma_read()`.
- `vdp_dma_read()` reads through the harness memory bus (`rd8_raw`), so ROM-backed transfer sources are available to the emulator without having to infer pixel data from the displayed framebuffer.
- The VDP stores 64 KiB VRAM, 64 CRAM words, 64 VSRAM words, and 32 registers. The sprite renderer follows the SAT links and reads the referenced tile patterns from VRAM.

This gives us a concrete asset-indexing strategy: index ROM-backed VDP DMA transfers by source address, length, destination address and transfer type, then associate the resulting VRAM patterns with SAT compositions and the actor/object callbacks identified by the static code report. The DMA metadata and tile bytes can be handled as a bounded asset cache; we do not need a full CPU/RAM/recompiler-stack snapshot.

## Build #306 transfer-helper findings

The expanded static report now includes the full bodies of several routines that both configure the VDP and feed its data port:

- `f_7D04` reads a 32-bit pointer from `$FF085A`, a word from `$FF0858`, and two words from `$FF0852/$FF0854`. It issues VDP control words `0x54000000` and `0x40000010`, writes the two words to the VDP data port, advances two pointers by 4,480 bytes, then invokes a helper with `D0=0x1180` and `D1=2`. This is a concrete staged graphics-transfer candidate, but we still need to identify who fills the staging buffer and what graphic class it represents.
- `f_8A22` reads a current source pointer from `$FFBC00`, issues VDP command `0x40020010`, transfers one longword to the data port, advances the source pointer by four, and saves it back to `$FFBC00`. It looks like a generic sequential VDP upload primitive, not an asset definition by itself.
- `f_D75E` checks a flag at `$FF9A86`, builds a descriptor under `$FFBC00` (length/size field `0x50`, source pointer `$FF9A88`, another field `0x90`), installs handler `f_D7A0` at `$FFBC10`, and issues VDP control/data writes. This is consistent with a queued/small transfer descriptor, but the exact content and owner of `$FF9A88` remain to be identified.
- `f_19FA` stores its input pointer at `$FFBC50`, checks a byte at offset +48, copies fields from the record into several shared dispatch slots (offsets +4, +18, +22, +26, +30, +34, +42), and calls through pointers loaded from nested offsets +10, +8, and +38. This is strong evidence of a structured runtime context with multiple callback fields. Combined with the indexed lookup in `f_156A`, the current best interpretation is a stage/profile context, not a global enemy/boss definition format.

The Build #308 caller index found two direct call relationships:

- `f_200` calls `f_6B80` from its early initialization path. This is a startup VDP setup sequence, not enough evidence of a whole-game asset library.
- `f_6C3E` calls `f_7D04`, then checks `$FFBC18` and dispatches through that callback pointer. This is a stronger per-context/per-object graphics-update candidate because it sits inside the shared callback path. Its exact object class is still unknown.

The `f_D75E` transfer descriptor appears to chain through `f_D7A0`, `f_D7B4`, and `f_D7C8` using the callback slot `$FFBC10`. It stores source pointer `$FF9A88`, length/size fields `0x50` and `0x90`, and issues VDP control/data writes. That is consistent with a small queued transfer/state machine, but the source content and owner have not yet been identified.

## Build #313 refinement: which transfers are actual game assets?

The deeper helper bodies show why it is important not to call every VDP transfer a sprite loader:

- `f_7B72` is a generic longword copy loop. It copies from A0 to A1 for a count supplied in D0; it is not itself a decompressor.
- `f_7B8A` is a text/font helper. It maps character byte ranges to tile indices beginning around `0x530`, builds VDP tile attributes, and writes those indices to a VDP address. This is a text renderer, not an enemy sprite decoder.
- `f_76EA` copies a ROM block beginning at `0x7FA6` into RAM at `0x1000`, then initializes and drives a VDP transfer state machine using `$FF0852-$FF0873`. It also calls the generic copy helper and VDP status/queue helpers. The exact payload class (font, title/UI graphics, or another resource block) is not yet proven.
- `f_7360` similarly copies a ROM block beginning at `0x8040` into RAM at `0x1000` and runs a staged VDP transfer process. Since these two ROM sources are near one another and are used by UI/text helpers in the same neighborhood, treat them as probable display/font resources until their callers and byte formats prove otherwise.
- `f_7D04` consumes a staging descriptor at `$FF0852-$FF086F`, issues VDP control/data writes, advances its source and destination pointers by 4,480 bytes, and calls a follow-up helper. It is a transfer worker, not a content definition.
- `f_6C3E` is reached via the shared callback context, calls `f_7D04`, then invokes the callback at `$FFBC18`. This keeps it interesting for per-context graphics updates, but it is not enough to conclude that the context is a game actor.

A significant structural finding remains `f_19FA`: it receives a pointer in A0, stores it at `$FFBC50`, checks a flag at offset +48, and installs numerous callbacks from offsets +4, +18, +22, +26, +30, +34, and +42 into the shared runtime dispatch table. It also follows nested pointers at +8, +10, and +38. Since `f_156A` selects that pointer through the stage word at `$FFBF1E`, the current best interpretation is a structured stage/profile context, not a per-enemy object definition.

Build #316 further established:

- `f_1BDE` is a secondary context initializer. It starts from the pointer in `$FFBC28`, uses offsets +16 and +8 to copy/setup linked data, installs additional callbacks, and uses the same stage word `$FFBF1E`. That reinforces the interpretation that these are linked stage/runtime contexts.
- `f_224C` is a large state machine operating on fields including `$FFBCDA/$FFBCDC` (coordinate-like word values), `$FFBCC0/$FFBCC4/$FFBCC8` (state/callback/timer-like values), and flags around `$FFBCF3-$FFBCFE`.
- `f_2A18` is one of its transitions: based on flags at `$FFBC84` and `$FFBCD8`, it selects ROM data base `0x20000` or `0x24000` into `$FFBCC4`, sets a small state value (0x15 or 0x1B) at `$FFBCC0`, and updates a state flag. This is **not a function-pointer dispatch**: `f_224C` dereferences `$FFBCC4` at word offsets, reads state data, advances the data pointer, and saves it back. The two addresses are therefore state/animation data tables or related ROM data blocks, not code entry points. Their exact record format and actor ownership still need to be established.

The next static step is to map the data layout at ROM bases `0x20000` and `0x24000` (state/animation data) and index other ROM lookup tables used by enemy/actor constructors. In parallel, we need a distinct object-spawn/instance list. Until those links are proven, these routines are evidence of the engine's state machinery, not a ready-to-use enemy catalogue.

## Build #324: the object list allocator and a five-child spawner

This is the strongest object-system evidence so far.

### `f_5300`: linked-list object manager

The function uses two list-head fields:

- `$FFBC2C`: the list from which it takes the head record.
- `$FFBC28`: the list to which it links that record.

When the source head is non-null, it removes the first node, repairs the next node's back-link, inserts that node at the destination head, and repairs the new head's back-link. It returns the record address in A0 and resets fields including +16 and several state/flag bytes (+10 through +15, +42, +43). If the source list is empty, it instead selects the fallback record at `$FFBF3C` and sets D0 to -1.

This is consistent with a reusable record pool. The interpretation of `$FFBC28` as the active/used list is strengthened by `f_1BDE`, which walks nodes from that head during stage-context refresh and reads each node's fields. `$FFBC2C` is the list from which `f_5300` takes a new node, so it is the likely free/available list. The source does not give either list a human-readable name, so those labels remain inferred from their behavior.

The common record layout now has a credible structural interpretation:
- +0/+4: linked-list next/back-link pointers
- +8/+20: copied per-object context/resource fields in the common setup helper
- +10 through +15, +42/+43: initialization flags
- +24/+26: position coordinates
- +28: state/substate
- +30/+34/+38: three 32-bit per-object slots whose meanings vary by object family. Do not label them as graphics pointers. In several families, all three contain generated-code routine addresses. For example, the C402 family assigns +30=`0x5C08`, +34=`0xC402`, +38=`0xC448`; the 0x6280 family assigns +30=`0x6280`, +34=`0x6212`, +38=`0x62AA`. The +34 slot is repeatedly initialized with the object's active state/update handler. The exact roles of +30 and +38 are still being verified from their consumers.
- +44/+46/+48/+50/+52/+54: counters, animation/state data pointers and related per-object fields (exact widths/meanings vary by routine)

### `f_BCB6` → `f_BD20`: create an object group

The caller context for `f_BD20` is now visible in the generated-code report. `f_BCB6` calls the shared `f_5300` manager, then stores `0xBD20` in the returned record's +34 handler field and sets +44 to `0xB4`. It then proceeds through a descriptor/setup routine at `0xC08E` and updates the shared timer at `$FF572A`. So `f_BD20` is not an arbitrary global function: it is explicitly installed as a per-object update handler by another gameplay routine.

### `f_BD20`: five child object records

When that handler reaches its initialization branch, it calls `f_5300` five times. Each returned record is initialized from the parent template:
- copy parent position at +24/+26;
- assign child handler `0xBE16` at +34;
- copy parent data/context fields at +30 and +38;
- set child flags and state fields;
- assign each child its own 8-byte auxiliary record, advancing through a table beginning at `$FF56F2`.

It also clears/initializes a wider staging area beginning at `$FF5612`. This is a real parent-to-children spawn pattern backed by the native object pool, not an editor-side sprite placement trick. What the five children represent (enemy components, projectiles, an attack pattern, or a visual effect) is not identified yet; we must trace their resource pointers and the `f_BE16` state handler before naming them.

### Another confirmed spawning pattern: `f_A1E8`

`f_A1E8` is another A5-record state handler. It checks state and timer fields, applies the world/scroll offset to +24/+26, tests position bounds, and in one branch calls `f_5300` repeatedly to create two child records. Those children copy position/context from the parent and are assigned handler `0xA3D6`. This confirms the allocator is reused by more than one object family.

### Confirmed per-frame object dispatch path — Build #333

The complete function bodies now confirm the object loop precisely:

- `f_5432` reads the first list head at `$FFBC28` and calls `f_543C`; it then reads a second list head at `$FFBC30` and calls the same traversal again.
- `f_543C` checks whether the current pointer is null. For each record, it copies the record's +0 next pointer onto the stack, loads the +34 field, calls that routine through `rt_call_addr`, restores the saved next pointer, and repeats.
- This confirms +0 is the forward link and +34 is the per-frame update/state callback for records processed by this list walker.
- The two lists are definitely traversed separately each frame. Their exact category labels (for example, ordinary objects versus another update class) are not named in code and remain to be determined.
- The stage/profile initializer `f_19FA` is separate: it copies its +30 and +34 fields into global callback slots `$FFBC1C` and `$FFBC20`, and later calls +38 through `f_1B52`. Do not conflate those stage-context callbacks with the object-record update list.

### Object-pool initialization — `f_5232`

The pool initializer is now in the report too:

- It clears the two active list heads `$FFBC28` and `$FFBC30`.
- It initializes the free-list head at `$FFBC2C`.
- Starting from record memory at `$FFBF7A`, it constructs a chain using a 62-byte stride and a loop count of `0x4F` (79 records).
- It then clears/reinitializes the auxiliary globals `$FFBC34` and `$FFBC38` and a separate block beginning at `$FFD55A`.

### Exact allocator and release behavior

Build #333 provides the full `f_5300` and `f_5400` bodies:

- `f_5300` reads the free-list head at `$FFBC2C`. If a node exists, it removes that first node, repairs the next node's back-link, inserts the node at the head of `$FFBC28`, repairs both links, clears its +16 longword, and resets the initialization bytes at +10 through +15 and +42/+43. The allocated record is returned in A0.
- If the free list is empty, `f_5300` returns the fallback record at `$FFBF3C`, sets D0 to -1, and performs the same state-field clearing on that fallback record.
- `f_5400` compares the supplied A0 pointer with the fallback record. For a normal record, it unlinks the record from its current doubly-linked list using +0/+4, inserts it at the head of the free list at `$FFBC2C`, and repairs the neighboring pointers. The fallback record is not put back into a list.

Together with `f_5232` (initialize the 79-record pool), `f_5300` (allocate), `f_5432/f_543C` (walk and update active records), and `f_5400` (release), we now have a direct map of the engine's object lifecycle: initialize pool → allocate a record → set up its object-specific fields and +34 handler → update it through the frame list walker → release it back to the pool.

The next static pass is to find the other consumers of per-object +30 and +38, then correlate spawn routines, update routines, and ROM animation/resource pointers into verified object families. That is the step needed before exposing safe named objects in the Maker.

The generated-code scan currently finds 43 distinct addresses assigned to the +34 object slot. They include `0x3E5C`, `0x406E`, `0x439E`, `0x4466`, `0x46B2`, `0x49C8`, `0x4A5A`, `0x4AC0`, `0x4BD0`, `0x5962`, `0x5B42`, `0x5BE4`, `0x5CD0`, `0x617C`, `0x6212`, `0x623C`, `0x6334`, `0x6410`, `0x959A`, `0xA3D6`, `0xA5D4`, `0xA94E`, `0xAA74`, `0xAF80`, `0xB4AA`, `0xB5BA`, `0xB710`, `0xB852`, `0xBD20`, `0xBE16`, `0xBE1E`, `0xBF50`, `0xC262`, `0xC402`, `0xC46C`, `0xC8A6`, and others.

These addresses are code handlers, not user-facing actor names. Some are later state transitions installed by other handlers, so the list is an implementation index, not a count of distinct enemy types. Verified initial allocator-owner → first +34 handler relationships include `f_4992 → 0x49C8`, `f_4B58/f_4B74 → 0x4BD0`, `f_60EE → 0x617C`, `f_62FA → 0x6334`, `f_A114 → 0xC8A6`, `f_A1E8 → 0xA3D6`, `f_A556 → 0xA5D4`, `f_A708 → 0xAA74`, `f_BCB6 → 0xBD20`, `f_C212 → 0xC262`, and `f_C2E4/f_C310/f_C32E → 0xC402`. A single owner may create several child records or transition an object to a different handler later.

The next static task is to inspect the full `f_BCB6`, `f_BE34`, `f_BE7C`, `f_BE16`, `f_A3D6`, and `f_A3A0` routines, then trace the data pointers at +30/+38/+48 into the ROM tables and graphic-transfer code. That should reveal what these spawned object families represent and how their frame/animation data is selected.

## Build #319 full work-RAM map: new candidate areas

The full 64 KiB work-RAM frequency map shows several clusters outside the already understood global context:

- `$FFBC00`: 1,296 generated absolute references, primarily from `f_224C`, `f_2E94`, `f_156A`, `f_1994`, `f_19FA`, and `f_3BD8`. This is the shared game-state/context block already being traced.
- `$FFBD00`: 358 references, again dominated by `f_224C` and the main update path. Likely related to player/gameplay state and HUD fields, but individual meanings still need verification.
- `$FFBF00`: 217 references, with `f_156A`, `f_1994`, `f_1E64`, `f_19FA`, and `f_1BDE` prominent. This contains the known stage/health/lives/timer state.
- `$FF0800`: 274 references, dominated by `f_76EA`, `f_79B6`, `f_6E7E`, `f_6FCE`, and `f_7360`. This is the graphics-transfer queue/staging area and should not be confused with actor slots.
- `$FFDF00` (164 references), `$FF5700` (68), `$FF5600` (54), and `$FF3D00` (63) are new high-priority candidate regions. Functions such as `f_9DD4`, `f_932A`, `f_9CA4`, `f_9222`, `f_9198`, `f_9B6C`, `f_9DA2`, `f_DDAE`, and `f_DF46` touch these regions repeatedly.

These are address-cluster leads, not confirmed enemy-object arrays. Build #320 is extracting those function bodies and their call edges to see whether the clusters represent actor instances, stage structures, collision/animation state, or unrelated systems.

## Build #320 candidate routines — what the code suggests so far

- `f_9222` reads an active flag from `$FF5600`, advances counters in `$FF5602/$FF5604`, uses ROM tables at `0x91E8` and `0x8F6E` to select a variable ROM pointer, and copies 32 longwords (128 bytes) into a RAM buffer at `$FFDC9E`. It also stores the selected pointer in `$FFBC5A`. This strongly resembles a timed frame/sequence resource loader. It is a promising place to investigate sprite animation data, but the data has not yet been decoded or linked to a named actor.
- `f_9CA4` installs `f_9DD4` into the shared callback slot `$FFBC20`. `f_9DD4` then manages counters at `$FF578A`, coordinate-like values at `$FF5784/$FF5786/$FF5788`, and prepares a 7-longword descriptor from ROM `0x8FCE` into `$FFDCFE`. It also installs further callbacks. That looks like a state/sequence transition and associated data setup, not an actor spawn routine.
- `f_932A` is called by `f_931A`. It uses bounds such as `0x1A0`, `0x2B0`, `0x5F0`, and `0x620`, updates paired coordinate-like words in `$FFDFD4-$FFDFDA`, and refreshes fields under `$FFBF0E`. This looks more like world/camera bounds or display-window positioning than an actor pool.
- `f_DDAE`, `f_DF46`, `f_DAF6`, `f_DE60`, and `f_DEC8` mostly toggle flags, counters, and copy small tables in `$FF3Dxx`. At present they are not strong actor-instance candidates.
- `f_10078` is still interesting: it uses an A5-relative structure with coordinate-like fields at +24/+26, state flags at +9/+11/+28, timers/state values at +44/+46/+48/+50, and a linked pointer at +52. This could be a reusable object/actor record, but we need to find the constructor or caller that supplies A5 and compare its fields against other routines before treating it as a confirmed actor structure.

Build #321 adds a cross-function index of all A5-relative field layouts and pointer setup sites. The goal is to find other routines using the same +24/+26/+52 structure and, most importantly, locate where A5 is populated.

The next static step is to map all callers and callers-of-callers for `f_19FA`, `f_156A`, `f_7360`, and `f_76EA`, then inspect the callback installers and object/level tables they consume. Keep graphics transfer routines separate from semantic actor definitions.

The current Maker uses `mtlb_update_vdp_resources(vdp.vram, vdp.cram, vdp.reg)` while it is open. This exposes actual patterns and SAT sprite parts from the currently loaded scene, but it does not create semantic actor definitions or a reusable whole-game asset catalogue.

## Static runtime findings (Build #296 report)

The generated code reveals a callback/context mechanism:

- `f_156A` is part of the main game-frame/update path. It reads the 16-bit word at `$FFBF1E`, multiplies it by four, indexes a longword pointer table based at ROM address `0x1994`, and passes the selected pointer to `f_19FA`.
- The low byte of `$FFBF1E` is `$FFBF1F`, the byte previously recorded as the current stage. Therefore, the `0x1994` lookup is more plausibly a stage/profile selection table than an enemy catalogue. The high byte may distinguish a world, mode, or profile; that interpretation still needs confirmation.
- `f_19FA` initializes the selected stage/runtime context and installs its callbacks into shared RAM dispatch slots. It is not proven to describe an individual enemy or boss.
- Observed callback slots include `$FFBC3C`, `$FFBC44`, `$FFBC4C`, `$FFBC1C`, `$FFBC62`, `$FFBC20`, `$FFBC5A`, and `$FFBC5E`.
- `f_19FA` stores its incoming A0 value in `$FFBC50`, then copies 32-bit values from offsets in the pointed-to structure into callback slots. Notable offsets include +18, +22, +30, +34, and +42.
- This is strong evidence for a runtime object/context descriptor whose fields include callback pointers. It is not yet proof that each descriptor is an enemy or boss definition.
- Constant callback assignments seen in the report include `$FFBC44 <- 0x9B6C / 0x915A / 0xA18A`, `$FFBC4C <- 0x9B5C / 0x0582`, `$FFBC20 <- 0x9BE0 / 0x9AB4 / 0xA080 / 0x99FE / 0xA114 / 0xA18A`, and `$FFBC62 <- 0x224C`. These are routine addresses, not actor IDs.

The next reports extend this work by capturing the installer routine bodies and indexing writes to the VDP data/control ports. This should help locate object setup routines and ROM-to-VDP graphics transfer paths.

## Correct build direction

1. Keep the Creator outside the pause menu. Keep the in-game pause menu for gameplay options only.
2. Build a static research index from generated routines and ROM-data references. Do not use a giant live CPU/RAM snapshot for this.
3. Trace the callback descriptor layout and the routines that install its handlers. Identify which contexts are player logic, enemy logic, boss logic, pickups, or stage objects before assigning names.
4. Trace ROM-to-VDP transfer/decompression paths. The asset browser should be populated from actual ROM data using the game's own formats, not by presenting arbitrary individual SAT entries as enemies.
5. Define reusable semantic actor records only after the sprite composition, animation data, spawn routine, update routine, collision behavior, and properties are identified.
6. Implement level document loading in the gameplay runtime before enabling Test Play. A saved Maker map must become a real playable level, not remain an editor-only picture.
7. Add music import/selection as a separate asset pipeline using the runtime audio playback path; keep Classic and Modern modes as distinct level profiles.

## Build references

- Build #299 (safe pause-menu and capture cleanup): successful Windows build.
- Build #295: do not use for further testing; it contains the removed live snapshot experiment.
