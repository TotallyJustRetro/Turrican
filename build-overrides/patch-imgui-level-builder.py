#!/usr/bin/env python3
"""Install the Dear ImGui Level Builder as a high-resolution PC overlay."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def once(source: str, anchor: str, replacement: str, label: str) -> str:
    count = source.count(anchor)
    if count != 1:
        raise RuntimeError(f"{label}: expected one insertion anchor, found {count}")
    return source.replace(anchor, replacement, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-imgui-level-builder.py PROJECT_ROOT")
    project = Path(sys.argv[1]).resolve()
    runtime = project / "runtime"
    sdl_path = runtime / "sdl_main.c"
    if not sdl_path.is_file():
        raise RuntimeError(f"Native SDL entry point not found: {sdl_path}")

    source_dir = Path(__file__).resolve().parent / "level-builder"
    for name in ("mt_level_builder_imgui.cpp", "mt_level_builder_imgui.h"):
        source = source_dir / name
        if not source.is_file():
            raise RuntimeError(f"Dear ImGui Level Builder source is missing: {source}")
        shutil.copy2(source, runtime / name)

    s = sdl_path.read_text(encoding="utf-8-sig")

    include = '#include "mt_level_builder_imgui.h"'
    if include not in s:
        anchor = "#include <SDL.h>\n"
        s = once(s, anchor, anchor + include + "\n", "ImGui framebuffer bridge include")

    # ImGui receives the same SDL input events as the native pause screen.
    route_anchor = (
        "    if(e->type==SDL_WINDOWEVENT&&e->window.event==SDL_WINDOWEVENT_RESIZED)"
        "{ws_update();make_texture();}\n"
    )
    route_patch = route_anchor + (
        "    /* ImGui owns pointer/keyboard interaction while the editor is open. */\n"
        "    if(native_menu_state==11){mtlb_process_event(e);return;}\n"
    )
    if "ImGui owns pointer/keyboard interaction" not in s:
        s = once(s, route_anchor, route_patch, "Level Builder SDL event routing")

    # The game keeps its native-resolution video pipeline. Dear ImGui is
    # drawn afterward on the PC renderer at the actual game viewport size.
    frame_anchor = (
        "static void native_menu_present_frame(void) {\n"
        "    int w=vdp.width?vdp.width:320, h=vdp.height?vdp.height:224;\n"
        "    ws_update();"
    )
    frame_patch = (
        "static void native_menu_present_frame(void) {\n"
        "    int w=vdp.width?vdp.width:320, h=vdp.height?vdp.height:224;\n"
        "    /* MT_LEVEL_BUILDER_PC_OVERLAY: refresh live cartridge assets. */\n"
        "    if(native_menu_state==11) mtlb_update_vdp_resources(vdp.vram,vdp.cram,vdp.reg);\n"
        "    ws_update();"
    )
    if "MT_LEVEL_BUILDER_PC_OVERLAY" not in s:
        s = once(s, frame_anchor, frame_patch, "PC-resolution Maker asset refresh")

        present_anchor = (
            "    SDL_RenderCopy(ren,tex,&src,&game_dst);\n"
            "    SDL_RenderPresent(ren);"
        )
        present_patch = (
            "    SDL_RenderCopy(ren,tex,&src,&game_dst);\n"
            "    int native_maker_closed=0;\n"
            "    if(native_menu_state==11)\n"
            "        native_maker_closed=mtlb_render_to_screen(ren,game_dst.x,game_dst.y,game_dst.w,game_dst.h);\n"
            "    SDL_RenderPresent(ren);\n"
            "    if(native_maker_closed) {\n"
            "        mtlb_shutdown();\n"
            "        if(native_level_builder_from_pause) {\n"
            "            native_level_builder_from_pause=0;\n"
            "            native_menu_state=1; native_menu_sel=7;\n"
            "        } else {\n"
            "            native_custom_enter_parent();\n"
            "        }\n"
            "    }"
        )
        s = once(s, present_anchor, present_patch, "PC-resolution Maker screen overlay")

    # Initialize Dear ImGui against the actual PC game renderer, not a
    # software surface constrained to 320x224.
    init_anchor = "    if(adev&&pause_audio)SDL_PauseAudioDevice(adev,1);"
    init_patch = init_anchor + (
        "    if(native_menu_state==11 && !mtlb_init(SDL_RenderGetWindow(ren),ren)) {\n"
        "        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR,\"Mega Turrican Reborn\","
        "\"Could not initialize the Level Builder renderer.\",NULL);\n"
        "        native_custom_enter_parent();\n"
        "    }"
    )
    if "initialize Dear ImGui PC-resolution renderer" not in s:
        s = once(s, init_anchor,
            init_patch + "\n    /* initialize Dear ImGui PC-resolution renderer */",
            "initialize Dear ImGui PC-resolution renderer")

    sdl_path.write_text(s, encoding="utf-8")
    print("Installed Dear ImGui at PC output resolution above the processed game frame.")


if __name__ == "__main__":
    main()
