#!/usr/bin/env python3
"""Embed the Reborn pixel logo and add a reliable title-screen bumper."""

from __future__ import annotations

import base64
import hashlib
import re
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image


C_CODE = r'''
/* ---- Mega Turrican Reborn title bumper (compiled into the native game) ---- */
static SDL_Texture *reborn_titlefix_stage[5];
static int reborn_titlefix_state = 0; /* 0 waiting, 1 bumper playing, 2 shown */
static int reborn_titlefix_played = 0;
static uint32_t reborn_titlefix_started = 0;

static int reborn_titlefix_is_title(int w, int h)
{
    if (w < 256 || h < 200) return 0;

    int menu_white = 0;
    int logo_warm = 0;
    int x0 = w * 22 / 100;
    int x1 = w * 78 / 100;
    int y0 = h * 54 / 100;
    int y1 = h * 71 / 100;

    /* The native title screen has two bright, centred menu labels below its logo. */
    for (int y = y0; y < y1; ++y) {
        const uint32_t *row = &vdp.fb[y * 320];
        for (int x = x0; x < x1; ++x) {
            uint32_t p = row[x];
            int r = (p >> 16) & 255;
            int g = (p >> 8) & 255;
            int b = p & 255;
            if (r > 145 && g > 145 && b > 150) ++menu_white;
        }
    }

    /* Also require the original orange/yellow flame artwork in the upper half. */
    int top_end = h * 52 / 100;
    for (int y = 0; y < top_end; ++y) {
        const uint32_t *row = &vdp.fb[y * 320];
        for (int x = 0; x < w; ++x) {
            uint32_t p = row[x];
            int r = (p >> 16) & 255;
            int g = (p >> 8) & 255;
            int b = p & 255;
            if (r > 150 && g > 35 && r > g + 55 && g > b + 20)
                ++logo_warm;
        }
    }
    return menu_white > 100 && logo_warm > 700;
}

static int reborn_titlefix_create_textures(void)
{
    static const int stage_w[5] = {10, 20, 40, 80, REBORN_LOGO_WIDTH};
    static const int stage_h[5] = { 3,  5, 10, 20, REBORN_LOGO_HEIGHT};
    uint32_t base[REBORN_LOGO_WIDTH * REBORN_LOGO_HEIGHT];

    for (int i = 0; i < REBORN_LOGO_WIDTH * REBORN_LOGO_HEIGHT; ++i) {
        base[i] = REBORN_LOGO_PALETTE[REBORN_LOGO_PIXELS[i]];
    }

    for (int stage = 0; stage < 5; ++stage) {
        SDL_Surface *surface = SDL_CreateRGBSurfaceWithFormat(
            0, stage_w[stage], stage_h[stage], 32, SDL_PIXELFORMAT_ARGB8888);
        if (!surface) return 0;

        for (int y = 0; y < stage_h[stage]; ++y) {
            uint32_t *dst = (uint32_t *)((uint8_t *)surface->pixels + y * surface->pitch);
            int sy = y * REBORN_LOGO_HEIGHT / stage_h[stage];
            for (int x = 0; x < stage_w[stage]; ++x) {
                int sx = x * REBORN_LOGO_WIDTH / stage_w[stage];
                dst[x] = base[sy * REBORN_LOGO_WIDTH + sx];
            }
        }

        reborn_titlefix_stage[stage] = SDL_CreateTextureFromSurface(ren, surface);
        SDL_FreeSurface(surface);
        if (!reborn_titlefix_stage[stage]) return 0;
        SDL_SetTextureBlendMode(reborn_titlefix_stage[stage], SDL_BLENDMODE_BLEND);
        SDL_SetTextureScaleMode(reborn_titlefix_stage[stage], SDL_ScaleModeNearest);
    }
    return 1;
}

static void reborn_titlefix_render(int w, int h)
{
    int title_screen = reborn_titlefix_is_title(w, h);

    if (title_screen && !reborn_titlefix_played) {
        reborn_titlefix_played = 1;
        reborn_titlefix_state = 1;
        reborn_titlefix_started = SDL_GetTicks();
    }

    if (reborn_titlefix_state == 0 && !title_screen) return;

    if (!reborn_titlefix_stage[4] && !reborn_titlefix_create_textures())
        return;

    if (reborn_titlefix_state == 1) {
        uint32_t elapsed = SDL_GetTicks() - reborn_titlefix_started;
        if (elapsed >= 1850) {
            reborn_titlefix_state = 2;
        } else {
            /* Hold the game on the title screen while the studio mark plays. */
            md_live_mask = 0;

            int overlay_alpha = 255;
            int logo_alpha = 255;
            if (elapsed > 1400) {
                int fade = (int)(elapsed - 1400);
                overlay_alpha = 255 - (fade * 255 / 450);
                logo_alpha = overlay_alpha;
                if (overlay_alpha < 0) overlay_alpha = 0;
                if (logo_alpha < 0) logo_alpha = 0;
            }

            SDL_SetRenderDrawBlendMode(ren, SDL_BLENDMODE_BLEND);
            SDL_SetRenderDrawColor(ren, 0, 0, 0, (uint8_t)overlay_alpha);
            SDL_RenderFillRect(ren, &game_dst);

            int stage = elapsed < 220 ? 0 :
                       elapsed < 440 ? 1 :
                       elapsed < 660 ? 2 :
                       elapsed < 900 ? 3 : 4;

            int logo_w = game_dst.w * 70 / 100;
            int logo_h = logo_w / 4;
            if (logo_h > game_dst.h / 3) {
                logo_h = game_dst.h / 3;
                logo_w = logo_h * 4;
            }
            SDL_Rect logo_dst = {
                game_dst.x + (game_dst.w - logo_w) / 2,
                game_dst.y + (game_dst.h - logo_h) / 2,
                logo_w, logo_h
            };
            SDL_SetTextureAlphaMod(reborn_titlefix_stage[stage], (uint8_t)logo_alpha);
            SDL_RenderCopy(ren, reborn_titlefix_stage[stage], NULL, &logo_dst);
            SDL_SetTextureAlphaMod(reborn_titlefix_stage[stage], 255);
            SDL_SetRenderDrawBlendMode(ren, SDL_BLENDMODE_NONE);
            return;
        }
    }

    /* Keep the Reborn wordmark on the original title screen after the bumper. */
    if (title_screen && reborn_titlefix_state == 2) {
        int logo_w = game_dst.w * 26 / 100;
        int logo_h = logo_w / 4;
        SDL_Rect logo_dst = {
            game_dst.x + (game_dst.w - logo_w) / 2,
            game_dst.y + game_dst.h * 70 / 100,
            logo_w, logo_h
        };
        SDL_RenderCopy(ren, reborn_titlefix_stage[4], NULL, &logo_dst);
    }
}
/* ---- end Reborn title bumper ---- */
'''


