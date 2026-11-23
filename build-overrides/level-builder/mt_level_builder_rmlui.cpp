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
    body { margin: 0; padding: 0; font-family: Lato, sans-serif; color: #e7edf4; background-color: #0b111a; }
    .viewport { position: absolute; display: flex; flex-direction: column; overflow: hidden; background-color: #0b111a; }
    .header { height: 48px; min-height: 48px; display: flex; flex-direction: row; align-items: center; padding: 0 14px; background-color: #111b28; border-bottom: 1px solid #314357; }
    .brand-mark { width: 27px; height: 27px; background-color: #e7a747; border-radius: 5px; margin-right: 9px; }
    .brand { width: 205px; }
    .brand-title { color: #f0b65b; font-size: 18px; font-weight: bold; letter-spacing: 1.2px; }
    .brand-sub { color: #8fa3b8; font-size: 11px; letter-spacing: 1.7px; }
    .header-title { flex-grow: 1; color: #d7e3ee; font-size: 16px; font-weight: bold; }
    .header-meta { color: #8195a8; font-size: 12px; margin-right: 10px; }
    .button { display: inline-block; padding: 8px 14px; margin-left: 5px; border-radius: 4px; background-color: #243448; border: 1px solid #3c536c; color: #dce8f2; font-size: 12px; font-weight: bold; text-align: center; }
    .button:hover { background-color: #354b62; border-color: #e0a74e; }
    .button.primary { color: #21190f; background-color: #e5ad57; border-color: #ffd080; }
    .button.primary:hover { background-color: #f6c675; }
    .button.danger { color: #e8b8b8; background-color: #39252a; border-color: #704047; }
    .toolbar { height: 34px; min-height: 34px; display: flex; align-items: center; padding: 0 12px; background-color: #172434; border-bottom: 1px solid #26394c; }
    .crumb { color: #7f94a9; font-size: 12px; }
    .crumb strong { color: #e5b05d; }
    .toolbar-right { flex-grow: 1; text-align: right; color: #8297aa; font-size: 11px; }
    .workspace { display: flex; flex-direction: row; flex-grow: 1; padding: 8px; }
    .sidebar { width: 142px; min-width: 142px; background-color: #111b27; border: 1px solid #2b3d50; border-radius: 5px; padding: 9px 7px; }
    .section-label { color: #72879b; font-size: 11px; font-weight: bold; letter-spacing: 1.4px; margin: 5px 4px 8px 4px; }
    .nav-item { display: block; padding: 10px 8px; margin-bottom: 4px; background-color: #172433; border: 1px solid transparent; border-radius: 4px; color: #9fb1c3; font-size: 12px; font-weight: bold; }
    .nav-item:hover { color: #ffffff; background-color: #24364a; border-color: #435a70; }
    .nav-item.active { color: #ffd18a; background-color: #3a3025; border-color: #bd8b43; }
    .sidebar-note { margin: 12px 4px 4px 4px; padding-top: 9px; border-top: 1px solid #2a3a4a; color: #75899d; font-size: 11px; line-height: 1.5; }
    .main { display: flex; flex-direction: column; flex-grow: 1; margin-left: 8px; margin-right: 8px; min-width: 0; }
    .panel { background-color: #111b27; border: 1px solid #2b3d50; border-radius: 5px; }
    .panel-heading { height: 34px; display: flex; align-items: center; padding: 0 12px; border-bottom: 1px solid #2b3d50; color: #e4edf5; font-size: 12px; font-weight: bold; letter-spacing: 1px; }
    .panel-kicker { flex-grow: 1; color: #748ba1; font-size: 11px; font-weight: normal; text-align: right; }
    .stage-panel { flex-grow: 1; padding: 8px; }
    .stage-screen { width: 100%; height: 100%; min-height: 420px; display: flex; flex-direction: column; align-items: center; justify-content: center; background-color: #0a121c; border: 1px solid #263a4e; border-radius: 3px; }
    .stage-topline { width: 100%; padding: 0 12px 8px 12px; color: #8198ad; font-size: 11px; }
    .stage-grid-wrap { padding: 9px; background-color: #0d1a27; border: 1px solid #294158; border-radius: 3px; }
    .stage-grid { width: 768px; height: 384px; overflow: hidden; background-color: #142638; }
    .stage-hint { width: 100%; padding: 8px 12px 0 12px; color: #72889d; font-size: 11px; }
    .shelf { height: 75px; min-height: 75px; margin-top: 8px; }
    .shelf-content { display: flex; flex-direction: row; align-items: center; padding: 9px; }
    .brush { width: 62px; height: 48px; margin-right: 8px; display: flex; flex-direction: column; align-items: center; justify-content: center; background-color: #19293a; border: 1px solid #334b62; border-radius: 4px; color: #b8c9d7; font-size: 10px; }
    .brush:hover { background-color: #30465c; border-color: #e1a84e; }
    .brush.active { background-color: #403426; border-color: #e1a84e; color: #ffcf85; }
    .brush-swatch { width: 17px; height: 17px; margin-bottom: 3px; background-color: #668b77; border: 1px solid #94baa0; border-radius: 2px; }
    .brush-swatch.b2 { background-color: #718da7; border-color: #a1bed9; }
    .brush-swatch.b3 { background-color: #b77f4c; border-color: #e0ad77; }
    .brush-swatch.b4 { background-color: #766b9d; border-color: #a89acb; }
    .brush-swatch.b5 { background-color: #9b9b78; border-color: #c6c59f; }
    .shelf-caption { color: #7890a5; font-size: 11px; margin-right: 12px; }
    .inspector { width: 174px; min-width: 174px; padding: 0 9px 9px 9px; }
    .inspector-section { padding: 10px 2px; border-bottom: 1px solid #293b4d; }
    .inspector-label { color: #7790a5; font-size: 11px; letter-spacing: 1px; margin-bottom: 7px; }
    .inspector-value { color: #e5b15e; font-size: 15px; font-weight: bold; }
    .inspector-copy { color: #9aafc1; font-size: 11px; line-height: 1.5; }
    .statusbar { height: 30px; min-height: 30px; display: flex; align-items: center; padding: 0 12px; background-color: #111b27; border-top: 1px solid #2b3d50; color: #8095a8; font-size: 11px; }
    .status-left { flex-grow: 1; }
    .status-accent { color: #e8b25d; }
  </style>
</head>
<body>
  <div id="viewport" class="viewport">
    <div class="header">
      <div class="brand-mark"></div>
      <div class="brand"><div class="brand-title">MEGA TURRICAN</div><div class="brand-sub">REBORN / CREATION SYSTEM</div></div>
      <div class="header-title">LEVEL MAKER <span class="crumb">/ UNTITLED LEVEL</span></div>
      <div class="header-meta">64 × 32 GENESIS GRID</div>
      <div class="button" data-action="load">LOAD</div>
      <div class="button primary" data-action="save">SAVE LEVEL</div>
      <div class="button danger" data-action="exit">DONE</div>
    </div>
    <div class="toolbar">
      <div class="crumb"><strong>BUILD</strong> &nbsp; / &nbsp; STAGE EDITOR &nbsp; / &nbsp; LAYER 04: GAMEPLAY</div>
      <div class="toolbar-right">ROM ASSET INDEX CONNECTED &nbsp; • &nbsp; DOCUMENT READY</div>
    </div>
    <div class="workspace">
      <div class="sidebar">
        <div class="section-label">CREATE</div>
        <div id="nav-tiles" class="nav-item active" data-action="section" data-section="TILES">01 &nbsp; TILE PALETTE</div>
        <div id="nav-actors" class="nav-item" data-action="section" data-section="ACTORS">02 &nbsp; ACTORS</div>
        <div id="nav-objects" class="nav-item" data-action="section" data-section="OBJECTS">03 &nbsp; OBJECTS</div>
        <div id="nav-bosses" class="nav-item" data-action="section" data-section="BOSSES">04 &nbsp; BOSSES</div>
        <div id="nav-events" class="nav-item" data-action="section" data-section="EVENTS">05 &nbsp; EVENTS</div>
        <div id="nav-backgrounds" class="nav-item" data-action="section" data-section="BACKGROUNDS">06 &nbsp; BACKGROUNDS</div>
        <div class="sidebar-note">BUILT-IN CONTENT<br/>Original cartridge art index<br/>No stage capture required</div>
      </div>
      <div class="main">
        <div class="panel stage-panel">
          <div class="panel-heading">STAGE CANVAS <span class="panel-kicker">CLICK CELLS TO PAINT • 64 × 32</span></div>
          <div class="stage-screen">
            <div class="stage-topline">LEVEL 01 &nbsp; / &nbsp; GAMEPLAY LAYER &nbsp; / &nbsp; GRID SNAP ENABLED</div>
            <div class="stage-grid-wrap"><div id="stage-grid" class="stage-grid"></div></div>
            <div class="stage-hint">This is the editable level grid. Selected tiles are stored in the level document.</div>
          </div>
        </div>
        <div class="panel shelf">
          <div class="panel-heading">QUICK TILE BRUSHES <span class="panel-kicker">SELECT A BRUSH, THEN PAINT THE GRID</span></div>
          <div class="shelf-content">
            <div class="shelf-caption">ROM TILE</div>
            <div id="brush-176" class="brush active" data-action="brush" data-brush="176"><div class="brush-swatch"></div>$0B0</div>
            <div id="brush-177" class="brush" data-action="brush" data-brush="177"><div class="brush-swatch b2"></div>$0B1</div>
            <div id="brush-178" class="brush" data-action="brush" data-brush="178"><div class="brush-swatch b3"></div>$0B2</div>
            <div id="brush-179" class="brush" data-action="brush" data-brush="179"><div class="brush-swatch b4"></div>$0B3</div>
            <div id="brush-180" class="brush" data-action="brush" data-brush="180"><div class="brush-swatch b5"></div>$0B4</div>
          </div>
        </div>
      </div>
      <div class="panel inspector">
        <div class="panel-heading">INSPECTOR</div>
        <div class="inspector-section">
          <div class="inspector-label">ACTIVE SECTION</div>
          <div id="section-value" class="inspector-value">TILE PALETTE</div>
          <div class="inspector-copy">Choose a content category on the left to switch the library view.</div>
        </div>
        <div class="inspector-section">
          <div class="inspector-label">SELECTED BRUSH</div>
          <div id="brush-value" class="inspector-value">$0001</div>
          <div class="inspector-copy">Paints the selected map cell with this tile ID.</div>
        </div>
        <div class="inspector-section">
          <div class="inspector-label">LEVEL DOCUMENT</div>
          <div class="inspector-value">64 × 32</div>
          <div class="inspector-copy">2048 editable cells<br/>Save and load from the Maker workspace.</div>
        </div>
        <div class="inspector-section">
          <div class="inspector-label">EDITOR STATUS</div>
          <div class="inspector-copy">RmlUi interface active<br/>SDL renderer retained<br/>ImGui fallback preserved</div>
        </div>
      </div>
    </div>
    <div class="statusbar"><div class="status-left"><span class="status-accent">READY</span> &nbsp; <span id="status-text">RmlUi Maker interface online — original editor data retained.</span></div><div>MEGA TURRICAN REBORN &nbsp; • &nbsp; MAKER</div></div>
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
    set_status("RmlUi Maker interface online — existing level document and editor data retained.");
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
