#include "mt_level_builder_rmlui.h"
#include "mt_level_builder_imgui.h"

#include "RmlUi_Platform_SDL.h"
#include "RmlUi_Renderer_SDL.h"
#include <RmlUi/Core/Core.h>
#include <RmlUi/Core/Context.h>
#include <RmlUi/Core/ElementDocument.h>
#include <RmlUi/Core/EventListener.h>
#include <RmlUi/Core/Log.h>

#include <algorithm>
#include <cstdio>
#include <cmath>
#include <cstdarg>
#include <cstdlib>
#include <string>
#include <vector>

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
static bool g_rml_initialised = false;
static bool g_exit_requested = false;
static int g_brush_tile = 1;
static int g_map_cols = 64;
static int g_map_rows = 32;
static int g_cached_window_width = -1, g_cached_window_height = -1;
static int g_cached_view_x = -1, g_cached_view_y = -1, g_cached_view_width = -1, g_cached_view_height = -1;
static int g_last_painted_x = -1, g_last_painted_y = -1, g_drag_tile = -1;
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

static void maker_prepare_log()
{
    if (!g_log_path.empty()) return;
    g_log_path = maker_portable_root();
    if (g_log_path != "." && g_log_path.back() != '/' && g_log_path.back() != '\\')
        g_log_path += '/';
    g_log_path += "maker-rmlui.log";
}

static void maker_log(const char *format, ...)
{
    maker_prepare_log();
    FILE *file = std::fopen(g_log_path.c_str(), "ab");
    if (!file) return;
    va_list args;
    va_start(args, format);
    std::vfprintf(file, format, args);
    va_end(args);
    std::fputc('\n', file);
    std::fclose(file);
}

static int maker_fail(const char *reason)
{
    std::snprintf(g_last_error, sizeof(g_last_error), "%s", reason ? reason : "Unknown RmlUi startup failure.");
    maker_log("INITIALIZATION FAILED: %s", g_last_error);
    return 0;
}

class MakerSystemInterface final : public SystemInterface_SDL
{
public:
    explicit MakerSystemInterface(SDL_Window *window) : SystemInterface_SDL(window) {}
    bool LogMessage(Rml::Log::Type type, const Rml::String &message) override
    {
        maker_log("RmlUi log type %d: %s", (int)type, message.c_str());
        return Rml::SystemInterface::LogMessage(type, message);
    }
};

