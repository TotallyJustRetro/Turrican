#pragma once
#ifndef MT_LEVEL_BUILDER_IMGUI_H
#define MT_LEVEL_BUILDER_IMGUI_H

#include <SDL.h>

#ifdef __cplusplus
extern "C" {
#endif

int mtlb_init(SDL_Window *window, SDL_Renderer *renderer);
void mtlb_shutdown(void);
void mtlb_process_event(const SDL_Event *event);
int mtlb_render(SDL_Renderer *renderer);

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
