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
#include <cstdlib>
#include <string>

namespace {
static SDL_Window *g_window = nullptr;
static SDL_Renderer *g_renderer = nullptr;
static SystemInterface_SDL *g_system = nullptr;
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
    .stage-grid { width: 768px; height: 384px; overflow: hidden; display: flex; flex-direction: column; background-color: #142638; }
    .stage-row { width: 768px; height: 12px; min-height: 12px; display: flex; flex-direction: row; }
    .cell { display: block; flex: 0 0 12px; width: 12px; height: 12px; min-width: 12px; margin: 0; padding: 0; background-color: #182d41; border-right: 1px solid #2c465f; border-bottom: 1px solid #2c465f; }
    .cell:hover { background-color: #e5ad57; }
    .cell.filled { background-color: #628b77; }
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

static std::string make_stage_cells()
{
    std::string markup;
    markup.reserve((size_t)g_map_cols * (size_t)g_map_rows * 128u);
    for (int y = 0; y < g_map_rows; ++y) {
        markup += "<div class='stage-row'>";
        for (int x = 0; x < g_map_cols; ++x) {
            const int tile = mtlb_map_get(x, y);
            char cell[160];
            std::snprintf(cell, sizeof(cell),
                "<div id='cell-%d-%d' class='cell%s' data-action='paint' data-cell='%d'></div>",
                x, y, tile != 0 ? " filled" : "", y * g_map_cols + x);
            markup += cell;
        }
        markup += "</div>";
    }
    return markup;
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

static void update_cell_visual(int x, int y)
{
    if (!g_document || x < 0 || y < 0 || x >= g_map_cols || y >= g_map_rows) return;
    char id[48];
    std::snprintf(id, sizeof(id), "cell-%d-%d", x, y);
    Rml::Element *cell = g_document->GetElementById(id);
    if (cell) cell->SetClass("filled", mtlb_map_get(x, y) != 0);
}

static void refresh_stage_visuals()
{
    for (int y = 0; y < g_map_rows; ++y)
        for (int x = 0; x < g_map_cols; ++x)
            update_cell_visual(x, y);
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
                refresh_stage_visuals();
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
        if (action == "paint") {
            const Rml::String raw = element->GetAttribute<Rml::String>("data-cell", "-1");
            const int index = std::atoi(raw.c_str());
            if (index < 0 || index >= g_map_cols * g_map_rows) return;
            const int x = index % g_map_cols;
            const int y = index / g_map_cols;
            mtlb_map_set(x, y, g_brush_tile);
            update_cell_visual(x, y);
            char message[96];
            std::snprintf(message, sizeof(message), "Painted cell %d, %d with tile $%04X.", x, y, g_brush_tile);
            set_status(message);
        }
    }
};
static MakerEventListener g_listener;
} // namespace

extern "C" int mtlbr_init(SDL_Window *window, SDL_Renderer *renderer)
{
    if (g_context) return 1;
    if (!window || !renderer) return 0;

    g_window = window;
    g_renderer = renderer;
    g_map_cols = mtlb_map_cols();
    g_map_rows = mtlb_map_rows();
    if (g_map_cols <= 0 || g_map_rows <= 0) return 0;

    g_system = new SystemInterface_SDL(window);
    g_render = new RenderInterface_SDL(renderer);
    Rml::SetSystemInterface(g_system);
    Rml::SetRenderInterface(g_render);
    if (!Rml::Initialise()) {
        Rml::SetRenderInterface(nullptr);
        Rml::SetSystemInterface(nullptr);
        delete g_render; g_render = nullptr;
        delete g_system; g_system = nullptr;
        g_window = nullptr; g_renderer = nullptr;
        return 0;
    }
    g_rml_initialised = true;

    // Bundle fonts with the portable build; do not depend on the user's Windows font folder.
    char *base_path = SDL_GetBasePath();
    if (!base_path) {
        Rml::Log::Message(Rml::Log::LT_ERROR, "Could not resolve the game folder for bundled Maker fonts.");
        mtlbr_shutdown();
        return 0;
    }
    const std::string font_regular = std::string(base_path) + "assets/fonts/LatoLatin-Regular.ttf";
    const std::string font_bold = std::string(base_path) + "assets/fonts/LatoLatin-Bold.ttf";
    SDL_free(base_path);
    const bool regular_loaded = Rml::LoadFontFace(font_regular, true);
    const bool bold_loaded = Rml::LoadFontFace(font_bold, false);
    if (!regular_loaded || !bold_loaded) {
        Rml::Log::Message(Rml::Log::LT_ERROR, "Failed to load bundled Lato fonts from assets/fonts.");
        mtlbr_shutdown();
        return 0;
    }
    int width = 0, height = 0;
    SDL_GetWindowSize(window, &width, &height);
    g_context = Rml::CreateContext("MegaTurricanMaker", Rml::Vector2i(width, height), g_render);
    if (!g_context) {
        mtlbr_shutdown();
        return 0;
    }

    g_document = g_context->LoadDocumentFromMemory(kDocument);
    if (!g_document) {
        mtlbr_shutdown();
        return 0;
    }
    g_viewport = g_document->GetElementById("viewport");
    g_stage_grid = g_document->GetElementById("stage-grid");
    g_status = g_document->GetElementById("status-text");
    if (!g_viewport || !g_stage_grid || !g_status) {
        mtlbr_shutdown();
        return 0;
    }

    const std::string cells = make_stage_cells();
    g_stage_grid->SetInnerRML(cells);
    g_document->AddEventListener("click", &g_listener);
    g_document->Show();
    g_exit_requested = false;
    g_brush_tile = mtlb_map_brush();
    if (g_brush_tile < 176 || g_brush_tile > 180) g_brush_tile = 176;
    select_brush(g_brush_tile);
    set_status("RmlUi Maker interface online — existing level document and editor data retained.");
    return 1;
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
    if (event->type == SDL_KEYDOWN && event->key.keysym.sym == SDLK_ESCAPE) {
        g_exit_requested = true;
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

    g_context->SetDimensions(Rml::Vector2i(window_width, window_height));
    if (g_viewport) {
        char value[48];
        std::snprintf(value, sizeof(value), "%dpx", view_x);
        g_viewport->SetProperty("left", value);
        std::snprintf(value, sizeof(value), "%dpx", view_y);
        g_viewport->SetProperty("top", value);
        std::snprintf(value, sizeof(value), "%dpx", view_width);
        g_viewport->SetProperty("width", value);
        std::snprintf(value, sizeof(value), "%dpx", view_height);
        g_viewport->SetProperty("height", value);
    }

    const SDL_BlendMode rml_blend = SDL_ComposeCustomBlendMode(
        SDL_BLENDFACTOR_ONE, SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA, SDL_BLENDOPERATION_ADD,
        SDL_BLENDFACTOR_ONE, SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA, SDL_BLENDOPERATION_ADD);
    SDL_SetRenderDrawBlendMode(renderer, rml_blend);
    g_context->Update();
    g_context->Render();
    SDL_RenderSetClipRect(renderer, nullptr);
    SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
    return g_exit_requested ? 1 : 0;
}
