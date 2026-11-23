#pragma once
#ifndef MT_LEVEL_BUILDER_IMPORTER_H
#define MT_LEVEL_BUILDER_IMPORTER_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
int mtlb_import_model(const char *path);
int mtlb_import_texture(const char *path);
int mtlb_imported_model_count(void);
int mtlb_imported_model_info(int index,char *name,int name_capacity,char *path,int path_capacity,
                             uint32_t *triangles,uint32_t *bones,float bounds_xyz[3],
                             int *has_diffuse,int *has_normal,int *has_emissive,int *classification);
int mtlb_imported_model_preview(int index,float *xyz,int max_vertices);
void mtlb_imported_model_classify(int index,int classification);
int mtlb_imported_texture_count(void);
int mtlb_imported_texture_info(int index,char *name,int name_capacity,char *path,int path_capacity,
                               int *width,int *height);
const char *mtlb_importer_last_error(void);
#ifdef __cplusplus
}
#endif
#endif
