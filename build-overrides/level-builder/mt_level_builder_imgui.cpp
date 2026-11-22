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
    TOOL_EVENT_WIRE
};

static bool g_initialized = false;
static bool g_sdl_backend = false;
static bool g_renderer_backend = false;
static SDL_Window *g_window = nullptr;
static EditorMode g_mode = MODE_TILES;
static EditorTool g_tool = TOOL_TILE_BRUSH;
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

struct EditorEntity { float x,y; int type,hp; };
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

    s.WindowPadding = ImVec2(9.0f, 8.0f);
    s.FramePadding = ImVec2(9.0f, 6.0f);
    s.ItemSpacing = ImVec2(7.0f, 6.0f);
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

static ImU32 tile_color(int tile)
{
    const int v = tile & 0x7ff;
    const int r = 25 + ((v * 7) % 24);
    const int g = 34 + ((v * 11) % 28);
    const int b = 45 + ((v * 5) % 34);
    return IM_COL32(r, g, b, 245);
}

static void draw_stage_canvas()
{
    const int cols=mtlb_map_cols(),rows=mtlb_map_rows();
    g_selected_x=std::max(0,std::min(cols-1,g_selected_x));
    g_selected_y=std::max(0,std::min(rows-1,g_selected_y));
    g_map_origin_x=std::max(0,std::min(cols-16,g_selected_x-8));
    g_map_origin_y=std::max(0,std::min(rows-16,g_selected_y-8));

    ImGui::TextColored(ImVec4(.38f,.83f,.89f,1),"%s",g_level_name);
    ImGui::SameLine();ImGui::TextDisabled(" / EMPTY DOCUMENT / %d x %d TILES",cols,rows);
    ImGui::SameLine();ImGui::SetCursorPosX(ImGui::GetWindowWidth()-164.0f);
    if(ImGui::SmallButton(g_show_grid?"GRID ON":"GRID OFF"))g_show_grid=!g_show_grid;
    ImGui::SameLine();if(ImGui::SmallButton("CENTER")){g_selected_x=cols/2;g_selected_y=rows/2;}

    ImGui::BeginChild("##stage_canvas",ImVec2(0,0),true);
    ImVec2 avail=ImGui::GetContentRegionAvail();
    const float aspect=(float)g_stage_width/(float)g_stage_height;
    float w=std::max(240.0f,avail.x-12.0f),h=w/aspect;
    if(h>avail.y-12.0f){h=std::max(140.0f,avail.y-12.0f);w=h*aspect;}
    ImVec2 origin=ImGui::GetCursorScreenPos();origin.x+=(avail.x-w)*0.5f;
    ImVec2 finish(origin.x+w,origin.y+h);ImDrawList *d=ImGui::GetWindowDrawList();

    // Empty editor document: no title/game framebuffer, preview art or sample actors.
    d->AddRectFilled(ImVec2(origin.x-5,origin.y-5),ImVec2(finish.x+5,finish.y+5),IM_COL32(4,7,12,255),3.0f);
    d->AddRectFilled(origin,finish,IM_COL32(12,18,27,255));
    d->AddRect(origin,finish,IM_COL32(91,116,133,255),1.0f,1.5f);

    const float cw=w/16.0f,ch=h/16.0f;
    for(int y=0;y<16;y++)for(int x=0;x<16;x++){
        const int tile=mtlb_map_get(g_map_origin_x+x,g_map_origin_y+y);
        if(tile==0)continue;
        ImVec2 a(origin.x+x*cw,origin.y+y*ch),b(a.x+cw,a.y+ch);
        d->AddRectFilled(a,b,tile_color(tile));
        if(cw>=22.0f){char v[8];std::snprintf(v,sizeof(v),"%03X",tile);d->AddText(ImVec2(a.x+3,a.y+3),IM_COL32(218,229,236,245),v);}
    }
    if(g_show_grid&&g_layers[2])for(int i=0;i<=16;i++){
        float x=origin.x+i*cw,y=origin.y+i*ch;
        d->AddLine(ImVec2(x,origin.y),ImVec2(x,finish.y),IM_COL32(112,156,169,105));
        d->AddLine(ImVec2(origin.x,y),ImVec2(finish.x,y),IM_COL32(112,156,169,105));
    }

    ImGui::SetCursorScreenPos(origin);
    ImGui::InvisibleButton("##stage_surface",ImVec2(w,h),ImGuiButtonFlags_MouseButtonLeft|ImGuiButtonFlags_MouseButtonRight);
    if(ImGui::IsItemHovered()){
        ImVec2 m=ImGui::GetIO().MousePos;
        int cx=std::max(0,std::min(15,(int)((m.x-origin.x)/cw)));
        int cy=std::max(0,std::min(15,(int)((m.y-origin.y)/ch)));
        int mx=g_map_origin_x+cx,my=g_map_origin_y+cy;
        if(g_mode==MODE_TILES){
            g_selected_x=mx;g_selected_y=my;
            if(ImGui::IsMouseClicked(ImGuiMouseButton_Right)){g_brush_tile=mtlb_map_get(mx,my);std::snprintf(g_status,sizeof(g_status),"SAMPLED TILE %03X / CELL %d,%d",g_brush_tile,mx,my);}
            if(ImGui::IsMouseDown(ImGuiMouseButton_Left)&&g_tool==TOOL_TILE_BRUSH&&g_brush_tile>0){mtlb_map_set(mx,my,g_brush_tile);std::snprintf(g_status,sizeof(g_status),"PAINTED TILE %03X / CELL %d,%d",g_brush_tile,mx,my);}
        }else if(g_mode==MODE_ENTITY&&ImGui::IsMouseClicked(ImGuiMouseButton_Left)&&g_entity_count<64){
            EditorEntity &e=g_entities[g_entity_count++];e.x=(m.x-origin.x)/w;e.y=(m.y-origin.y)/h;e.type=g_entity_type;e.hp=100;g_selected_entity=g_entity_count-1;
        }
    }
    for(int i=0;i<g_entity_count;i++){EditorEntity &e=g_entities[i];ImVec2 p(origin.x+e.x*w,origin.y+e.y*h);d->AddCircleFilled(p,7.0f,IM_COL32(245,157,48,240));d->AddCircle(p,10.0f,IM_COL32(255,224,147,255),16,2.0f);}
    if(g_mode==MODE_BOSS&&g_boss_created)d->AddText(ImVec2(origin.x+12,origin.y+12),IM_COL32(255,206,112,255),"BOSS CORE");
    if(g_mode==MODE_TILES){int sx=g_selected_x-g_map_origin_x,sy=g_selected_y-g_map_origin_y;ImVec2 a(origin.x+sx*cw,origin.y+sy*ch),b(a.x+cw,a.y+ch);d->AddRect(a,b,IM_COL32(255,179,62,255),0.0f,2.5f);}
    ImGui::SetCursorScreenPos(ImVec2(origin.x,finish.y+5));
    ImGui::TextDisabled("CURSOR X:%03d Y:%03d / SNAP 8 PX / BRUSH %03X / %s",g_selected_x,g_selected_y,g_brush_tile,g_document_dirty?"UNSAVED CHANGES":"DOCUMENT CLEAN");
    ImGui::EndChild();
}

