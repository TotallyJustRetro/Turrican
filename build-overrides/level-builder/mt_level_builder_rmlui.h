#pragma once
#ifndef MT_LEVEL_BUILDER_RMLUI_H
#define MT_LEVEL_BUILDER_RMLUI_H

#include <SDL.h>

#ifdef __cplusplus
extern "C" {
#endif

int mtlbr_init(SDL_Window *window, SDL_Renderer *renderer);
void mtlbr_shutdown(void);
void mtlbr_process_event(const SDL_Event *event);
int mtlbr_is_active(void);
int mtlbr_render_to_screen(SDL_Renderer *renderer, int view_x, int view_y, int view_width, int view_height);

#ifdef __cplusplus
}
#endif

#endif