static const char *kDocument = R"RML(
<rml>
<head>
<title>Mega Turrican Reborn Maker</title>
<style>
* { box-sizing: border-box; }
body { margin:0; padding:0; font-family:Lato,sans-serif; color:#e7edf4; background-color:#090f17; font-size:13px; }
.viewport { position:absolute; display:flex; flex-direction:column; overflow:hidden; background-color:#0b111a; }
.header { height:52px; min-height:52px; display:flex; flex-direction:row; align-items:center; padding:0 14px; background-color:#101a27; border-bottom:1px solid #34485c; }
.brand-mark { width:30px; height:30px; background-color:#e7a747; border-radius:5px; margin-right:10px; }
.brand { width:220px; }
.brand-title { color:#f0b65b; font-size:18px; font-weight:bold; letter-spacing:1.2px; }
.brand-sub { color:#8fa3b8; font-size:10px; letter-spacing:1.7px; }
.header-title { flex-grow:1; color:#d7e3ee; font-size:15px; font-weight:bold; }
.header-meta { color:#8195a8; font-size:11px; margin-right:10px; }
.button { display:inline-block; padding:8px 12px; margin-left:5px; border-radius:4px; background-color:#243448; border:1px solid #3c536c; color:#dce8f2; font-size:11px; font-weight:bold; text-align:center; }
.button:hover { background-color:#354b62; border-color:#e0a74e; }
.button.primary { color:#21190f; background-color:#e5ad57; border-color:#ffd080; }
.button.danger { color:#e8b8b8; background-color:#39252a; border-color:#704047; }
.modebar { height:46px; min-height:46px; display:flex; flex-direction:row; align-items:stretch; padding:6px 12px; background-color:#0d1621; border-bottom:1px solid #26394c; }
.mode-tab { flex:1; margin-right:5px; padding:7px 10px; text-align:center; color:#9eb0c2; background-color:#182637; border:1px solid #30465b; border-radius:4px; font-size:12px; font-weight:bold; letter-spacing:1px; }
.mode-tab:hover { color:#fff; background-color:#273c52; }
.mode-tab.active { color:#ffe0a4; background-color:#62401f; border-color:#d69c4c; }
.workspace { display:flex; flex-direction:row; flex-grow:1; min-height:0; padding:8px; }
.sidebar { width:190px; min-width:190px; background-color:#111b27; border:1px solid #2b3d50; border-radius:5px; padding:9px 7px; overflow:hidden; }
.section-label { color:#72879b; font-size:11px; font-weight:bold; letter-spacing:1.4px; margin:5px 4px 8px 4px; }
.tool-button { display:block; padding:9px 9px; margin-bottom:4px; background-color:#172433; border:1px solid #283d50; border-radius:4px; color:#aebdcb; font-size:12px; font-weight:bold; }
.tool-button:hover { color:#fff; background-color:#263a4d; border-color:#73889b; }
.tool-button.active { color:#ffdb9c; background-color:#3d3023; border-color:#c18b43; }
.sidebar-divider { height:1px; background-color:#2b3d50; margin:12px 3px; }
.library-item { display:block; padding:7px 8px; margin-bottom:3px; background-color:#0f1924; border:1px solid #263748; color:#8fa4b8; border-radius:3px; font-size:11px; }
.library-item:hover { color:#e8f0f7; border-color:#58748b; }
.main { display:flex; flex-direction:column; flex-grow:1; margin-left:8px; margin-right:8px; min-width:0; min-height:0; }
.layerbar { height:40px; min-height:40px; display:flex; flex-direction:row; align-items:center; padding:5px 8px; background-color:#111c29; border:1px solid #2b3d50; border-radius:5px; margin-bottom:8px; }
.layer-caption { color:#7f95a9; font-size:10px; font-weight:bold; letter-spacing:1px; margin-right:10px; }
.layer-chip { padding:6px 12px; margin-right:5px; border:1px solid #30445a; border-radius:4px; background-color:#1a2939; color:#95a9bc; font-size:10px; font-weight:bold; }
.layer-chip.active { color:#ffe0a4; border-color:#c58b40; background-color:#49331f; }
.layer-chip:hover { border-color:#8da3b6; }
.panel { background-color:#111b27; border:1px solid #2b3d50; border-radius:5px; }
.panel-heading { height:36px; display:flex; align-items:center; padding:0 12px; border-bottom:1px solid #2b3d50; color:#e4edf5; font-size:12px; font-weight:bold; letter-spacing:1px; }
.panel-kicker { flex-grow:1; color:#748ba1; font-size:10px; font-weight:normal; text-align:right; }
.stage-panel { display:flex; flex-direction:column; flex-grow:1; min-height:0; padding:8px; }
.stage-screen { display:flex; flex-direction:column; align-items:stretch; justify-content:stretch; flex-grow:1; min-height:0; background-color:#0a121c; border:1px solid #263a4e; border-radius:3px; padding:8px; }
.stage-topline { width:100%; padding:0 4px 7px 4px; color:#8198ad; font-size:10px; }
.stage-grid-wrap { flex-grow:1; min-height:0; width:100%; padding:8px; background-color:#0d1a27; border:1px solid #294158; border-radius:3px; }
.stage-grid { width:100%; height:100%; min-height:240px; overflow:hidden; background-color:#142638; }
.stage-hint { width:100%; padding:7px 4px 0 4px; color:#72889d; font-size:10px; }
.shelf { height:122px; min-height:122px; margin-top:8px; }
.asset-shelf-items { display:flex; flex-direction:row; flex-wrap:nowrap; align-items:center; padding:8px; height:84px; overflow:hidden; }
.asset-tile { width:58px; min-width:58px; height:64px; margin-right:6px; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; padding:3px; background-color:#19293a; border:1px solid #334b62; border-radius:4px; color:#b8c9d7; font-size:10px; }
.asset-tile:hover { background-color:#30465c; border-color:#e1a84e; }
.asset-tile.active { background-color:#403426; border-color:#e1a84e; color:#ffcf85; }
.asset-thumb { width:42px; height:42px; margin-bottom:2px; background-color:#0b121c; }
.inspector { width:238px; min-width:238px; padding:0 9px 9px 9px; overflow-y:auto; }
.inspector-section { padding:10px 2px; border-bottom:1px solid #293b4d; }
.inspector-label { color:#7790a5; font-size:10px; letter-spacing:1px; margin-bottom:7px; font-weight:bold; }
.inspector-value { color:#e5b15e; font-size:14px; font-weight:bold; }
.inspector-copy { color:#9aafc1; font-size:11px; line-height:1.5; }
.option-row { display:flex; flex-direction:row; align-items:center; margin:5px 0; }
.option-name { flex-grow:1; color:#9fb2c4; font-size:11px; }
.option-button { padding:6px 8px; margin-right:4px; background-color:#1b2b3c; border:1px solid #344b61; border-radius:3px; color:#b9c9d7; font-size:10px; }
.option-button.active { background-color:#49351f; border-color:#c58b40; color:#ffe0a4; }
.option-button:hover { border-color:#8197aa; }
.statusbar { height:30px; min-height:30px; display:flex; align-items:center; padding:0 12px; background-color:#111b27; border-top:1px solid #2b3d50; color:#8095a8; font-size:10px; }
.status-left { flex-grow:1; }
.status-accent { color:#e8b25d; }
.hidden { display:none; }
.modal-shade { position:absolute; left:0; top:0; width:100%; height:100%; display:flex; align-items:center; justify-content:center; background-color:#000000aa; z-index:100; }
.modal-shade.hidden { display:none; }
.settings-dialog { width:620px; max-height:88%; background-color:#121e2b; border:1px solid #b47c35; border-radius:6px; padding:14px; }
.settings-title { color:#f2bd68; font-size:17px; font-weight:bold; padding-bottom:10px; border-bottom:1px solid #34485b; }
.settings-columns { display:flex; flex-direction:row; }
.settings-col { flex:1; padding:8px 12px 8px 2px; }
.setting-card { margin-bottom:12px; padding:10px; background-color:#0e1823; border:1px solid #2d4358; border-radius:4px; }
.setting-card-title { color:#82cbd2; font-size:11px; font-weight:bold; margin-bottom:8px; }
</style>
</head>
<body>
<div id="viewport" class="viewport">
  <div class="header">
    <div class="brand-mark"></div>
    <div class="brand"><div class="brand-title">MEGA TURRICAN</div><div class="brand-sub">REBORN / LEVEL CREATION SYSTEM</div></div>
    <div class="header-title">MAKER <span style="color:#7f94a9">/ UNTITLED LEVEL</span></div>
    <div class="header-meta">64 × 32 GENESIS GRID</div>
    <div class="button" data-action="undo">UNDO</div>
    <div class="button" data-action="redo">REDO</div>
    <div class="button" data-action="settings">SETTINGS</div>
    <div class="button" data-action="load">LOAD</div>
    <div class="button primary" data-action="save">SAVE</div>
    <div class="button danger" data-action="exit">DONE</div>
  </div>
  <div class="modebar">
    <div id="mode-0" class="mode-tab active" data-action="mode" data-mode="0">TILES</div>
    <div id="mode-1" class="mode-tab" data-action="mode" data-mode="1">OBJECTS</div>
    <div id="mode-2" class="mode-tab" data-action="mode" data-mode="2">EVENT SCRIPT</div>
    <div id="mode-3" class="mode-tab" data-action="mode" data-mode="3">ASSET STUDIO</div>
    <div id="mode-4" class="mode-tab" data-action="mode" data-mode="4">BOSS FORGE</div>
    <div id="mode-5" class="mode-tab" data-action="mode" data-mode="5">BACKGROUNDS</div>
  </div>
  <div class="workspace">
    <div class="sidebar">
      <div id="tool-heading" class="section-label">TILE TOOLS</div>
      <div id="tool-list">
        <div class="tool-button active" data-action="tool" data-tool="0">SELECT</div>
        <div class="tool-button" data-action="tool" data-tool="1">TILE BRUSH</div>
        <div class="tool-button" data-action="tool" data-tool="7">ERASER</div>
        <div class="tool-button" data-action="tool" data-tool="2">COLLISION PAINTER</div>
        <div class="tool-button" data-action="tool" data-tool="3">GRAPPLE ANCHOR</div>
        <div class="tool-button" data-action="tool" data-tool="4">TRIGGER BOX</div>
      </div>
      <div class="sidebar-divider"></div>
      <div class="section-label">LIBRARY</div>
      <div id="library-list">
        <div class="library-item" data-action="library" data-library="ROM TILES">ROM TILE BANK</div>
        <div class="library-item" data-action="library" data-library="SPRITE SETS">SPRITE SETS</div>
        <div class="library-item" data-action="library" data-library="CUSTOM ASSETS">CUSTOM ASSETS</div>
      </div>
      <div class="sidebar-divider"></div>
      <div class="section-label">PROJECT</div>
      <div class="inspector-copy">Portable project settings and level documents are stored beside the launcher.</div>
      <div class="button" data-action="settings" style="width:100%;margin:8px 0 0 0">PROJECT OPTIONS</div>
    </div>
    <div class="main">
      <div class="layerbar">
        <div class="layer-caption">LAYERS</div>
        <div id="layer-0" class="layer-chip active" data-action="layer" data-layer="0">BG</div>
        <div id="layer-1" class="layer-chip active" data-action="layer" data-layer="1">MID</div>
        <div id="layer-2" class="layer-chip active" data-action="layer" data-layer="2">GAMEPLAY</div>
        <div id="layer-3" class="layer-chip active" data-action="layer" data-layer="3">FG</div>
        <div id="layer-4" class="layer-chip" data-action="layer" data-layer="4">3D DEPTH</div>
        <div style="flex-grow:1"></div>
        <div class="option-button active" data-action="toggle" data-key="grid">GRID</div>
        <div class="option-button active" data-action="toggle" data-key="snap">SNAP</div>
      </div>
      <div class="panel stage-panel">
        <div class="panel-heading">STAGE CANVAS <span id="stage-meta" class="panel-kicker">TILE EDITOR / 64 × 32 / GAMEPLAY LAYER</span></div>
        <div class="stage-screen">
          <div id="stage-topline" class="stage-topline">LEVEL 01 / GAMEPLAY LAYER / GRID SNAP ENABLED</div>
          <div class="stage-grid-wrap"><div id="stage-grid" class="stage-grid"></div></div>
          <div id="stage-hint" class="stage-hint">Left click paints the selected cartridge tile. Right click erases.</div>
        </div>
      </div>
      <div class="panel shelf">
        <div class="panel-heading">CARTRIDGE ASSET BROWSER <span id="asset-count" class="panel-kicker">WAITING FOR VDP ASSETS</span></div>
        <div id="asset-shelf-items" class="asset-shelf-items"></div>
      </div>
    </div>
    <div class="panel inspector">
      <div class="panel-heading">INSPECTOR <span class="panel-kicker">LIVE</span></div>
      <div id="mode-inspector">
        <div class="inspector-section">
          <div class="inspector-label">SELECTED TILE</div>
          <div id="brush-value" class="inspector-value">$00B0</div>
          <div class="inspector-copy">Choose a cartridge tile from the asset browser, then paint the stage.</div>
        </div>
        <div class="inspector-section">
          <div class="inspector-label">TILE OPTIONS</div>
          <div class="option-row"><div class="option-name">PALETTE</div><div class="option-button active" data-action="palette" data-palette="0">0</div><div class="option-button" data-action="palette" data-palette="1">1</div><div class="option-button" data-action="palette" data-palette="2">2</div><div class="option-button" data-action="palette" data-palette="3">3</div></div>
          <div class="option-row"><div class="option-name">COLLISION</div><div class="option-button active" data-action="toggle" data-key="collision">ON</div></div>
        </div>
        <div class="inspector-section">
          <div class="inspector-label">SELECTED CELL</div>
          <div id="selected-cell" class="inspector-value">X:00 / Y:00</div>
          <div class="inspector-copy">64 × 32 editable cells. Changes are saved in the level document.</div>
        </div>
      </div>
    </div>
  </div>
  <div class="statusbar"><div class="status-left"><span class="status-accent">READY</span> &nbsp; <span id="status-text">RmlUi Maker ready. Choose a mode, tool and cartridge asset.</span></div><div>MEGA TURRICAN REBORN / MAKER</div></div>
</div>
<div id="settings-modal" class="modal-shade hidden">
  <div class="settings-dialog">
    <div class="settings-title">PROJECT / EDITOR SETTINGS</div>
    <div class="settings-columns">
      <div class="settings-col">
        <div class="setting-card">
          <div class="setting-card-title">GRAPHICS PROFILE</div>
          <div class="option-row"><div class="option-name">GENESIS / VANILLA</div><div id="graphics-vanilla" class="option-button active" data-action="graphics" data-value="vanilla">64 COLORS</div></div>
          <div class="option-row"><div class="option-name">MODERN MODE</div><div id="graphics-modern" class="option-button" data-action="graphics" data-value="modern">FULL RGBA</div></div>
        </div>
        <div class="setting-card">
          <div class="setting-card-title">DRAWING CANVAS</div>
          <div class="option-row"><div class="option-name">PIXEL GRID</div><div id="canvas-16" class="option-button active" data-action="canvas-size" data-size="16">16 × 16</div><div id="canvas-32" class="option-button" data-action="canvas-size" data-size="32">32 × 32</div></div>
          <div class="option-row"><div class="option-name">DISPLAY GRID</div><div class="option-button active" data-action="toggle" data-key="grid">ON / OFF</div></div>
          <div class="option-row"><div class="option-name">SNAP TO GRID</div><div class="option-button active" data-action="toggle" data-key="snap">ON / OFF</div></div>
        </div>
      </div>
      <div class="settings-col">
        <div class="setting-card">
          <div class="setting-card-title">STAGE LAYERS</div>
          <div class="option-row"><div class="option-name">BACKGROUND</div><div class="option-button active" data-action="layer" data-layer="0">VISIBLE</div></div>
          <div class="option-row"><div class="option-name">MID PARALLAX</div><div class="option-button active" data-action="layer" data-layer="1">VISIBLE</div></div>
          <div class="option-row"><div class="option-name">GAMEPLAY</div><div class="option-button active" data-action="layer" data-layer="2">VISIBLE</div></div>
          <div class="option-row"><div class="option-name">FOREGROUND</div><div class="option-button active" data-action="layer" data-layer="3">VISIBLE</div></div>
          <div class="option-row"><div class="option-name">3D DEPTH</div><div class="option-button" data-action="layer" data-layer="4">VISIBLE</div></div>
        </div>
        <div class="setting-card">
          <div class="setting-card-title">AUDIO / BACKGROUND</div>
          <div class="inspector-copy">Custom background music and layered image import are being connected to the portable asset pipeline. These options will not pretend to import files until that pipeline is complete.</div>
        </div>
      </div>
    </div>
    <div style="text-align:right;padding-top:8px;border-top:1px solid #34485b">
      <div class="button" data-action="settings-close">CLOSE</div>
      <div class="button primary" data-action="settings-save">APPLY / SAVE OPTIONS</div>
    </div>
  </div>
</div>
</body>
</rml>
)RML";

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

    g_stage_vertices.clear();
    g_stage_indices.clear();
    const size_t quads = (size_t)g_map_cols * (size_t)g_map_rows + (size_t)g_map_cols + (size_t)g_map_rows + 2u;
    if (g_stage_vertices.capacity() < quads * 4u) g_stage_vertices.reserve(quads * 4u);
    if (g_stage_indices.capacity() < quads * 6u) g_stage_indices.reserve(quads * 6u);

    static const SDL_Color palette[8] = {
        {104,145,125,255}, {112,151,185,255}, {196,132,77,255}, {135,119,184,255},
        {167,166,119,255}, {77,151,157,255}, {181,103,111,255}, {103,124,155,255}
    };
    const float cell_w = width / (float)g_map_cols;
    const float cell_h = height / (float)g_map_rows;

    // Fill existing cells in one geometry batch instead of creating 2,048 DOM elements.
    for (int y = 0; y < g_map_rows; ++y) {
        for (int x = 0; x < g_map_cols; ++x) {
            const int tile = mtlb_map_get(x, y);
            if (tile == 0) continue;
            const int ci = (tile >= 176 && tile <= 183) ? tile - 176 : (tile & 7);
            append_stage_quad(origin.x + x*cell_w + 1.0f, origin.y + y*cell_h + 1.0f,
                origin.x + (x+1)*cell_w - 1.0f, origin.y + (y+1)*cell_h - 1.0f, palette[ci]);
        }
    }

    const SDL_Color grid = {43,65,83,255};
    for (int x = 0; x <= g_map_cols; ++x) {
        const float px = origin.x + x*cell_w;
        append_stage_quad(px, origin.y, px + 1.0f, origin.y + height, grid);
    }
    for (int y = 0; y <= g_map_rows; ++y) {
        const float py = origin.y + y*cell_h;
        append_stage_quad(origin.x, py, origin.x + width, py + 1.0f, grid);
    }

    SDL_Rect clip{(int)std::floor(origin.x), (int)std::floor(origin.y),
        (int)std::ceil(width), (int)std::ceil(height)};
    SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
    SDL_RenderSetClipRect(renderer, &clip);
    SDL_RenderGeometry(renderer, nullptr, g_stage_vertices.data(), (int)g_stage_vertices.size(),
        g_stage_indices.data(), (int)g_stage_indices.size());
    SDL_RenderSetClipRect(renderer, nullptr);
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
    if(!g_document) return;
    for(int i=0;i<MAKER_MODE_COUNT;i++){
        char id[32];std::snprintf(id,sizeof(id),"mode-%d",i);
        if(Rml::Element *tab=g_document->GetElementById(id)) tab->SetClass("active",i==g_maker_mode);
    }
    if(Rml::Element *heading=g_document->GetElementById("tool-heading"))
        heading->SetInnerRML(std::string(maker_mode_name(g_maker_mode))+" TOOLS");
    if(Rml::Element *tools=g_document->GetElementById("tool-list"))
        tools->SetInnerRML(maker_tool_list(g_maker_mode));
    if(Rml::Element *meta=g_document->GetElementById("stage-meta"))
        meta->SetInnerRML(std::string(maker_mode_name(g_maker_mode))+" / 64 × 32 / "+(g_maker_layer==2?"GAMEPLAY":"CUSTOM LAYER"));
    if(Rml::Element *hint=g_document->GetElementById("stage-hint")){
        static const char *hints[MAKER_MODE_COUNT]={
            "Select a cartridge tile below. Left click paints; right click erases. Brush size and palette are in the inspector.",
            "Choose a ROM sprite set below, then click the stage to place an enemy, pickup or spawn marker.",
            "Choose a trigger, condition, action or dialogue tool. Click the stage to place a script marker.",
            "Choose 16×16 or 32×32, Genesis 64-color or Modern RGBA in Settings. The pixel canvas tools are shown in the inspector.",
            "Choose a ROM sprite set below, then select a boss part or phase tool. Boss assembly options are in the inspector.",
            "Select one of five depth layers. Parallax and raster controls are available in the inspector."
        };
        hint->SetInnerRML(hints[g_maker_mode]);
    }
    if(Rml::Element *inspector=g_document->GetElementById("mode-inspector")){
        std::string content;
        if(g_maker_mode==MAKER_TILES){
            char value[80];std::snprintf(value,sizeof(value),"$%04X",g_brush_tile);
            content="<div class='inspector-section'><div class='inspector-label'>TILE BRUSH</div><div id='brush-value' class='inspector-value'>"+std::string(value)+"</div><div class='inspector-copy'>Selected cartridge tile and VDP palette attributes.</div></div>"
            "<div class='inspector-section'><div class='inspector-label'>PALETTE</div><div class='option-row'>";
            for(int i=0;i<4;i++){char b[140];std::snprintf(b,sizeof(b),"<div class='option-button %s' data-action='palette' data-palette='%d'>PAL %d</div>",i==g_maker_palette?"active":"",i,i);content+=b;}
            content+="</div><div class='inspector-label'>TILE OPTIONS</div><div class='option-row'><div class='option-name'>COLLISION OVERLAY</div>";
            content+=std::string("<div class='option-button ")+(g_maker_collision?"active":"")+"' data-action='toggle' data-key='collision'>"+(g_maker_collision?"ON":"OFF")+"</div></div></div>";
            content+="<div class='inspector-section'><div class='inspector-label'>SELECTED CELL</div><div id='selected-cell' class='inspector-value'>X:"+std::to_string(mtlb_map_cursor_x())+" / Y:"+std::to_string(mtlb_map_cursor_y())+"</div><div class='inspector-copy'>64 × 32 cells. Undo and redo are available in the top bar.</div></div>";
        }else if(g_maker_mode==MAKER_OBJECTS){
            content="<div class='inspector-section'><div class='inspector-label'>OBJECT PLACEMENT</div><div class='inspector-value'>ROM SPRITE SETS</div><div class='inspector-copy'>Choose a cartridge sprite set in the asset shelf. Select PLACE ENEMY or PLACE PICKUP, then click the stage.</div></div>"
            "<div class='inspector-section'><div class='inspector-label'>OBJECT OPTIONS</div><div class='option-row'><div class='option-name'>SNAP TO GRID</div><div class='option-button active' data-action='toggle' data-key='snap'>ON / OFF</div></div><div class='option-row'><div class='option-name'>COLLISION</div><div class='option-button active' data-action='toggle' data-key='collision'>ON / OFF</div></div></div>";
        }else if(g_maker_mode==MAKER_EVENTS){
            content="<div class='inspector-section'><div class='inspector-label'>SCRIPT MAKER</div><div class='inspector-value'>EVENT FLOW</div><div class='inspector-copy'>Create nodes using the tools. Supported node types include WHEN triggers, IF conditions, actions, dialogue and boss spawn markers.</div></div>"
            "<div class='inspector-section'><div class='inspector-label'>QUICK ADD</div><div class='option-row'><div class='option-button' data-action='event-add' data-event='0'>+ WHEN</div><div class='option-button' data-action='event-add' data-event='1'>+ IF</div></div><div class='option-row'><div class='option-button' data-action='event-add' data-event='2'>+ ACTION</div><div class='option-button' data-action='event-add' data-event='3'>+ DIALOGUE</div></div><div id='event-count' class='inspector-copy'>0 event nodes in this level.</div></div>";
        }else if(g_maker_mode==MAKER_ASSETS){
            content="<div class='inspector-section'><div class='inspector-label'>ASSET STUDIO</div><div class='inspector-value'>"+std::to_string(g_maker_canvas_size)+" × "+std::to_string(g_maker_canvas_size)+" PIXEL CANVAS</div><div class='inspector-copy'>Genesis mode uses 64-color palettes. Modern mode allows unrestricted RGBA color.</div></div>"
            "<div class='inspector-section'><div class='inspector-label'>CANVAS SIZE</div><div class='option-row'><div class='option-button "+std::string(g_maker_canvas_size==16?"active":"")+"' data-action='canvas-size' data-size='16'>16 × 16</div><div class='option-button "+(g_maker_canvas_size==32?"active":"")+"' data-action='canvas-size' data-size='32'>32 × 32</div></div><div class='option-row'><div class='option-button "+(g_maker_modern?"":"active")+"' data-action='graphics' data-value='vanilla'>GENESIS CRAM</div><div class='option-button "+(g_maker_modern?"active":"")+"' data-action='graphics' data-value='modern'>MODERN RGBA</div></div></div>"
            "<div class='inspector-section'><div class='inspector-label'>PALETTE COLOR</div><div class='option-copy'>Choose a color swatch in the settings window. Pixel drawing canvas is the active work surface.</div></div>";
        }else if(g_maker_mode==MAKER_BOSS){
            char b[80];std::snprintf(b,sizeof(b),"%d HP / PHASE %d",g_boss_hp,g_boss_phase);
            content="<div class='inspector-section'><div class='inspector-label'>BOSS ASSEMBLY</div><div class='inspector-value'>"+std::string(g_boss_created?"CORE CREATED":"NO CORE")+"</div><div class='inspector-copy'>Assemble body parts, turrets, shield plates and weakpoints from ROM sprite sets.</div></div>"
            "<div class='inspector-section'><div class='inspector-label'>BOSS CORE</div><div class='option-row'><div class='option-button' data-action='boss-create'>CREATE CORE</div><div class='option-button' data-action='boss-hp' data-delta='-10'>- HP</div><div class='option-button' data-action='boss-hp' data-delta='10'>+ HP</div></div><div class='inspector-value'>"+std::string(b)+"</div><div class='option-row'><div class='option-button' data-action='boss-phase' data-phase='1'>PHASE 1</div><div class='option-button' data-action='boss-phase' data-phase='2'>PHASE 2</div><div class='option-button' data-action='boss-phase' data-phase='3'>ENRAGE</div></div></div>";
        }else{
            content="<div class='inspector-section'><div class='inspector-label'>BACKGROUND LAYERS</div><div class='inspector-value'>4 PARALLAX PLANES</div><div class='inspector-copy'>Choose a depth layer, then adjust its horizontal and vertical scroll multipliers.</div></div>";
            for(int i=0;i<4;i++){char row[260];std::snprintf(row,sizeof(row),"<div class='inspector-section'><div class='inspector-label'>LAYER %d / X %.2f / Y %.2f</div><div class='option-row'><div class='option-name'>SCROLL X</div><div class='option-button' data-action='parallax' data-layer='%d' data-axis='x' data-delta='-0.1'>-</div><div class='option-button' data-action='parallax' data-layer='%d' data-axis='x' data-delta='0.1'>+</div></div><div class='option-row'><div class='option-name'>SCROLL Y</div><div class='option-button' data-action='parallax' data-layer='%d' data-axis='y' data-delta='-0.1'>-</div><div class='option-button' data-action='parallax' data-layer='%d' data-axis='y' data-delta='0.1'>+</div></div></div>",i+1,g_parallax_x[i],g_parallax_y[i],i,i,i,i);
                content+=row;}
        }
        inspector->SetInnerRML(content);
    }
}

static void maker_refresh_asset_shelf()
{
    if(!g_document) return;
    const int count=mtlb_editor_tile_count();
    if(count!=g_asset_shelf_count || mtlb_editor_vdp_art_hash()!=g_asset_shelf_hash){
        g_asset_shelf_count=count;
        g_asset_shelf_hash=mtlb_editor_vdp_art_hash();
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
            g_maker_mode = std::max(0,std::min(MAKER_MODE_COUNT-1,element->GetAttribute<int>("data-mode",0)));
            g_maker_tool = 0;
            maker_update_mode_ui();
            maker_save_settings();
            set_status(std::string("Switched to ")+maker_mode_name(g_maker_mode)+".");
            return;
        }
        if (action == "tool") {
            g_maker_tool = std::max(0,std::min(8,element->GetAttribute<int>("data-tool",0)));
            if(g_maker_mode==MAKER_TILES && g_maker_tool==1) select_brush(g_brush_tile);
            maker_update_mode_ui();
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
                maker_save_settings();
                set_status(key+" option updated.");
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
            set_status(std::string("Library filter: ")+name+".");
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

    g_document = g_context->LoadDocumentFromMemory(kDocument);
    if (!g_document) {
        mtlbr_shutdown();
        return maker_fail("RmlUi failed to parse or load the embedded Maker document. See maker-rmlui.log.");
    }
    maker_log("Embedded Maker RML document loaded.");
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
    g_document->Show();
    g_exit_requested = false;
    g_brush_tile = mtlb_map_brush();
    if (g_brush_tile < 176 || g_brush_tile > 180) g_brush_tile = 176;
    select_brush(g_brush_tile);
    maker_update_mode_ui();
    maker_refresh_asset_shelf();
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
