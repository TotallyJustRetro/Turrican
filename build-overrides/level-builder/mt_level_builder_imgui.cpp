#include "mt_level_builder_imgui.h"

#include "imgui.h"
#include "imgui_impl_sdl2.h"
#include "imgui_impl_sdlrenderer2.h"

#include <algorithm>
#include <cstdio>
#include <cstdint>
#include <cstring>
#ifdef _WIN32
#include <direct.h>
#else
#include <sys/stat.h>
#endif

namespace {
enum EditorMode {
    MODE_TILES = 0,
    MODE_ENTITY,
    MODE_EVENTS,
    MODE_ASSETS,
    MODE_BOSS,
    MODE_COUNT
};

enum EditorTool {
    TOOL_TILE_BRUSH = 0,
    TOOL_AUTO_SLOPE,
    TOOL_COLLISION,
    TOOL_GRAPPLE,
    TOOL_TRIGGER,
    TOOL_EVENT_WIRE,
    TOOL_SELECT,
    TOOL_ERASER,
    TOOL_COPY
};

static bool g_initialized = false;
static bool g_sdl_backend = false;
static bool g_renderer_backend = false;
static SDL_Window *g_window = nullptr;
static SDL_Surface *g_imgui_surface = nullptr;
static SDL_Renderer *g_imgui_surface_renderer = nullptr;
static int g_imgui_width = 320;
static int g_imgui_height = 224;
static uint8_t g_live_vram[65536] = {};
static uint16_t g_live_cram[64] = {};
static uint32_t g_live_art_hash = 0;
static int g_live_tile_ids[256] = {};
static int g_live_tile_count = 0;
static uint8_t g_live_regs[32] = {};
struct LiveSpritePart {
    uint16_t tile_attr;
    uint8_t width_tiles;
    uint8_t height_tiles;
    int16_t x;
    int16_t y;
};
static LiveSpritePart g_live_sprites[80] = {};
static int g_live_sprite_count = 0;
static int g_selected_sprite = -1;
static int g_selected_palette = 0;
static int g_tile_shelf_offset = 0;
static int g_selected_asset_slot = 0;
static bool g_left_was_down = false;
static int g_undo_count = 0;
static int g_redo_count = 0;
static uint16_t g_undo_stack[12][64 * 32] = {};
static uint16_t g_redo_stack[12][64 * 32] = {};
static EditorMode g_mode = MODE_TILES;
static EditorTool g_tool = TOOL_SELECT;
static const int kEditorMapCols = 64;
static const int kEditorMapRows = 32;
static std::uint16_t g_level_tiles[kEditorMapCols * kEditorMapRows] = {};
static bool g_document_dirty = false;
static int g_selected_x = 0;
static int g_selected_y = 0;
static int g_brush_tile = 1;
static int g_last_painted_x = -1;
static int g_last_painted_y = -1;
static int g_map_origin_x = 0;
static int g_map_origin_y = 0;
static bool g_layers[5] = {true, true, true, true, false};
static int g_asset_pixels[32 * 32] = {};
static int g_asset_color = 12;
static bool g_asset_modern = false;
static char g_status[160] = "NEW LEVEL DOCUMENT  |  EMPTY 64 x 32 GRID";
static bool g_exit_requested = false;
static int g_fade_in_frame = 0;
static int g_fade_out_frame = -1;
static bool g_show_grid = true;
static const int g_stage_width = 320, g_stage_height = 224;
static int g_active_layer = 3;
static bool g_collision_enabled = true;
static bool g_behavior_flags[4] = {true,false,true,false};
static int g_entity_type = 0, g_entity_count = 0, g_selected_entity = -1;
static int g_asset_size = 16, g_selected_frame = 0, g_boss_phase = 1, g_boss_hp = 100;
static bool g_boss_created = false;
static char g_level_name[64] = "UNTITLED LEVEL";
static char g_speaker[40] = "";
static char g_dialogue[256] = "";
static float g_dialogue_pitch = 1.0f;
static bool g_dialogue_auto = false, g_dialogue_camera_pan = true;

struct EditorEntity {
    float x,y;
    int type,hp;
    uint16_t tile_attr;
    uint8_t width_tiles,height_tiles;
};
static EditorEntity g_entities[64] = {};
struct EventNode { int type; float x,y; char title[28]; char detail[56]; };
static EventNode g_nodes[12] = {};
static int g_node_count = 0, g_selected_node = -1;
static int g_link_from[12] = {}, g_link_to[12] = {}, g_link_count = 0;

static const char *kModeNames[MODE_COUNT] = {
    "TILES", "ENTITY PLACEMENT", "EVENT SCRIPT", "ASSET STUDIO", "BOSS / ENEMY"
};

static const char *kLayerNames[5] = {
    "BACKGROUND", "MID-PARALLAX", "GAMEPLAY", "FOREGROUND", "3D DEPTH"
};

static const char *kTileTools[] = {
    "TILE BRUSH", "AUTO-TILE SLOPE", "COLLISION PAINTER",
    "GRAPPLE ANCHOR", "TRIGGER BOX", "EVENT WIRE LINKER"
};

static const char *kEntityTools[] = {
    "SELECT ENTITY", "PLACE ENEMY", "PLACE PICKUP",
    "PLAYER START", "PATROL PATH", "DELETE ENTITY"
};

static const char *kEventTools[] = {
    "SELECT NODE", "WHEN / TRIGGER", "IF / CONDITION",
    "ACTION BLOCK", "DIALOGUE", "CONNECT WIRE"
};

static const char *kAssetTools[] = {
    "PENCIL", "ERASER", "FILL", "EYEDROPPER", "SELECTION"
};

static const char *kBossTools[] = {
    "ADD BODY PART", "MOVE PIVOT", "WEAKPOINT", "ATTACK PATTERN",
    "PHASE TRANSITION", "ANIMATION TRACK"
};

static void apply_theme()
{
    ImGui::StyleColorsDark();
    ImGuiStyle &s = ImGui::GetStyle();

    s.WindowPadding = ImVec2(8.0f, 7.0f);
    s.FramePadding = ImVec2(4.0f, 2.0f);
    s.ItemSpacing = ImVec2(5.0f, 2.0f);
    s.ItemInnerSpacing = ImVec2(6.0f, 5.0f);
    s.ScrollbarSize = 12.0f;
    s.WindowBorderSize = 1.0f;
    s.ChildBorderSize = 1.0f;
    s.PopupBorderSize = 1.0f;
    s.FrameBorderSize = 1.0f;
    s.WindowRounding = 3.0f;
    s.ChildRounding = 3.0f;
    s.FrameRounding = 2.0f;
    s.PopupRounding = 3.0f;
    s.ScrollbarRounding = 2.0f;
    s.GrabRounding = 2.0f;
    s.TabRounding = 2.0f;

    ImVec4 *c = s.Colors;
    c[ImGuiCol_Text]                 = ImVec4(0.82f, 0.88f, 0.93f, 1.00f);
    c[ImGuiCol_TextDisabled]         = ImVec4(0.39f, 0.47f, 0.56f, 1.00f);
    c[ImGuiCol_WindowBg]             = ImVec4(0.035f, 0.050f, 0.071f, 0.96f);
    c[ImGuiCol_ChildBg]              = ImVec4(0.040f, 0.058f, 0.080f, 0.94f);
    c[ImGuiCol_PopupBg]              = ImVec4(0.045f, 0.063f, 0.086f, 0.98f);
    c[ImGuiCol_Border]               = ImVec4(0.17f, 0.24f, 0.31f, 0.95f);
    c[ImGuiCol_BorderShadow]         = ImVec4(0.00f, 0.00f, 0.00f, 0.30f);
    c[ImGuiCol_FrameBg]              = ImVec4(0.075f, 0.105f, 0.140f, 1.00f);
    c[ImGuiCol_FrameBgHovered]       = ImVec4(0.12f, 0.18f, 0.22f, 1.00f);
    c[ImGuiCol_FrameBgActive]        = ImVec4(0.16f, 0.22f, 0.25f, 1.00f);
    c[ImGuiCol_TitleBg]              = ImVec4(0.025f, 0.036f, 0.052f, 1.00f);
    c[ImGuiCol_TitleBgActive]        = ImVec4(0.045f, 0.065f, 0.086f, 1.00f);
    c[ImGuiCol_MenuBarBg]            = ImVec4(0.045f, 0.064f, 0.086f, 1.00f);
    c[ImGuiCol_ScrollbarBg]          = ImVec4(0.025f, 0.035f, 0.050f, 0.80f);
    c[ImGuiCol_ScrollbarGrab]        = ImVec4(0.20f, 0.29f, 0.36f, 1.00f);
    c[ImGuiCol_ScrollbarGrabHovered] = ImVec4(0.30f, 0.42f, 0.49f, 1.00f);
    c[ImGuiCol_ScrollbarGrabActive]  = ImVec4(0.95f, 0.57f, 0.16f, 1.00f);
    c[ImGuiCol_CheckMark]            = ImVec4(1.00f, 0.66f, 0.22f, 1.00f);
    c[ImGuiCol_SliderGrab]           = ImVec4(0.88f, 0.48f, 0.13f, 1.00f);
    c[ImGuiCol_SliderGrabActive]     = ImVec4(1.00f, 0.68f, 0.27f, 1.00f);
    c[ImGuiCol_Button]               = ImVec4(0.095f, 0.135f, 0.175f, 1.00f);
    c[ImGuiCol_ButtonHovered]        = ImVec4(0.20f, 0.28f, 0.33f, 1.00f);
    c[ImGuiCol_ButtonActive]         = ImVec4(0.78f, 0.40f, 0.10f, 1.00f);
    c[ImGuiCol_Header]               = ImVec4(0.12f, 0.18f, 0.22f, 1.00f);
    c[ImGuiCol_HeaderHovered]        = ImVec4(0.20f, 0.30f, 0.35f, 1.00f);
    c[ImGuiCol_HeaderActive]         = ImVec4(0.78f, 0.42f, 0.13f, 1.00f);
    c[ImGuiCol_Separator]            = ImVec4(0.18f, 0.26f, 0.33f, 0.95f);
    c[ImGuiCol_SeparatorHovered]     = ImVec4(0.95f, 0.57f, 0.16f, 0.80f);
    c[ImGuiCol_SeparatorActive]      = ImVec4(1.00f, 0.66f, 0.22f, 1.00f);
    c[ImGuiCol_ResizeGrip]           = ImVec4(0.50f, 0.34f, 0.18f, 0.35f);
    c[ImGuiCol_ResizeGripHovered]    = ImVec4(0.95f, 0.57f, 0.16f, 0.70f);
    c[ImGuiCol_ResizeGripActive]     = ImVec4(1.00f, 0.66f, 0.22f, 0.95f);
    c[ImGuiCol_Tab]                  = ImVec4(0.07f, 0.10f, 0.14f, 1.00f);
    c[ImGuiCol_TabHovered]           = ImVec4(0.20f, 0.29f, 0.34f, 1.00f);
    c[ImGuiCol_TabSelected]          = ImVec4(0.26f, 0.17f, 0.10f, 1.00f);
    c[ImGuiCol_TabSelectedOverline]  = ImVec4(1.00f, 0.62f, 0.18f, 1.00f);
    c[ImGuiCol_TableHeaderBg]        = ImVec4(0.08f, 0.12f, 0.16f, 1.00f);
    c[ImGuiCol_TableBorderStrong]    = ImVec4(0.20f, 0.29f, 0.36f, 1.00f);
    c[ImGuiCol_TableBorderLight]     = ImVec4(0.13f, 0.19f, 0.25f, 1.00f);
    c[ImGuiCol_TextSelectedBg]       = ImVec4(0.85f, 0.48f, 0.14f, 0.45f);
    c[ImGuiCol_NavHighlight]         = ImVec4(1.00f, 0.66f, 0.22f, 0.80f);
}

static void panel_heading(const char *label, const char *right = nullptr)
{
    ImGui::TextColored(ImVec4(1.00f, 0.65f, 0.22f, 1.00f), "%s", label);
    if (right) {
        ImGui::SameLine();
        const float width = ImGui::CalcTextSize(right).x;
        ImGui::SetCursorPosX(ImGui::GetWindowWidth() - width - 14.0f);
        ImGui::TextColored(ImVec4(0.34f, 0.78f, 0.83f, 1.00f), "%s", right);
    }
    ImGui::Separator();
}

static bool mode_button(const char *label, EditorMode mode, float width)
{
    const bool active = g_mode == mode;
    if (active) {
        ImGui::PushStyleColor(ImGuiCol_Button, ImVec4(0.48f, 0.25f, 0.09f, 1.0f));
        ImGui::PushStyleColor(ImGuiCol_Border, ImVec4(1.0f, 0.60f, 0.18f, 1.0f));
    }
    const bool clicked = ImGui::Button(label, ImVec2(width, 30.0f));
    if (active) ImGui::PopStyleColor(2);
    if (clicked) g_mode = mode;
    return clicked;
}

static void tool_button(const char *label, int index, int selected)
{
    if (ImGui::Selectable(label, selected == index, ImGuiSelectableFlags_None, ImVec2(0.0f, 27.0f))) {
        if (g_mode == MODE_TILES) g_tool = static_cast<EditorTool>(index);
        else g_tool = TOOL_TILE_BRUSH;
    }
}

static ImU32 vdp_color(int palette,int index)
{
    if(index==0)return IM_COL32(0,0,0,0);
    const uint16_t raw=g_live_cram[(palette&3)*16+(index&15)];
    const int r=(raw>>1)&7,g=(raw>>5)&7,b=(raw>>9)&7;
    return IM_COL32(r*255/7,g*255/7,b*255/7,255);
}
static int vdp_pixel(int tile,int x,int y)
{
    if(tile<0||tile>=2048)return 0;
    const uint8_t packed=g_live_vram[tile*32+y*4+(x>>1)];
    return (x&1)?(packed&15):(packed>>4);
}
static void draw_vdp_tile(ImDrawList *draw,ImVec2 pos,float size,int entry)
{
    const int tile=entry&0x7ff;
    const int hflip=(entry>>11)&1,vflip=(entry>>12)&1,palette=(entry>>13)&3;
    const float pixel=size/8.0f;
    for(int y=0;y<8;y++)for(int x=0;x<8;x++){
        const int sx=hflip?7-x:x,sy=vflip?7-y:y;
        const int color=vdp_pixel(tile,sx,sy);
        if(!color)continue;
        ImVec2 a(pos.x+x*pixel,pos.y+y*pixel);
        draw->AddRectFilled(a,ImVec2(a.x+pixel+.15f,a.y+pixel+.15f),vdp_color(palette,color));
    }
}

static void draw_vdp_sprite(ImDrawList *draw,ImVec2 pos,float tileSize,
                            uint16_t tileAttr,int widthTiles,int heightTiles)
{
    const int base=tileAttr&0x07FF;
    const bool hflip=(tileAttr&0x0800)!=0;
    const bool vflip=(tileAttr&0x1000)!=0;
    const int attributes=tileAttr&0xF800;
    for(int row=0;row<heightTiles;row++){
        for(int col=0;col<widthTiles;col++){
            const int tileRow=vflip?(heightTiles-1-row):row;
            const int tileCol=hflip?(widthTiles-1-col):col;
            const int tile=(base+tileCol*heightTiles+tileRow)&0x07FF;
            draw_vdp_tile(draw,
                ImVec2(pos.x+col*tileSize,pos.y+row*tileSize),
                tileSize,attributes|tile);
        }
    }
}


static void push_level_undo();
static void undo_level_edit();
static void redo_level_edit();
static void draw_tool_palette();

static void draw_stage_canvas()
{
    const int cols=mtlb_map_cols(),rows=mtlb_map_rows();
    g_selected_x=std::max(0,std::min(cols-1,g_selected_x));
    g_selected_y=std::max(0,std::min(rows-1,g_selected_y));
    ImGui::BeginChild("##stage_canvas",ImVec2(0,0),true);
    ImVec2 avail=ImGui::GetContentRegionAvail();
    const float cell=std::max(9.0f,std::min(16.0f,std::min(avail.x/22.0f,avail.y/5.0f)));
    const int viewCols=std::max(1,std::min(cols,(int)(avail.x/cell)));
    const int viewRows=std::max(1,std::min(rows,(int)(avail.y/cell)));
    g_map_origin_x=std::max(0,std::min(cols-viewCols,g_selected_x-viewCols/2));
    g_map_origin_y=std::max(0,std::min(rows-viewRows,g_selected_y-viewRows/2));
    ImVec2 origin=ImGui::GetCursorScreenPos();
    const float w=viewCols*cell,h=viewRows*cell;
    ImVec2 finish(origin.x+w,origin.y+h);
    ImDrawList *d=ImGui::GetWindowDrawList();
    d->AddRectFilled(ImVec2(origin.x-3,origin.y-3),ImVec2(finish.x+3,finish.y+3),IM_COL32(3,7,12,255),2.0f);
    d->AddRectFilled(origin,finish,IM_COL32(8,13,21,255));
    if(g_mode==MODE_TILES){
        for(int y=0;y<viewRows;y++)for(int x=0;x<viewCols;x++){
            const int entry=mtlb_map_get(g_map_origin_x+x,g_map_origin_y+y);
            if(entry)draw_vdp_tile(d,ImVec2(origin.x+x*cell,origin.y+y*cell),cell,entry);
        }
    }
    if(g_show_grid){
        for(int x=0;x<=viewCols;x++){float px=origin.x+x*cell;d->AddLine(ImVec2(px,origin.y),ImVec2(px,finish.y),IM_COL32(108,138,154,88),1.0f);}
        for(int y=0;y<=viewRows;y++){float py=origin.y+y*cell;d->AddLine(ImVec2(origin.x,py),ImVec2(finish.x,py),IM_COL32(108,138,154,88),1.0f);}
    }
    ImGui::SetCursorScreenPos(origin);
    ImGui::InvisibleButton("##stage_surface",ImVec2(w,h),ImGuiButtonFlags_MouseButtonLeft|ImGuiButtonFlags_MouseButtonRight);
    const bool mouseDown=ImGui::IsItemHovered()&&ImGui::IsMouseDown(ImGuiMouseButton_Left);
    if(ImGui::IsItemHovered()){
        ImVec2 m=ImGui::GetIO().MousePos;
        int cx=std::max(0,std::min(viewCols-1,(int)((m.x-origin.x)/cell)));
        int cy=std::max(0,std::min(viewRows-1,(int)((m.y-origin.y)/cell)));
        int mx=g_map_origin_x+cx,my=g_map_origin_y+cy;
        g_selected_x=mx;g_selected_y=my;
        if(ImGui::IsMouseClicked(ImGuiMouseButton_Right)){
            g_brush_tile=mtlb_map_get(mx,my);
            if(g_brush_tile){g_selected_palette=(g_brush_tile>>13)&3;g_tool=TOOL_TILE_BRUSH;}
        }
        if(mouseDown&&g_mode==MODE_TILES){
            if(!g_left_was_down&&(g_tool==TOOL_TILE_BRUSH||g_tool==TOOL_ERASER))push_level_undo();
            if(g_tool==TOOL_TILE_BRUSH&&g_brush_tile>0)mtlb_map_set(mx,my,g_brush_tile);
            else if(g_tool==TOOL_ERASER)mtlb_map_set(mx,my,0);
        }else if(g_mode==MODE_ENTITY&&ImGui::IsMouseClicked(ImGuiMouseButton_Left)&&
                 g_selected_sprite>=0&&g_selected_sprite<g_live_sprite_count&&g_entity_count<64){
            const LiveSpritePart &sprite=g_live_sprites[g_selected_sprite];
            EditorEntity &entity=g_entities[g_entity_count++];
            entity.x=(m.x-origin.x)/w;
            entity.y=(m.y-origin.y)/h;
            entity.type=g_entity_type;
            entity.hp=100;
            entity.tile_attr=sprite.tile_attr;
            entity.width_tiles=sprite.width_tiles;
            entity.height_tiles=sprite.height_tiles;
            g_selected_entity=g_entity_count-1;
            g_document_dirty=true;
            std::snprintf(g_status,sizeof(g_status),"PLACED LIVE SPRITE PART");
        }
    }
    g_left_was_down=mouseDown;
    for(int i=0;i<g_entity_count;i++){
        const EditorEntity &entity=g_entities[i];
        const ImVec2 p(origin.x+entity.x*w,origin.y+entity.y*h);
        if(entity.width_tiles&&entity.height_tiles)
            draw_vdp_sprite(d,p,cell,entity.tile_attr,entity.width_tiles,entity.height_tiles);
        else
            d->AddCircleFilled(p,3.0f,IM_COL32(255,190,76,255));
        if(i==g_selected_entity)
            d->AddRect(p,ImVec2(p.x+entity.width_tiles*cell,p.y+entity.height_tiles*cell),
                       IM_COL32(255,190,76,255),0.0f,2.0f);
    }
    if(g_mode==MODE_TILES){
        int sx=g_selected_x-g_map_origin_x,sy=g_selected_y-g_map_origin_y;
        ImVec2 a(origin.x+sx*cell,origin.y+sy*cell),b(a.x+cell,a.y+cell);
        d->AddRect(a,b,IM_COL32(255,190,76,255),0.0f,2.0f);
    }
    ImGui::SetCursorScreenPos(ImVec2(origin.x,finish.y+2));
    ImGui::TextDisabled("X:%02d  Y:%02d   %s",g_selected_x,g_selected_y,g_document_dirty?"UNSAVED":"SAVED");
    ImGui::EndChild();
}



static void add_event_node(int type);
static void draw_advanced_tool_palette();
static void draw_advanced_layers();
static void draw_advanced_inspector();
static void draw_advanced_asset_canvas();
static void draw_node_graph();
static void draw_stage_canvas();
static void draw_bottom_workspace()
{
    ImGui::BeginChild("##workspace_bottom",ImVec2(0,25),true);
    ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"%s",g_level_name);
    ImGui::SameLine();
    if(g_undo_count>0){if(ImGui::SmallButton("U"))undo_level_edit();}
    else{ImGui::BeginDisabled();ImGui::SmallButton("U");ImGui::EndDisabled();}
    ImGui::SameLine();
    if(g_redo_count>0){if(ImGui::SmallButton("R"))redo_level_edit();}
    else{ImGui::BeginDisabled();ImGui::SmallButton("R");ImGui::EndDisabled();}
    ImGui::SameLine();
    if(ImGui::SmallButton("SAVE")){bool ok=mtlb_map_save();std::snprintf(g_status,sizeof(g_status),"%s",ok?"LEVEL SAVED":"SAVE FAILED");}
    ImGui::SameLine();
    ImGui::BeginDisabled();ImGui::SmallButton("TEST");ImGui::EndDisabled();
    ImGui::SameLine();
    if(ImGui::SmallButton("EXIT"))g_exit_requested=true;
    ImGui::EndChild();
}

