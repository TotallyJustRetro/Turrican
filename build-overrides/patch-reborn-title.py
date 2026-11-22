#!/usr/bin/env python3
"""Install Reborn as an animated native VDP title sprite, not an SDL overlay."""
from __future__ import annotations

import base64
import re
import struct
import sys
import zlib
from io import BytesIO
from pathlib import Path

from PIL import Image


WIDTH = 72
HEIGHT = 18
FRAME_COUNT = 12
FRAME_TICKS = 4


def repair_palette_png(data: bytes) -> bytes:
    """Repair the supplied indexed PNG's damaged PLTE boundary/CRCs."""
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise RuntimeError("Reborn logo payload is not a PNG")

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    ihdr_at = data.find(b"IHDR")
    plte_at = data.find(b"PLTE")
    trns_at = data.find(b"tRNS")
    idat_at = data.find(b"IDAT")
    iend_at = data.find(b"IEND")
    if min(ihdr_at, plte_at, trns_at, idat_at, iend_at) < 4:
        raise RuntimeError("Reborn logo PNG is missing a required chunk")
    if not (ihdr_at < plte_at < trns_at < idat_at < iend_at):
        raise RuntimeError("Reborn logo PNG chunks are in an unexpected order")

    ihdr_len = struct.unpack(">I", data[ihdr_at - 4:ihdr_at])[0]
    plte_len = struct.unpack(">I", data[plte_at - 4:plte_at])[0]
    trns_len = struct.unpack(">I", data[trns_at - 4:trns_at])[0]
    idat_len = struct.unpack(">I", data[idat_at - 4:idat_at])[0]
    if ihdr_len != 13 or plte_len != 768:
        raise RuntimeError(f"Unexpected Reborn PNG chunk sizes: IHDR={ihdr_len}, PLTE={plte_len}")

    ihdr = data[ihdr_at + 4:ihdr_at + 4 + ihdr_len]
    palette = data[plte_at + 4:plte_at + 4 + plte_len]
    transparency = data[trns_at + 4:trns_at + 4 + trns_len]
    compressed = data[idat_at + 4:idat_at + 4 + idat_len]
    width, height, bit_depth, color_type = struct.unpack(">IIBB", ihdr[:10])
    if (width, height, bit_depth, color_type) != (160, 40, 8, 3):
        raise RuntimeError(f"Unexpected Reborn PNG format: {width}x{height}, depth={bit_depth}, type={color_type}")
    decoded = zlib.decompress(compressed)
    if len(decoded) != (width + 1) * height:
        raise RuntimeError("Reborn PNG image stream has an unexpected decoded size")
    if len(transparency) > 256:
        raise RuntimeError("Reborn PNG transparency table is too large")

    return (
        signature
        + chunk(b"IHDR", ihdr)
        + chunk(b"PLTE", palette)
        + chunk(b"tRNS", transparency)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def _pack_indices(indices: list[int]) -> bytes:
    out = bytearray((len(indices) + 1) // 2)
    for i in range(0, len(indices), 2):
        hi = indices[i] & 15
        lo = indices[i + 1] & 15 if i + 1 < len(indices) else 0
        out[i // 2] = (hi << 4) | lo
    return bytes(out)


def make_vdp_asset(image: Image.Image, target: Path) -> None:
    """Make a compact multi-frame 4-bit pixel animation for the VDP sprite path."""
    if image.size != (160, 40):
        raise RuntimeError(f"Unexpected supplied Reborn logo size: {image.width}x{image.height}")

    image = image.resize((WIDTH, HEIGHT), Image.Resampling.NEAREST).convert("RGBA")
    pixels = list(image.getdata())
    transparent = (0, 0, 0, 0)
    palette = [transparent]
    lookup = {transparent: 0}
    base: list[int] = []

    for r, g, b, a in pixels:
        color = (r, g, b, a) if a >= 128 else transparent
        idx = lookup.get(color)
        if idx is None:
            idx = len(palette)
            if idx >= 16:
                raise RuntimeError("Downscaled Reborn logo exceeds the 16-colour VDP palette")
            lookup[color] = idx
            palette.append(color)
        base.append(idx)

    palette += [transparent] * (16 - len(palette))
    rgb = [(c[0], c[1], c[2]) for c in palette]

    # Give every 4x3 pixel cell a deterministic centre-outward reveal rank.
    block_w, block_h = 4, 3
    blocks_x, blocks_y = WIDTH // block_w, HEIGHT // block_h
    cx, cy = (blocks_x - 1) / 2.0, (blocks_y - 1) / 2.0
    ranks: dict[tuple[int, int], float] = {}
    for by in range(blocks_y):
        for bx in range(blocks_x):
            dist = abs(bx - cx) / max(cx, 1.0) + abs(by - cy) / max(cy, 1.0)
            noise = ((bx * 37 + by * 19 + bx * by * 7) % 23) / 90.0
            ranks[(bx, by)] = dist + noise
    low, high = min(ranks.values()), max(ranks.values())
    for key, value in list(ranks.items()):
        ranks[key] = (value - low) / max(high - low, 0.001)

    frames: list[list[int]] = []
    frames.append([0] * (WIDTH * HEIGHT))

    # Brief glints, then a deliberately pixelated centre-out assembly.
    spark = [0] * (WIDTH * HEIGHT)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            p = y * WIDTH + x
            if base[p] and ((x * 29 + y * 43 + x * y * 7) % 97) < 4:
                spark[p] = base[p]
    frames.append(spark)

    thresholds = [0.10, 0.24, 0.42, 0.62, 0.82, 1.01]
    for threshold in thresholds:
        frame = [0] * (WIDTH * HEIGHT)
        for y in range(HEIGHT):
            for x in range(WIDTH):
                p = y * WIDTH + x
                if base[p] == 0:
                    continue
                if ranks[(x // block_w, y // block_h)] <= threshold:
                    frame[p] = base[p]
        frames.append(frame)

    # A narrow metallic light sweep travels across the finished wordmark.
    bright_map = [0] * 16
    for i in range(1, 16):
        r, g, b = rgb[i]
        target_rgb = (min(255, r + 58), min(255, g + 58), min(255, b + 58))
        bright_map[i] = min(
            range(1, 16),
            key=lambda j: sum((rgb[j][k] - target_rgb[k]) ** 2 for k in range(3)),
        )
    for centre in (18, 48, 78):
        frame = list(base)
        for y in range(HEIGHT):
            for x in range(WIDTH):
                p = y * WIDTH + x
                if frame[p] and abs(x - centre - (y - HEIGHT / 2) * 0.22) <= 3:
                    frame[p] = bright_map[frame[p]]
        frames.append(frame)

    frames.append(list(base))
    if len(frames) != FRAME_COUNT:
        raise RuntimeError(f"Expected {FRAME_COUNT} Reborn animation frames, got {len(frames)}")

    palette_values = []
    for r, g, b, a in palette:
        palette_values.append((r << 16) | (g << 8) | b if a >= 128 else 0)

    def emit_rows(values: list[int], per_row: int, render) -> str:
        return ",\n".join(
            "        " + ", ".join(render(v) for v in values[i:i + per_row])
            for i in range(0, len(values), per_row)
        )

    packed_frames = [_pack_indices(frame) for frame in frames]
    frame_bytes = len(packed_frames[0])
    header = (
        "#ifndef REBORN_VDP_ASSET_H\n"
        "#define REBORN_VDP_ASSET_H\n"
        "#include <stdint.h>\n"
        f"#define REBORN_VDP_WIDTH {WIDTH}\n"
        f"#define REBORN_VDP_HEIGHT {HEIGHT}\n"
        f"#define REBORN_VDP_FRAME_COUNT {FRAME_COUNT}\n"
        f"#define REBORN_VDP_FRAME_TICKS {FRAME_TICKS}\n"
        f"#define REBORN_VDP_FRAME_BYTES {frame_bytes}\n"
        "static const uint32_t REBORN_VDP_PALETTE[16] = {\n"
        + emit_rows(palette_values, 4, lambda v: f"0x{v:06X}u")
        + "\n};\n"
        "static const uint8_t REBORN_VDP_FRAMES[REBORN_VDP_FRAME_COUNT][REBORN_VDP_FRAME_BYTES] = {\n"
        + ",\n".join(
            "    {\n" + emit_rows(list(frame), 16, lambda v: f"0x{v:02X}") + "\n    }"
            for frame in packed_frames
        )
        + "\n};\n#endif\n"
    )
    target.write_text(header, encoding="utf-8", newline="\n")


VDP_DRAW = r'''
/* Reborn is a native title-only extended sprite in the emulated VDP path.
 * It enters the same sprite pixel buffer as the cartridge sprites, before
 * priority composition, scaling, scanlines, and the SDL presentation stage. */
static void draw_reborn_title_sprite(int y, uint8_t *dst, int W)
{
    if (!vdp.reborn_title_active) return;
    int y0 = (vdp.height * 465) / 1000;
    int row = y - y0;
    if (row < 0 || row >= REBORN_VDP_HEIGHT) return;

    int x0 = (W - REBORN_VDP_WIDTH) / 2;
    if (x0 < 0) return;

    int frame = vdp.reborn_title_frame;
    if (frame < 0) frame = 0;
    if (frame >= REBORN_VDP_FRAME_COUNT) frame = REBORN_VDP_FRAME_COUNT - 1;
    const uint8_t *packed = REBORN_VDP_FRAMES[frame];
    size_t row_start = (size_t)row * REBORN_VDP_WIDTH;

    for (int x = 0; x < REBORN_VDP_WIDTH && x0 + x < W; ++x) {
        size_t pixel = row_start + (size_t)x;
        uint8_t byte = packed[pixel >> 1];
        uint8_t index = (pixel & 1) ? (byte & 15) : (byte >> 4);
        if (index) dst[x0 + x] = (uint8_t)(0xC0 | index);
    }
}
'''


TITLE_HELPERS = r'''
#define REBORN_VDP_FRAME_COUNT 12
#define REBORN_VDP_FRAME_TICKS 4
#define REBORN_VDP_TITLE_EXIT_FRAMES 3
#define REBORN_OPTIONS_RESET_FRAMES 8

/* Recognize the original title card from its MEGA letters, metallic TURRICAN/fire artwork, and copyright credit block. Do not key off START/OPTIONS selection colours: hovering either menu item changes those colours. */
static int reborn_title_scene_visible(void)
{
    int W = vdp.width, H = vdp.height;
    if (W < 256 || W > 320 || H < 200 || H > 240) return 0;

    int mega = 0, fire = 0;
    int metal[3] = {0, 0, 0};

    /* Original MEGA lettering, high above the metallic Turrican wordmark. */
    for (int y = H * 2 / 100; y < H * 15 / 100; ++y) {
        const uint32_t *row = &vdp.fb[y * 320];
        for (int x = W * 28 / 100; x < W * 75 / 100; ++x) {
            uint32_t p = row[x];
            int r = (p >> 16) & 255, g = (p >> 8) & 255, b = p & 255;
            if (r > 135 && g > 30 && r > g + 25 && g > b + 10) ++mega;
        }
    }

    /* Metallic title wordmark and orange fire band across all three zones. */
    for (int y = H * 12 / 100; y < H * 46 / 100; ++y) {
        const uint32_t *row = &vdp.fb[y * 320];
        for (int x = W * 3 / 100; x < W * 97 / 100; ++x) {
            uint32_t p = row[x];
            int r = (p >> 16) & 255, g = (p >> 8) & 255, b = p & 255;
            if (r > 130 && g > 25 && r > g + 35 && g > b + 10) ++fire;
            int hi = r > g ? (r > b ? r : b) : (g > b ? g : b);
            int lo = r < g ? (r < b ? r : b) : (g < b ? g : b);
            if (hi > 70 && hi < 245 && hi - lo < 75 &&
                r > 50 && g > 45 && b > 60) {
                int zone = (x * 3) / W;
                if (zone < 0) zone = 0;
                if (zone > 2) zone = 2;
                ++metal[zone];
            }
        }
    }

    return mega > 200 && fire > 600 &&
           metal[0] > 500 && metal[1] > 500 && metal[2] > 500;
}

/* Reveal once when the original title composition first appears. Keep the
 * completed logo visible, then loop its metallic glint frames indefinitely.
 * The logo is removed after leaving the title composition for several frames,
 * and a later return to the title restarts the pixelated reveal. */
static int reborn_game_options_visible(void)
{
    /* The original Game Options menu is drawn into the VDP Window Plane.
     * Detect its actual tilemap strings rather than screen-colour thresholds:
     * the selected row changes from palette 1 to palette 2, so a pixel-based
     * detector that expects one colour per item fails as the cursor moves. */
    if (vdp.width < 256 || vdp.width > 320 || vdp.height < 200 || vdp.height > 240)
        return 0;

    const uint32_t base = ((uint32_t)vdp.reg[3] & 0x3Eu) << 10;
    const int cols = (vdp.reg[16] & 0x02) ? 64 : 32;

    static const uint16_t heading[] = {
        0x537,0x531,0x53D,0x535,0x530,0x53F,0x540,0x544,0x539,0x53F,0x53E,0x543
    }; /* GAME OPTIONS */
    static const uint16_t game_level[] = {
        0x537,0x531,0x53D,0x535,0x530,0x53C,0x535,0x546,0x535,0x53C
    }; /* GAME LEVEL */
    static const uint16_t rapid_fire[] = {
        0x542,0x531,0x540,0x539,0x534,0x530,0x536,0x539,0x542,0x535
    }; /* RAPID FIRE */
    static const uint16_t controls[] = {
        0x533,0x53F,0x53E,0x544,0x542,0x53F,0x53C,0x543
    }; /* CONTROLS */
    static const uint16_t music_test[] = {
        0x53D,0x545,0x543,0x539,0x533,0x55A,0x544,0x535,0x543,0x544
    }; /* MUSIC-TEST */
    static const uint16_t exit_text[] = {0x535,0x548,0x539,0x544}; /* EXIT */

    const struct { int row, col; const uint16_t *tiles; size_t count; } marks[] = {
        {3,2,heading,sizeof heading/sizeof heading[0]},
        {8,3,game_level,sizeof game_level/sizeof game_level[0]},
        {12,3,rapid_fire,sizeof rapid_fire/sizeof rapid_fire[0]},
        {16,4,controls,sizeof controls/sizeof controls[0]},
        {21,3,music_test,sizeof music_test/sizeof music_test[0]},
        {26,6,exit_text,sizeof exit_text/sizeof exit_text[0]}
    };

    for (size_t m=0; m<sizeof marks/sizeof marks[0]; ++m) {
        for (size_t i=0; i<marks[m].count; ++i) {
            uint32_t at=base + ((uint32_t)marks[m].row*(uint32_t)cols +
                               (uint32_t)marks[m].col + (uint32_t)i)*2u;
            at &= 0xFFFFu;
            uint16_t entry=(uint16_t)(((uint16_t)vdp.vram[at] << 8) |
                                      vdp.vram[(at+1u)&0xFFFFu]);
            if ((entry & 0x07FFu) != marks[m].tiles[i])
                return 0;
        }
    }
    return 1;
}

static void reborn_title_update(void)
{
    static int present_frames = 0;
    static int missing_frames = 0;
    static int options_frames = 0;
    static int options_reset_latched = 0;
    static int frame_ticks = 0;
    static int reveal_consumed = 0;

    const int title_visible = reborn_title_scene_visible();

    if (title_visible) {
        /* The title logo and credits stay visible when START/OPTIONS selection
         * changes, so menu hover never hides or restarts the Reborn mark. */
        missing_frames = 0;
        options_frames = 0;
        options_reset_latched = 0;
        if (present_frames < REBORN_VDP_TITLE_EXIT_FRAMES)
            ++present_frames;
    } else {
        present_frames = 0;
        if (missing_frames < REBORN_OPTIONS_RESET_FRAMES)
            ++missing_frames;

        /* Only a sustained, specific GAME OPTIONS screen can re-arm the
         * one-shot. Gameplay and single-frame detector misses cannot do so. */
        if (missing_frames >= REBORN_OPTIONS_RESET_FRAMES &&
            !options_reset_latched &&
            reborn_game_options_visible()) {
            if (options_frames < REBORN_OPTIONS_RESET_FRAMES)
                ++options_frames;
        } else {
            options_frames = 0;
        }
    }

    if (options_frames >= REBORN_OPTIONS_RESET_FRAMES) {
        reveal_consumed = 0;
        vdp.reborn_title_active = 0;
        vdp.reborn_title_frame = 0;
        frame_ticks = 0;
        options_reset_latched = 1;
        options_frames = 0;
        return;
    }

    if (!vdp.reborn_title_active &&
        present_frames >= REBORN_VDP_TITLE_EXIT_FRAMES) {
        vdp.reborn_title_active = 1;
        frame_ticks = 0;

        if (!reveal_consumed) {
            /* Initial launch or return from GAME OPTIONS: animate once. */
            vdp.reborn_title_frame = 0;
            reveal_consumed = 1;
        } else {
            /* Every other re-entry holds the final frame; never loop. */
            vdp.reborn_title_frame = REBORN_VDP_FRAME_COUNT - 1;
        }
    }

    if (!vdp.reborn_title_active) return;

    if (missing_frames >= REBORN_VDP_TITLE_EXIT_FRAMES) {
        /* Leave the logo hidden during gameplay. Preserve reveal_consumed. */
        vdp.reborn_title_active = 0;
        return;
    }

    /* Advance only through the original one-shot Build #63 reveal frames.
     * Once the final frame is reached it remains static indefinitely. */
    if (vdp.reborn_title_frame < REBORN_VDP_FRAME_COUNT - 1) {
        if (++frame_ticks >= REBORN_VDP_FRAME_TICKS) {
            frame_ticks = 0;
            ++vdp.reborn_title_frame;
        }
    } else {
        frame_ticks = 0;
    }
}'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} marker, found {count}")
    return source.replace(old, new, 1)


def patch_vdp(project: Path) -> None:
    header = project / "runtime" / "vdp.h"
    source = project / "runtime" / "vdp.c"
    h = header.read_text(encoding="utf-8")
    c = source.read_text(encoding="utf-8")

    h = replace_once(
        h,
        "int width, height; uint32_t fb[320 * 240];",
        "int width, height; uint32_t fb[320 * 240];\n"
        "    int reborn_title_active, reborn_title_frame;",
        "VDP presentation fields",
    )
    c = replace_once(
        c,
        '#include "vdp.h"\n#include <string.h>\n',
        '#include "vdp.h"\n#include <string.h>\n#include "reborn_vdp_asset.h"\n',
        "VDP asset include",
    )
    c = replace_once(
        c,
        "void vdp_render_line(int y){",
        VDP_DRAW + "\nvoid vdp_render_line(int y){",
        "VDP scanline renderer",
    )
    c = replace_once(
        c,
        "draw_plane(y, pb, 1, W); draw_plane(y, pa, 0, W); draw_window(y, pa, W); draw_sprites(y, sp, W);",
        "draw_plane(y, pb, 1, W); draw_plane(y, pa, 0, W); draw_window(y, pa, W); "
        "draw_sprites(y, sp, W); draw_reborn_title_sprite(y, sp, W);",
        "VDP sprite composition call",
    )
    c = replace_once(
        c,
        "uint8_t a = pa[x], b = pb[x], s = sp[x]; int v, mode = 0, spr = 0;",
        "uint8_t a = pa[x], b = pb[x], s = sp[x];\n"
        "        if (s & 0x40) { out[x] = REBORN_VDP_PALETTE[s & 15] & 0x00FFFFFFu; continue; }\n"
        "        int v, mode = 0, spr = 0;",
        "VDP custom sprite palette path",
    )
    header.write_text(h, encoding="utf-8", newline="\n")
    source.write_text(c, encoding="utf-8", newline="\n")


def patch_sdl(project: Path) -> None:
    path = project / "runtime" / "sdl_main.c"
    source = path.read_text(encoding="utf-8")

    start = "/* ------------------------------------------------------------------ Reborn intro bumper */"
    frame_hook = "/* ------------------------------------------------------------------ frame hook */"
    if source.count(start) != 1 or source.count(frame_hook) != 1:
        raise RuntimeError("Could not uniquely locate the old SDL Reborn bumper section")
    a = source.index(start)
    b = source.index(frame_hook, a)
    source = source[:a] + source[b:]

    # Remove the old input-swallowing bumper behavior.
    event_block = re.compile(
        r"\n\s*if\s*\(reborn_intro_active\s*&&[\s\S]*?\n\s*\}\n",
        re.MULTILINE,
    )
    source, n = event_block.subn("\n", source, count=1)
    if n != 1:
        raise RuntimeError("Could not remove old Reborn bumper input interception")

    source = replace_once(
        source,
        "    /* Reborn bumper runs once after the original Mega Turrican logo card. */\n"
        "    reborn_intro_update();",
        "    /* Update the native title-only VDP sprite before the next emulated frame. */\n"
        "    reborn_title_update();",
        "old Reborn frame update",
    )
    source = replace_once(
        source,
        "md_live_mask = (overlay_state==0 && !reborn_intro_active) ? readpad() : 0;",
        "md_live_mask = (overlay_state==0) ? readpad() : 0;",
        "old bumper input gate",
    )
    source = replace_once(
        source,
        "    if(reborn_intro_active) reborn_intro_draw(ww,wh);\n",
        "",
        "old SDL bumper draw call",
    )
    source = replace_once(
        source,
        "    reborn_logo_init();\n",
        "",
        "old SDL logo texture initialization",
    )

    source = source.replace(frame_hook, TITLE_HELPERS + "\n" + frame_hook, 1)
    if "reborn_intro_active" in source or "reborn_intro_draw" in source or "reborn_logo_init" in source:
        raise RuntimeError("Old SDL Reborn bumper code remains after cleanup")
    if "SDL_RenderCopy(ren, reborn" in source or "reborn_titlefix_render" in source:
        raise RuntimeError("SDL Reborn overlay rendering remains after cleanup")

    path.write_text(source, encoding="utf-8", newline="\n")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch-reborn-title.py PROJECT_ROOT", file=sys.stderr)
        return 2

    project = Path(sys.argv[1]).resolve()
    asset_b64 = Path(__file__).with_name("reborn-logo.png.b64").read_text(
        encoding="ascii"
    ).strip()
    png_path = project / "runtime" / "reborn-logo-build.png"
    header_path = project / "runtime" / "reborn_vdp_asset.h"
    png_path.write_bytes(base64.b64decode(asset_b64, validate=True))

    try:
        raw = png_path.read_bytes()
        try:
            image = Image.open(BytesIO(raw)).convert("RGBA")
        except Exception:
            repaired = repair_palette_png(raw)
            image = Image.open(BytesIO(repaired)).convert("RGBA")
            png_path.write_bytes(repaired)
            print("Repaired supplied Reborn PNG palette and chunk checksums.")
        make_vdp_asset(image, header_path)
        patch_vdp(project)
        patch_sdl(project)
    finally:
        try:
            png_path.unlink()
        except FileNotFoundError:
            pass

    print(
        "Installed Reborn as a native VDP title sprite: "
        f"{WIDTH}x{HEIGHT}, {FRAME_COUNT} animation frames, "
        f"header SHA256={__import__('hashlib').sha256(header_path.read_bytes()).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