static void draw_placeholder_viewport(const char *title, const char *description)
{
    ImGui::TextColored(ImVec4(0.34f, 0.78f, 0.83f, 1.0f), "%s", title);
    ImGui::Separator();
    ImGui::Spacing();
    ImGui::TextWrapped("%s", description);
    ImGui::Spacing();
    ImGui::BeginChild("##module_preview", ImVec2(0.0f, 220.0f), true);
    const ImVec2 p = ImGui::GetCursorScreenPos();
    const ImVec2 a(p.x + 12.0f, p.y + 12.0f);
    const ImVec2 b(a.x + 280.0f, a.y + 150.0f);
    ImDrawList *draw = ImGui::GetWindowDrawList();
    draw->AddRectFilled(a, b, IM_COL32(9, 15, 22, 255), 2.0f);
    draw->AddRect(a, b, IM_COL32(56, 81, 96, 255));
    draw->AddLine(ImVec2(a.x + 15.0f, a.y + 76.0f),
                  ImVec2(b.x - 15.0f, a.y + 76.0f), IM_COL32(35, 72, 84, 255));
    draw->AddText(ImVec2(a.x + 15.0f, a.y + 18.0f),
                  IM_COL32(255, 174, 54, 255), "MODULE ONLINE");
    draw->AddText(ImVec2(a.x + 15.0f, a.y + 48.0f),
                  IM_COL32(163, 184, 196, 255), "EDITOR SYSTEM / FOUNDATION");
    draw->AddText(ImVec2(a.x + 15.0f, a.y + 104.0f),
                  IM_COL32(83, 192, 202, 255), "DATA PIPELINE PENDING");
    ImGui::EndChild();
}