static void draw_layer_bar()
{
    ImGui::BeginChild("##categories",ImVec2(0,28),true);
    const struct {const char *label;EditorMode mode;} tabs[]={
        {"TILES",MODE_TILES},{"OBJECTS",MODE_ENTITY},
        {"BOSSES",MODE_BOSS},{"DRAW",MODE_ASSETS},{"EVENTS",MODE_EVENTS}
    };
    const float tabWidth=(ImGui::GetContentRegionAvail().x-12.0f)/5.0f;
    for(int i=0;i<5;i++){
        if(i)ImGui::SameLine(0,3);
        bool active=g_mode==tabs[i].mode;
        if(active)ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.50f,.27f,.10f,1));
        if(ImGui::Button(tabs[i].label,ImVec2(tabWidth,20)))g_mode=tabs[i].mode;
        if(active)ImGui::PopStyleColor();
    }
    ImGui::EndChild();
}

static void draw_inspector() { draw_advanced_inspector(); }

static void draw_asset_canvas() { draw_advanced_asset_canvas(); }

static void draw_center_view()
{
    if(g_mode==MODE_TILES||g_mode==MODE_ENTITY||g_mode==MODE_BOSS) draw_stage_canvas();
    else if(g_mode==MODE_EVENTS) draw_node_graph();
    else draw_advanced_asset_canvas();
}


