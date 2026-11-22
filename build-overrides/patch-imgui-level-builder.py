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


BRIDGE = r'''
/* Dear ImGui Level Builder bridge to the existing Genesis VDP tile plane. */
int mtlb_map_cols(void) { return native_level_cols(); }
int mtlb_map_rows(void) { return native_level_rows(); }
int mtlb_map_get(int x,int y) {
    int cols=native_level_cols(),rows=native_level_rows();
    if(x<0||y<0||x>=cols||y>=rows)return 0;
    uint32_t at=(native_level_plane_a()+(uint32_t)(y*cols+x)*2)&0xFFFF;
    return ((int)vdp.vram[at]<<8 | (int)vdp.vram[(at+1)&0xFFFF]) & 0x7FF;
}
void mtlb_map_set(int x,int y,int tile) {
    native_editor_x=x;native_editor_y=y;
    native_editor_tile=tile&0x7FF;
    native_level_paint();
}
int mtlb_map_save(void) {
#ifdef _WIN32
    _mkdir("levels");
#else
    mkdir("levels",0775);
#endif
    return native_level_export();
}
int mtlb_map_load(void) { return native_level_import(); }
int mtlb_map_cursor_x(void) { return native_editor_x; }
int mtlb_map_cursor_y(void) { return native_editor_y; }
int mtlb_map_brush(void) { return native_editor_tile; }
'''


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

    if "Dear ImGui Level Builder bridge to the existing Genesis VDP tile plane" not in s:
        anchor = "static void render_native_level_builder(void) {"
        s = once(s, anchor, BRIDGE + "\n" + anchor, "VDP bridge functions")

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

    render_anchor = "    SDL_RenderCopy(ren,tex,&src,&game_dst);\n    SDL_RenderPresent(ren);"
    render_patch = (
        "    SDL_RenderCopy(ren,tex,&src,&game_dst);\n"
        "    if(native_menu_state==11) mtlb_set_stage_texture(tex,tw,h);\n"
        "    if(native_menu_state==11 && mtlb_render(ren)) {\n"
        "        mtlb_shutdown();\n"
        "        native_custom_enter_parent();\n"
        "    } else if(native_menu_state!=11) {\n"
        "        mtlb_shutdown();\n"
        "    }\n"
        "    SDL_RenderPresent(ren);"
    )
    if "mtlb_render(ren)" not in s:
        s = once(s, render_anchor, render_patch, "ImGui frame presentation hook")

    sdl_path.write_text(s, encoding="utf-8")
    print("Installed custom ImGui Level Builder shell and live VDP tile-plane bridge.")


if __name__ == "__main__":
    main()