static void draw_tool_palette() { draw_advanced_tool_palette(); }

static void draw_layer_bar() { draw_advanced_layers(); }

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
    for(int row=0;row<3;row++){ImGui::TextColored(ImVec4(.67f,.75f,.81f,1),"%s",names[row]);ImGui::SameLine(58);ImVec2 p=ImGui::GetCursorScreenPos();float w=ImGui::GetContentRegionAvail().x;ImDrawList *d=ImGui::GetWindowDrawList();d->AddRectFilled(p,ImVec2(p.x+w,p.y+14),IM_COL32(34,41,55,255));d->AddRectFilled(ImVec2(p.x+w*(row==0?.05f:row==1?.25f:.45f),p.y+2),ImVec2(p.x+w*(row==0?.48f:row==1?.63f:.82f),p.y+12),colors[row],2);float play=p.x+w*(g_selected_frame/8.0f);d->AddLine(ImVec2(play,p.y-2),ImVec2(play,p.y+16),IM_COL32(255,100,70,255),2);ImGui::Dummy(ImVec2(w,15));}
    ImGui::TextDisabled("FRAME %02d / DURATION 6 TICKS / HITBOX & SFX TRACKS",g_selected_frame+1);ImGui::EndChild();
}
static void draw_bottom_workspace()
{
    ImGui::BeginChild("##workspace_bottom",ImVec2(0,126),true);
    if(g_mode==MODE_EVENTS||g_mode==MODE_ASSETS)draw_timeline_panel();
    else {
        ImGui::TextColored(ImVec4(.43f,.84f,.90f,1),"LEVEL EVENT SUMMARY");
        ImGui::SameLine();
        ImGui::TextDisabled("%02d NODES / %02d LINKS",g_node_count,g_link_count);
        if(g_node_count==0)
            ImGui::TextDisabled("NO EVENTS CREATED FOR THIS LEVEL");
        else
            ImGui::TextDisabled("EVENT GRAPH DATA IS STORED IN THIS LEVEL DOCUMENT");
    }
    ImGui::EndChild();
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
        ImGui::Separator();if(ImGui::Button("SAVE LEVEL",ImVec2(-1,30))){bool ok=mtlb_map_save();std::snprintf(g_status,sizeof(g_status),"%s",ok?"SAVED /levels/slot1.mtl":"SAVE FAILED");}
        if(ImGui::Button("LOAD LEVEL",ImVec2(-1,28))){bool ok=mtlb_map_load();std::snprintf(g_status,sizeof(g_status),"%s",ok?"LOADED /levels/slot1.mtl":"LOAD FAILED");}
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
static void draw_top_bar()
{
    ImGui::BeginChild("##topbar",ImVec2(0,48),true);
    ImVec2 a=ImGui::GetWindowPos(),b(a.x+ImGui::GetWindowWidth(),a.y+48);
    ImDrawList *d=ImGui::GetWindowDrawList();
    d->AddRectFilled(a,b,IM_COL32(7,11,18,255));
    d->AddLine(ImVec2(a.x,a.y+46),ImVec2(b.x,b.y+46),IM_COL32(120,145,161,255),2);
    ImGui::TextColored(ImVec4(1,.66f,.22f,1),"MEGA");
    ImGui::SameLine();ImGui::TextColored(ImVec4(.83f,.88f,.93f,1),"TURRICAN");
    ImGui::SameLine();ImGui::TextColored(ImVec4(.39f,.81f,.88f,1),"REBORN / LEVEL SYSTEM");
    ImGui::SameLine();ImGui::Dummy(ImVec2(8,1));ImGui::SameLine();
    mode_button("TILES",MODE_TILES,70);ImGui::SameLine();mode_button("ENTITY",MODE_ENTITY,78);
    ImGui::SameLine();mode_button("SCRIPT",MODE_EVENTS,76);ImGui::SameLine();mode_button("ASSETS",MODE_ASSETS,76);
    ImGui::SameLine();mode_button("BOSS",MODE_BOSS,70);ImGui::SameLine();ImGui::Dummy(ImVec2(5,1));ImGui::SameLine();
    ImGui::BeginDisabled();ImGui::Button("START",ImVec2(70,30));ImGui::EndDisabled();
    if(ImGui::IsItemHovered())ImGui::SetTooltip("Live playtest will hand Bren directly into the stage.");
    ImGui::SameLine();if(ImGui::Button("EXIT",ImVec2(52,30)))g_exit_requested=true;
    ImGui::EndChild();
}
} // namespace

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
    const std::uint16_t value=(std::uint16_t)std::max(0,std::min(2047,tile));
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
    const char magic[8]={'M','T','L','B','L','V','L',1};
    const std::uint32_t cols=kEditorMapCols,rows=kEditorMapRows;
    bool ok=std::fwrite(magic,1,sizeof(magic),file)==sizeof(magic)&&
        std::fwrite(&cols,sizeof(cols),1,file)==1&&std::fwrite(&rows,sizeof(rows),1,file)==1&&
        std::fwrite(g_level_tiles,sizeof(g_level_tiles),1,file)==1;
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
        std::memcmp(magic,"MTLBLVL",7)==0&&(unsigned char)magic[7]==1&&
        std::fread(&cols,sizeof(cols),1,file)==1&&std::fread(&rows,sizeof(rows),1,file)==1&&
        cols==(std::uint32_t)kEditorMapCols&&rows==(std::uint32_t)kEditorMapRows&&
        std::fread(loaded,sizeof(loaded),1,file)==1;
    std::fclose(file);
    if(!ok)return 0;
    std::memcpy(g_level_tiles,loaded,sizeof(g_level_tiles));g_document_dirty=false;return 1;
}
extern "C" int mtlb_map_cursor_x(void) { return g_selected_x; }
extern "C" int mtlb_map_cursor_y(void) { return g_selected_y; }
extern "C" int mtlb_map_brush(void) { return g_brush_tile; }