static void draw_advanced_layers()
{
    ImGui::BeginChild("##layer_bar",ImVec2(0,34),true);
    ImGui::TextColored(ImVec4(1,.66f,.23f,1),"DEPTH");
    const char *names[5]={"BG","MID","FG1","FG2","3D"};
    for(int i=0;i<5;i++){ImGui::SameLine();ImGui::Checkbox(names[i],&g_layers[i]);}
    ImGui::SameLine();ImGui::TextDisabled(" / GRID 16 x 16");
    ImGui::EndChild();
}
static void draw_advanced_tool_palette()
{
    panel_heading(g_mode==MODE_EVENTS?"SCRIPT TOOLBOX":"TOOL DECK","01");
    if(g_mode==MODE_EVENTS) {
        ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"EVENT BLOCKS");
        ImGui::TextWrapped("Create a node in the event canvas, then select it to edit its parameters.");
        ImGui::Separator();
        ImGui::TextDisabled("WHEN / TRIGGER");
        ImGui::BulletText("Player enters zone");
        ImGui::BulletText("Enemy defeated");
        ImGui::BulletText("Timer reaches value");
        ImGui::Separator();
        ImGui::TextDisabled("NPC / DIALOGUE");
        ImGui::TextDisabled("Dialogue portraits appear only after a dialogue node is created.");
        return;
    }
    const char **items=kTileTools;int count=6;
    if(g_mode==MODE_ENTITY)items=kEntityTools;
    else if(g_mode==MODE_ASSETS){items=kAssetTools;count=5;}
    else if(g_mode==MODE_BOSS)items=kBossTools;
    for(int i=0;i<count;i++) {
        bool active=(g_mode==MODE_TILES&&(int)g_tool==i)||
                    (g_mode==MODE_ENTITY&&g_entity_type==i);
        if(active)ImGui::PushStyleColor(ImGuiCol_Header,ImVec4(.38f,.21f,.10f,1));
        const char *glyph=g_mode==MODE_TILES?
            (i==0?"[T]":i==1?"[/]":i==2?"[C]":i==3?"[G]":i==4?"[TR]":"[W]"):
            g_mode==MODE_ENTITY?
            (i==0?"[SEL]":i==1?"[EN]":i==2?"[IT]":i==3?"[P1]":i==4?"[PATH]":"[DEL]"):
            g_mode==MODE_BOSS?
            (i==0?"[CORE]":i==1?"[TUR]":i==2?"[SHD]":i==3?"[WP]":i==4?"[ATK]":"[PH]"):
            (i==0?"[P]":i==1?"[E]":i==2?"[F]":i==3?"[I]":"[S]");
        char label[64];std::snprintf(label,sizeof(label),"%s  %s",glyph,items[i]);
        if(ImGui::Selectable(label,active,0,ImVec2(0,33))) {
            if(g_mode==MODE_TILES)g_tool=(EditorTool)i;
            else if(g_mode==MODE_ENTITY)g_entity_type=i;
            else if(g_mode==MODE_BOSS)g_selected_entity=i;
        }
        if(active)ImGui::PopStyleColor();
    }
    ImGui::Separator();
    if(g_mode==MODE_TILES){
        ImGui::TextDisabled("BRUSH TILE");ImGui::SetNextItemWidth(-1);
        ImGui::InputInt("##brush_tile",&g_brush_tile,1,16);
        g_brush_tile=std::max(1,std::min(2047,g_brush_tile));
    }else if(g_mode==MODE_ENTITY){
        ImGui::TextDisabled("PLACEMENT");ImGui::Text("SNAP 8 PX");
        ImGui::Text("OBJECTS %02d",g_entity_count);
    }else if(g_mode==MODE_BOSS){
        ImGui::TextDisabled("ASSEMBLY");ImGui::Text("%s",g_boss_created?"CORE CREATED":"NO BOSS CREATED");
        ImGui::Text("PIVOT GRID");
    }else{
        ImGui::TextDisabled("ASSET TOOLS");ImGui::Text("CANVAS %d x %d",g_asset_size,g_asset_size);
    }
}





