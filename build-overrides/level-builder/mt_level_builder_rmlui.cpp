#include "mt_level_builder_rmlui.h"
#include "mt_level_builder_model.h"
#include "mt_level_builder_importer.h"

#include "RmlUi_Platform_SDL.h"
#include "RmlUi_Renderer_SDL.h"
#include <RmlUi/Core/Core.h>
#include <RmlUi/Core/Context.h>
#include <RmlUi/Core/DataModelHandle.h>
#include <RmlUi/Core/ElementDocument.h>
#include <RmlUi/Core/EventListener.h>
#include <RmlUi/Core/StringUtilities.h>
#include <RmlUi/Core/Log.h>

#include <algorithm>
#include <cstdio>
#include <cmath>
#include <cstdarg>
#include <cstdlib>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#include <commdlg.h>
#endif

namespace {
class MakerSystemInterface;
static SDL_Window *g_window = nullptr;
static SDL_Renderer *g_renderer = nullptr;
static MakerSystemInterface *g_system = nullptr;
static RenderInterface_SDL *g_render = nullptr;
static Rml::Context *g_context = nullptr;
static Rml::ElementDocument *g_document = nullptr;
static Rml::Element *g_viewport = nullptr;
static Rml::Element *g_stage_grid = nullptr;
static Rml::Element *g_status = nullptr;
static Rml::DataModelHandle g_model_handle;
static Rml::String g_global_mode = "MODERN REBORN";
static Rml::String g_selected_tool = "brush";
static Rml::String g_active_tab = "tiles";
static int g_cursor_x = 24, g_cursor_y = 12, g_ui_selected_entity = -1;
static bool g_rml_initialised = false;
static bool g_exit_requested = false;
static int g_brush_tile = 1;
static int g_map_cols = 64;
static int g_map_rows = 32;
static int g_cached_window_width = -1, g_cached_window_height = -1;
static int g_cached_view_x = -1, g_cached_view_y = -1, g_cached_view_width = -1, g_cached_view_height = -1;
static int g_last_painted_x = -1, g_last_painted_y = -1, g_drag_tile = -1;
static bool g_stage_batch_dirty = true;
static float g_stage_batch_x=-1.0f,g_stage_batch_y=-1.0f,g_stage_batch_w=-1.0f,g_stage_batch_h=-1.0f;
static unsigned g_perf_frames = 0;
static double g_perf_update_ms = 0.0, g_perf_render_ms = 0.0, g_perf_grid_ms = 0.0;
static std::vector<SDL_Vertex> g_stage_vertices;
static std::vector<int> g_stage_indices;

enum MakerMode { MAKER_TILES=0, MAKER_OBJECTS, MAKER_EVENTS, MAKER_ASSETS, MAKER_BOSS, MAKER_BACKGROUNDS, MAKER_MODE_COUNT };
static int g_maker_mode = MAKER_TILES;
static int g_maker_tool = 1;
static int g_maker_layer = 2;
static int g_maker_palette = 0;
static int g_maker_canvas_size = 16;
static bool g_maker_modern = false;
static bool g_maker_show_grid = true;
static bool g_maker_snap = true;
static bool g_maker_collision = true;
static bool g_maker_layers[5] = {true,true,true,true,false};
static bool g_settings_open = false;
static int g_asset_shelf_offset = 0;
static int g_asset_shelf_count = -1;
static uint32_t g_asset_shelf_hash = 0;
static int g_asset_filter = 0;
static int g_selected_asset_id = -1;
static Rml::String g_selected_asset_type;
static int g_selected_model_asset = -1;
static int g_pending_model_asset = -1;
static int g_selected_texture_asset = -1;
static bool g_asset_drag_active = false;
static int g_drag_asset_id = -1;
static Rml::String g_drag_asset_type;
static int g_placed_model_count = 0;
struct PlacedMakerModel { int asset_id; float x, y; };
static PlacedMakerModel g_placed_models[64] = {};
struct MakerLight { float x,y,radius,intensity; uint32_t color; int type; };
static MakerLight g_lights[32] = {};
static int g_light_count = 0;
static int g_light_type = 0;
static uint32_t g_light_color = 0xFFE619E6u;
static float g_light_radius = 96.0f;
static float g_light_intensity = 0.65f;
static bool g_fx_bloom = false, g_fx_rim = false, g_fx_cel = false, g_fx_fog = false, g_fx_crt = false;
static char g_custom_music_path[260] = "";
static char g_background_name[96] = "NONE";
static int g_background_layer = 0;
static float g_parallax_x[4] = {0.25f,0.5f,1.0f,1.0f};
static float g_parallax_y[4] = {0.25f,0.5f,1.0f,1.0f};
static int g_event_node_count = 0;
static int g_event_selected = -1;
static int g_boss_hp = 100;
static int g_boss_phase = 1;
static bool g_boss_created = false;
static bool g_asset_canvas_dirty = false;
static int g_asset_color = 12;
static int g_asset_pixels[32*32] = {};
static int g_selected_rom_sprite = -1;

static std::string g_log_path;
static std::string g_portable_root;
static char g_last_error[512] = "RmlUi Maker has not been initialized.";

/*
 * The Electron launcher explicitly sets MEGATURRICAN_CONFIG_DIR to the
 * portable launcher folder. Prefer it over SDL_GetBasePath(), which follows
 * the native game EXE and may point at launcher/native or another subfolder.
 */
static const std::string &maker_portable_root()
{
    if (!g_portable_root.empty()) return g_portable_root;

    const char *portable = std::getenv("MEGATURRICAN_CONFIG_DIR");
    if (portable && portable[0] != '\0') {
        g_portable_root = portable;
    } else {
        char *base = SDL_GetBasePath();
        if (base) {
            g_portable_root = base;
            SDL_free(base);
        } else {
            g_portable_root = ".";
        }
    }

    while (g_portable_root.size() > 1 &&
           (g_portable_root.back() == '/' || g_portable_root.back() == '\\'))
        g_portable_root.pop_back();
    return g_portable_root;
}

static void set_status(const char *message);

static std::string maker_choose_file(bool texture)
{
#ifdef _WIN32
    char path[32768] = {};
    static const char model_filter[] = "3D Models (GLB, GLTF, OBJ, FBX)\0*.glb;*.gltf;*.obj;*.fbx\0All Files\0*.*\0";
    static const char texture_filter[] = "Textures (PNG, TGA)\0*.png;*.tga\0All Files\0*.*\0";
    OPENFILENAMEA dialog = {};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = nullptr;
    dialog.lpstrFilter = texture ? texture_filter : model_filter;
    dialog.nFilterIndex = 1;
    dialog.lpstrFile = path;
    dialog.nMaxFile = sizeof(path);
    dialog.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;
    dialog.lpstrTitle = texture ? "Import PNG / TGA texture" : "Import GLB / GLTF / OBJ / FBX model";
    if (GetOpenFileNameA(&dialog)) return path;
#endif
    return std::string();
}

static void maker_set_modal(const char *id, bool visible)
{
    if (g_document) {
        if (Rml::Element *modal = g_document->GetElementById(id))
            modal->SetClass("hidden", !visible);
    }
}

static void maker_update_imported_model_panel(int index)
{
    if (!g_document || index < 0) return;
    char name[128]={}, path[1024]={};
    uint32_t triangles=0, bones=0;
    float bounds[3]={0,0,0};
    int diffuse=0, normal=0, emissive=0, classification=0;
    if (!mtlb_imported_model_info(index,name,sizeof(name),path,sizeof(path),&triangles,&bones,bounds,
        &diffuse,&normal,&emissive,&classification)) return;

    if (Rml::Element *element=g_document->GetElementById("model-preview"))
        element->SetInnerRML("<div class='model-wireframe-label'>SELECTED: "+Rml::StringUtilities::EncodeRml(name)+"</div>");
    if (Rml::Element *element=g_document->GetElementById("model-triangle-count")) {
        char value[64]; std::snprintf(value,sizeof(value),"%u / 256 TRIS",triangles); element->SetInnerRML(value);
    }
    if (Rml::Element *element=g_document->GetElementById("model-bone-count")) {
        char value[48]; std::snprintf(value,sizeof(value),"%u",bones); element->SetInnerRML(value);
    }
    if (Rml::Element *element=g_document->GetElementById("model-texture-state")) {
        char value[96]; std::snprintf(value,sizeof(value),"%s%s%s",
            diffuse?"ALBEDO ":"",normal?"NORMAL ":"",emissive?"EMISSIVE":"");
        element->SetInnerRML(value[0]?value:"NONE");
    }
    if (Rml::Element *element=g_document->GetElementById("model-classification")) {
        char value[8]; std::snprintf(value,sizeof(value),"%d",std::max(0,std::min(4,classification)));
        element->SetAttribute("value",value);
    }
    if (Rml::Element *element=g_document->GetElementById("modal-asset-info")) {
        char value[512];
        std::snprintf(value,sizeof(value),"%s / %u TRIS / %u BONES / BOUNDS %.2f x %.2f x %.2f",
            name,triangles,bones,bounds[0],bounds[1],bounds[2]);
        element->SetInnerRML(Rml::StringUtilities::EncodeRml(value));
    }
}

static void maker_open_model_importer()
{
    const std::string path=maker_choose_file(false);
    if(path.empty())return;
    const int index=mtlb_import_model(path.c_str());
    if(index<0){
        set_status(mtlb_importer_last_error());
        maker_log("Model import failed: %s",mtlb_importer_last_error());
        return;
    }
    g_pending_model_asset=index;
    g_selected_model_asset=index;
    maker_update_imported_model_panel(index);
    maker_set_modal("model-import-modal",true);
    maker_refresh_asset_shelf();
    set_status("Model inspected. Choose its role to register the asset.");
    maker_log("Imported model asset %d: %s",index,path.c_str());
}

static void maker_open_texture_importer()
{
    const std::string path=maker_choose_file(true);
    if(path.empty())return;
    const int index=mtlb_import_texture(path.c_str());
    if(index<0){
        set_status(mtlb_importer_last_error());
        maker_log("Texture import failed: %s",mtlb_importer_last_error());
        return;
    }
    g_selected_texture_asset=index;
    char name[128]={}, stored[1024]={}; int width=0, height=0;
    mtlb_imported_texture_info(index,name,sizeof(name),stored,sizeof(stored),&width,&height);
    char message[256]; std::snprintf(message,sizeof(message),"Imported texture %s (%d x %d).",name,width,height);
    set_status(message);
}
static void maker_log(const char *format, ...);
static void maker_refresh_sprite_lists()
{
    if(!g_document)return;
    std::string enemies,bosses;
    const int count=mtlb_editor_sprite_asset_count();
    for(int i=0;i<count;i++){
        char card[320];
        std::snprintf(card,sizeof(card),
            "<div id='asset-sprite-enemy-%d' class='asset-card' draggable='true' data-action='asset-select' data-asset-id='%d' data-asset-type='enemy'><div class='asset-thumb' id='sprite-thumb-enemy-%d'></div><div>SPRITE SET %02d</div><div class='asset-tag'>2D</div></div>",
            i,i,i,i+1);
        enemies+=card;
        std::snprintf(card,sizeof(card),
            "<div id='asset-sprite-boss-%d' class='asset-card' draggable='true' data-action='asset-select' data-asset-id='%d' data-asset-type='boss'><div class='asset-thumb' id='sprite-thumb-boss-%d'></div><div>BOSS SET %02d</div><div class='asset-tag'>2D</div></div>",
            i,i,i,i+1);
        bosses+=card;
    }
    if(count==0){
        enemies="<div class='folder-subheading'>No validated ROM sprite descriptors were found.</div>";
        bosses="<div class='folder-subheading'>No validated ROM boss descriptors were found.</div>";
    }
    if(Rml::Element *list=g_document->GetElementById("asset-list-enemies"))list->SetInnerRML(enemies);
    if(Rml::Element *list=g_document->GetElementById("asset-list-bosses"))list->SetInnerRML(bosses);
}

static void maker_refresh_imported_asset_lists()
{
    if(!g_document)return;
    std::string lists[5];
    const int count=mtlb_imported_model_count();
    for(int i=0;i<count;i++){
        char name[128]={},path[1024]={};
        uint32_t triangles=0,bones=0;float bounds[3]={0,0,0};
        int diffuse=0,normal=0,emissive=0,classification=1;
        if(!mtlb_imported_model_info(i,name,sizeof(name),path,sizeof(path),&triangles,&bones,bounds,
            &diffuse,&normal,&emissive,&classification))continue;
        char card[1024];
        const bool locked=!g_maker_modern;
        std::snprintf(card,sizeof(card),
            "<div id='asset-model-%d' class='asset-card %s' draggable='true' data-action='asset-select' data-asset-id='%d' data-asset-type='3d_model'><div class='asset-thumb model-thumb'>3D</div><div>%s</div><div class='asset-tag tag-3d'>3D</div></div>",
            i,locked?"locked-modern-only":"",i,Rml::StringUtilities::EncodeRml(name).c_str());
        lists[std::max(0,std::min(4,classification))]+=card;
    }
    static const char *ids[]={"asset-list-3d-tiles","asset-list-stage","asset-list-items","asset-list-3d-enemies","asset-list-3d-bosses"};
    for(int i=0;i<5;i++){
        if(Rml::Element *list=g_document->GetElementById(ids[i]))list->SetInnerRML(lists[i]);
    }
}

static void maker_refresh_asset_shelf()
{
    if(!g_document)return;
    const int count=mtlb_editor_tile_count();
    const uint32_t page_key=(uint32_t)(g_asset_shelf_offset+1);
    if(count!=g_asset_shelf_count || g_asset_shelf_hash!=page_key){
        g_asset_shelf_count=count;
        g_asset_shelf_hash=page_key;
        std::string markup;
        const int visible=std::min(20,std::max(0,count-g_asset_shelf_offset));
        for(int i=0;i<visible;i++){
            const int index=g_asset_shelf_offset+i;
            const int entry=mtlb_editor_tile_entry(index,g_maker_palette);
            char card[420];
            std::snprintf(card,sizeof(card),
                "<div id='asset-tile-%d' class='asset-card %s' draggable='true' data-action='asset-select' data-asset-id='%d' data-asset-type='2d_tile'><div class='asset-thumb'></div><div>$%03X</div><div class='asset-tag'>2D</div></div>",
                index,entry==g_brush_tile?"selected":"",index,entry&0x07FF);
            markup+=card;
        }
        if(count==0)markup="<div class='folder-subheading'>Waiting for cartridge VDP tiles and ROM tile banks.</div>";
        if(Rml::Element *shelf=g_document->GetElementById("asset-shelf-items"))shelf->SetInnerRML(markup);
    }
    maker_refresh_sprite_lists();
    maker_refresh_imported_asset_lists();
}

static void set_status(const char *message);

static void append_stage_quad(float x0, float y0, float x1, float y1, SDL_Color color)
{
    const int base = (int)g_stage_vertices.size();
    SDL_Vertex v{};
    v.color = color;
    v.tex_coord = SDL_FPoint{0.0f, 0.0f};
    v.position = SDL_FPoint{x0, y0}; g_stage_vertices.push_back(v);
    v.position = SDL_FPoint{x1, y0}; g_stage_vertices.push_back(v);
    v.position = SDL_FPoint{x1, y1}; g_stage_vertices.push_back(v);
    v.position = SDL_FPoint{x0, y1}; g_stage_vertices.push_back(v);
    g_stage_indices.insert(g_stage_indices.end(), {base, base+1, base+2, base, base+2, base+3});
}

static void draw_stage_grid(SDL_Renderer *renderer)
{
    if (!renderer || !g_stage_grid || g_map_cols <= 0 || g_map_rows <= 0) return;
    const Rml::Vector2f origin = g_stage_grid->GetAbsoluteOffset();
    const float width = g_stage_grid->GetClientWidth();
    const float height = g_stage_grid->GetClientHeight();
    if (width < 2.0f || height < 2.0f) return;

    const bool viewport_changed = origin.x != g_stage_batch_x || origin.y != g_stage_batch_y ||
        width != g_stage_batch_w || height != g_stage_batch_h;
    if (viewport_changed) g_stage_batch_dirty = true;

    if (g_stage_batch_dirty) {
        g_stage_vertices.clear();
        g_stage_indices.clear();
        const size_t quads=(size_t)g_map_cols*(size_t)g_map_rows+(size_t)g_map_cols+(size_t)g_map_rows+2u;
        if(g_stage_vertices.capacity()<quads*4u)g_stage_vertices.reserve(quads*4u);
        if(g_stage_indices.capacity()<quads*6u)g_stage_indices.reserve(quads*6u);

        static const SDL_Color palette[8]={
            {104,145,125,255},{112,151,185,255},{196,132,77,255},{135,119,184,255},
            {167,166,119,255},{77,151,157,255},{181,103,111,255},{103,124,155,255}
        };
        const float cell_w=width/(float)g_map_cols,cell_h=height/(float)g_map_rows;
        for(int y=0;y<g_map_rows;y++)for(int x=0;x<g_map_cols;x++){
            const int tile=mtlb_map_get(x,y);
            if(tile==0)continue;
            const int ci=(tile>=176&&tile<=183)?tile-176:(tile&7);
            append_stage_quad(origin.x+x*cell_w+1.0f,origin.y+y*cell_h+1.0f,
                origin.x+(x+1)*cell_w-1.0f,origin.y+(y+1)*cell_h-1.0f,palette[ci]);
        }
        if(g_maker_show_grid){
            const SDL_Color grid={43,65,83,255};
            for(int x=0;x<=g_map_cols;x++){
                const float px=origin.x+x*cell_w;
                append_stage_quad(px,origin.y,px+1.0f,origin.y+height,grid);
            }
            for(int y=0;y<=g_map_rows;y++){
                const float py=origin.y+y*cell_h;
                append_stage_quad(origin.x,py,origin.x+width,py+1.0f,grid);
            }
        }
        g_stage_batch_x=origin.x;g_stage_batch_y=origin.y;
        g_stage_batch_w=width;g_stage_batch_h=height;
        g_stage_batch_dirty=false;
    }
    if(g_stage_indices.empty())return;
    SDL_Rect clip{(int)std::floor(origin.x),(int)std::floor(origin.y),
        (int)std::ceil(width),(int)std::ceil(height)};
    SDL_SetRenderDrawBlendMode(renderer,SDL_BLENDMODE_NONE);
    SDL_RenderSetClipRect(renderer,&clip);
    SDL_RenderGeometry(renderer,nullptr,g_stage_vertices.data(),(int)g_stage_vertices.size(),
        g_stage_indices.data(),(int)g_stage_indices.size());
    SDL_RenderSetClipRect(renderer,nullptr);
}

static void paint_stage_at(int mouse_x, int mouse_y, int tile)
{
    if (!g_stage_grid || g_map_cols <= 0 || g_map_rows <= 0) return;
    const Rml::Vector2f origin = g_stage_grid->GetAbsoluteOffset();
    const float width = g_stage_grid->GetClientWidth();
    const float height = g_stage_grid->GetClientHeight();
    if (mouse_x < origin.x || mouse_y < origin.y || mouse_x >= origin.x + width ||
        mouse_y >= origin.y + height || width <= 0.0f || height <= 0.0f) {
        g_last_painted_x = g_last_painted_y = -1;
        return;
    }
    const int x = std::min(g_map_cols-1, (int)((mouse_x-origin.x)*g_map_cols/width));
    const int y = std::min(g_map_rows-1, (int)((mouse_y-origin.y)*g_map_rows/height));
    if (x == g_last_painted_x && y == g_last_painted_y && tile == g_drag_tile) return;
    g_last_painted_x = x; g_last_painted_y = y; g_drag_tile = tile;
    mtlb_map_set(x, y, tile);
    g_stage_batch_dirty = true;
    char message[96];
    std::snprintf(message, sizeof(message), "%s cell %d, %d with tile $%04X.",
        tile == 0 ? "Erased" : "Painted", x, y, tile);
    set_status(message);
}


static void maker_save_settings()
{
    const std::string root = maker_portable_root();
    const std::string path = (root == "." || root.back() == '/' || root.back() == '\\')
        ? root + "maker-settings.ini" : root + "/maker-settings.ini";
    FILE *file = std::fopen(path.c_str(), "wb");
    if (!file) {
        maker_log("Could not save editor settings to %s.", path.c_str());
        return;
    }
    std::fprintf(file,
        "mode=%d\ntool=%d\nlayer=%d\npalette=%d\ncanvas=%d\nmodern=%d\ngrid=%d\nsnap=%d\ncollision=%d\n",
        g_maker_mode,g_maker_tool,g_maker_layer,g_maker_palette,g_maker_canvas_size,
        g_maker_modern?1:0,g_maker_show_grid?1:0,g_maker_snap?1:0,g_maker_collision?1:0);
    for (int i=0;i<5;i++) std::fprintf(file,"layer%d=%d\n",i,g_maker_layers[i]?1:0);
    std::fclose(file);
    maker_log("Saved portable Maker settings to %s.",path.c_str());
}

static void maker_load_settings()
{
    const std::string root = maker_portable_root();
    const std::string path = (root == "." || root.back() == '/' || root.back() == '\\')
        ? root + "maker-settings.ini" : root + "/maker-settings.ini";
    FILE *file=std::fopen(path.c_str(),"rb");
    if(!file) return;
    char line[128];
    while(std::fgets(line,sizeof(line),file)){
        int value=0;
        if(std::sscanf(line,"mode=%d",&value)==1) g_maker_mode=std::max(0,std::min(MAKER_MODE_COUNT-1,value));
        else if(std::sscanf(line,"tool=%d",&value)==1) g_maker_tool=std::max(0,std::min(8,value));
        else if(std::sscanf(line,"layer=%d",&value)==1) g_maker_layer=std::max(0,std::min(4,value));
        else if(std::sscanf(line,"palette=%d",&value)==1) g_maker_palette=std::max(0,std::min(3,value));
        else if(std::sscanf(line,"canvas=%d",&value)==1) g_maker_canvas_size=(value==32)?32:16;
        else if(std::sscanf(line,"modern=%d",&value)==1) g_maker_modern=value!=0;
        else if(std::sscanf(line,"grid=%d",&value)==1) g_maker_show_grid=value!=0;
        else if(std::sscanf(line,"snap=%d",&value)==1) g_maker_snap=value!=0;
        else if(std::sscanf(line,"collision=%d",&value)==1) g_maker_collision=value!=0;
        else for(int i=0;i<5;i++){
            char key[16];std::snprintf(key,sizeof(key),"layer%d=%%d",i);
            if(std::sscanf(line,key,&value)==1) g_maker_layers[i]=value!=0;
        }
    }
    std::fclose(file);
    maker_log("Loaded portable Maker settings from %s.",path.c_str());
}

static const char *maker_mode_name(int mode)
{
    static const char *names[MAKER_MODE_COUNT]={"TILES","OBJECTS","EVENT SCRIPT","ASSET STUDIO","BOSS FORGE","BACKGROUNDS"};
    return names[std::max(0,std::min(MAKER_MODE_COUNT-1,mode))];
}

static const char *maker_tool_list(int mode)
{
    switch(mode){
    case MAKER_OBJECTS:
        return "<div class='tool-button active' data-action='tool' data-tool='0'>SELECT OBJECT</div>"
               "<div class='tool-button' data-action='tool' data-tool='1'>PLACE ENEMY</div>"
               "<div class='tool-button' data-action='tool' data-tool='2'>PLACE PICKUP</div>"
               "<div class='tool-button' data-action='tool' data-tool='3'>PLAYER START</div>"
               "<div class='tool-button' data-action='tool' data-tool='4'>PATROL PATH</div>"
               "<div class='tool-button' data-action='tool' data-tool='7'>DELETE OBJECT</div>";
    case MAKER_EVENTS:
        return "<div class='tool-button active' data-action='tool' data-tool='0'>SELECT NODE</div>"
               "<div class='tool-button' data-action='tool' data-tool='1'>WHEN / TRIGGER</div>"
               "<div class='tool-button' data-action='tool' data-tool='2'>IF / CONDITION</div>"
               "<div class='tool-button' data-action='tool' data-tool='3'>ACTION BLOCK</div>"
               "<div class='tool-button' data-action='tool' data-tool='4'>DIALOGUE</div>"
               "<div class='tool-button' data-action='tool' data-tool='5'>CONNECT WIRE</div>";
    case MAKER_ASSETS:
        return "<div class='tool-button active' data-action='tool' data-tool='0'>PENCIL</div>"
               "<div class='tool-button' data-action='tool' data-tool='7'>ERASER</div>"
               "<div class='tool-button' data-action='tool' data-tool='2'>FILL</div>"
               "<div class='tool-button' data-action='tool' data-tool='3'>EYEDROPPER</div>"
               "<div class='tool-button' data-action='tool' data-tool='8'>SELECTION</div>";
    case MAKER_BOSS:
        return "<div class='tool-button active' data-action='tool' data-tool='0'>ADD BODY PART</div>"
               "<div class='tool-button' data-action='tool' data-tool='1'>MOVE PIVOT</div>"
               "<div class='tool-button' data-action='tool' data-tool='2'>WEAKPOINT</div>"
               "<div class='tool-button' data-action='tool' data-tool='3'>ATTACK PATTERN</div>"
               "<div class='tool-button' data-action='tool' data-tool='4'>PHASE TRANSITION</div>"
               "<div class='tool-button' data-action='tool' data-tool='5'>ANIMATION TRACK</div>";
    case MAKER_BACKGROUNDS:
        return "<div class='tool-button active' data-action='tool' data-tool='0'>SELECT LAYER</div>"
               "<div class='tool-button' data-action='tool' data-tool='1'>ADD PARALLAX LAYER</div>"
               "<div class='tool-button' data-action='tool' data-tool='2'>RASTER WAVE</div>"
               "<div class='tool-button' data-action='tool' data-tool='3'>ANIMATED TILES</div>";
    default:
        return "<div class='tool-button active' data-action='tool' data-tool='0'>SELECT</div>"
               "<div class='tool-button' data-action='tool' data-tool='1'>TILE BRUSH</div>"
               "<div class='tool-button' data-action='tool' data-tool='7'>ERASER</div>"
               "<div class='tool-button' data-action='tool' data-tool='2'>COLLISION PAINTER</div>"
               "<div class='tool-button' data-action='tool' data-tool='3'>GRAPPLE ANCHOR</div>"
               "<div class='tool-button' data-action='tool' data-tool='4'>TRIGGER BOX</div>";
    }
}

static void maker_update_mode_ui()
{
    if(!g_document)return;
    for(int i=0;i<5;i++){
        char id[32];std::snprintf(id,sizeof(id),"mode-%d",i);
        if(Rml::Element *tab=g_document->GetElementById(id))tab->SetClass("active",i==g_maker_mode);
    }
    static const char *tool_names[]={"select","brush","fill","slope","rope","trigger","light","erase"};
    const int tool_index=std::max(0,std::min(7,g_maker_tool));
    g_selected_tool=tool_names[tool_index];
    for(int i=0;i<8;i++){
        char id[32];std::snprintf(id,sizeof(id),"tool-%d",i);
        if(Rml::Element *tool=g_document->GetElementById(id))tool->SetClass("active",i==tool_index);
    }

    static const char *tab_names[]={"tiles","entity","script","assets","boss","assets"};
    g_active_tab=tab_names[std::max(0,std::min(MAKER_MODE_COUNT-1,g_maker_mode))];
    g_global_mode=g_maker_modern?"MODERN REBORN":"VANILLA 1994";
    if(Rml::Element *label=g_document->GetElementById("global-mode-label"))
        label->SetInnerRML(g_global_mode);
    if(Rml::Element *button=g_document->GetElementById("global-mode-button"))
        button->SetClass("active",g_maker_modern);
    if(Rml::Element *resolution=g_document->GetElementById("stage-resolution"))
        resolution->SetInnerRML(g_maker_modern?"MODERN 16:9 / 2.5D":"VANILLA 320 × 224 / 16-BIT");
    if(Rml::Element *stage=g_document->GetElementById("stage-viewport")){
        if(g_maker_modern){
            stage->SetProperty("width","100%");
            stage->SetProperty("height","100%");
            stage->SetProperty("flex-grow","1");
            stage->SetProperty("align-self","stretch");
        }else{
            stage->SetProperty("width","320px");
            stage->SetProperty("height","224px");
            stage->SetProperty("flex-grow","0");
            stage->SetProperty("align-self","center");
        }
    }
    if(Rml::Element *locked=g_document->GetElementById("vanilla-lock-note"))
        locked->SetClass("hidden",g_maker_modern);

    static const char *hints[MAKER_MODE_COUNT]={
        "ROM TILES / Drag a tile card onto the stage, or use BRUSH to paint. Right-click erases.",
        "ENTITY PLACEMENT / Drag a 2D sprite or 3D model onto the stage. Snap and collision are in Properties.",
        "EVENT SCRIPT / Add trigger, condition, action and dialogue nodes to the bottom flow strip.",
        "ASSET STUDIO / Import GLB, GLTF, OBJ, FBX models and PNG/TGA textures into the portable project.",
        "BOSS FORGE / Drag a multipart sprite or articulated 3D model, then configure phases and weakpoints.",
        "BACKGROUND / Select a depth layer and configure parallax, raster and background props."
    };
    if(Rml::Element *hint=g_document->GetElementById("stage-hint"))
        hint->SetInnerRML(hints[std::max(0,std::min(MAKER_MODE_COUNT-1,g_maker_mode))]);

    if(g_model_handle){
        g_model_handle.DirtyVariable("global_mode");
        g_model_handle.DirtyVariable("selected_tool");
        g_model_handle.DirtyVariable("active_tab");
        g_model_handle.DirtyVariable("selected_entity");
    }
    g_stage_batch_dirty=true;
}

static void maker_refresh_asset_shelf()
{
    if(!g_document) return;
    const int count=mtlb_editor_tile_count();
    if(count!=g_asset_shelf_count || g_asset_shelf_hash!=(uint32_t)(g_asset_shelf_offset+1)){
        g_asset_shelf_count=count;
        g_asset_shelf_hash=(uint32_t)(g_asset_shelf_offset+1);
        std::string markup;
        const int visible=std::min(20,std::max(0,count-g_asset_shelf_offset));
        for(int i=0;i<visible;i++){
            const int index=g_asset_shelf_offset+i;
            const int entry=mtlb_editor_tile_entry(index,g_maker_palette);
            char button[220];
            std::snprintf(button,sizeof(button),"<div id='asset-tile-%d' class='asset-tile %s' data-action='asset-brush' data-index='%d'><div class='asset-thumb'></div>$%03X</div>",index,entry==g_brush_tile?"active":"",index,entry&0x07FF);
            markup+=button;
        }
        if(count==0) markup="<div class='inspector-copy'>Waiting for cartridge VRAM and ROM assets. Start the game and open Maker after the title screen.</div>";
        if(Rml::Element *shelf=g_document->GetElementById("asset-shelf-items")) shelf->SetInnerRML(markup);
        if(Rml::Element *label=g_document->GetElementById("asset-count")){
            char summary[96];std::snprintf(summary,sizeof(summary),"%d TILES / %d VISIBLE / PAGE %d",count,visible,g_asset_shelf_offset/20+1);
            label->SetInnerRML(summary);
        }
    }
}

static void set_status(const char *message)
{
    if (g_status) g_status->SetInnerRML(message ? message : "");
}

static Rml::Element *find_action_element(Rml::Element *element)
{
    while (element) {
        if (element->HasAttribute("data-action")) return element;
        element = element->GetParentNode();
    }
    return nullptr;
}


static void select_brush(int tile)
{
    g_brush_tile = std::max(1, std::min(2047, tile));
    mtlb_map_set_brush(g_brush_tile);
    for (int i = 176; i <= 180; ++i) {
        char id[32];
        std::snprintf(id, sizeof(id), "brush-%d", i);
        Rml::Element *button = g_document ? g_document->GetElementById(id) : nullptr;
        if (button) button->SetClass("active", i == g_brush_tile);
    }
    char label[32];
    std::snprintf(label, sizeof(label), "$%04X", g_brush_tile);
    Rml::Element *value = g_document ? g_document->GetElementById("brush-value") : nullptr;
    if (value) value->SetInnerRML(label);
    std::snprintf(label, sizeof(label), "Brush set to tile $%04X.", g_brush_tile);
    set_status(label);
}

class MakerEventListener final : public Rml::EventListener {
public:
    void ProcessEvent(Rml::Event &event) override
    {
        Rml::Element *element = find_action_element(event.GetTargetElement());
        if (!element) return;

        const Rml::String action = element->GetAttribute<Rml::String>("data-action", "");

        if (action == "mode") {
            g_maker_mode = std::max(0,std::min(4,element->GetAttribute<int>("data-mode",0)));
            g_maker_tool = 0;
            maker_update_mode_ui();
            maker_save_settings();
            set_status((std::string("Switched to ")+maker_mode_name(g_maker_mode)+".").c_str());
            return;
        }
        if (action == "global-mode") {
            const Rml::String requested=element->GetAttribute<Rml::String>("data-mode","");
            if(requested=="modern")g_maker_modern=true;
            else if(requested=="vanilla")g_maker_modern=false;
            else g_maker_modern=!g_maker_modern;
            maker_update_mode_ui();
            maker_refresh_asset_shelf();
            maker_save_settings();
            set_status(g_maker_modern?
                "MODERN REBORN: widescreen, 3D models and dynamic lighting unlocked.":
                "VANILLA 1994: 320 x 224, 2D CRAM palette and hardware limits enforced.");
            return;
        }
        if (action == "asset-filter") {
            const Rml::String filter=element->GetAttribute<Rml::String>("data-filter","all");
            g_asset_filter=(filter=="2d")?1:((filter=="3d")?2:0);
            static const char *buttons[]={"filter-all","filter-2d","filter-3d"};
            for(int i=0;i<3;i++)if(Rml::Element *b=g_document->GetElementById(buttons[i]))b->SetClass("active",i==g_asset_filter);
            const char *groups[]={"asset-shelf-items","asset-list-enemies","asset-list-bosses"};
            const char *models[]={"asset-list-3d-tiles","asset-list-stage","asset-list-items","asset-list-3d-enemies","asset-list-3d-bosses"};
            for(const char *id:groups)if(Rml::Element *el=g_document->GetElementById(id))el->SetClass("hidden",g_asset_filter==2);
            for(const char *id:models)if(Rml::Element *el=g_document->GetElementById(id))el->SetClass("hidden",g_asset_filter==1);
            return;
        }
        if (action == "folder-toggle") {
            const Rml::String folder_name=element->GetAttribute<Rml::String>("data-folder","");
            Rml::Element *folder=find_action_element(element);
            if(folder)folder=folder->GetParentNode();
            if(folder)folder->SetClass("collapsed",!folder->IsClassSet("collapsed"));
            return;
        }
        if (action == "asset-select") {
            g_selected_asset_id=element->GetAttribute<int>("data-asset-id",-1);
            g_selected_asset_type=element->GetAttribute<Rml::String>("data-asset-type","");
            if(Rml::Element *label=g_document->GetElementById("selected-asset-name"))
                label->SetInnerRML(Rml::StringUtilities::EncodeRml(g_selected_asset_type+" / "+std::to_string(g_selected_asset_id)));
            if(g_selected_asset_type=="2d_tile"){
                const int tile=mtlb_editor_tile_entry(g_selected_asset_id,g_maker_palette);
                if(tile){select_brush(tile);g_maker_mode=MAKER_TILES;g_maker_tool=1;}
            }else if(g_selected_asset_type=="enemy"||g_selected_asset_type=="boss"){
                g_selected_rom_sprite=g_selected_asset_id;
                g_maker_mode=(g_selected_asset_type=="boss")?MAKER_BOSS:MAKER_OBJECTS;
                g_maker_tool=1;
            }else if(g_selected_asset_type=="3d_model"){
                if(!g_maker_modern){
                    set_status("Modern Mode Required: this 3D model is locked by the Vanilla 1994 quality gate.");
                    return;
                }
                g_selected_model_asset=g_selected_asset_id;
                maker_update_imported_model_panel(g_selected_model_asset);
            }
            maker_update_mode_ui();
            return;
        }
        if (action == "import-model") {
            if(!g_maker_modern){
                set_status("Switch to MODERN REBORN before importing 3D models.");
                return;
            }
            maker_open_model_importer();
            return;
        }
        if (action == "import-texture") {
            maker_open_texture_importer();
            return;
        }
        if (action == "classify" || action == "import-confirm") {
            if(g_pending_model_asset>=0){
                const int classification=element->HasAttribute("data-class")?
                    element->GetAttribute<int>("data-class",1):
                    element->GetAttribute<int>("value",1);
                mtlb_imported_model_classify(g_pending_model_asset,classification);
                g_selected_model_asset=g_pending_model_asset;
                g_pending_model_asset=-1;
                maker_update_imported_asset_lists();
                maker_update_imported_model_panel(g_selected_model_asset);
                maker_set_modal("model-import-modal",false);
                set_status("3D model inspected, classified and registered in the portable Assets/Imported folder.");
            }
            return;
        }
        if (action == "import-cancel") {
            g_pending_model_asset=-1;
            maker_set_modal("model-import-modal",false);
            set_status("Import classification closed. The model remains in the imported library.");
            return;
        }
        if (action == "model-classification") {
            if(g_selected_model_asset>=0){
                const int classification=event.GetParameter<int>("value",element->GetAttribute<int>("value",1));
                mtlb_imported_model_classify(g_selected_model_asset,classification);
                maker_refresh_imported_asset_lists();
            }
            return;
        }
        if (action == "property") {
            const Rml::String property=element->GetAttribute<Rml::String>("data-property","");
            const Rml::String value=event.GetParameter<Rml::String>("value",element->GetAttribute<Rml::String>("value",""));
            if(property=="light-type"){
                g_light_type=(value=="SPOTLIGHT")?1:((value=="AMBIENT TINT")?2:0);
            }else if(property=="light-color"){
                unsigned int rgb=0xE619E6u;
                if(value.size()==7&&value[0]=='#')std::sscanf(value.c_str()+1,"%x",&rgb);
                g_light_color=0xFF000000u|(rgb&0xFFFFFFu);
            }else if(property=="light-radius"){
                g_light_radius=(float)event.GetParameter<double>("value",g_light_radius);
            }else if(property=="light-intensity"){
                g_light_intensity=(float)event.GetParameter<double>("value",g_light_intensity)/100.0f;
            }else if(property=="bloom")g_fx_bloom=event.GetParameter<bool>("checked",false);
            else if(property=="rim")g_fx_rim=event.GetParameter<bool>("checked",false);
            else if(property=="cel")g_fx_cel=event.GetParameter<bool>("checked",false);
            else if(property=="fog")g_fx_fog=event.GetParameter<bool>("checked",false);
            else if(property=="crt")g_fx_crt=event.GetParameter<bool>("checked",false);
            maker_save_settings();
            return;
        }
        if (action == "playtest") {
            set_status("Playtest is not connected to the native player-spawn handoff yet; level editing remains active.");
            return;
        }

        if (action == "tool") {
            g_maker_tool = std::max(0,std::min(7,element->GetAttribute<int>("data-tool",0)));
            if(g_maker_mode==MAKER_TILES && g_maker_tool==1) select_brush(g_brush_tile);
            maker_update_mode_ui();
            maker_save_settings();
            set_status("Tool selected.");
            return;
        }
        if (action == "layer") {
            const int layer=std::max(0,std::min(4,element->GetAttribute<int>("data-layer",0)));
            g_maker_layers[layer]=!g_maker_layers[layer];
            g_maker_layer=layer;
            char id[32];std::snprintf(id,sizeof(id),"layer-%d",layer);
            if(Rml::Element *chip=g_document->GetElementById(id)) chip->SetClass("active",g_maker_layers[layer]);
            maker_save_settings();
            set_status("Stage layer visibility updated.");
            return;
        }
        if (action == "toggle") {
            const Rml::String key=element->GetAttribute<Rml::String>("data-key","");
            bool *target=nullptr;
            if(key=="grid")target=&g_maker_show_grid;
            else if(key=="snap")target=&g_maker_snap;
            else if(key=="collision")target=&g_maker_collision;
            if(target){
                *target=!*target;
                element->SetClass("active",*target);
                element->SetInnerRML(*target?"ON":"OFF");
                if(key=="grid") g_stage_batch_dirty=true;
                maker_save_settings();
                set_status((key+" option updated.").c_str());
            }
            return;
        }
        if (action == "palette") {
            g_maker_palette=std::max(0,std::min(3,element->GetAttribute<int>("data-palette",0)));
            g_asset_shelf_hash=0;
            maker_refresh_asset_shelf();
            maker_update_mode_ui();
            maker_save_settings();
            set_status("Genesis palette selection updated.");
            return;
        }
        if (action == "asset-brush") {
            const int index=element->GetAttribute<int>("data-index",0);
            const int tile=mtlb_editor_tile_entry(index,g_maker_palette);
            if(tile){select_brush(tile);g_maker_tool=1;maker_update_mode_ui();}
            return;
        }
        if (action == "asset-page") {
            const int dir=element->GetAttribute<int>("data-dir",1);
            g_asset_shelf_offset=std::max(0,std::min(std::max(0,mtlb_editor_tile_count()-20),g_asset_shelf_offset+dir*20));
            g_asset_shelf_hash=0;
            maker_refresh_asset_shelf();
            return;
        }
        if (action == "canvas-size") {
            const int size=element->GetAttribute<int>("data-size",16);
            g_maker_canvas_size=(size==32)?32:16;
            maker_update_mode_ui();
            maker_save_settings();
            set_status("Pixel canvas size updated.");
            return;
        }
        if (action == "graphics") {
            const Rml::String value=element->GetAttribute<Rml::String>("data-value","vanilla");
            g_maker_modern=(value=="modern");
            maker_update_mode_ui();
            maker_save_settings();
            set_status(g_maker_modern?"Modern RGBA graphics mode selected.":"Genesis-compatible 64-color mode selected.");
            return;
        }
        if (action == "settings") {
            g_settings_open=true;
            if(Rml::Element *modal=g_document->GetElementById("settings-modal")) modal->SetClass("hidden",false);
            return;
        }
        if (action == "settings-close") {
            g_settings_open=false;
            if(Rml::Element *modal=g_document->GetElementById("settings-modal")) modal->SetClass("hidden",true);
            return;
        }
        if (action == "settings-save") {
            maker_save_settings();
            g_settings_open=false;
            if(Rml::Element *modal=g_document->GetElementById("settings-modal")) modal->SetClass("hidden",true);
            set_status("Project options saved beside the portable launcher.");
            return;
        }
        if (action == "library") {
            const Rml::String name=element->GetAttribute<Rml::String>("data-library","ROM TILES");
            set_status((std::string("Library filter: ")+name+".").c_str());
            return;
        }
        if (action == "event-add") {
            ++g_event_node_count;
            g_event_selected=g_event_node_count-1;
            set_status("Event node added to the current script workspace.");
            maker_update_mode_ui();
            return;
        }
        if (action == "boss-create") {
            g_boss_created=true;maker_update_mode_ui();set_status("Boss core created.");return;
        }
        if (action == "boss-hp") {
            g_boss_hp=std::max(1,std::min(999,g_boss_hp+element->GetAttribute<int>("data-delta",0)));
            maker_update_mode_ui();return;
        }
        if (action == "boss-phase") {
            g_boss_phase=std::max(1,std::min(3,element->GetAttribute<int>("data-phase",1)));
            maker_update_mode_ui();return;
        }
        if (action == "parallax") {
            const int layer=std::max(0,std::min(3,element->GetAttribute<int>("data-layer",0)));
            const float delta=(float)element->GetAttribute<double>("data-delta",0.1);
            const Rml::String axis=element->GetAttribute<Rml::String>("data-axis","x");
            float &value=(axis=="y")?g_parallax_y[layer]:g_parallax_x[layer];
            value=std::max(0.0f,std::min(4.0f,value+delta));
            maker_update_mode_ui();maker_save_settings();return;
        }
        if (action == "exit") {
            g_exit_requested = true;
            return;
        }
        if (action == "save") {
            set_status(mtlb_map_save() ? "Level saved to the Maker levels folder." : "Could not save the level document.");
            return;
        }
        if (action == "load") {
            if (mtlb_map_load()) {
                g_stage_batch_dirty = true;
                set_status("Level document loaded.");
            } else {
                set_status("No saved level document was found.");
            }
            return;
        }
        if (action == "section") {
            const Rml::String section = element->GetAttribute<Rml::String>("data-section", "TILES");
            static const char *ids[] = {"nav-tiles","nav-actors","nav-objects","nav-bosses","nav-events","nav-backgrounds"};
            static const char *names[] = {"TILES","ACTORS","OBJECTS","BOSSES","EVENTS","BACKGROUNDS"};
            int selected = 0;
            for (int i = 0; i < 6; ++i) {
                Rml::Element *nav = g_document ? g_document->GetElementById(ids[i]) : nullptr;
                if (nav) nav->SetClass("active", section == names[i]);
                if (section == names[i]) selected = i;
            }
            Rml::Element *value = g_document ? g_document->GetElementById("section-value") : nullptr;
            if (value) value->SetInnerRML(section);
            if (selected == 0) set_status("Tile palette selected.");
            else set_status("Category selected. Its full asset browser will be migrated from the existing Maker catalog next.");
            return;
        }
        if (action == "brush") {
            const Rml::String raw = element->GetAttribute<Rml::String>("data-brush", "1");
            select_brush(std::atoi(raw.c_str()));
            return;
        }
    }
};
static MakerEventListener g_listener;
} // namespace

