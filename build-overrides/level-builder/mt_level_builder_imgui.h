#pragma once
#ifndef MT_LEVEL_BUILDER_IMGUI_H
#define MT_LEVEL_BUILDER_IMGUI_H

#include <SDL.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Dear ImGui is rendered at the PC window resolution over the processed game frame. */
int mtlb_init(SDL_Window *window, SDL_Renderer *renderer);
void mtlb_shutdown(void);
void mtlb_process_event(const SDL_Event *event);
int mtlb_render_to_screen(SDL_Renderer *renderer, int view_x, int view_y, int view_width, int view_height);
void mtlb_update_vdp_resources(const uint8_t *vram, const uint16_t *cram, const uint8_t *regs);
int md_rom_copy_region(uint32_t offset, void *destination, uint32_t bytes);

int mtlb_map_cols(void);
int mtlb_map_rows(void);
int mtlb_map_get(int x, int y);
void mtlb_map_set(int x, int y, int tile);
void mtlb_map_set_brush(int tile);
int mtlb_map_save(void);
int mtlb_map_load(void);
int mtlb_map_cursor_x(void);
int mtlb_map_cursor_y(void);
int mtlb_map_brush(void);

#ifdef __cplusplus
}
#endif

#endif