static void add_event_node(int type)
{
    if(g_node_count>=12)return;EventNode &n=g_nodes[g_node_count];n.type=type;n.x=18+(g_node_count%3)*160;n.y=62+(g_node_count/3)*112;
    const char *t=type==0?"NEW_TRIGGER":type==1?"NPC DIALOGUE":type==3?"BOSS SPAWN":"NEW ACTION";
    const char *v=type==0?"PLAYER ENTERS ZONE":type==1?"COMMANDER MESSAGE":"SET STAGE FLAG";
    std::snprintf(n.title,sizeof(n.title),"%s",t);std::snprintf(n.detail,sizeof(n.detail),"%s",v);
    if(g_node_count&&g_link_count<12){g_link_from[g_link_count]=g_node_count-1;g_link_to[g_link_count]=g_node_count;g_link_count++;}
    g_selected_node=g_node_count++;
}
static void draw_node_graph()
{
    ImGui::TextColored(ImVec4(.43f,.84f,.90f,1),"SCRIPT / EVENT FLOW");ImGui::SameLine();ImGui::TextDisabled("%02d NODES / %02d LINKS",g_node_count,g_link_count);
    ImGui::SameLine();if(ImGui::SmallButton("+ WHEN"))add_event_node(0);ImGui::SameLine();if(ImGui::SmallButton("+ DIALOGUE"))add_event_node(1);ImGui::SameLine();if(ImGui::SmallButton("+ ACTION"))add_event_node(2);ImGui::SameLine();if(ImGui::SmallButton("+ BOSS"))add_event_node(3);
    ImGui::BeginChild("##node_canvas",ImVec2(0,0),true);
    if(g_node_count==0)ImGui::TextDisabled("EMPTY EVENT GRAPH / ADD A WHEN, ACTION OR DIALOGUE NODE");
    ImVec2 p=ImGui::GetCursorScreenPos(),sz=ImGui::GetContentRegionAvail(),end(p.x+sz.x,p.y+sz.y);ImDrawList *d=ImGui::GetWindowDrawList();
    d->AddRectFilled(p,end,IM_COL32(13,18,27,255));
    for(float x=p.x;x<end.x;x+=24)d->AddLine(ImVec2(x,p.y),ImVec2(x,end.y),IM_COL32(57,74,88,95));
    for(float y=p.y;y<end.y;y+=24)d->AddLine(ImVec2(p.x,y),ImVec2(end.x,y),IM_COL32(57,74,88,95));
    for(int i=0;i<g_link_count;i++){int a=g_link_from[i],b=g_link_to[i];if(a<0||b<0||a>=g_node_count||b>=g_node_count)continue;EventNode &na=g_nodes[a],&nb=g_nodes[b];ImVec2 from(p.x+na.x+140,p.y+na.y+34),to(p.x+nb.x,p.y+nb.y+34);d->AddBezierCubic(from,ImVec2(from.x+40,from.y),ImVec2(to.x-40,to.y),to,IM_COL32(68,194,206,230),3);d->AddCircleFilled(from,4,IM_COL32(116,234,240,255));d->AddCircleFilled(to,4,IM_COL32(116,234,240,255));}
    for(int i=0;i<g_node_count;i++){EventNode &n=g_nodes[i];ImVec2 np(p.x+n.x,p.y+n.y),ns(np.x+142,np.y+72);ImGui::SetCursorScreenPos(np);ImGui::PushID(i);ImGui::InvisibleButton("##node",ImVec2(142,72));if(ImGui::IsItemClicked())g_selected_node=i;if(ImGui::IsItemActive()&&ImGui::IsMouseDragging(0)){n.x+=ImGui::GetIO().MouseDelta.x;n.y+=ImGui::GetIO().MouseDelta.y;n.x=std::max(0.0f,std::min(n.x,std::max(0.0f,sz.x-148)));n.y=std::max(0.0f,std::min(n.y,std::max(0.0f,sz.y-78)));}ImU32 c=n.type==0?IM_COL32(238,214,70,255):n.type==1?IM_COL32(70,165,242,255):n.type==3?IM_COL32(227,70,73,255):IM_COL32(70,195,178,255);d->AddRectFilled(np,ns,IM_COL32(4,9,16,248),4);d->AddRect(np,ns,c,4.0f,g_selected_node==i?3.0f:1.5f);d->AddRectFilled(np,ImVec2(ns.x,np.y+23),c,3);d->AddText(ImVec2(np.x+9,np.y+6),IM_COL32(245,248,250,255),n.title);d->AddText(ImVec2(np.x+9,np.y+35),IM_COL32(185,203,215,255),n.detail);d->AddCircleFilled(ImVec2(np.x+5,np.y+36),4,c);d->AddCircleFilled(ImVec2(ns.x-5,np.y+36),4,c);if(g_selected_node==i)d->AddRect(ImVec2(np.x-4,np.y-4),ImVec2(ns.x+4,ns.y+4),IM_COL32(238,245,247,220),5.0f,1.5f);ImGui::PopID();}
    ImGui::SetCursorScreenPos(ImVec2(p.x+4,p.y+sz.y-23));ImGui::TextDisabled("DRAG NODES / SELECT TO EDIT / CONNECTORS FOLLOW NODE POSITIONS");ImGui::EndChild();
}
static void draw_timeline_panel()
{
    ImGui::BeginChild("##sequencer",ImVec2(0,0),true);
    ImGui::TextColored(ImVec4(.43f,.84f,.90f,1),"ANIMATION / EVENT SEQUENCER");ImGui::SameLine();
    if(ImGui::SmallButton("||"))g_selected_frame=(g_selected_frame+1)%9;ImGui::SameLine();if(ImGui::SmallButton("STOP"))g_selected_frame=0;
    ImGui::SameLine();ImGui::TextDisabled("NO CLIP SELECTED");ImGui::SameLine();if(ImGui::SmallButton("+ FRAME"))g_selected_frame=std::min(8,g_selected_frame+1);
    for(int i=0;i<9;i++){if(i)ImGui::SameLine(0,3);ImGui::PushID(i);ImVec2 p=ImGui::GetCursorScreenPos();ImGui::InvisibleButton("##frame",ImVec2(60,45));if(ImGui::IsItemClicked())g_selected_frame=i;ImDrawList *d=ImGui::GetWindowDrawList();d->AddRectFilled(p,ImVec2(p.x+60,p.y+45),i==g_selected_frame?IM_COL32(52,77,90,255):IM_COL32(22,30,41,255));d->AddRect(p,ImVec2(p.x+60,p.y+45),i==g_selected_frame?IM_COL32(255,161,51,255):IM_COL32(85,103,118,255),0.0f,1.5f);d->AddText(ImVec2(p.x+17,p.y+17),IM_COL32(94,115,129,255),"EMPTY");char num[8];std::snprintf(num,sizeof(num),"%02d",i+1);d->AddText(ImVec2(p.x+3,p.y+2),IM_COL32(182,198,208,255),num);ImGui::PopID();}
    const char *names[3]={"POSE","FX","SOUND"};const ImU32 colors[3]={IM_COL32(130,139,166,255),IM_COL32(60,163,216,255),IM_COL32(177,160,95,255)};
    for(int row=0;row<3;row++){ImGui::TextColored(ImVec4(.67f,.75f,.81f,1),"%s",names[row]);ImGui::SameLine(58);ImVec2 p=ImGui::GetCursorScreenPos();float w=ImGui::GetContentRegionAvail().x;ImDrawList *d=ImGui::GetWindowDrawList();d->AddRectFilled(p,ImVec2(p.x+w,p.y+14),IM_COL32(34,41,55,255));float play=p.x+w*(g_selected_frame/8.0f);d->AddLine(ImVec2(play,p.y-2),ImVec2(play,p.y+16),IM_COL32(255,100,70,255),2);ImGui::Dummy(ImVec2(w,15));}
    ImGui::TextDisabled("NO KEYS / NO EVENTS IN THIS TRACK",g_selected_frame+1);ImGui::EndChild();
}