extern "C" int mtlbr_init(SDL_Window *window, SDL_Renderer *renderer)
{
    maker_prepare_log();
    maker_log("============================================================");
    maker_log("RmlUi Maker initialization starting.");
    std::snprintf(g_last_error, sizeof(g_last_error), "%s", "RmlUi initialization in progress.");

    if (g_context) {
        maker_log("RmlUi context already exists; reusing it.");
        return 1;
    }
    if (!window || !renderer)
        return maker_fail("SDL window or renderer pointer is null.");

    g_window = window;
    g_renderer = renderer;
    g_map_cols = mtlb_map_cols();
    g_map_rows = mtlb_map_rows();
    mtlb_editor_prepare_rom_assets();
    maker_load_settings();
    g_global_mode = g_maker_modern ? "MODERN REBORN" : "VANILLA 1994";
    maker_log("Map dimensions: %d x %d.", g_map_cols, g_map_rows);
    if (g_map_cols <= 0 || g_map_rows <= 0)
        return maker_fail("The shared Maker map model returned invalid dimensions.");

    g_system = new MakerSystemInterface(window);
    g_render = new RenderInterface_SDL(renderer);
    Rml::SetSystemInterface(g_system);
    Rml::SetRenderInterface(g_render);
    maker_log("RmlUi interfaces registered. Calling Rml::Initialise().");
    if (!Rml::Initialise()) {
        maker_log("Rml::Initialise() returned false.");
        Rml::SetRenderInterface(nullptr);
        Rml::SetSystemInterface(nullptr);
        delete g_render; g_render = nullptr;
        delete g_system; g_system = nullptr;
        g_window = nullptr; g_renderer = nullptr;
        return maker_fail("Rml::Initialise() returned false. Check maker-rmlui.log for the library's error message.");
    }
    g_rml_initialised = true;
    const Rml::String version = Rml::GetVersion();
    maker_log("Rml::Initialise() succeeded. RmlUi version: %s.", version.c_str());

    const std::string portable_root = maker_portable_root();
    const std::string font_prefix =
        (portable_root == "." || portable_root.back() == '/' || portable_root.back() == '\\')
            ? portable_root
            : portable_root + "/";
    const std::string font_regular = font_prefix + "assets/fonts/LatoLatin-Regular.ttf";
    const std::string font_bold = font_prefix + "assets/fonts/LatoLatin-Bold.ttf";
    maker_log("Portable root: %s.", portable_root.c_str());
    maker_log("Diagnostic log path: %s.", g_log_path.c_str());
    maker_log("Loading regular font: %s.", font_regular.c_str());
    const bool regular_loaded = Rml::LoadFontFace(font_regular, true);
    maker_log("Regular font result: %d.", regular_loaded ? 1 : 0);
    maker_log("Loading bold font: %s.", font_bold.c_str());
    const bool bold_loaded = Rml::LoadFontFace(font_bold, "Lato", Rml::Style::FontStyle::Normal, Rml::Style::FontWeight::Bold, false);
    maker_log("Bold font result: %d.", bold_loaded ? 1 : 0);
    if (!regular_loaded || !bold_loaded) {
        mtlbr_shutdown();
        return maker_fail("RmlUi could not load the bundled Lato fonts. See maker-rmlui.log.");
    }

    int width = 0, height = 0;
    SDL_GetWindowSize(window, &width, &height);
    maker_log("Creating RmlUi context at %d x %d.", width, height);
    g_context = Rml::CreateContext("MegaTurricanMaker", Rml::Vector2i(width, height), g_render);
    if (!g_context) {
        mtlbr_shutdown();
        return maker_fail("Rml::CreateContext failed. See maker-rmlui.log.");
    }
    maker_log("RmlUi context created.");

    Rml::DataModelConstructor data_model = g_context->CreateDataModel("editor");
    if (!data_model ||
        !data_model.Bind("global_mode", &g_global_mode) ||
        !data_model.Bind("selected_tool", &g_selected_tool) ||
        !data_model.Bind("active_tab", &g_active_tab) ||
        !data_model.Bind("cursor_x", &g_cursor_x) ||
        !data_model.Bind("cursor_y", &g_cursor_y) ||
        !data_model.Bind("selected_entity", &g_ui_selected_entity)) {
        mtlbr_shutdown();
        return maker_fail("Could not create the RmlUi editor data model.");
    }
    g_model_handle = data_model.GetModelHandle();
    maker_log("RmlUi editor data model bound: global_mode, selected_tool, active_tab, cursor_x, cursor_y, selected_entity.");

    const std::string document_path = font_prefix + "assets/maker/editor.rml";
    maker_log("Loading external Maker document: %s.", document_path.c_str());
    g_document = g_context->LoadDocument(document_path);
    if (!g_document) {
        mtlbr_shutdown();
        return maker_fail("RmlUi failed to load assets/maker/editor.rml or its RCSS stylesheet. See maker-rmlui.log.");
    }
    maker_log("External Maker RML document and RCSS loaded.");
    g_viewport = g_document->GetElementById("viewport");
    g_stage_grid = g_document->GetElementById("stage-grid");
    g_status = g_document->GetElementById("status-text");
    maker_log("Document elements: viewport=%d grid=%d status=%d.",
        g_viewport ? 1 : 0, g_stage_grid ? 1 : 0, g_status ? 1 : 0);
    if (!g_viewport || !g_stage_grid || !g_status) {
        mtlbr_shutdown();
        return maker_fail("The embedded Maker document is missing required UI elements. See maker-rmlui.log.");
    }

    maker_log("Using batched SDL stage-grid rendering for %d x %d cells.", g_map_cols, g_map_rows);
    g_stage_vertices.reserve((size_t)g_map_cols * (size_t)g_map_rows * 4u);
    g_stage_indices.reserve((size_t)g_map_cols * (size_t)g_map_rows * 6u);
    g_document->AddEventListener("click", &g_listener);
    g_document->AddEventListener("change", &g_listener);
    g_document->AddEventListener("input", &g_listener);
    g_document->Show();
    g_exit_requested = false;
    g_brush_tile = mtlb_map_brush();
    if (g_brush_tile < 176 || g_brush_tile > 180) g_brush_tile = 176;
    select_brush(g_brush_tile);
    maker_update_mode_ui();
    maker_refresh_asset_shelf();
    g_model_handle.DirtyAllVariables();
    set_status("RmlUi Maker ready. Cartridge asset catalog connected; project options restored.");
    std::snprintf(g_last_error, sizeof(g_last_error), "%s", "");
    maker_log("RmlUi Maker initialized successfully.");
    return 1;
}

