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
- `f_19FA` stores its input pointer at `$FFBC50`, checks a byte at offset +48, copies fields from the record into several shared dispatch slots (offsets +4, +18, +22, +26, +30, +34, +42), and calls through pointers loaded from nested offsets +10, +8, and +38. This is much stronger evidence of a structured runtime context with multiple callback fields than a flat sprite table. It is not yet proven to be the global enemy/boss definition format.

The next static step is call-site mapping for `f_7D04`, `f_8A22`, `f_D75E`, and their helper routines. Then trace where `$FF0852-$FF086F`, `$FF9A86-$FF9A88`, and the source pointer at `$FFBC00` are populated. Those are better next targets than a user-triggered runtime snapshot.

The current Maker uses `mtlb_update_vdp_resources(vdp.vram, vdp.cram, vdp.reg)` while it is open. This exposes actual patterns and SAT sprite parts from the currently loaded scene, but it does not create semantic actor definitions or a reusable whole-game asset catalogue.

## Static runtime findings (Build #296 report)

The generated code reveals a callback/context mechanism:

- `f_156A` and `f_1994` read several 32-bit addresses from fixed work-RAM slots and dispatch through them with `rt_call_addr`.
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
