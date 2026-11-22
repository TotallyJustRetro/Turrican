#include "mt_level_builder_imgui.h"

#include "imgui.h"
#include "imgui_impl_sdl2.h"
#include "imgui_impl_sdlrenderer2.h"

#include <algorithm>
#include <cstdio>

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
static int g_selected_x = 12;
static int g_selected_y = 10;
static int g_brush_tile = 1;
static int g_last_painted_x = -1;
static int g_last_painted_y = -1;
static int g_map_origin_x = 0;
static int g_map_origin_y = 0;
static bool g_layers[5] = {true, true, true, true, false};
static int g_asset_pixels[16 * 16] = {};
static int g_asset_color = 12;
static bool g_asset_modern = false;
static char g_status[160] = "LEVEL SYSTEM ONLINE  |  VANILLA VDP TILE PLANE CONNECTED";
static bool g_exit_requested = false;
static bool g_show_grid = true;

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

static void draw_tiles_viewport()
{
    const int cols = std::max(1, mtlb_map_cols());
    const int rows = std::max(1, mtlb_map_rows());
    g_selected_x = std::max(0, std::min(cols - 1, g_selected_x));
    g_selected_y = std::max(0, std::min(rows - 1, g_selected_y));

    g_map_origin_x = std::max(0, std::min(cols - 16, g_selected_x - 8));
    g_map_origin_y = std::max(0, std::min(rows - 16, g_selected_y - 8));

    ImGui::TextColored(ImVec4(0.34f, 0.78f, 0.83f, 1.0f),
        "VDP PLANE A  /  %d x %d  /  16 x 16 EDIT WINDOW", cols, rows);
    ImGui::SameLine();
    ImGui::TextDisabled("LMB: paint   RMB: sample tile");

    ImVec2 available = ImGui::GetContentRegionAvail();
    const float gap = 8.0f;
    const float cell = std::max(12.0f, std::min((available.x - gap * 2.0f) / 16.0f,
                                               (available.y - 28.0f) / 16.0f));
    const ImVec2 origin = ImGui::GetCursorScreenPos();
    const ImVec2 grid_min(origin.x + 4.0f, origin.y + 4.0f);
    const ImVec2 grid_size(cell * 16.0f, cell * 16.0f);
    ImDrawList *draw = ImGui::GetWindowDrawList();

    draw->AddRectFilled(ImVec2(grid_min.x - 5.0f, grid_min.y - 5.0f),
                        ImVec2(grid_min.x + grid_size.x + 5.0f, grid_min.y + grid_size.y + 5.0f),
                        IM_COL32(5, 9, 14, 205), 2.0f);
    for (int y = 0; y < 16; ++y) {
        for (int x = 0; x < 16; ++x) {
            const int map_x = g_map_origin_x + x;
            const int map_y = g_map_origin_y + y;
            const int tile = mtlb_map_get(map_x, map_y);
            const ImVec2 a(grid_min.x + x * cell, grid_min.y + y * cell);
            const ImVec2 b(a.x + cell - 1.0f, a.y + cell - 1.0f);
            draw->AddRectFilled(a, b, tile_color(tile));
            draw->AddRect(a, b, IM_COL32(72, 94, 108, 170));
            if (cell >= 23.0f) {
                char value[8];
                std::snprintf(value, sizeof(value), "%03X", tile & 0x7ff);
                draw->AddText(ImVec2(a.x + 3.0f, a.y + 3.0f),
                              IM_COL32(184, 198, 205, 220), value);
            }
            if (map_x == g_selected_x && map_y == g_selected_y) {
                draw->AddRect(ImVec2(a.x - 1.0f, a.y - 1.0f),
                              ImVec2(b.x + 1.0f, b.y + 1.0f),
                              IM_COL32(255, 174, 54, 255), 0.0f, 0, 2.5f);
            }
        }
    }

    ImGui::SetCursorScreenPos(grid_min);
    ImGui::InvisibleButton("##mtlb_map_canvas", grid_size,
        ImGuiButtonFlags_MouseButtonLeft | ImGuiButtonFlags_MouseButtonRight);
    if (ImGui::IsItemHovered()) {
        const ImVec2 mouse = ImGui::GetIO().MousePos;
        const int x = std::max(0, std::min(15, static_cast<int>((mouse.x - grid_min.x) / cell)));
        const int y = std::max(0, std::min(15, static_cast<int>((mouse.y - grid_min.y) / cell)));
        const int map_x = g_map_origin_x + x;
        const int map_y = g_map_origin_y + y;
        g_selected_x = map_x;
        g_selected_y = map_y;
        if (ImGui::IsMouseClicked(ImGuiMouseButton_Right)) {
            g_brush_tile = mtlb_map_get(map_x, map_y);
            std::snprintf(g_status, sizeof(g_status), "SAMPLED TILE %03X FROM CELL %d,%d",
                          g_brush_tile, map_x, map_y);
        }
        if (ImGui::IsMouseDown(ImGuiMouseButton_Left) &&
            (map_x != g_last_painted_x || map_y != g_last_painted_y)) {
            if (g_tool == TOOL_TILE_BRUSH) {
                mtlb_map_set(map_x, map_y, g_brush_tile);
                std::snprintf(g_status, sizeof(g_status), "PAINTED TILE %03X AT %d,%d",
                              g_brush_tile, map_x, map_y);
            } else {
                std::snprintf(g_status, sizeof(g_status), "%s SELECTED AT %d,%d",
                              kTileTools[static_cast<int>(g_tool)], map_x, map_y);
            }
            g_last_painted_x = map_x;
            g_last_painted_y = map_y;
        }
    } else {
        g_last_painted_x = -1;
        g_last_painted_y = -1;
    }
    ImGui::Dummy(ImVec2(1.0f, 5.0f));
    ImGui::TextDisabled("MAP WINDOW ORIGIN  X:%d  Y:%d   |   SELECTED  X:%d  Y:%d",
        g_map_origin_x, g_map_origin_y, g_selected_x, g_selected_y);
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

static void draw_tool_palette()
{
    panel_heading("TOOL PALETTE", "01");
    const char **tools = kTileTools;
    int count = 6;
    int selected = static_cast<int>(g_tool);
    switch (g_mode) {
    case MODE_ENTITY: tools = kEntityTools; count = 6; selected = 0; break;
    case MODE_EVENTS: tools = kEventTools; count = 6; selected = 0; break;
    case MODE_ASSETS: tools = kAssetTools; count = 5; selected = 0; break;
    case MODE_BOSS: tools = kBossTools; count = 6; selected = 0; break;
    default: break;
    }

    for (int i = 0; i < count; ++i) tool_button(tools[i], i, selected);
    ImGui::Spacing();
    ImGui::Separator();
    ImGui::TextDisabled("ACTIVE MODE");
    ImGui::TextColored(ImVec4(1.0f, 0.65f, 0.22f, 1.0f), "%s", kModeNames[g_mode]);
    if (g_mode == MODE_TILES) {
        ImGui::Spacing();
        ImGui::TextDisabled("BRUSH TILE");
        ImGui::SetNextItemWidth(-1.0f);
        ImGui::InputInt("##brush_tile", &g_brush_tile, 1, 16);
        g_brush_tile = std::max(0, std::min(2047, g_brush_tile));
    }
}

static void draw_layer_bar()
{
    ImGui::BeginChild("##layer_bar", ImVec2(0.0f, 38.0f), true);
    ImGui::TextColored(ImVec4(1.0f, 0.65f, 0.22f, 1.0f), "DEPTH");
    ImGui::SameLine();
    for (int i = 0; i < 5; ++i) {
        if (i) ImGui::SameLine();
        ImGui::Checkbox(kLayerNames[i], &g_layers[i]);
    }
    ImGui::EndChild();
}

static void draw_inspector()
{
    panel_heading("INSPECTOR", "LIVE");
    if (g_mode == MODE_TILES) {
        ImGui::TextDisabled("SELECTED TILE CELL");
        ImGui::Text("X: %d     Y: %d", g_selected_x, g_selected_y);
        int tile = mtlb_map_get(g_selected_x, g_selected_y);
        ImGui::Text("TILE INDEX");
        ImGui::SetNextItemWidth(-1.0f);
        if (ImGui::InputInt("##selected_tile", &tile, 1, 16)) {
            tile = std::max(0, std::min(2047, tile));
            mtlb_map_set(g_selected_x, g_selected_y, tile);
        }
        ImGui::Separator();
        ImGui::TextDisabled("TILE BRUSH");
        ImGui::SetNextItemWidth(-1.0f);
        ImGui::InputInt("##inspector_brush", &g_brush_tile, 1, 16);
        g_brush_tile = std::max(0, std::min(2047, g_brush_tile));
        ImGui::Spacing();
        if (ImGui::Button("APPLY TO SELECTED CELL", ImVec2(-1.0f, 30.0f))) {
            mtlb_map_set(g_selected_x, g_selected_y, g_brush_tile);
            std::snprintf(g_status, sizeof(g_status), "APPLIED TILE %03X TO CELL %d,%d",
                          g_brush_tile, g_selected_x, g_selected_y);
        }
        if (ImGui::Button("SAVE TILEMAP", ImVec2(-1.0f, 28.0f))) {
            std::snprintf(g_status, sizeof(g_status), "%s",
                mtlb_map_save() ? "TILEMAP SAVED  /levels/slot1.mtl" : "SAVE FAILED  /levels/slot1.mtl");
        }
        if (ImGui::Button("LOAD TILEMAP", ImVec2(-1.0f, 28.0f))) {
            std::snprintf(g_status, sizeof(g_status), "%s",
                mtlb_map_load() ? "TILEMAP LOADED  /levels/slot1.mtl" : "LOAD FAILED  /levels/slot1.mtl");
        }
    } else if (g_mode == MODE_ENTITY) {
        ImGui::TextDisabled("ENTITY PROPERTIES");
        ImGui::Text("Selection: none");
        ImGui::Text("Placement plane: 2D");
        ImGui::Text("Snap: 8 px");
        ImGui::Separator();
        ImGui::TextWrapped("Entity records and spawn integration are the next editor module.");
    } else if (g_mode == MODE_EVENTS) {
        ImGui::TextDisabled("SCRIPT NODE");
        ImGui::Text("Selection: none");
        ImGui::Text("Execution: paused");
        ImGui::Separator();
        ImGui::TextWrapped("Node graph storage and runtime event dispatch are not connected yet.");
    } else if (g_mode == MODE_ASSETS) {
        ImGui::TextDisabled("ASSET DOCUMENT");
        ImGui::Checkbox("MODERN RGBA", &g_asset_modern);
        ImGui::Text("Canvas: 16 x 16");
        ImGui::Text("CRAM mode: %s", g_asset_modern ? "OFF" : "64-COLOR");
        ImGui::Separator();
        ImGui::TextWrapped("Sprite and background import/export will be added in Asset Studio.");
    } else {
        ImGui::TextDisabled("ENTITY FORGE");
        ImGui::Text("Boss: NEW ENTITY");
        ImGui::Text("Phase: 01 / 03");
        ImGui::Text("Weakpoints: 0");
        ImGui::Separator();
        ImGui::TextWrapped("Boss assembly, AI behavior graphs and phase data are not connected yet.");
    }
}

static void draw_asset_canvas()
{
    ImGui::Text("16 x 16 PIXEL CANVAS");
    ImGui::SameLine();
    ImGui::Checkbox("MODERN RGBA", &g_asset_modern);
    ImGui::SetNextItemWidth(120.0f);
    ImGui::SliderInt("COLOR", &g_asset_color, 0, g_asset_modern ? 255 : 63);

    const float pixel = 14.0f;
    ImVec2 p = ImGui::GetCursorScreenPos();
    ImVec2 size(pixel * 16.0f, pixel * 16.0f);
    ImDrawList *draw = ImGui::GetWindowDrawList();
    draw->AddRectFilled(p, ImVec2(p.x + size.x, p.y + size.y), IM_COL32(7, 11, 17, 255));
    for (int y = 0; y < 16; ++y) {
        for (int x = 0; x < 16; ++x) {
            const int value = g_asset_pixels[y * 16 + x];
            if (value) {
                const int c = value & 255;
                draw->AddRectFilled(ImVec2(p.x + x * pixel, p.y + y * pixel),
                    ImVec2(p.x + (x + 1) * pixel - 1, p.y + (y + 1) * pixel - 1),
                    IM_COL32(55 + c % 170, 70 + (c * 3) % 150, 90 + (c * 7) % 140, 255));
            }
        }
    }
    for (int i = 0; i <= 16; ++i) {
        draw->AddLine(ImVec2(p.x + i * pixel, p.y),
                      ImVec2(p.x + i * pixel, p.y + size.y), IM_COL32(50, 69, 81, 150));
        draw->AddLine(ImVec2(p.x, p.y + i * pixel),
                      ImVec2(p.x + size.x, p.y + i * pixel), IM_COL32(50, 69, 81, 150));
    }
    ImGui::InvisibleButton("##asset_canvas", size,
        ImGuiButtonFlags_MouseButtonLeft | ImGuiButtonFlags_MouseButtonRight);
    if (ImGui::IsItemHovered() && ImGui::IsMouseDown(ImGuiMouseButton_Left)) {
        const ImVec2 m = ImGui::GetIO().MousePos;
        const int x = std::max(0, std::min(15, static_cast<int>((m.x - p.x) / pixel)));
        const int y = std::max(0, std::min(15, static_cast<int>((m.y - p.y) / pixel)));
        g_asset_pixels[y * 16 + x] = g_asset_color;
    }
    ImGui::TextDisabled("LOCAL CANVAS PREVIEW  /  IMPORT AND EXPORT PIPELINE PENDING");
}

static void draw_center_view()
{
    if (g_mode == MODE_TILES) {
        draw_tiles_viewport();
    } else if (g_mode == MODE_ENTITY) {
        draw_placeholder_viewport("ENTITY PLACEMENT / GAMEPLAY PLANE",
            "Choose an entity tool, then place spawn markers, enemies, pickups and patrol points. "
            "The visual controls are in place; entity serialization and runtime spawning are the next connection.");
    } else if (g_mode == MODE_EVENTS) {
        draw_placeholder_viewport("EVENT SCRIPT / NODE CANVAS",
            "WHEN, IF and ACTION blocks will connect through a visual wire graph. "
            "The editor layout is ready for the node system; event execution is not yet wired to gameplay.");
        ImGui::Text("AVAILABLE TRIGGERS");
        ImGui::BulletText("Player enters zone");
        ImGui::BulletText("Enemy or boss defeated");
        ImGui::BulletText("Timer reaches value");
        ImGui::BulletText("Player uses Plasma-Rope");
    } else if (g_mode == MODE_ASSETS) {
        draw_asset_canvas();
    } else {
        draw_placeholder_viewport("ENTITY FORGE / BOSS ASSEMBLY",
            "Assemble sprite and 3D body parts, set weakpoints, choose AI routines and create boss phases. "
            "This first pass establishes the custom editor surface.");
        ImGui::Text("BEHAVIOR PRESETS");
        ImGui::BulletText("Patrol Ledge     /     Hover & Swoop");
        ImGui::BulletText("Ceiling Crawler  /     Wall-Cling");
        ImGui::BulletText("Charge Bren      /     Three-Way Spread");
    }
}

static void draw_top_bar()
{
    ImGui::BeginChild("##topbar", ImVec2(0.0f, 48.0f), true);
    ImGui::TextColored(ImVec4(1.0f, 0.65f, 0.22f, 1.0f), "MEGA TURRICAN");
    ImGui::SameLine();
    ImGui::TextDisabled(" / REBORN LEVEL SYSTEM");
    ImGui::SameLine();
    ImGui::Dummy(ImVec2(8.0f, 1.0f));
    ImGui::SameLine();
    mode_button("TILES", MODE_TILES, 66.0f);
    ImGui::SameLine();
    mode_button("ENTITY", MODE_ENTITY, 80.0f);
    ImGui::SameLine();
    mode_button("EVENTS", MODE_EVENTS, 76.0f);
    ImGui::SameLine();
    mode_button("ASSETS", MODE_ASSETS, 76.0f);
    ImGui::SameLine();
    mode_button("BOSS FORGE", MODE_BOSS, 104.0f);
    ImGui::SameLine();
    ImGui::Dummy(ImVec2(8.0f, 1.0f));
    ImGui::SameLine();
    ImGui::BeginDisabled();
    ImGui::Button("START", ImVec2(82.0f, 30.0f));
    ImGui::EndDisabled();
    if (ImGui::IsItemHovered()) {
        ImGui::SetTooltip("Live playtest handoff is being connected after the editor foundation.");
    }
    ImGui::SameLine();
    if (ImGui::Button("EXIT", ImVec2(58.0f, 30.0f))) g_exit_requested = true;
    ImGui::EndChild();
}
} // namespace

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
    if (!renderer) return 0;
    if (!g_initialized) {
        SDL_Window *window = SDL_RenderGetWindow(renderer);
        if (!mtlb_init(window, renderer)) return 0;
    }

    ImGui_ImplSDLRenderer2_NewFrame();
    ImGui_ImplSDL2_NewFrame();
    ImGui::NewFrame();

    const ImGuiIO &io = ImGui::GetIO();
    if (!io.WantTextInput && ImGui::IsKeyPressed(ImGuiKey_Escape, false))
        g_exit_requested = true;

    const ImVec2 display = io.DisplaySize;
    const float width = std::max(800.0f, display.x);
    const float height = std::max(560.0f, display.y);

    ImGui::SetNextWindowPos(ImVec2(0.0f, 0.0f));
    ImGui::SetNextWindowSize(display);
    ImGui::SetNextWindowBgAlpha(0.68f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(10.0f, 9.0f));
    ImGui::Begin("##MT_LEVEL_BUILDER_ROOT", nullptr,
        ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
        ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoCollapse |
        ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoScrollbar |
        ImGuiWindowFlags_NoScrollWithMouse | ImGuiWindowFlags_NoBringToFrontOnFocus);

    draw_top_bar();

    const float body_height = std::max(360.0f, height - 88.0f);
    const float left_width = 198.0f;
    const float right_width = 246.0f;
    const float center_width = std::max(330.0f, display.x - left_width - right_width - 48.0f);

    ImGui::BeginChild("##tools", ImVec2(left_width, body_height), true);
    draw_tool_palette();
    ImGui::EndChild();
    ImGui::SameLine();

    ImGui::BeginChild("##center_column", ImVec2(center_width, body_height), false);
    draw_layer_bar();
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0.025f, 0.040f, 0.055f, 0.72f));
    ImGui::BeginChild("##stage_viewport", ImVec2(0.0f, body_height - 48.0f), true);
    draw_center_view();
    ImGui::EndChild();
    ImGui::PopStyleColor();
    ImGui::EndChild();
    ImGui::SameLine();

    ImGui::BeginChild("##inspector", ImVec2(right_width, body_height), true);
    draw_inspector();
    ImGui::EndChild();

    ImGui::SetCursorPosY(ImGui::GetCursorPosY() + 5.0f);
    ImGui::TextColored(ImVec4(0.34f, 0.78f, 0.83f, 1.0f), "SYSTEM");
    ImGui::SameLine();
    ImGui::TextDisabled("%s", g_status);
    ImGui::SameLine();
    ImGui::SetCursorPosX(ImGui::GetWindowWidth() - 120.0f);
    ImGui::TextDisabled("IMGUI 1.93.0");

    ImGui::End();
    ImGui::PopStyleVar();

    ImGui::Render();
    ImGui_ImplSDLRenderer2_RenderDrawData(ImGui::GetDrawData(), renderer);

    const bool exit_requested = g_exit_requested;
    if (exit_requested) g_exit_requested = false;
    return exit_requested ? 1 : 0;
}
