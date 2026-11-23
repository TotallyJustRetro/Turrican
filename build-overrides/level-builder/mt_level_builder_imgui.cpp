#include "mt_level_builder_imgui.h"
#include "mt_maker_asset_catalog.h"

#include "imgui.h"
#include "imgui_impl_sdl2.h"
#include "imgui_impl_sdlrenderer2.h"

#include <algorithm>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
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
static SDL_Renderer *g_renderer = nullptr;
static int g_imgui_width = 320;
static int g_imgui_height = 224;
static float g_ui_scale = 1.0f;
static float g_theme_scale = 0.0f;
static float ui(float value) { return value * g_ui_scale; }
static uint8_t g_live_vram[65536] = {};
static uint16_t g_live_cram[64] = {};
static uint32_t g_live_art_hash = 0;
static int g_live_tile_ids[512] = {};
static int g_live_tile_count = 0;
/* f_C8A6: ROM $03AF80 -> VRAM $1600; D0=$0A00 words becomes $1400 bytes in f_6E6. */
static uint8_t g_rom_art_block[0x1400] = {};
static bool g_rom_art_valid = false;
/* Original 8 x 64-byte HUD animation uploads, confirmed at ROM $26D20/$26D40. */
static uint8_t g_rom_hud_art_a[0x0200] = {};
static uint8_t g_rom_hud_art_b[0x0200] = {};
static bool g_rom_hud_art_a_valid = false;
static bool g_rom_hud_art_b_valid = false;
/* f_4C70: twenty ROM-selected animation frames, each DMA-uploaded as 0x100 bytes to VRAM $3280. */
static uint8_t g_rom_fx_frames[20][0x0100] = {};
static bool g_rom_fx_frame_valid[20] = {};
static int g_rom_fx_frame = 0;
static int g_rom_fx_frame_count = 0;
static int g_rom_fx_tile_start_index = -1;
static int g_rom_tile_start_index = -1;
static int g_rom_tile_count = 0;
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

struct MakerRomSpriteAsset {
    uint32_t owner_pc;
    uint32_t descriptor_pc;
    uint32_t first_frame_pc;
    uint16_t frame_count;
    uint16_t first_frame_parts;
};
static MakerRomSpriteAsset g_rom_sprite_assets[256] = {};
static int g_rom_sprite_asset_count = 0;
static bool g_maker_rom_assets_prepared = false;
static int g_rom_sprite_offset = 0;
static int g_selected_rom_sprite = -1;
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
    s.ScaleAllSizes(g_ui_scale);
    g_theme_scale = g_ui_scale;
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