static void draw_advanced_inspector()
{
    panel_heading(g_mode==MODE_EVENTS?"NODE PROPERTIES":"PROPERTIES","LIVE");
    if(g_mode==MODE_TILES){
        int tile=mtlb_map_get(g_selected_x,g_selected_y);
        ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"SELECTED CELL");ImGui::Text("X:%03d  Y:%03d",g_selected_x,g_selected_y);ImGui::Separator();
        ImGui::Text("TILE INDEX");ImGui::SetNextItemWidth(-1);if(ImGui::InputInt("##tile_index",&tile,1,16))mtlb_map_set(g_selected_x,g_selected_y,std::max(0,std::min(2047,tile)));
        ImGui::Text("LAYER");const char *layers[5]={"BG1","BG2","FG1","FG2","3D"};ImGui::SetNextItemWidth(-1);ImGui::Combo("##layer",&g_active_layer,layers,5);
        ImGui::Checkbox("COLLISION ON",&g_collision_enabled);ImGui::Separator();ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"TILE PALETTE");
        for(int i=0;i<12;i++){if(i%4)ImGui::SameLine();ImGui::PushID(i);ImVec4 c=ImVec4(.18f+(i%4)*.12f,.10f+(i%3)*.13f,.25f+(i%5)*.10f,1);if(ImGui::ColorButton("##pal",c,0,ImVec2(34,26)))g_brush_tile=(g_brush_tile+i+1)&2047;ImGui::PopID();}
        ImGui::Separator();ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"BEHAVIOR");ImGui::Checkbox("BREAKABLE",&g_behavior_flags[0]);ImGui::Checkbox("ANIMATED",&g_behavior_flags[1]);ImGui::Checkbox("HAZARD",&g_behavior_flags[2]);ImGui::Checkbox("GRAPPLE POINT",&g_behavior_flags[3]);
        ImGui::Separator();if(ImGui::Button("SAVE LEVEL",ImVec2(-1,30))){bool ok=mtlb_map_save();std::snprintf(g_status,sizeof(g_status),"%s",ok?"SAVED /levels/untitled.mtlb":"SAVE FAILED");}
        if(ImGui::Button("LOAD LEVEL",ImVec2(-1,28))){bool ok=mtlb_map_load();std::snprintf(g_status,sizeof(g_status),"%s",ok?"LOADED /levels/untitled.mtlb":"LOAD FAILED");}
    }else if(g_mode==MODE_ENTITY){
        ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"ENTITY PLACEMENT");ImGui::Text("OBJECT COUNT %02d",g_entity_count);
        if(g_selected_entity>=0&&g_selected_entity<g_entity_count){EditorEntity &e=g_entities[g_selected_entity];ImGui::Separator();ImGui::Text("ENTITY_%02d",g_selected_entity);ImGui::SliderInt("TYPE",&e.type,0,5);ImGui::SliderInt("HEALTH",&e.hp,1,999);ImGui::Text("X %.3f  Y %.3f",e.x,e.y);if(ImGui::Button("DELETE ENTITY",ImVec2(-1,28))){for(int i=g_selected_entity;i<g_entity_count-1;i++)g_entities[i]=g_entities[i+1];g_entity_count--;g_selected_entity=-1;}}
        else ImGui::TextWrapped("Choose an entity tool, then click the stage to place an enemy, pickup or spawn marker.");
        ImGui::Separator();ImGui::Checkbox("SNAP TO GRID",&g_show_grid);ImGui::Text("PLACEMENT PLANE 2D");ImGui::Text("GRAPPLE ANCHORS ENABLED");
    }else if(g_mode==MODE_EVENTS){
        if(g_node_count==0){
            ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"NO NODE SELECTED");
            ImGui::TextWrapped("Create the first node from the event canvas. This new level has no preloaded scripts.");
        }else{
            g_selected_node=std::max(0,std::min(g_node_count-1,g_selected_node));
            EventNode &n=g_nodes[g_selected_node];
            ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"SELECTED NODE");
            ImGui::Text("NODE_%02d",g_selected_node+1);
            ImGui::Text("TYPE %s",n.type==0?"TRIGGER":n.type==1?"DIALOGUE":n.type==3?"BOSS":"ACTION");
            ImGui::Separator();
            ImGui::Text("NODE NAME");ImGui::SetNextItemWidth(-1);
            ImGui::InputText("##node_title",n.title,sizeof(n.title));
            ImGui::Text("PARAMETER / TARGET");ImGui::SetNextItemWidth(-1);
            ImGui::InputText("##node_detail",n.detail,sizeof(n.detail));
            if(n.type==1){
                ImGui::Separator();
                ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"NPC DIALOGUE");
                ImGui::Text("SPEAKER");ImGui::SetNextItemWidth(-1);ImGui::InputText("##speaker",g_speaker,sizeof(g_speaker));
                ImGui::Text("MESSAGE");ImGui::SetNextItemWidth(-1);ImGui::InputTextMultiline("##dialogue",g_dialogue,sizeof(g_dialogue),ImVec2(-1,94));
                ImGui::SliderFloat("BLIP PITCH",&g_dialogue_pitch,.5f,2.0f,"%.2fx");
                ImGui::Checkbox("AUTO ADVANCE",&g_dialogue_auto);
                ImGui::Checkbox("CAMERA PAN",&g_dialogue_camera_pan);
            }
            ImGui::Separator();ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"LOGIC LINKS");
            ImGui::Text("OUTGOING %d",g_link_count);
            if(ImGui::Button("LINK TO NEXT NODE",ImVec2(-1,30))&&g_selected_node+1<g_node_count&&g_link_count<12){
                g_link_from[g_link_count]=g_selected_node;g_link_to[g_link_count]=g_selected_node+1;g_link_count++;
            }
        }
    }else if(g_mode==MODE_ASSETS){
        ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"ASSET DOCUMENT");ImGui::Text("CANVAS %d x %d",g_asset_size,g_asset_size);ImGui::Checkbox("MODERN RGBA",&g_asset_modern);ImGui::SliderInt("COLOR",&g_asset_color,0,g_asset_modern?255:63);ImGui::Separator();
        if(ImGui::Button("CLEAR CANVAS",ImVec2(-1,30)))std::fill(g_asset_pixels,g_asset_pixels+1024,0);
        ImGui::TextDisabled("PNG / SPRITE SHEET PIPELINE");ImGui::TextWrapped("Local canvas drawing is active. Import, slicing and export are the next pipeline connection.");
    }else{
        if(!g_boss_created){
            ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"NO BOSS ASSEMBLED");
            ImGui::TextWrapped("The boss workspace is empty. Create a core when you are ready to start assembly.");
            if(ImGui::Button("CREATE BOSS CORE",ImVec2(-1,32)))g_boss_created=true;
        }else{
            ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"BOSS CORE");
            ImGui::Text("PHASE 1 / HP");ImGui::SliderInt("##boss_hp",&g_boss_hp,1,100);
            ImGui::Text("PHASE 2 / 60 - 25%%");ImGui::ProgressBar(.38f,ImVec2(-1,14));
            ImGui::Text("PHASE 3 / ENRAGE");ImGui::Separator();
            ImGui::Checkbox("AGGRESSIVE",&g_behavior_flags[0]);ImGui::Checkbox("DEFENSIVE",&g_behavior_flags[1]);
            ImGui::Checkbox("RAGE MODE",&g_behavior_flags[2]);ImGui::Checkbox("SHIELD CORE",&g_behavior_flags[3]);
            ImGui::Separator();ImGui::RadioButton("PHASE 1",&g_boss_phase,1);
            ImGui::RadioButton("PHASE 2",&g_boss_phase,2);ImGui::RadioButton("PHASE 3",&g_boss_phase,3);
        }
    }
}
static void draw_advanced_asset_canvas()
{
    ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"PIXEL / VECTOR CANVAS");ImGui::SameLine();if(ImGui::SmallButton("16 x 16"))g_asset_size=16;ImGui::SameLine();if(ImGui::SmallButton("32 x 32"))g_asset_size=32;ImGui::SameLine();ImGui::TextDisabled(g_asset_modern?"MODERN RGBA":"GENESIS CRAM / 64 COLORS");
    ImGui::BeginChild("##asset_workspace",ImVec2(0,0),true);ImGui::Text("COLOR");ImGui::SameLine();
    for(int i=0;i<12;i++){if(i)ImGui::SameLine(0,3);ImGui::PushID(100+i);ImVec4 c=ImVec4((float)((i*37+65)%220)/255,(float)((i*61+90)%220)/255,(float)((i*89+120)%220)/255,1);if(ImGui::ColorButton("##swatch",c,0,ImVec2(20,20)))g_asset_color=i*5+8;ImGui::PopID();}
    ImGui::Spacing();float av=ImGui::GetContentRegionAvail().x;float px=std::max(7.0f,std::min(18.0f,(av-8)/g_asset_size));ImVec2 p=ImGui::GetCursorScreenPos(),sz(px*g_asset_size,px*g_asset_size);ImDrawList *d=ImGui::GetWindowDrawList();d->AddRectFilled(p,ImVec2(p.x+sz.x,p.y+sz.y),IM_COL32(5,9,15,255));
    for(int y=0;y<g_asset_size;y++)for(int x=0;x<g_asset_size;x++){int v=g_asset_pixels[y*32+x];if(v){int c=v&255;d->AddRectFilled(ImVec2(p.x+x*px,p.y+y*px),ImVec2(p.x+(x+1)*px-1,p.y+(y+1)*px-1),IM_COL32(40+(c*7)%205,45+(c*11)%200,55+(c*13)%190,255));}}
    for(int i=0;i<=g_asset_size;i++){d->AddLine(ImVec2(p.x+i*px,p.y),ImVec2(p.x+i*px,p.y+sz.y),IM_COL32(65,88,103,160));d->AddLine(ImVec2(p.x,p.y+i*px),ImVec2(p.x+sz.x,p.y+i*px),IM_COL32(65,88,103,160));}
    ImGui::SetCursorScreenPos(p);ImGui::InvisibleButton("##asset_canvas",sz,ImGuiButtonFlags_MouseButtonLeft|ImGuiButtonFlags_MouseButtonRight);
    if(ImGui::IsItemHovered()&&(ImGui::IsMouseDown(0)||ImGui::IsMouseDown(1))){ImVec2 m=ImGui::GetIO().MousePos;int x=std::max(0,std::min(g_asset_size-1,(int)((m.x-p.x)/px))),y=std::max(0,std::min(g_asset_size-1,(int)((m.y-p.y)/px)));g_asset_pixels[y*32+x]=ImGui::IsMouseDown(1)?0:g_asset_color;}
    ImGui::TextDisabled("LEFT CLICK PAINT / RIGHT CLICK ERASE / 0 TRANSPARENT");ImGui::EndChild();
}
static void draw_tool_palette()
{
    ImGui::BeginChild("##maker_tool_row",ImVec2(0,26),true);
    const struct { const char *glyph; EditorTool tool; const char *hint; } buttons[] = {
        {"S",TOOL_SELECT,"Select"},
        {"B",TOOL_TILE_BRUSH,"Place / paint"},
        {"E",TOOL_ERASER,"Erase"},
        {"C",TOOL_COPY,"Copy"},
        {"G",TOOL_GRAPPLE,"Grapple anchor"},
        {"T",TOOL_TRIGGER,"Trigger"}
    };
    for(int i=0;i<6;i++) {
        const auto &button=buttons[i];
        if(i)ImGui::SameLine(0,3);
        const bool active=(g_tool==button.tool);
        if(active)ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.55f,.30f,.10f,1.0f));
        if(ImGui::Button(button.glyph,ImVec2(35,17)))g_tool=button.tool;
        if(active)ImGui::PopStyleColor();
        if(ImGui::IsItemHovered())ImGui::SetTooltip("%s",button.hint);
    }
    ImGui::SameLine(0,8);
    ImGui::TextDisabled(g_mode==MODE_TILES?"TOOLS":"PLACE / SELECT / ERASE");
    ImGui::EndChild();
}

