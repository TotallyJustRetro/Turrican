#pragma once
#ifndef MT_LEVEL_BUILDER_MODEL_H
#define MT_LEVEL_BUILDER_MODEL_H
#include <SDL.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
int md_rom_copy_region(uint32_t offset, void *destination, uint32_t bytes);
void mtlb_model_update_vdp_resources(const uint8_t *vram, const uint16_t *cram, const uint8_t *regs);
int mtlb_map_cols(void);
int mtlb_map_rows(void);
int mtlb_map_get(int x,int y);
void mtlb_map_set(int x,int y,int tile);
void mtlb_map_set_brush(int tile);
int mtlb_map_save(void);
int mtlb_map_load(void);
int mtlb_map_cursor_x(void);
int mtlb_map_cursor_y(void);
int mtlb_map_brush(void);
void mtlb_map_set_cursor(int x,int y);
void mtlb_editor_push_undo(void);
void mtlb_editor_undo(void);
void mtlb_editor_redo(void);
int mtlb_editor_prepare_rom_assets(void);
int mtlb_editor_tile_count(void);
int mtlb_editor_tile_entry(int index,int palette);
void mtlb_editor_tile_rgba(int entry,int x,int y,uint8_t rgba[4]);
int mtlb_editor_sprite_asset_count(void);
int mtlb_editor_sprite_asset_info(int index,uint32_t *owner_pc,uint32_t *descriptor_pc,uint16_t *frame_count,uint16_t *part_count);
int mtlb_editor_sprite_asset_category(int index);
int mtlb_editor_sprite_asset_set_category(int index,int category);
int mtlb_editor_sprite_asset_part(int index,int part_index,int *x,int *y,int *width_tiles,int *height_tiles,uint16_t *tile_attr);
uint32_t mtlb_editor_vdp_art_hash(void);
int mtlb_editor_entity_count(void);
int mtlb_editor_place_entity(float x,float y,int type,int sprite_asset_index);
int mtlb_editor_entity_info(int index,float *x,float *y,int *type,int *hp,uint16_t *tile_attr,int *width_tiles,int *height_tiles);
int mtlb_editor_entity_sprite_asset(int index);
#ifdef __cplusplus
}
#endif
#endif