static int rom_vdp_pixel(int tile,int x,int y)
{
    if(tile<0||tile>=2048)return 0;
    const uint8_t *block=nullptr;
    int localTile=tile;
    // Backward-compatible local indices from earlier Maker documents.
    if(tile<80 && g_rom_art_valid) {
        block=g_rom_art_block;
    } else if(tile>=80 && tile<96 && g_rom_hud_art_a_valid) {
        block=g_rom_hud_art_a; localTile=tile-80;
    } else if(tile>=96 && tile<112 && g_rom_hud_art_b_valid) {
        block=g_rom_hud_art_b; localTile=tile-96;
    }
    // Original VDP tile ranges used by object and animation descriptors.
    else if(tile>=0xB0 && tile<0xB0+160 && g_rom_art_valid) {
        block=g_rom_art_block; localTile=tile-0xB0;
    } else if(tile>=0x1E9 && tile<=0x1F8 && g_rom_hud_art_a_valid) {
        block=g_rom_hud_art_a; localTile=tile-0x1E9;
    } else if(tile>=0x1EA && tile<=0x1F9 && g_rom_hud_art_b_valid) {
        block=g_rom_hud_art_b; localTile=tile-0x1EA;
    } else if(tile>=0x194 && tile<0x19C && g_rom_fx_frame_count>0 &&
              g_rom_fx_frame_valid[g_rom_fx_frame]) {
        block=g_rom_fx_frames[g_rom_fx_frame]; localTile=tile-0x194;
    }
    if(!block)return 0;
    const uint8_t packed=block[localTile*32+y*4+(x>>1)];
    return (x&1)?(packed&15):(packed>>4);
}
static void append_rom_art_tiles()
{
    if(g_rom_tile_count)return;
    g_rom_tile_start_index=g_live_tile_count;
    if(g_rom_art_valid) {
        for(int tile=0;tile<160 && g_live_tile_count<(int)(sizeof(g_live_tile_ids)/sizeof(g_live_tile_ids[0]));tile++)
            g_live_tile_ids[g_live_tile_count++]=0xB0+tile;
    }
    if(g_rom_hud_art_a_valid) {
        for(int tile=0;tile<16 && g_live_tile_count<(int)(sizeof(g_live_tile_ids)/sizeof(g_live_tile_ids[0]));tile++)
            g_live_tile_ids[g_live_tile_count++]=0x1E9+tile;
    }
    if(g_rom_hud_art_b_valid) {
        if(g_rom_hud_art_a_valid) {
            if(g_live_tile_count<(int)(sizeof(g_live_tile_ids)/sizeof(g_live_tile_ids[0])))
                g_live_tile_ids[g_live_tile_count++]=0x1F9;
        } else {
            for(int tile=0;tile<16 && g_live_tile_count<(int)(sizeof(g_live_tile_ids)/sizeof(g_live_tile_ids[0]));tile++)
                g_live_tile_ids[g_live_tile_count++]=0x1EA+tile;
        }
    }
    g_rom_fx_tile_start_index=-1;
    if(g_rom_fx_frame_count>0 && g_rom_fx_frame_valid[g_rom_fx_frame]) {
        g_rom_fx_tile_start_index=g_live_tile_count;
        for(int tile=0;tile<8 && g_live_tile_count<(int)(sizeof(g_live_tile_ids)/sizeof(g_live_tile_ids[0]));tile++)
            g_live_tile_ids[g_live_tile_count++]=0x194+tile;
    }
    g_rom_tile_count=g_live_tile_count-g_rom_tile_start_index;
}
static void draw_vdp_tile(ImDrawList *draw,ImVec2 pos,float size,int entry)
{
    const int tile=entry&0x7ff;
    const int hflip=(entry>>11)&1,vflip=(entry>>12)&1,palette=(entry>>13)&3;
    const float pixel=size/8.0f;
    for(int y=0;y<8;y++)for(int x=0;x<8;x++){
        const int sx=hflip?7-x:x,sy=vflip?7-y:y;
        const int color=(entry&0x8000u)?rom_vdp_pixel(tile,sx,sy):vdp_pixel(tile,sx,sy);
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


static bool maker_rom_read_u16(uint32_t address,uint16_t &value)
{
    uint8_t bytes[2];
    if(!md_rom_copy_region(address,bytes,2))return false;
    value=(uint16_t)(((uint16_t)bytes[0]<<8)|bytes[1]);
    return true;
}
static bool maker_rom_read_u32(uint32_t address,uint32_t &value)
{
    uint8_t bytes[4];
    if(!md_rom_copy_region(address,bytes,4))return false;
    value=((uint32_t)bytes[0]<<24)|((uint32_t)bytes[1]<<16)|
          ((uint32_t)bytes[2]<<8)|(uint32_t)bytes[3];
    return true;
}
static bool maker_rom_range(uint32_t address,uint32_t bytes)
{
    return address>=0x200u && address<0x400000u &&
           bytes<=0x400000u-address;
}
static bool maker_sprite_frame_probe(uint32_t frame,uint16_t *partCount)
{
    if(!maker_rom_range(frame,8))return false;
    // The renderer consumes the first piece, then tests the next piece's X
    // word for the negative terminator before processing each later piece.
    uint16_t firstX=0,firstY=0;
    uint32_t firstAttr=0;
    if(!maker_rom_read_u16(frame,firstX)||!maker_rom_read_u16(frame+2,firstY)||
       !maker_rom_read_u32(frame+4,firstAttr))return false;
    uint16_t count=1;
    for(uint32_t part=1;part<64;part++) {
        const uint32_t at=frame+part*8u;
        if(!maker_rom_range(at,8))break;
        uint16_t px=0,py=0;
        uint32_t attr=0;
        if(!maker_rom_read_u16(at,px))break;
        if(px&0x8000u)break;
        if(!maker_rom_read_u16(at+2,py)||!maker_rom_read_u32(at+4,attr))break;
        count++;
    }
    if(partCount)*partCount=count;
    return true;
}
static bool maker_sprite_descriptor_probe(uint32_t owner,uint32_t descriptor,
                                          MakerRomSpriteAsset &asset)
{
    if(!maker_rom_range(descriptor,4))return false;
    uint32_t firstFrame=0;
    if(!maker_rom_read_u32(descriptor,firstFrame) ||
       !maker_sprite_frame_probe(firstFrame,nullptr))return false;

    uint16_t frameCount=0,firstParts=0;
    for(uint32_t frame=0;frame<32;frame++) {
        uint32_t framePointer=0;
        if(!maker_rom_range(descriptor+frame*4u,4) ||
           !maker_rom_read_u32(descriptor+frame*4u,framePointer) ||
           !maker_sprite_frame_probe(framePointer,frame==0?&firstParts:nullptr))
            break;
        frameCount++;
    }
    if(frameCount==0)return false;
    asset.owner_pc=owner;
    asset.descriptor_pc=descriptor;
    asset.first_frame_pc=firstFrame;
    asset.frame_count=frameCount;
    asset.first_frame_parts=firstParts;
    return true;
}
static void maker_add_rom_sprite_descriptor(uint32_t owner,uint32_t descriptor)
{
    if(g_rom_sprite_asset_count>=(int)(sizeof(g_rom_sprite_assets)/sizeof(g_rom_sprite_assets[0])))
        return;
    for(int i=0;i<g_rom_sprite_asset_count;i++)
        if(g_rom_sprite_assets[i].descriptor_pc==descriptor)return;
    MakerRomSpriteAsset asset={};
    if(!maker_sprite_descriptor_probe(owner,descriptor,asset))return;
    g_rom_sprite_assets[g_rom_sprite_asset_count++]=asset;
}
static void maker_load_rom_fx_frames()
{
    g_rom_fx_frame=0;
    g_rom_fx_frame_count=0;
    for(int i=0;i<20;i++) {
        g_rom_fx_frame_valid[i]=false;
        uint32_t source=0;
        if(!maker_rom_read_u32(0x4D94u+(uint32_t)i*4u,source) ||
           !maker_rom_range(source,0x0100u))continue;
        if(md_rom_copy_region(source,g_rom_fx_frames[i],0x0100u)) {
            g_rom_fx_frame_valid[i]=true;
            if(g_rom_fx_frame_count==0)g_rom_fx_frame=i;
            g_rom_fx_frame_count++;
        }
    }
}
static void maker_build_rom_sprite_catalog()
{
    g_rom_sprite_asset_count=0;
    g_rom_sprite_offset=0;
    g_selected_rom_sprite=-1;
    for(uint32_t i=0;i<kMTMakerStaticSpriteDescriptorCount;i++) {
        const MTMakerStaticSpriteDescriptor &entry=kMTMakerStaticSpriteDescriptors[i];
        maker_add_rom_sprite_descriptor(entry.owner_pc,entry.descriptor_pc);
    }
    for(uint32_t t=0;t<kMTMakerSpritePointerTableCount;t++) {
        const MTMakerSpritePointerTable &table=kMTMakerSpritePointerTables[t];
        uint32_t misses=0;
        for(uint32_t i=0;i<table.entry_limit;i++) {
            uint32_t descriptor=0;
            if(!maker_rom_range(table.table_pc+i*4u,4) ||
               !maker_rom_read_u32(table.table_pc+i*4u,descriptor) ||
               !maker_rom_range(descriptor,4)) {
                if(++misses>=2)break;
                continue;
            }
            const int before=g_rom_sprite_asset_count;
            maker_add_rom_sprite_descriptor(table.owner_pc,descriptor);
            if(g_rom_sprite_asset_count==before) {
                // Keep scanning a short run of invalid table cells, but do not
                // treat arbitrary following ROM data as a descriptor sequence.
                if(++misses>=3)break;
            } else misses=0;
        }
    }
}

static bool maker_sprite_tile_supported(int tile)
{
    if(tile>=0xB0 && tile<0xB0+160)return g_rom_art_valid;
    if(tile>=0x1E9 && tile<=0x1F8)return g_rom_hud_art_a_valid ||
        (g_rom_hud_art_b_valid && tile>=0x1EA);
    if(tile==0x1F9)return g_rom_hud_art_b_valid;
    if(tile>=0x194 && tile<0x19C)
        return g_rom_fx_frame_count>0 && g_rom_fx_frame_valid[g_rom_fx_frame];
    return false;
}
static bool draw_rom_sprite_preview(ImDrawList *draw,ImVec2 box,float boxWidth,
                                    float boxHeight,const MakerRomSpriteAsset &asset)
{
    struct Part { int x,y,w,h; uint16_t attr; };
    Part parts[64]={};
    int count=0,minX=0,minY=0,maxX=0,maxY=0;
    for(int i=0;i<asset.first_frame_parts && i<64;i++) {
        const uint32_t at=asset.first_frame_pc+(uint32_t)i*8u;
        uint16_t rawX=0,rawY=0;
        uint32_t packed=0;
        if(!maker_rom_read_u16(at,rawX)||!maker_rom_read_u16(at+2,rawY)||
           !maker_rom_read_u32(at+4,packed))break;
        if(i>0 && (rawX&0x8000u))break;
        const uint16_t sizeLink=(uint16_t)(packed>>16);
        const uint16_t attr=(uint16_t)(packed&0x7FFFu);
        const int w=((sizeLink>>8)&3)+1;
        const int h=((sizeLink>>10)&3)+1;
        const int baseTile=attr&0x07FF;
        bool supported=true;
        for(int row=0;row<h;row++)for(int col=0;col<w;col++)
            if(!maker_sprite_tile_supported(baseTile+col*h+row))supported=false;
        if(!supported)continue;
        const int px=(int)(int16_t)rawX,py=(int)(int16_t)rawY;
        parts[count++]=Part{px,py,w,h,(uint16_t)(attr|0x8000u)};
        if(count==1) { minX=px;minY=py;maxX=px+w*8;maxY=py+h*8; }
        else {
            minX=std::min(minX,px); minY=std::min(minY,py);
            maxX=std::max(maxX,px+w*8); maxY=std::max(maxY,py+h*8);
        }
    }
    if(count==0)return false;
    const float worldW=(float)std::max(8,maxX-minX);
    const float worldH=(float)std::max(8,maxY-minY);
    const float scale=std::min((boxWidth-6.0f)/worldW,(boxHeight-6.0f)/worldH);
    if(scale<=0.0f)return false;
    const float offsetX=box.x+(boxWidth-worldW*scale)*0.5f;
    const float offsetY=box.y+(boxHeight-worldH*scale)*0.5f;
    const float tileSize=8.0f*scale;
    for(int i=0;i<count;i++) {
        const Part &p=parts[i];
        draw_vdp_sprite(draw,
            ImVec2(offsetX+(p.x-minX)*scale,offsetY+(p.y-minY)*scale),
            tileSize,p.attr,p.w,p.h);
    }
    return true;
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
    const float cell=std::max(12.0f,std::min(36.0f,std::min(avail.x/(cols*0.82f),avail.y/(rows*0.68f))));
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
    ImGui::BeginChild("##workspace_bottom",ImVec2(0,ui(32)),true);
    ImGui::TextColored(ImVec4(.42f,.82f,.88f,1),"%s",g_level_name);
    ImGui::SameLine();
    if(g_undo_count>0){if(ImGui::Button("UNDO",ImVec2(ui(74),ui(29))))undo_level_edit();}
    else{ImGui::BeginDisabled();ImGui::Button("UNDO",ImVec2(ui(74),ui(29)));ImGui::EndDisabled();}
    ImGui::SameLine();
    if(g_redo_count>0){if(ImGui::Button("REDO",ImVec2(ui(74),ui(29))))redo_level_edit();}
    else{ImGui::BeginDisabled();ImGui::Button("REDO",ImVec2(ui(74),ui(29)));ImGui::EndDisabled();}
    ImGui::SameLine();
    if(ImGui::Button("SAVE",ImVec2(ui(78),ui(29)))){bool ok=mtlb_map_save();std::snprintf(g_status,sizeof(g_status),"%s",ok?"LEVEL SAVED":"SAVE FAILED");}
    ImGui::SameLine();
    ImGui::BeginDisabled();ImGui::Button("TEST",ImVec2(ui(74),ui(29)));ImGui::EndDisabled();
    ImGui::SameLine();
    if(ImGui::Button("EXIT",ImVec2(ui(74),ui(29))))g_exit_requested=true;
    ImGui::EndChild();
}

static void draw_layer_bar()
{
    ImGui::BeginChild("##categories",ImVec2(0,ui(31)),true);
    const struct {const char *label;EditorMode mode;} tabs[]={
        {"TILES",MODE_TILES},{"OBJECTS",MODE_ENTITY},
        {"BOSSES",MODE_BOSS},{"DRAW",MODE_ASSETS},{"EVENTS",MODE_EVENTS}
    };
    const float tabWidth=(ImGui::GetContentRegionAvail().x-12.0f)/5.0f;
    for(int i=0;i<5;i++){
        if(i)ImGui::SameLine(0,3);
        bool active=g_mode==tabs[i].mode;
        if(active)ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.50f,.27f,.10f,1));
        if(ImGui::Button(tabs[i].label,ImVec2(tabWidth,ui(27))))g_mode=tabs[i].mode;
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
    ImGui::BeginChild("##maker_tool_row",ImVec2(0,ui(40)),true);
    const struct { const char *glyph; EditorTool tool; const char *hint; } buttons[] = {
        {"SELECT",TOOL_SELECT,"Select tiles or objects"},
        {"PAINT",TOOL_TILE_BRUSH,"Paint selected tile"},
        {"ERASE",TOOL_ERASER,"Erase tile or object"},
        {"COPY",TOOL_COPY,"Copy selected item"},
        {"GRAPPLE",TOOL_GRAPPLE,"Place grapple anchor"},
        {"TRIGGER",TOOL_TRIGGER,"Place event trigger"}
    };
    for(int i=0;i<6;i++) {
        const auto &button=buttons[i];
        if(i)ImGui::SameLine(0,ui(5));
        const bool active=(g_tool==button.tool);
        if(active)ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.55f,.30f,.10f,1.0f));
        if(ImGui::Button(button.glyph,ImVec2(ui(88),ui(30))))g_tool=button.tool;
        if(active)ImGui::PopStyleColor();
        if(ImGui::IsItemHovered())ImGui::SetTooltip("%s",button.hint);
    }
    ImGui::SameLine(0,ui(8));
    ImGui::TextDisabled(g_mode==MODE_TILES?"TOOLS":"PLACE / SELECT / ERASE");
    ImGui::EndChild();
}