static void draw_asset_shelf()
{
    ImGui::BeginChild("##asset_shelf",ImVec2(0,34),true);
    const char *heading=g_mode==MODE_TILES?"GAME TILES":
        g_mode==MODE_ENTITY?"LIVE SPRITES":g_mode==MODE_BOSS?"SPRITE PARTS":
        g_mode==MODE_ASSETS?"DRAW":"EVENTS";
    ImGui::TextColored(ImVec4(.46f,.83f,.88f,1),"%s",heading);

    if(g_mode==MODE_TILES){
        ImGui::SameLine();
        if(ImGui::SmallButton("<"))g_tile_shelf_offset=std::max(0,g_tile_shelf_offset-4);
        for(int i=g_tile_shelf_offset;i<g_live_tile_count&&i<g_tile_shelf_offset+4;i++){
            ImGui::SameLine(0,2);
            const int tile=g_live_tile_ids[i];
            ImGui::PushID(tile);
            ImVec2 p=ImGui::GetCursorScreenPos();
            ImGui::InvisibleButton("##tile_pick",ImVec2(28,30));
            ImDrawList *d=ImGui::GetWindowDrawList();
            const bool selected=(g_brush_tile&0x7ff)==tile;
            d->AddRectFilled(p,ImVec2(p.x+28,p.y+30),selected?IM_COL32(71,49,27,255):IM_COL32(14,22,31,255),2.0f);
            draw_vdp_tile(d,ImVec2(p.x+3,p.y+4),22.0f,tile|(g_selected_palette<<13));
            d->AddRect(p,ImVec2(p.x+28,p.y+30),selected?IM_COL32(255,190,76,255):IM_COL32(82,105,120,255),2.0f,0,selected?2.0f:1.0f);
            if(ImGui::IsItemClicked()){g_brush_tile=tile|(g_selected_palette<<13);g_tool=TOOL_TILE_BRUSH;}
            ImGui::PopID();
        }
        ImGui::SameLine(0,2);
        if(ImGui::SmallButton(">"))g_tile_shelf_offset=std::min(std::max(0,g_live_tile_count-4),g_tile_shelf_offset+4);
        if(g_live_tile_count==0){ImGui::SameLine();ImGui::TextDisabled("ENTER A STAGE TO CAPTURE TILES");}
        ImGui::SameLine();
        ImGui::TextDisabled("PAL");
        for(int pal=0;pal<4;pal++){
            ImGui::SameLine(0,1);
            char label[4];std::snprintf(label,sizeof(label),"%d",pal);
            if(g_selected_palette==pal)ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.50f,.27f,.10f,1));
            if(ImGui::SmallButton(label))g_selected_palette=pal;
            if(g_selected_palette==pal)ImGui::PopStyleColor();
        }
    }else if(g_mode==MODE_ENTITY||g_mode==MODE_BOSS){
        ImGui::SameLine();
        if(g_live_sprite_count==0){
            ImGui::TextDisabled("ENTER A STAGE TO CAPTURE LIVE SPRITES");
        }else{
            const int shown=std::min(5,g_live_sprite_count);
            for(int i=0;i<shown;i++){
                ImGui::SameLine(0,3);
                ImGui::PushID(2000+i);
                const LiveSpritePart &sprite=g_live_sprites[i];
                ImVec2 p=ImGui::GetCursorScreenPos();
                ImGui::InvisibleButton("##sprite_pick",ImVec2(36,34));
                ImDrawList *d=ImGui::GetWindowDrawList();
                const bool active=g_selected_sprite==i;
                d->AddRectFilled(p,ImVec2(p.x+36,p.y+34),active?IM_COL32(71,49,27,255):IM_COL32(14,22,31,255),2.0f);
                const float scale=24.0f/(float)std::max(sprite.width_tiles,sprite.height_tiles);
                const float sw=scale*sprite.width_tiles,sh=scale*sprite.height_tiles;
                draw_vdp_sprite(d,ImVec2(p.x+(28.0f-sw)*.5f,p.y+(24.0f-sh)*.5f),
                                scale,sprite.tile_attr,sprite.width_tiles,sprite.height_tiles);
                d->AddRect(p,ImVec2(p.x+28,p.y+24),active?IM_COL32(255,190,76,255):IM_COL32(82,105,120,255),2.0f,0,active?2.0f:1.0f);
                if(ImGui::IsItemClicked()){
                    g_selected_sprite=i;
                    g_status[0]=0;
                }
                ImGui::PopID();
            }
            ImGui::SameLine();
            ImGui::TextDisabled("%d LIVE PARTS",g_live_sprite_count);
        }
    }else if(g_mode==MODE_ASSETS){
        ImGui::SameLine();if(ImGui::SmallButton("16 x 16"))g_asset_size=16;
        ImGui::SameLine();if(ImGui::SmallButton("32 x 32"))g_asset_size=32;
        ImGui::SameLine();ImGui::Checkbox("RGBA",&g_asset_modern);
    }else{
        ImGui::SameLine();if(ImGui::SmallButton("+ WHEN"))add_event_node(0);
        ImGui::SameLine();if(ImGui::SmallButton("+ TALK"))add_event_node(1);
        ImGui::SameLine();if(ImGui::SmallButton("+ ACTION"))add_event_node(2);
        ImGui::SameLine();if(ImGui::SmallButton("+ BOSS"))add_event_node(3);
    }
    ImGui::EndChild();
}
static void push_level_undo()
{
    if(g_undo_count>=12){
        std::memmove(g_undo_stack,g_undo_stack+1,sizeof(g_undo_stack[0])*11);
        g_undo_count=11;
    }
    std::memcpy(g_undo_stack[g_undo_count++],g_level_tiles,sizeof(g_level_tiles));
    g_redo_count=0;
}
static void undo_level_edit()
{
    if(g_undo_count<=0)return;
    if(g_redo_count>=12){
        std::memmove(g_redo_stack,g_redo_stack+1,sizeof(g_redo_stack[0])*11);
        g_redo_count=11;
    }
    std::memcpy(g_redo_stack[g_redo_count++],g_level_tiles,sizeof(g_level_tiles));
    std::memcpy(g_level_tiles,g_undo_stack[--g_undo_count],sizeof(g_level_tiles));
    g_document_dirty=true;
    std::snprintf(g_status,sizeof(g_status),"UNDONE");
}
static void redo_level_edit()
{
    if(g_redo_count<=0)return;
    if(g_undo_count>=12){
        std::memmove(g_undo_stack,g_undo_stack+1,sizeof(g_undo_stack[0])*11);
        g_undo_count=11;
    }
    std::memcpy(g_undo_stack[g_undo_count++],g_level_tiles,sizeof(g_level_tiles));
    std::memcpy(g_level_tiles,g_redo_stack[--g_redo_count],sizeof(g_level_tiles));
    g_document_dirty=true;
    std::snprintf(g_status,sizeof(g_status),"REDONE");
}

