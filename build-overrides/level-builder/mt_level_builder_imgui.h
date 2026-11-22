#pragma once
#ifndef MT_LEVEL_BUILDER_IMGUI_H
#define MT_LEVEL_BUILDER_IMGUI_H

#include <SDL.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Dear ImGui is rasterized at the game's native VDP resolution and composited
   into the same framebuffer used by the cartridge and native pause menus. */
int mtlb_init(SDL_Window *window, int width, int height);
void mtlb_shutdown(void);
void mtlb_process_event(const SDL_Event *event);
int mtlb_render_to_framebuffer(uint32_t *framebuffer, int width, int height, int pitch_pixels);

int mtlb_map_cols(void);
int mtlb_map_rows(void);
int mtlb_map_get(int x, int y);
void mtlb_map_set(int x, int y, int tile);
int mtlb_map_save(void);
int mtlb_map_load(void);
int mtlb_map_cursor_x(void);
int mtlb_map_cursor_y(void);
int mtlb_map_brush(void);

#ifdef __cplusplus
}
#endif

#endif
