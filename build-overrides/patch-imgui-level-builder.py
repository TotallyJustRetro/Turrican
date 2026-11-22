#!/usr/bin/env python3
"""Install the Dear ImGui Level Builder shell into the native SDL2 game loop."""
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
        s = once(s, anchor, anchor + include + "\n", "ImGui bridge include")

    route_anchor = (
        "    if(e->type==SDL_WINDOWEVENT&&e->window.event==SDL_WINDOWEVENT_RESIZED)"
        "{ws_update();make_texture();}\n"
    )
    route_patch = route_anchor + (
        "    /* ImGui owns pointer/keyboard interaction while the new editor is open. */\n"
        "    if(native_menu_state==11){mtlb_process_event(e);return;}\n"
    )
    if "ImGui owns pointer/keyboard interaction" not in s:
        s = once(s, route_anchor, route_patch, "Level Builder SDL event routing")

    # Level Builder is a dedicated game screen, not a VDP-frame overlay.
    present_anchor = "static void native_menu_present_frame(void) {"
    present_patch = present_anchor + (
        "\n    if(native_menu_state==11) {\n"
        "        SDL_SetRenderDrawColor(ren,0,0,0,255);\n"
        "        SDL_RenderClear(ren);\n"
        "        if(mtlb_render(ren)) {\n"
        "            mtlb_shutdown();\n"
        "            native_custom_enter_parent();\n"
        "        }\n"
        "        SDL_RenderPresent(ren);\n"
        "        return;\n"
        "    }\n"
    )
    if "Level Builder is a dedicated game screen" not in s:
        s = once(s, present_anchor, present_patch, "standalone Level Builder render state")

    init_anchor = "    if(adev&&pause_audio)SDL_PauseAudioDevice(adev,1);"
    init_patch = init_anchor + (
        "\n    if(native_menu_state==11 && !mtlb_init(SDL_RenderGetWindow(ren),ren)) {\n"
        "        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR,\"Mega Turrican Reborn\","
        "\"Could not initialize the Level Builder renderer.\",NULL);\n"
        "        native_custom_enter_parent();\n"
        "    }"
    )
    if "initialize Dear ImGui before routing editor input" not in s:
        s = once(s, init_anchor, init_patch + "\n    /* initialize Dear ImGui before routing editor input */",
                 "initialize Dear ImGui before routing editor input")

    sdl_path.write_text(s, encoding="utf-8")
    print("Installed custom ImGui Level Builder shell and live VDP tile-plane bridge.")


if __name__ == "__main__":
    main()