static void draw_top_bar()
{
    ImGui::BeginChild("##topbar",ImVec2(0,20),true);
    ImDrawList *d=ImGui::GetWindowDrawList();
    ImVec2 p=ImGui::GetWindowPos();
    d->AddRectFilled(p,ImVec2(p.x+ImGui::GetWindowWidth(),p.y+20),IM_COL32(7,11,18,255));
    ImGui::TextColored(ImVec4(1.0f,.66f,.22f,1),"MEGA TURRICAN");
    ImGui::SameLine();ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"MAKER");
    ImGui::SameLine();ImGui::TextDisabled("/ %s",g_level_name);
    ImGui::EndChild();
}
} // namespace

extern "C" void mtlb_update_vdp_resources(const uint8_t *vram,const uint16_t *cram,const uint8_t *regs)
{
    if(!vram||!cram||!regs)return;
    uint32_t hash=2166136261u;
    for(size_t i=0;i<65536;i++)hash=(hash^vram[i])*16777619u;
    for(size_t i=0;i<64;i++){
        hash=(hash^(uint8_t)(cram[i]&255u))*16777619u;
        hash=(hash^(uint8_t)(cram[i]>>8))*16777619u;
    }
    for(size_t i=0;i<32;i++)hash=(hash^regs[i])*16777619u;
    if(hash==g_live_art_hash)return;
    g_live_art_hash=hash;
    std::memcpy(g_live_vram,vram,sizeof(g_live_vram));
    std::memcpy(g_live_cram,cram,sizeof(g_live_cram));
    std::memcpy(g_live_regs,regs,sizeof(g_live_regs));

    g_live_tile_count=0;
    for(int tile=1;tile<2048&&g_live_tile_count<256;tile++){
        const uint8_t *pattern=&g_live_vram[tile*32];
        bool visible=false;
        for(int i=0;i<32;i++)if(pattern[i]){visible=true;break;}
        if(visible)g_live_tile_ids[g_live_tile_count++]=tile;
    }

    // Genesis VDP register 5 points to a linked Sprite Attribute Table.
    g_live_sprite_count=0;
    const int h40=(g_imgui_width==320);
    const uint32_t satBase=(uint32_t)(g_live_regs[5]&(h40?0x7Eu:0x7Fu))<<9;
    const int maxSprites=h40?80:64;
    bool visited[128]={};
    unsigned link=0;
    for(int n=0;n<maxSprites&&link<128&&!visited[link];n++){
        visited[link]=true;
        const uint32_t at=(satBase+link*8u)&0xFFFFu;
        const uint8_t size=g_live_vram[(at+2u)&0xFFFFu];
        const unsigned next=g_live_vram[(at+3u)&0xFFFFu]&0x7Fu;
        const uint16_t attr=(uint16_t)(((uint16_t)g_live_vram[(at+4u)&0xFFFFu]<<8)|
                                        g_live_vram[(at+5u)&0xFFFFu]);
        const int height=(size&3u)+1;
        const int width=((size>>2)&3u)+1;
        const uint16_t yword=(uint16_t)(((uint16_t)g_live_vram[at]<<8)|g_live_vram[(at+1u)&0xFFFFu]);
        const uint16_t xword=(uint16_t)(((uint16_t)g_live_vram[(at+6u)&0xFFFFu]<<8)|g_live_vram[(at+7u)&0xFFFFu]);
        const unsigned xraw=xword&0x01FFu;
        // X=0 is the Genesis SAT sprite-mask entry; later linked sprites do
        // not reach the renderer once this marker is encountered.
        if(xraw==0u && g_live_sprite_count>0)break;
        if(xraw!=0u && (attr&0x07FFu)!=0 && g_live_sprite_count<80){
            LiveSpritePart &sprite=g_live_sprites[g_live_sprite_count++];
            sprite.tile_attr=attr;
            sprite.width_tiles=(uint8_t)width;
            sprite.height_tiles=(uint8_t)height;
            sprite.x=(int16_t)(xraw-128);
            sprite.y=(int16_t)((yword&0x03FFu)-128);
        }
        if(next==0)break;
        link=next;
    }
}
extern "C" int mtlb_map_cols(void) { return kEditorMapCols; }
extern "C" int mtlb_map_rows(void) { return kEditorMapRows; }
extern "C" int mtlb_map_get(int x,int y)
{
    if(x<0||y<0||x>=kEditorMapCols||y>=kEditorMapRows)return 0;
    return (int)g_level_tiles[y*kEditorMapCols+x];
}
extern "C" void mtlb_map_set(int x,int y,int tile)
{
    if(x<0||y<0||x>=kEditorMapCols||y>=kEditorMapRows)return;
    const std::uint16_t value=(std::uint16_t)std::max(0,std::min(65535,tile));
    const int index=y*kEditorMapCols+x;
    if(g_level_tiles[index]!=value){g_level_tiles[index]=value;g_document_dirty=true;}
}
static bool mtlb_level_document_path(char *path,size_t capacity)
{
    char *base=SDL_GetBasePath();if(!base)return false;
    char folder[4096];
    const int folderLen=std::snprintf(folder,sizeof(folder),"%slevels",base);
    const int pathLen=std::snprintf(path,capacity,"%s/untitled.mtlb",folder);
    SDL_free(base);
    if(folderLen<0||pathLen<0||(size_t)folderLen>=sizeof(folder)||(size_t)pathLen>=capacity)return false;
#ifdef _WIN32
    _mkdir(folder);
#else
    mkdir(folder,0775);
#endif
    return true;
}
extern "C" int mtlb_map_save(void)
{
    char path[4096];if(!mtlb_level_document_path(path,sizeof(path)))return 0;
    FILE *file=std::fopen(path,"wb");if(!file)return 0;
    const char magic[8]={'M','T','L','B','L','V','L',2};
    const std::uint32_t cols=kEditorMapCols,rows=kEditorMapRows;
    const std::uint32_t entityCount=(std::uint32_t)g_entity_count;
    bool ok=std::fwrite(magic,1,sizeof(magic),file)==sizeof(magic)&&
        std::fwrite(&cols,sizeof(cols),1,file)==1&&std::fwrite(&rows,sizeof(rows),1,file)==1&&
        std::fwrite(g_level_tiles,sizeof(g_level_tiles),1,file)==1&&
        std::fwrite(&entityCount,sizeof(entityCount),1,file)==1&&
        std::fwrite(g_entities,sizeof(EditorEntity),g_entity_count,file)==(size_t)g_entity_count;
    if(std::fclose(file)!=0)ok=false;
    if(ok)g_document_dirty=false;
    return ok?1:0;
}
extern "C" int mtlb_map_load(void)
{
    char path[4096];if(!mtlb_level_document_path(path,sizeof(path)))return 0;
    FILE *file=std::fopen(path,"rb");if(!file)return 0;
    char magic[8]={};std::uint32_t cols=0,rows=0;
    std::uint16_t loaded[kEditorMapCols*kEditorMapRows]={};
    bool ok=std::fread(magic,1,sizeof(magic),file)==sizeof(magic)&&
        std::memcmp(magic,"MTLBLVL",7)==0&&
        ((unsigned char)magic[7]==1||(unsigned char)magic[7]==2)&&
        std::fread(&cols,sizeof(cols),1,file)==1&&std::fread(&rows,sizeof(rows),1,file)==1&&
        cols==(std::uint32_t)kEditorMapCols&&rows==(std::uint32_t)kEditorMapRows&&
        std::fread(loaded,sizeof(loaded),1,file)==1;
    std::uint32_t entityCount=0;
    EditorEntity loadedEntities[64]={};
    if(ok&&(unsigned char)magic[7]==2){
        ok=std::fread(&entityCount,sizeof(entityCount),1,file)==1&&entityCount<=64&&
           std::fread(loadedEntities,sizeof(EditorEntity),entityCount,file)==entityCount;
    }
    std::fclose(file);
    if(!ok)return 0;
    std::memcpy(g_level_tiles,loaded,sizeof(g_level_tiles));
    std::memcpy(g_entities,loadedEntities,sizeof(g_entities));
    g_entity_count=(unsigned char)magic[7]==2?(int)entityCount:0;
    g_selected_entity=-1;
    g_document_dirty=false;
    return 1;
}
extern "C" int mtlb_map_cursor_x(void) { return g_selected_x; }
extern "C" int mtlb_map_cursor_y(void) { return g_selected_y; }
extern "C" int mtlb_map_brush(void) { return g_brush_tile; }