extern "C" const char *mtlbr_last_error(void)
{
    return g_last_error;
}

extern "C" void mtlbr_shutdown(void)
{
    if (g_document) {
        g_document->RemoveEventListener("click", &g_listener);
        g_document = nullptr;
    }
    g_viewport = nullptr;
    g_stage_grid = nullptr;
    g_status = nullptr;
    g_context = nullptr;
    if (g_rml_initialised) {
        Rml::RemoveContext("MegaTurricanMaker");
        Rml::Shutdown();
        g_rml_initialised = false;
    }
    Rml::SetRenderInterface(nullptr);
    Rml::SetSystemInterface(nullptr);
    delete g_render; g_render = nullptr;
    delete g_system; g_system = nullptr;
    g_window = nullptr;
    g_renderer = nullptr;
    g_exit_requested = false;
}

extern "C" void mtlbr_process_event(const SDL_Event *event)
{
    if (!g_context || !g_window || !event) return;
    if (event->type == SDL_KEYDOWN && event->key.keysym.sym == SDLK_ESCAPE)
        g_exit_requested = true;

    if (event->type == SDL_MOUSEBUTTONDOWN) {
        const int tile = event->button.button == SDL_BUTTON_RIGHT ? 0 :
            (event->button.button == SDL_BUTTON_LEFT ? g_brush_tile : -1);
        if (tile >= 0) paint_stage_at(event->button.x, event->button.y, tile);
    } else if (event->type == SDL_MOUSEMOTION) {
        if (event->motion.state & SDL_BUTTON_LMASK)
            paint_stage_at(event->motion.x, event->motion.y, g_brush_tile);
        else if (event->motion.state & SDL_BUTTON_RMASK)
            paint_stage_at(event->motion.x, event->motion.y, 0);
        else
            g_last_painted_x = g_last_painted_y = -1;
    } else if (event->type == SDL_MOUSEBUTTONUP) {
        g_last_painted_x = g_last_painted_y = -1;
        g_drag_tile = -1;
    }

    SDL_Event copy = *event;
    RmlSDL::InputEventHandler(g_context, g_window, copy);
}