extern "C" int mtlb_init(SDL_Window *window, SDL_Renderer *renderer)
{
    if (g_initialized) return 1;
    if (!window || !renderer) return 0;

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO &io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io.IniFilename = nullptr;
    apply_theme();

    g_window = window;
    g_sdl_backend = ImGui_ImplSDL2_InitForSDLRenderer(window, renderer);
    if (!g_sdl_backend) {
        ImGui::DestroyContext();
        return 0;
    }
    g_renderer_backend = ImGui_ImplSDLRenderer2_Init(renderer);
    if (!g_renderer_backend) {
        ImGui_ImplSDL2_Shutdown();
        g_sdl_backend = false;
        ImGui::DestroyContext();
        return 0;
    }

    g_selected_x = std::max(0, mtlb_map_cursor_x());
    g_selected_y = std::max(0, mtlb_map_cursor_y());
    g_brush_tile = std::max(0, std::min(2047, mtlb_map_brush()));
    g_initialized = true;
    return 1;
}

extern "C" void mtlb_shutdown(void)
{
    if (!g_initialized) return;
    if (g_renderer_backend) ImGui_ImplSDLRenderer2_Shutdown();
    if (g_sdl_backend) ImGui_ImplSDL2_Shutdown();
    ImGui::DestroyContext();
    g_renderer_backend = false;
    g_sdl_backend = false;
    g_initialized = false;
    g_window = nullptr;
    g_last_painted_x = -1;
    g_last_painted_y = -1;
}

extern "C" void mtlb_process_event(const SDL_Event *event)
{
    if (g_initialized && event) ImGui_ImplSDL2_ProcessEvent(event);
}