def make_header(png_path: Path, header_path: Path) -> None:
    image = Image.open(png_path).convert("RGBA")
    width, height = image.size
    if (width, height) != (160, 40):
        raise RuntimeError(f"Unexpected embedded logo size: {width}x{height}")

    pixels = list(image.getdata())
    palette = [(0, 0, 0, 0)]
    lookup = {(0, 0, 0, 0): 0}
    indices = []

    for r, g, b, a in pixels:
        color = (r, g, b, a) if a >= 128 else (0, 0, 0, 0)
        idx = lookup.get(color)
        if idx is None:
            idx = len(palette)
            if idx >= 16:
                raise RuntimeError("Reborn logo has more than 16 colours")
            lookup[color] = idx
            palette.append(color)
        indices.append(idx)

    palette += [(0, 0, 0, 0)] * (16 - len(palette))
    packed = []
    for r, g, b, a in palette:
        packed.append((a << 24) | (r << 16) | (g << 8) | b)

    def rows(values: list[int], per_row: int, render) -> str:
        return ",\n".join(
            "    " + ", ".join(render(v) for v in values[i:i + per_row])
            for i in range(0, len(values), per_row)
        )

    header = (
        "#ifndef REBORN_LOGO_ASSET_H\n"
        "#define REBORN_LOGO_ASSET_H\n"
        "#include <stdint.h>\n"
        "#define REBORN_LOGO_WIDTH 160\n"
        "#define REBORN_LOGO_HEIGHT 40\n"
        "static const uint32_t REBORN_LOGO_PALETTE[16] = {\n"
        + rows(packed, 4, lambda v: f"0x{v:08X}u")
        + "\n};\n"
        "static const uint8_t REBORN_LOGO_PIXELS[REBORN_LOGO_WIDTH * REBORN_LOGO_HEIGHT] = {\n"
        + rows(indices, 24, lambda v: str(v))
        + "\n};\n"
        "#endif\n"
    )
    header_path.write_text(header, encoding="utf-8", newline="\n")


def patch_source(source_path: Path) -> None:
    source = source_path.read_text(encoding="utf-8")

    if "reborn_titlefix_render(w, h);" in source:
        raise RuntimeError("Reborn title bumper patch is already installed")

    include = '#include "reborn_logo_asset.h"\n'
    if include not in source:
        marker = '#include "vdp.h"\n'
        if marker not in source:
            raise RuntimeError('Could not find #include "vdp.h" in SDL frontend')
        source = source.replace(marker, marker + include, 1)

    frame_marker = "void md_frame_hook(void)"
    if source.count(frame_marker) != 1:
        raise RuntimeError("Could not uniquely identify md_frame_hook()")
    source = source.replace(frame_marker, C_CODE + "\n" + frame_marker, 1)

    render_pattern = re.compile(
        r"(?m)^([ \t]*)SDL_RenderCopy\(ren,\s*tex,\s*&src,\s*&game_dst\);\s*$"
    )
    matches = list(render_pattern.finditer(source))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one game-frame SDL_RenderCopy call, found {len(matches)}"
        )
    match = matches[0]
    indent = match.group(1)
    insertion = (
        match.group(0)
        + "\n"
        + indent
        + "reborn_titlefix_render(w, h);"
    )
    source = source[:match.start()] + insertion + source[match.end():]
    source_path.write_text(source, encoding="utf-8", newline="\n")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch-reborn-title.py PROJECT_ROOT", file=sys.stderr)
        return 2

    project = Path(sys.argv[1]).resolve()
    source_path = project / "runtime" / "sdl_main.c"
    header_path = project / "runtime" / "reborn_logo_asset.h"
    asset_b64 = Path(__file__).with_name("reborn-logo.png.b64").read_text(
        encoding="ascii"
    ).strip()
    png_path = project / "runtime" / "reborn-logo-build.png"
    png_path.write_bytes(base64.b64decode(asset_b64, validate=True))

    try:
        make_header(png_path, header_path)
        patch_source(source_path)
    finally:
        try:
            png_path.unlink()
        except FileNotFoundError:
            pass

    print(
        "Embedded Reborn logo and installed title-screen bumper: "
        + hashlib.sha256(header_path.read_bytes()).hexdigest()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