extern "C" int mtlbr_is_active(void)
{
    return g_context != nullptr;
}

static void draw_asset_shelf_previews(SDL_Renderer *renderer)
{
    if (!renderer || !g_document) return;
    static std::vector<SDL_Vertex> vertices;
    static std::vector<int> indices;
    vertices.clear();
    indices.clear();

    const int total=mtlb_editor_tile_count();
    const int visible=std::min(20,std::max(0,total-g_asset_shelf_offset));
    for(int n=0;n<visible;n++){
        const int index=g_asset_shelf_offset+n;
        char id[40];
        std::snprintf(id,sizeof(id),"asset-tile-%d",index);
        Rml::Element *button=g_document->GetElementById(id);
        if(!button || button->GetNumChildren()==0) continue;
        Rml::Element *thumb=button->GetChild(0);
        if(!thumb) continue;
        const Rml::Vector2f origin=thumb->GetAbsoluteOffset();
        const float width=thumb->GetClientWidth();
        const float height=thumb->GetClientHeight();
        if(width<4.0f || height<4.0f) continue;

        const int entry=mtlb_editor_tile_entry(index,g_maker_palette);
        const float pixel_w=width/8.0f;
        const float pixel_h=height/8.0f;
        for(int py=0;py<8;py++) for(int px=0;px<8;px++){
            uint8_t rgba[4];
            mtlb_editor_tile_rgba(entry,px,py,rgba);
            if(rgba[3]==0) continue;
            const int base=(int)vertices.size();
            const SDL_Color color={rgba[0],rgba[1],rgba[2],rgba[3]};
            SDL_Vertex v{};
            v.color=color;
            v.tex_coord=SDL_FPoint{0.0f,0.0f};
            v.position=SDL_FPoint{origin.x+px*pixel_w,origin.y+py*pixel_h};vertices.push_back(v);
            v.position=SDL_FPoint{origin.x+(px+1)*pixel_w,origin.y+py*pixel_h};vertices.push_back(v);
            v.position=SDL_FPoint{origin.x+(px+1)*pixel_w,origin.y+(py+1)*pixel_h};vertices.push_back(v);
            v.position=SDL_FPoint{origin.x+px*pixel_w,origin.y+(py+1)*pixel_h};vertices.push_back(v);
            indices.insert(indices.end(),{base,base+1,base+2,base,base+2,base+3});
        }
    }
    if(indices.empty()) return;
    SDL_SetRenderDrawBlendMode(renderer,SDL_BLENDMODE_BLEND);
    SDL_RenderGeometry(renderer,nullptr,vertices.data(),(int)vertices.size(),indices.data(),(int)indices.size());
    SDL_SetRenderDrawBlendMode(renderer,SDL_BLENDMODE_NONE);
}