static void draw_asset_shelf()
{
    ImGui::BeginChild("##asset_shelf",ImVec2(0,ui(43)),true);
    const char *heading=g_mode==MODE_TILES?"GAME TILES":
        g_mode==MODE_ENTITY?"ROM OBJECTS":g_mode==MODE_BOSS?"ROM SPRITE SETS":
        g_mode==MODE_ASSETS?"DRAW":"EVENTS";
    ImGui::TextColored(ImVec4(.46f,.83f,.88f,1),"%s",heading);

    if(g_mode==MODE_TILES){
        ImGui::SameLine();
        if(ImGui::SmallButton("<"))g_tile_shelf_offset=std::max(0,g_tile_shelf_offset-8);
        if(g_rom_tile_count>0){ImGui::SameLine(0,2);if(ImGui::SmallButton("ROM ART"))g_tile_shelf_offset=g_rom_tile_start_index;}
        if(g_rom_fx_tile_start_index>=0){
            ImGui::SameLine(0,2);
            if(ImGui::SmallButton("ROM FX"))g_tile_shelf_offset=g_rom_fx_tile_start_index;
            ImGui::SameLine(0,2);
            if(ImGui::SmallButton("FX NEXT")){
                for(int step=1;step<=20;step++){
                    int next=(g_rom_fx_frame+step)%20;
                    if(g_rom_fx_frame_valid[next]){g_rom_fx_frame=next;break;}
                }
            }
            ImGui::SameLine(0,2);
            ImGui::TextDisabled("FX %02d/%02d",g_rom_fx_frame+1,20);
        }
        for(int i=g_tile_shelf_offset;i<g_live_tile_count&&i<g_tile_shelf_offset+8;i++){
            ImGui::SameLine(0,2);
            const bool romTile=(g_rom_tile_start_index>=0 && i>=g_rom_tile_start_index && i<g_rom_tile_start_index+g_rom_tile_count);
            const int tile=g_live_tile_ids[i];
            const int tileEntry=tile|(g_selected_palette<<13)|(romTile?0x8000:0);
            ImGui::PushID(i);
            ImVec2 p=ImGui::GetCursorScreenPos();
            ImGui::InvisibleButton("##tile_pick",ImVec2(ui(31),ui(36)));
            ImDrawList *d=ImGui::GetWindowDrawList();
            const bool selected=(g_brush_tile==tileEntry);
            d->AddRectFilled(p,ImVec2(p.x+ui(31),p.y+ui(36)),selected?IM_COL32(71,49,27,255):IM_COL32(14,22,31,255),2.0f);
            draw_vdp_tile(d,ImVec2(p.x+ui(4),p.y+ui(5)),ui(26),tileEntry);
            d->AddRect(p,ImVec2(p.x+ui(31),p.y+ui(36)),selected?IM_COL32(255,190,76,255):IM_COL32(82,105,120,255),2.0f,0,selected?2.0f:1.0f);
            if(ImGui::IsItemClicked()){g_brush_tile=tileEntry;g_tool=TOOL_TILE_BRUSH;}
            ImGui::PopID();
        }
        ImGui::SameLine(0,2);
        if(ImGui::SmallButton(">"))g_tile_shelf_offset=std::min(std::max(0,g_live_tile_count-8),g_tile_shelf_offset+8);
        if(g_live_tile_count==0){ImGui::SameLine();ImGui::TextDisabled("NO ROM OR LIVE ART AVAILABLE");}
        else if(g_rom_tile_count>0){ImGui::SameLine();ImGui::TextDisabled("%d ROM TILES  |  BUILT-IN BANKS",g_rom_tile_count);}
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
        if(g_rom_sprite_asset_count==0){
            ImGui::TextDisabled("NO VALID ROM SPRITE DESCRIPTORS FOUND");
        }else{
            if(g_rom_sprite_asset_count>8){
                ImGui::SameLine(0,2);
                if(ImGui::SmallButton("<"))g_rom_sprite_offset=std::max(0,g_rom_sprite_offset-8);
            }
            const int shown=std::min(8,g_rom_sprite_asset_count-g_rom_sprite_offset);
            for(int n=0;n<shown;n++){
                const int i=g_rom_sprite_offset+n;
                ImGui::SameLine(0,3);
                ImGui::PushID(4000+i);
                const MakerRomSpriteAsset &asset=g_rom_sprite_assets[i];
                const ImVec2 p=ImGui::GetCursorScreenPos();
                ImGui::InvisibleButton("##rom_sprite_preview",ImVec2(ui(44),ui(42)));
                ImDrawList *d=ImGui::GetWindowDrawList();
                const bool active=g_selected_rom_sprite==i;
                d->AddRectFilled(p,ImVec2(p.x+ui(44),p.y+ui(42)),
                    active?IM_COL32(71,49,27,255):IM_COL32(14,22,31,255),2.0f);
                const bool previewed=draw_rom_sprite_preview(d,ImVec2(p.x+ui(2),p.y+ui(2)),
                    ui(40),ui(38),asset);
                if(!previewed) {
                    char label[12];
                    std::snprintf(label,sizeof(label),"SET %02d",i+1);
                    const ImVec2 t=ImGui::CalcTextSize(label);
                    d->AddText(ImVec2(p.x+(ui(44)-t.x)*.5f,p.y+(ui(42)-t.y)*.5f),
                        IM_COL32(190,200,207,255),label);
                }
                d->AddRect(p,ImVec2(p.x+ui(44),p.y+ui(42)),
                    active?IM_COL32(255,190,76,255):IM_COL32(82,105,120,255),2.0f,0,
                    active?2.0f:1.0f);
                if(ImGui::IsItemClicked())g_selected_rom_sprite=i;
                if(ImGui::IsItemHovered())
                    ImGui::SetTooltip("ROM descriptor $%06X\nOwner routine $%06X\nFrames %u  |  First-frame parts %u",
                        asset.descriptor_pc,asset.owner_pc,(unsigned)asset.frame_count,
                        (unsigned)asset.first_frame_parts);
                ImGui::PopID();
            }
            if(g_rom_sprite_offset+shown<g_rom_sprite_asset_count){
                ImGui::SameLine(0,2);
                if(ImGui::SmallButton(">"))
                    g_rom_sprite_offset=std::min(g_rom_sprite_asset_count-8,g_rom_sprite_offset+8);
            }
            ImGui::SameLine();
            ImGui::TextDisabled("%d-%d / %d ROM SETS",g_rom_sprite_offset+1,
                g_rom_sprite_offset+shown,g_rom_sprite_asset_count);
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
    ImGui::BeginChild("##topbar",ImVec2(0,ui(25)),true);
    ImDrawList *d=ImGui::GetWindowDrawList();
    ImVec2 p=ImGui::GetWindowPos();
    d->AddRectFilled(p,ImVec2(p.x+ImGui::GetWindowWidth(),p.y+ui(25)),IM_COL32(7,11,18,255));
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
    g_rom_tile_start_index=-1;
    g_rom_tile_count=0;
    for(int tile=1;tile<2048&&g_live_tile_count<256;tile++){
        const uint8_t *pattern=&g_live_vram[tile*32];
        bool visible=false;
        for(int i=0;i<32;i++)if(pattern[i]){visible=true;break;}
        if(visible)g_live_tile_ids[g_live_tile_count++]=tile;
    }
    append_rom_art_tiles();

    // Genesis VDP register 5 points to a linked Sprite Attribute Table.
    g_live_sprite_count=0;
    const int h40=(g_live_regs[12]&1u)!=0;
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
    g_selected_x=x;
    g_selected_y=y;
    if(g_level_tiles[index]!=value){g_level_tiles[index]=value;g_document_dirty=true;}
}
extern "C" void mtlb_map_set_brush(int tile)
{
    g_brush_tile=std::max(0,std::min(2047,tile));
}
static bool mtlb_level_document_path(char *path,size_t capacity)
{
    char base[4096]={};
    const char *portable=std::getenv("MEGATURRICAN_CONFIG_DIR");
    if(portable&&portable[0]){
        if(std::snprintf(base,sizeof(base),"%s",portable)<0)return false;
    }else{
        char *sdl_base=SDL_GetBasePath();
        if(!sdl_base)return false;
        const int copied=std::snprintf(base,sizeof(base),"%s",sdl_base);
        SDL_free(sdl_base);
        if(copied<0||(size_t)copied>=sizeof(base))return false;
    }
    size_t base_len=std::strlen(base);
    while(base_len>1&&(base[base_len-1]=='/'||base[base_len-1]=='\\')){
        base[--base_len]='\\0';
    }
    char folder[4096];
    const int folder_len=std::snprintf(folder,sizeof(folder),"%s/levels",base);
    const int path_len=std::snprintf(path,capacity,"%s/untitled.mtlb",folder);
    if(folder_len<0||path_len<0||(size_t)folder_len>=sizeof(folder)||(size_t)path_len>=capacity)return false;
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

extern "C" int mtlb_editor_prepare_rom_assets(void)
{
    if (!g_maker_rom_assets_prepared) {
        g_rom_art_valid = md_rom_copy_region(0x3AF80u, g_rom_art_block, (uint32_t)sizeof(g_rom_art_block)) != 0;
        g_rom_hud_art_a_valid = md_rom_copy_region(0x26D20u, g_rom_hud_art_a, (uint32_t)sizeof(g_rom_hud_art_a)) != 0;
        g_rom_hud_art_b_valid = md_rom_copy_region(0x26D40u, g_rom_hud_art_b, (uint32_t)sizeof(g_rom_hud_art_b)) != 0;
        maker_load_rom_fx_frames();
        maker_build_rom_sprite_catalog();
        g_maker_rom_assets_prepared = true;
    }
    append_rom_art_tiles();
    return g_rom_sprite_asset_count;
}

extern "C" int mtlb_editor_tile_count(void)
{
    append_rom_art_tiles();
    return g_live_tile_count;
}

extern "C" int mtlb_editor_tile_entry(int index, int palette)
{
    append_rom_art_tiles();
    if (index < 0 || index >= g_live_tile_count) return 0;
    const bool rom_tile = g_rom_tile_start_index >= 0 &&
        index >= g_rom_tile_start_index && index < g_rom_tile_start_index + g_rom_tile_count;
    return (g_live_tile_ids[index] & 0x07FF) | ((palette & 3) << 13) | (rom_tile ? 0x8000 : 0);
}

extern "C" void mtlb_editor_tile_rgba(int entry, int x, int y, uint8_t rgba[4])
{
    if (!rgba) return;
    rgba[0] = rgba[1] = rgba[2] = 0;
    rgba[3] = 0;
    if (x < 0 || x >= 8 || y < 0 || y >= 8) return;

    const int tile = entry & 0x07FF;
    const int sx = (entry & 0x0800) ? 7 - x : x;
    const int sy = (entry & 0x1000) ? 7 - y : y;
    const int pixel = (entry & 0x8000) ? rom_vdp_pixel(tile, sx, sy) : vdp_pixel(tile, sx, sy);
    if (pixel == 0) return;

    const int palette = (entry >> 13) & 3;
    const uint16_t raw = g_live_cram[palette * 16 + (pixel & 15)];
    const int r = (raw >> 1) & 7;
    const int g = (raw >> 5) & 7;
    const int b = (raw >> 9) & 7;
    rgba[0] = (uint8_t)(r * 255 / 7);
    rgba[1] = (uint8_t)(g * 255 / 7);
    rgba[2] = (uint8_t)(b * 255 / 7);
    rgba[3] = 255;
}

extern "C" int mtlb_editor_sprite_asset_count(void)
{
    mtlb_editor_prepare_rom_assets();
    return g_rom_sprite_asset_count;
}

extern "C" int mtlb_editor_sprite_asset_info(int index, uint32_t *owner_pc,
                                               uint32_t *descriptor_pc,
                                               uint16_t *frame_count,
                                               uint16_t *part_count)
{
    mtlb_editor_prepare_rom_assets();
    if (index < 0 || index >= g_rom_sprite_asset_count) return 0;
    const MakerRomSpriteAsset &asset = g_rom_sprite_assets[index];
    if (owner_pc) *owner_pc = asset.owner_pc;
    if (descriptor_pc) *descriptor_pc = asset.descriptor_pc;
    if (frame_count) *frame_count = asset.frame_count;
    if (part_count) *part_count = asset.first_frame_parts;
    return 1;
}

extern "C" int mtlb_editor_sprite_asset_part(int index, int part_index,
                                               int *x, int *y, int *width_tiles,
                                               int *height_tiles, uint16_t *tile_attr)
{
    mtlb_editor_prepare_rom_assets();
    if (index < 0 || index >= g_rom_sprite_asset_count || part_index < 0 || part_index >= 64)
        return 0;
    const MakerRomSpriteAsset &asset = g_rom_sprite_assets[index];
    if (part_index >= asset.first_frame_parts) return 0;
    const uint32_t at = asset.first_frame_pc + (uint32_t)part_index * 8u;
    uint16_t raw_x = 0, raw_y = 0;
    uint32_t packed = 0;
    if (!maker_rom_read_u16(at, raw_x) || !maker_rom_read_u16(at + 2, raw_y) ||
        !maker_rom_read_u32(at + 4, packed)) return 0;
    if (part_index > 0 && (raw_x & 0x8000u)) return 0;

    const uint16_t size_link = (uint16_t)(packed >> 16);
    const uint16_t attr = (uint16_t)(packed & 0x7FFFu);
    const int w = ((size_link >> 8) & 3) + 1;
    const int h = ((size_link >> 10) & 3) + 1;
    const int base_tile = attr & 0x07FF;
    for (int row = 0; row < h; ++row)
        for (int col = 0; col < w; ++col)
            if (!maker_sprite_tile_supported(base_tile + col * h + row)) return 0;
    if (x) *x = (int)(int16_t)raw_x;
    if (y) *y = (int)(int16_t)raw_y;
    if (width_tiles) *width_tiles = w;
    if (height_tiles) *height_tiles = h;
    if (tile_attr) *tile_attr = (uint16_t)(attr | 0x8000u);
    return 1;
}

extern "C" uint32_t mtlb_editor_vdp_art_hash(void)
{
    return g_live_art_hash;
}

extern "C" int mtlb_init(SDL_Window *window, SDL_Renderer *renderer)
{
    if(g_initialized)return 1;
    if(!window||!renderer)return 0;

    g_window=window;
    g_renderer=renderer;
    SDL_GetWindowSize(window,&g_imgui_width,&g_imgui_height);
    if(g_imgui_width<=0||g_imgui_height<=0)return 0;

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO &io=ImGui::GetIO();
    io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard;
    io.IniFilename=nullptr;
    g_ui_scale=1.0f;
    apply_theme();

    g_sdl_backend=ImGui_ImplSDL2_InitForSDLRenderer(window,renderer);
    if(!g_sdl_backend){
        ImGui::DestroyContext();
        g_window=nullptr;
        g_renderer=nullptr;
        return 0;
    }
    g_renderer_backend=ImGui_ImplSDLRenderer2_Init(renderer);
    if(!g_renderer_backend){
        ImGui_ImplSDL2_Shutdown();
        g_sdl_backend=false;
        ImGui::DestroyContext();
        g_window=nullptr;
        g_renderer=nullptr;
        return 0;
    }

    g_selected_x=std::max(0,mtlb_map_cursor_x());
    g_selected_y=std::max(0,mtlb_map_cursor_y());
    g_brush_tile=std::max(0,std::min(2047,mtlb_map_brush()));
    mtlb_editor_prepare_rom_assets();
    g_live_art_hash=0;
    g_live_tile_count=0;
    g_rom_tile_start_index=-1;
    g_rom_tile_count=0;
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
    g_renderer_backend=false;
    g_sdl_backend=false;
    g_initialized=false;
    g_window=nullptr;
    g_renderer=nullptr;
    g_last_painted_x=-1;
    g_last_painted_y=-1;
}

extern "C" void mtlb_process_event(const SDL_Event *event)
{
    if (g_initialized && event) ImGui_ImplSDL2_ProcessEvent(event);
}

extern "C" int mtlb_render_to_screen(SDL_Renderer *renderer,
                                      int view_x,int view_y,int view_width,int view_height)
{
    if(!g_initialized||!renderer||renderer!=g_renderer||
       view_width<=0||view_height<=0)return 0;

    int windowW=0,windowH=0;
    SDL_GetWindowSize(g_window,&windowW,&windowH);
    if(windowW<=0||windowH<=0)return 0;

    ImGui_ImplSDLRenderer2_NewFrame();
    ImGui_ImplSDL2_NewFrame();
    ImGuiIO &io=ImGui::GetIO();

    float scaleX=(float)view_width/960.0f;
    float scaleY=(float)view_height/540.0f;
    float nextScale=std::min(scaleX,scaleY);
    nextScale=std::max(0.85f,std::min(2.25f,nextScale));
    if(nextScale>g_theme_scale+0.01f||nextScale<g_theme_scale-0.01f){
        g_ui_scale=nextScale;
        apply_theme();
    }
    io.FontGlobalScale=g_ui_scale;

    ImGui::NewFrame();
    if(!g_exit_requested&&!io.WantTextInput&&ImGui::IsKeyPressed(ImGuiKey_Escape,false))
        g_exit_requested=true;

    ImGui::SetNextWindowPos(ImVec2((float)view_x,(float)view_y));
    ImGui::SetNextWindowSize(ImVec2((float)view_width,(float)view_height));
    ImGui::SetNextWindowBgAlpha(1.0f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,ImVec2(ui(8),ui(7)));
    ImGui::Begin("##MT_MAKER_ROOT",nullptr,
        ImGuiWindowFlags_NoTitleBar|ImGuiWindowFlags_NoResize|ImGuiWindowFlags_NoMove|
        ImGuiWindowFlags_NoCollapse|ImGuiWindowFlags_NoSavedSettings|
        ImGuiWindowFlags_NoScrollbar|ImGuiWindowFlags_NoScrollWithMouse|
        ImGuiWindowFlags_NoBringToFrontOnFocus);

    draw_top_bar();
    draw_layer_bar();
    draw_asset_shelf();
    draw_tool_palette();

    const float bottomHeight=ui(32);
    const float workspaceHeight=std::max(ui(90),
        (float)view_height-ui(25)-ui(31)-ui(43)-ui(40)-bottomHeight-ui(18));
    ImGui::BeginChild("##maker_workspace",ImVec2(0,workspaceHeight),false);
    ImGui::BeginChild("##maker_stage",ImVec2(0,0),true);
    draw_center_view();
    ImGui::EndChild();
    ImGui::EndChild();
    draw_bottom_workspace();
    ImGui::End();
    ImGui::PopStyleVar();

    const int gridW=20,gridH=15,total=gridW*gridH,frames=12;
    const bool closing=g_exit_requested;
    if(closing&&g_fade_out_frame<0)g_fade_out_frame=0;
    const int revealed=std::min(total,g_fade_in_frame*total/frames);
    const int covered=closing?std::min(total,g_fade_out_frame*total/frames):0;
    ImDrawList *fade=ImGui::GetForegroundDrawList();
    for(int i=0;i<total;i++){
        const int rank=(i*73+19)%total;
        const bool black=closing?(rank<covered):(rank>=revealed);
        if(!black)continue;
        const int x=i%gridW,y=i/gridW;
        ImVec2 a((float)view_x+x*(float)view_width/gridW,
                 (float)view_y+y*(float)view_height/gridH);
        ImVec2 b((float)view_x+(x+1)*(float)view_width/gridW,
                 (float)view_y+(y+1)*(float)view_height/gridH);
        fade->AddRectFilled(a,b,IM_COL32(0,0,0,255));
    }

    ImGui::Render();
    ImGui_ImplSDLRenderer2_RenderDrawData(ImGui::GetDrawData(),renderer);

    if(closing){
        if(g_fade_out_frame<frames)g_fade_out_frame++;
        return g_fade_out_frame>=frames;
    }
    if(g_fade_in_frame<frames)g_fade_in_frame++;
    return 0;
}


extern "C" void mtlb_map_set_cursor(int x,int y)
{
    g_selected_x=std::max(0,std::min(kEditorMapCols-1,x));
    g_selected_y=std::max(0,std::min(kEditorMapRows-1,y));
}
extern "C" void mtlb_editor_push_undo(void) { push_level_undo(); }
extern "C" void mtlb_editor_undo(void) { undo_level_edit(); }
extern "C" void mtlb_editor_redo(void) { redo_level_edit(); }
extern "C" int mtlb_editor_entity_count(void) { return g_entity_count; }

extern "C" int mtlb_editor_place_entity(float x,float y,int type,int sprite_asset_index)
{
    if(g_entity_count>=64)return -1;
    EditorEntity entity={};
    entity.x=std::max(0.0f,std::min(1.0f,x));
    entity.y=std::max(0.0f,std::min(1.0f,y));
    entity.type=std::max(0,std::min(5,type));
    entity.hp=100;
    if(sprite_asset_index>=0&&sprite_asset_index<mtlb_editor_sprite_asset_count()){
        int px=0,py=0,w=0,h=0;uint16_t attr=0;
        if(mtlb_editor_sprite_asset_part(sprite_asset_index,0,&px,&py,&w,&h,&attr)){
            entity.tile_attr=attr;
            entity.width_tiles=(uint8_t)w;
            entity.height_tiles=(uint8_t)h;
        }
    }
    g_entities[g_entity_count]=entity;
    g_selected_entity=g_entity_count;
    g_document_dirty=true;
    return g_entity_count++;
}

extern "C" int mtlb_editor_entity_info(int index,float *x,float *y,int *type,int *hp,
                                         uint16_t *tile_attr,int *width_tiles,int *height_tiles)
{
    if(index<0||index>=g_entity_count)return 0;
    const EditorEntity &entity=g_entities[index];
    if(x)*x=entity.x;if(y)*y=entity.y;if(type)*type=entity.type;if(hp)*hp=entity.hp;
    if(tile_attr)*tile_attr=entity.tile_attr;
    if(width_tiles)*width_tiles=entity.width_tiles;if(height_tiles)*height_tiles=entity.height_tiles;
    return 1;
}
