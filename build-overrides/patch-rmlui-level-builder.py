#!/usr/bin/env python3
"""Install the RmlUi-only Maker frontend and the framework-independent editor model."""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path


def insert_after_token(source: str, token: str, addition: str, label: str) -> str:
    count = source.count(token)
    if count != 1:
        raise RuntimeError(f"{label}: expected one insertion anchor, found {count}")
    end = source.index(token) + len(token)
    return source[:end] + addition + source[end:]


def insert_after_line(source: str, token: str, addition: str, label: str) -> str:
    count = source.count(token)
    if count != 1:
        raise RuntimeError(f"{label}: expected one insertion anchor, found {count}")
    start = source.index(token)
    line_end = source.find("\n", start)
    if line_end < 0:
        line_end = len(source)
        return source + addition
    return source[:line_end + 1] + addition + source[line_end + 1:]


def insert_include(source: str, include: str, after_token: str | None = None) -> str:
    if include in source:
        return source
    if after_token:
        match = re.search(r"(?m)^#include[ \t]+[<\"][^>\"]+[>\"][ \t]*$", source)
        if after_token not in source:
            raise RuntimeError(f"Required include anchor is missing: {after_token}")
        start = source.index(after_token)
        line_end = source.find("\n", start)
        if line_end < 0:
            line_end = len(source)
            return source + "\n" + include + "\n"
        return source[:line_end + 1] + include + "\n" + source[line_end + 1:]
    match = re.search(r"(?m)^#include[ \t]+[<\"][^>\"]+[>\"][ \t]*$", source)
    if not match:
        raise RuntimeError("Could not find an existing include directive in runtime/sdl_main.c.")
    return source[:match.end()] + "\n" + include + source[match.end():]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-rmlui-level-builder.py PROJECT_ROOT")
    project = Path(sys.argv[1]).resolve()
    runtime = project / "runtime"
    sdl_path = runtime / "sdl_main.c"
    if not sdl_path.is_file():
        raise RuntimeError(f"Native SDL entry point not found: {sdl_path}")

    source_dir = Path(__file__).resolve().parent / "level-builder"
    required = (
        "mt_level_builder_model.cpp",
        "mt_level_builder_model.h",
        "mt_level_builder_importer.cpp",
        "mt_level_builder_importer.h",
        "mt_level_builder_rmlui.cpp",
        "mt_level_builder_rmlui.h",
    )
    for name in required:
        source = source_dir / name
        if not source.is_file():
            raise RuntimeError(f"RmlUi Maker source is missing: {source}")
        shutil.copy2(source, runtime / name)

    s = sdl_path.read_text(encoding="utf-8-sig")

    model_include = '#include "mt_level_builder_model.h"'
    rml_include = '#include "mt_level_builder_rmlui.h"'
    s = insert_include(s, model_include)
    s = insert_include(s, rml_include, after_token=model_include)

    route_marker = "The Maker has one runtime frontend: RmlUi"
    route_token = "if(e->type==SDL_WINDOWEVENT&&e->window.event==SDL_WINDOWEVENT_RESIZED)"
    if route_marker not in s:
        s = insert_after_line(
            s,
            route_token,
            "    /* The Maker has one runtime frontend: RmlUi. */\n"
            "    if(native_menu_state==11){mtlbr_process_event(e);return;}\n",
            "RmlUi-only SDL event routing",
        )

    present_marker = "native_maker_closed=mtlbr_render_to_screen"
    present_anchor = (
        "    SDL_RenderCopy(ren,tex,&src,&game_dst);\n"
        "    SDL_RenderPresent(ren);"
    )
    present_patch = (
        "    SDL_RenderCopy(ren,tex,&src,&game_dst);\n"
        "    int native_maker_closed=0;\n"
        "    if(native_menu_state==11)\n"
        "        native_maker_closed=mtlbr_render_to_screen(ren,game_dst.x,game_dst.y,game_dst.w,game_dst.h);\n"
        "    SDL_RenderPresent(ren);\n"
        "    if(native_maker_closed) {\n"
        "        mtlbr_shutdown();\n"
        "        if(native_level_builder_from_pause) {\n"
        "            native_level_builder_from_pause=0;\n"
        "            native_menu_state=1; native_menu_sel=7;\n"
        "        } else {\n"
        "            native_custom_enter_parent();\n"
        "        }\n"
        "    }"
    )
    if present_marker not in s:
        s = insert_after_token(s, present_anchor, present_patch, "RmlUi-only Maker presentation")

    init_marker = "mtlb_model_update_vdp_resources(vdp.vram,vdp.cram,vdp.reg)"
    init_anchor = "if(adev&&pause_audio)SDL_PauseAudioDevice(adev,1);"
    if init_marker not in s:
        s = insert_after_token(
            s,
            init_anchor,
            "\n"
            "    if(native_menu_state==11) {\n"
            "        /* The game is paused in Maker: snapshot VDP art once on entry, not every frame. */\n"
            "        mtlb_model_update_vdp_resources(vdp.vram,vdp.cram,vdp.reg);\n"
            "        if(!mtlbr_init(SDL_RenderGetWindow(ren),ren)) {\n"
            '            SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR,"Mega Turrican Reborn - RmlUi",mtlbr_last_error(),SDL_RenderGetWindow(ren));\n'
            "            native_custom_enter_parent();\n"
            "        }\n"
            "    }",
            "one-time VDP snapshot and RmlUi startup",
        )

    if "mtlb_init(" in s or "mtlb_render_to_screen(" in s or "mtlb_process_event(" in s:
        raise RuntimeError("Legacy ImGui Maker runtime calls remain in sdl_main.c.")
    if "mtlb_update_vdp_resources(" in s:
        raise RuntimeError("Legacy per-frame ImGui VDP updater remains in sdl_main.c.")

    sdl_path.write_text(s, encoding="utf-8")
    print("Installed RmlUi-only Maker runtime; no ImGui frontend, fallback, or per-frame VDP scan.")


if __name__ == "__main__":
    main()