extern "C" int mtlbr_render_to_screen(SDL_Renderer *renderer, int view_x, int view_y, int view_width, int view_height)
{
    if (!g_context || !g_document || !renderer || renderer != g_renderer || view_width <= 0 || view_height <= 0)
        return 0;

    int window_width = 0, window_height = 0;
    SDL_GetWindowSize(g_window, &window_width, &window_height);
    if (window_width <= 0 || window_height <= 0) return 0;

    if (window_width != g_cached_window_width || window_height != g_cached_window_height) {
        g_context->SetDimensions(Rml::Vector2i(window_width, window_height));
        g_cached_window_width = window_width;
        g_cached_window_height = window_height;
        g_cached_view_x = g_cached_view_y = -1;
        g_cached_view_width = g_cached_view_height = -1;
    }
    if (g_viewport && (view_x != g_cached_view_x || view_y != g_cached_view_y ||
        view_width != g_cached_view_width || view_height != g_cached_view_height)) {
        char value[48];
        std::snprintf(value, sizeof(value), "%dpx", view_x); g_viewport->SetProperty("left", value);
        std::snprintf(value, sizeof(value), "%dpx", view_y); g_viewport->SetProperty("top", value);
        std::snprintf(value, sizeof(value), "%dpx", view_width); g_viewport->SetProperty("width", value);
        std::snprintf(value, sizeof(value), "%dpx", view_height); g_viewport->SetProperty("height", value);
        g_cached_view_x = view_x; g_cached_view_y = view_y;
        g_cached_view_width = view_width; g_cached_view_height = view_height;
    }

    const Uint64 update_start = SDL_GetPerformanceCounter();
    g_context->Update();
    const Uint64 update_end = SDL_GetPerformanceCounter();
    g_context->Render();
    const Uint64 render_end = SDL_GetPerformanceCounter();
    draw_stage_grid(renderer);
    draw_asset_shelf_previews(renderer);
    const Uint64 grid_end = SDL_GetPerformanceCounter();

    const double ticks_to_ms = 1000.0 / (double)SDL_GetPerformanceFrequency();
    g_perf_update_ms += (double)(update_end - update_start) * ticks_to_ms;
    g_perf_render_ms += (double)(render_end - update_end) * ticks_to_ms;
    g_perf_grid_ms += (double)(grid_end - render_end) * ticks_to_ms;
    if (++g_perf_frames >= 120) {
        maker_log("Maker frame averages over %u frames: RmlUi update %.3f ms, RmlUi render %.3f ms, stage batch %.3f ms.",
            g_perf_frames, g_perf_update_ms/g_perf_frames, g_perf_render_ms/g_perf_frames, g_perf_grid_ms/g_perf_frames);
        g_perf_frames = 0;
        g_perf_update_ms = g_perf_render_ms = g_perf_grid_ms = 0.0;
    }
    return g_exit_requested ? 1 : 0;
}