extern "C" int mtlb_init(SDL_Window *window,int width,int height)
{
    if(g_initialized)return 1;
    if(!window||width<=0||height<=0)return 0;

    g_imgui_width=width;
    g_imgui_height=height;
    g_imgui_surface=SDL_CreateRGBSurfaceWithFormat(
        0,g_imgui_width,g_imgui_height,32,SDL_PIXELFORMAT_ARGB8888);
    if(!g_imgui_surface)return 0;
    g_imgui_surface_renderer=SDL_CreateSoftwareRenderer(g_imgui_surface);
    if(!g_imgui_surface_renderer){
        SDL_FreeSurface(g_imgui_surface);
        g_imgui_surface=nullptr;
        return 0;
    }

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO &io=ImGui::GetIO();
    io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard;
    io.IniFilename=nullptr;
    apply_theme();

    g_window=window;
    g_sdl_backend=ImGui_ImplSDL2_InitForSDLRenderer(window,g_imgui_surface_renderer);
    if(!g_sdl_backend){
        ImGui::DestroyContext();
        SDL_DestroyRenderer(g_imgui_surface_renderer);
        SDL_FreeSurface(g_imgui_surface);
        g_imgui_surface_renderer=nullptr;
        g_imgui_surface=nullptr;
        g_window=nullptr;
        return 0;
    }
    g_renderer_backend=ImGui_ImplSDLRenderer2_Init(g_imgui_surface_renderer);
    if(!g_renderer_backend){
        ImGui_ImplSDL2_Shutdown();
        g_sdl_backend=false;
        ImGui::DestroyContext();
        SDL_DestroyRenderer(g_imgui_surface_renderer);
        SDL_FreeSurface(g_imgui_surface);
        g_imgui_surface_renderer=nullptr;
        g_imgui_surface=nullptr;
        g_window=nullptr;
        return 0;
    }

    g_selected_x=std::max(0,mtlb_map_cursor_x());
    g_selected_y=std::max(0,mtlb_map_cursor_y());
    g_brush_tile=std::max(0,std::min(2047,mtlb_map_brush()));
    g_fade_in_frame=0;
    g_fade_out_frame=-1;
    g_exit_requested=false;
    g_initialized=true;
    return 1;
}

extern "C" void mtlb_shutdown(void)
{
    if(!g_initialized)return;
    if(g_renderer_backend)ImGui_ImplSDLRenderer2_Shutdown();
    if(g_sdl_backend)ImGui_ImplSDL2_Shutdown();
    ImGui::DestroyContext();
    if(g_imgui_surface_renderer)SDL_DestroyRenderer(g_imgui_surface_renderer);
    if(g_imgui_surface)SDL_FreeSurface(g_imgui_surface);
    g_imgui_surface_renderer=nullptr;
    g_imgui_surface=nullptr;
    g_renderer_backend=false;
    g_sdl_backend=false;
    g_initialized=false;
    g_window=nullptr;
    g_last_painted_x=-1;
    g_last_painted_y=-1;
}

extern "C" void mtlb_process_event(const SDL_Event *event)
{
    if (g_initialized && event) ImGui_ImplSDL2_ProcessEvent(event);
}



extern "C" int mtlb_render_to_framebuffer(uint32_t *framebuffer,int width,int height,int pitch_pixels)
{
    if(!g_initialized||!g_imgui_surface||!g_imgui_surface_renderer||!framebuffer||
       width<=0||height<=0||pitch_pixels<width)return 0;
    if(width!=g_imgui_width||height!=g_imgui_height){
        ImGui_ImplSDLRenderer2_Shutdown();g_renderer_backend=false;
        SDL_DestroyRenderer(g_imgui_surface_renderer);SDL_FreeSurface(g_imgui_surface);
        g_imgui_surface=nullptr;g_imgui_surface_renderer=nullptr;
        g_imgui_width=width;g_imgui_height=height;
        g_imgui_surface=SDL_CreateRGBSurfaceWithFormat(0,width,height,32,SDL_PIXELFORMAT_ARGB8888);
        if(!g_imgui_surface)return 0;
        g_imgui_surface_renderer=SDL_CreateSoftwareRenderer(g_imgui_surface);
        if(!g_imgui_surface_renderer)return 0;
        if(!ImGui_ImplSDLRenderer2_Init(g_imgui_surface_renderer))return 0;
        g_renderer_backend=true;
    }
    ImGui_ImplSDLRenderer2_NewFrame();ImGui_ImplSDL2_NewFrame();
    ImGuiIO &io=ImGui::GetIO();
    int windowW=width,windowH=height;SDL_GetWindowSize(g_window,&windowW,&windowH);
    ImVec2 mouse=io.MousePos;
    if(mouse.x>=0&&mouse.y>=0&&windowW>0&&windowH>0){
        mouse.x*=((float)width/windowW);mouse.y*=((float)height/windowH);io.MousePos=mouse;
    }
    io.DisplaySize=ImVec2((float)width,(float)height);io.DisplayFramebufferScale=ImVec2(1,1);
    ImGui::NewFrame();
    if(!g_exit_requested&&!io.WantTextInput&&ImGui::IsKeyPressed(ImGuiKey_Escape,false))g_exit_requested=true;
    ImGui::SetNextWindowPos(ImVec2(0,0));ImGui::SetNextWindowSize(io.DisplaySize);
    ImGui::SetNextWindowBgAlpha(1);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,ImVec2(3,2));
    ImGui::Begin("##MT_MAKER_ROOT",nullptr,
        ImGuiWindowFlags_NoTitleBar|ImGuiWindowFlags_NoResize|ImGuiWindowFlags_NoMove|
        ImGuiWindowFlags_NoCollapse|ImGuiWindowFlags_NoSavedSettings|
        ImGuiWindowFlags_NoScrollbar|ImGuiWindowFlags_NoScrollWithMouse|
        ImGuiWindowFlags_NoBringToFrontOnFocus);
    draw_top_bar();
    draw_layer_bar();
    draw_asset_shelf();
    const float bottomHeight=25;
    const float workspaceHeight=std::max(58.0f,io.DisplaySize.y-20.0f-28.0f-34.0f-26.0f-bottomHeight-14.0f);
    draw_tool_palette();
    ImGui::BeginChild("##maker_workspace",ImVec2(0,workspaceHeight),false);
    ImGui::BeginChild("##maker_stage",ImVec2(0,0),true);
    draw_center_view();
    ImGui::EndChild();ImGui::EndChild();
    draw_bottom_workspace();
    ImGui::End();ImGui::PopStyleVar();ImGui::Render();

    SDL_SetRenderDrawBlendMode(g_imgui_surface_renderer,SDL_BLENDMODE_NONE);
    SDL_SetRenderDrawColor(g_imgui_surface_renderer,0,0,0,255);
    SDL_RenderClear(g_imgui_surface_renderer);
    ImGui_ImplSDLRenderer2_RenderDrawData(ImGui::GetDrawData(),g_imgui_surface_renderer);

    const int gridW=20,gridH=15,total=gridW*gridH,frames=12;
    const bool closing=g_exit_requested;
    if(closing&&g_fade_out_frame<0)g_fade_out_frame=0;
    const int revealed=std::min(total,g_fade_in_frame*total/frames);
    const int covered=closing?std::min(total,g_fade_out_frame*total/frames):0;
    SDL_SetRenderDrawBlendMode(g_imgui_surface_renderer,SDL_BLENDMODE_NONE);
    SDL_SetRenderDrawColor(g_imgui_surface_renderer,0,0,0,255);
    for(int i=0;i<total;i++){
        const int rank=(i*73+19)%total;
        const bool black=closing?(rank<covered):(rank>=revealed);
        if(!black)continue;
        const int x=i%gridW,y=i/gridW;
        SDL_Rect block={x*width/gridW,y*height/gridH,
            (x+1)*width/gridW-x*width/gridW,(y+1)*height/gridH-y*height/gridH};
        SDL_RenderFillRect(g_imgui_surface_renderer,&block);
    }
    SDL_RenderPresent(g_imgui_surface_renderer);
    if(SDL_MUSTLOCK(g_imgui_surface))SDL_LockSurface(g_imgui_surface);
    for(int y=0;y<height;y++){
        const uint32_t *src=(const uint32_t*)((const uint8_t*)g_imgui_surface->pixels+y*g_imgui_surface->pitch);
        uint32_t *dst=framebuffer+y*pitch_pixels;
        for(int x=0;x<width;x++){
            const uint32_t p=src[x];const unsigned a=(p>>24)&255u,r=(p>>16)&255u,g=(p>>8)&255u,b=p&255u;
            if(a==255)dst[x]=(r<<16)|(g<<8)|b;
            else if(a){const uint32_t old=dst[x],inv=255u-a;
                dst[x]=(((r*a+((old>>16)&255u)*inv)/255u)<<16)|
                       (((g*a+((old>>8)&255u)*inv)/255u)<<8)|
                       ((b*a+(old&255u)*inv)/255u);}
        }
    }
    if(SDL_MUSTLOCK(g_imgui_surface))SDL_UnlockSurface(g_imgui_surface);
    if(closing){if(g_fade_out_frame<frames)g_fade_out_frame++;return g_fade_out_frame>=frames;}
    if(g_fade_in_frame<frames)g_fade_in_frame++;
    return 0;
}
