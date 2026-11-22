#!/usr/bin/env python3
"""Install the Dear ImGui Level Builder into the native VDP framebuffer path."""
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

    # Render ImGui into vdp.fb BEFORE shade(), texture upload and normal
    # presentation. This is the same cartridge/pause-menu graphics path.
    frame_anchor = (
        "static void native_menu_present_frame(void) {\n"
        "    int w=vdp.width?vdp.width:320, h=vdp.height?vdp.height:224;\n"
        "    ws_update();"
    )
    frame_patch = (
        "static void native_menu_present_frame(void) {\n"
        "    int w=vdp.width?vdp.width:320, h=vdp.height?vdp.height:224;\n"
        "    if(native_menu_state==11 && "
        "mtlb_render_to_framebuffer(vdp.fb,w,h,320)) {\n"
        "        mtlb_shutdown();\n"
        "        native_custom_enter_parent();\n"
        "    }\n"
        "    ws_update();"
    )
    if "MT_LEVEL_BUILDER_VDP_FRAMEBUFFER" not in s:
        s = once(s, frame_anchor,
            frame_patch.replace("    if(native_menu_state==11", 
                "    /* MT_LEVEL_BUILDER_VDP_FRAMEBUFFER: composite ImGui before shade(). */\n"
                "    if(native_menu_state==11"),
            "native VDP framebuffer integration")

    # Initialize the offscreen software renderer at the current VDP dimensions.
    init_anchor = "    if(adev&&pause_audio)SDL_PauseAudioDevice(adev,1);"
    init_patch = init_anchor + (
        "\n    if(native_menu_state==11 && "
        "!mtlb_init(SDL_RenderGetWindow(ren),vdp.width?vdp.width:320,"
        "vdp.height?vdp.height:224)) {\n"
        "        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR,\"Mega Turrican Reborn\","
        "\"Could not initialize the Level Builder renderer.\",NULL);\n"
        "        native_custom_enter_parent();\n"
        "    }"
    )
    if "initialize Dear ImGui native-resolution framebuffer renderer" not in s:
        s = once(s, init_anchor,
            init_patch + "\n    /* initialize Dear ImGui native-resolution framebuffer renderer */",
            "initialize Dear ImGui native-resolution framebuffer renderer")

    sdl_path.write_text(s, encoding="utf-8")
    print("Installed Dear ImGui into the native VDP framebuffer before game video processing.")


if __name__ == "__main__":
    main()