extern "C" int mtlb_render(SDL_Renderer *renderer)
{
    if(!renderer)return 0;
    if(!g_initialized){
        SDL_Window *window=SDL_RenderGetWindow(renderer);
        if(!mtlb_init(window,renderer))return 0;
    }
    ImGui_ImplSDLRenderer2_NewFrame();
    ImGui_ImplSDL2_NewFrame();
    ImGui::NewFrame();
    const ImGuiIO &io=ImGui::GetIO();
    if(!g_exit_requested&&!io.WantTextInput&&ImGui::IsKeyPressed(ImGuiKey_Escape,false))
        g_exit_requested=true;

    const ImVec2 display=io.DisplaySize;
    const float height=std::max(560.0f,display.y);
    ImGui::SetNextWindowPos(ImVec2(0,0));
    ImGui::SetNextWindowSize(display);
    ImGui::SetNextWindowBgAlpha(1.0f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,ImVec2(8,7));
    ImGui::Begin("##MT_LEVEL_BUILDER_ROOT",nullptr,
        ImGuiWindowFlags_NoTitleBar|ImGuiWindowFlags_NoResize|ImGuiWindowFlags_NoMove|
        ImGuiWindowFlags_NoCollapse|ImGuiWindowFlags_NoSavedSettings|
        ImGuiWindowFlags_NoScrollbar|ImGuiWindowFlags_NoScrollWithMouse|
        ImGuiWindowFlags_NoBringToFrontOnFocus);

    draw_top_bar();
    const float work_height=std::max(340.0f,height-222.0f);
    const float left_width=g_mode==MODE_EVENTS?252.0f:88.0f;
    const float right_width=224.0f;
    const float center_width=std::max(360.0f,display.x-left_width-right_width-46.0f);
    ImGui::BeginChild("##tools",ImVec2(left_width,work_height),true);
    draw_tool_palette();
    ImGui::EndChild();
    ImGui::SameLine();
    ImGui::BeginChild("##center_column",ImVec2(center_width,work_height),false);
    draw_layer_bar();
    ImGui::PushStyleColor(ImGuiCol_ChildBg,ImVec4(.025f,.038f,.052f,1));
    ImGui::BeginChild("##stage_viewport",ImVec2(0,0),true);
    draw_center_view();
    ImGui::EndChild();
    ImGui::PopStyleColor();
    ImGui::EndChild();
    ImGui::SameLine();
    ImGui::BeginChild("##inspector",ImVec2(right_width,work_height),true);
    draw_inspector();
    ImGui::EndChild();
    ImGui::Spacing();
    draw_bottom_workspace();
    ImGui::TextColored(ImVec4(.39f,.81f,.88f,1),"SYSTEM");
    ImGui::SameLine();ImGui::TextDisabled("%s",g_status);
    ImGui::SameLine();ImGui::SetCursorPosX(ImGui::GetWindowWidth()-116);
    ImGui::TextDisabled("IMGUI 1.93.0");
    ImGui::End();
    ImGui::PopStyleVar();
    ImGui::Render();
    ImGui_ImplSDLRenderer2_RenderDrawData(ImGui::GetDrawData(),renderer);

    // Pixel-mosaic reveal on entry and the same effect in reverse on exit.
    int outputW=0,outputH=0;
    SDL_GetRendererOutputSize(renderer,&outputW,&outputH);
    const int gridW=20,gridH=15,total=gridW*gridH,frames=12;
    const bool closing=g_exit_requested;
    if(closing&&g_fade_out_frame<0)g_fade_out_frame=0;
    const int revealed=std::min(total,g_fade_in_frame*total/frames);
    const int covered=closing?std::min(total,g_fade_out_frame*total/frames):0;
    SDL_SetRenderDrawBlendMode(renderer,SDL_BLENDMODE_NONE);
    SDL_SetRenderDrawColor(renderer,0,0,0,255);
    for(int i=0;i<total;i++){
        const int rank=(i*73+19)%total;
        const bool black=closing?(rank<covered):(rank>=revealed);
        if(!black)continue;
        const int x=i%gridW,y=i/gridW;
        SDL_Rect block={x*outputW/gridW,y*outputH/gridH,
            (x+1)*outputW/gridW-x*outputW/gridW,
            (y+1)*outputH/gridH-y*outputH/gridH};
        SDL_RenderFillRect(renderer,&block);
    }
    if(closing){
        if(g_fade_out_frame<frames)g_fade_out_frame++;
        return g_fade_out_frame>frames;
    }
    if(g_fade_in_frame<frames)g_fade_in_frame++;
    return 0;
}
