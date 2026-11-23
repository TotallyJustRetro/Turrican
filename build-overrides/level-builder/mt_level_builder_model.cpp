#include "mt_level_builder_model.h"
#include "mt_maker_asset_catalog.h"
#include <algorithm>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <vector>
#ifdef _WIN32
#include <direct.h>
#else
#include <sys/stat.h>
#endif

namespace {

static uint8_t g_live_vram[65536] = {};
static uint16_t g_live_cram[64] = {};
static uint32_t g_live_art_hash = 0;
static int g_live_tile_ids[512] = {};
static int g_live_tile_count = 0;
static uint8_t g_rom_art_block[0x1400] = {};
static bool g_rom_art_valid = false;
static uint8_t g_rom_hud_art_a[0x0200] = {};
static uint8_t g_rom_hud_art_b[0x0200] = {};
static bool g_rom_hud_art_a_valid = false;
static bool g_rom_hud_art_b_valid = false;
static uint8_t g_rom_fx_frames[20][0x0100] = {};
static bool g_rom_fx_frame_valid[20] = {};
static int g_rom_fx_frame = 0;
static int g_rom_fx_frame_count = 0;
static int g_rom_fx_tile_start_index = -1;
static int g_rom_tile_start_index = -1;
static int g_rom_tile_count = 0;
static uint8_t g_live_regs[32] = {};
struct LiveSpritePart { uint16_t tile_attr; uint8_t width_tiles, height_tiles; int16_t x, y; };
static LiveSpritePart g_live_sprites[80] = {};
static int g_live_sprite_count = 0;
struct MakerRomSpriteAsset { uint32_t owner_pc, descriptor_pc, first_frame_pc; uint16_t frame_count, first_frame_parts; };
static MakerRomSpriteAsset g_rom_sprite_assets[256] = {};
static uint8_t g_rom_sprite_categories[256] = {}; // 0=review, 1=character, 2=item, 3=enemy, 4=boss
static int g_rom_sprite_asset_count = 0;
static bool g_maker_rom_assets_prepared = false;
static int g_rom_sprite_offset = 0, g_selected_rom_sprite = -1;

static const int kEditorMapCols = 64, kEditorMapRows = 32;
static std::uint16_t g_level_tiles[kEditorMapCols*kEditorMapRows] = {};
static bool g_document_dirty = false;
static int g_selected_x = 0, g_selected_y = 0, g_brush_tile = 1;
static int g_undo_count = 0, g_redo_count = 0;
static uint16_t g_undo_stack[12][64*32] = {}, g_redo_stack[12][64*32] = {};
struct EditorEntity { float x,y; int type,hp; uint16_t tile_attr; uint8_t width_tiles,height_tiles; };
static std::vector<EditorEntity> g_entities;
static int g_selected_entity = -1;

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
static bool maker_sprite_category_path(char *path,size_t capacity)
{
    if(!path||capacity==0)return false;
    const char *portable=std::getenv("MEGATURRICAN_CONFIG_DIR");
    char base[4096]={};
    if(portable&&portable[0]){
        const int n=std::snprintf(base,sizeof(base),"%s",portable);
        if(n<0||(size_t)n>=sizeof(base))return false;
    }else{
        char *sdl_base=SDL_GetBasePath();
        if(!sdl_base)return false;
        const int n=std::snprintf(base,sizeof(base),"%s",sdl_base);
        SDL_free(sdl_base);
        if(n<0||(size_t)n>=sizeof(base))return false;
    }
    const size_t length=std::strlen(base);
    const char *separator=(length>0&&base[length-1]!='/'&&base[length-1]!='\\')?"/":"";
    const int n=std::snprintf(path,capacity,"%s%smaker-sprite-categories.ini",base,separator);
    return n>=0&&(size_t)n<capacity;
}

static void maker_load_sprite_categories()
{
    for(int i=0;i<256;i++)g_rom_sprite_categories[i]=0;
    char path[4096]={};
    if(!maker_sprite_category_path(path,sizeof(path)))return;
    FILE *file=std::fopen(path,"rb");
    if(!file)return;
    char line[128];
    while(std::fgets(line,sizeof(line),file)){
        unsigned int descriptor=0;
        int category=0;
        if(std::sscanf(line,"%x=%d",&descriptor,&category)!=2||category<0||category>4)continue;
        for(int i=0;i<g_rom_sprite_asset_count;i++)
            if(g_rom_sprite_assets[i].descriptor_pc==(uint32_t)descriptor){
                g_rom_sprite_categories[i]=(uint8_t)category;
                break;
            }
    }
    std::fclose(file);
}

static bool maker_save_sprite_categories()
{
    char path[4096]={};
    if(!maker_sprite_category_path(path,sizeof(path)))return false;
    FILE *file=std::fopen(path,"wb");
    if(!file)return false;
    bool ok=true;
    for(int i=0;i<g_rom_sprite_asset_count;i++){
        if(g_rom_sprite_categories[i]==0)continue;
        if(std::fprintf(file,"%08X=%u\n",g_rom_sprite_assets[i].descriptor_pc,
            (unsigned)g_rom_sprite_categories[i])<0){ok=false;break;}
    }
    if(std::fclose(file)!=0)ok=false;
    return ok;
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
}


} // namespace

extern "C" void mtlb_model_update_vdp_resources(const uint8_t *vram,const uint16_t *cram,const uint8_t *regs)
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
        base[--base_len]='\0';
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
    const std::uint32_t entityCount=(std::uint32_t)g_entities.size();
    bool ok=std::fwrite(magic,1,sizeof(magic),file)==sizeof(magic)&&
        std::fwrite(&cols,sizeof(cols),1,file)==1&&std::fwrite(&rows,sizeof(rows),1,file)==1&&
        std::fwrite(g_level_tiles,sizeof(g_level_tiles),1,file)==1&&
        std::fwrite(&entityCount,sizeof(entityCount),1,file)==1;
    if(ok&&!g_entities.empty())
        ok=std::fwrite(g_entities.data(),sizeof(EditorEntity),g_entities.size(),file)==g_entities.size();
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
    std::vector<EditorEntity> loaded_entities;
    if(ok&&(unsigned char)magic[7]==2){
        std::uint32_t entity_count=0;
        ok=std::fread(&entity_count,sizeof(entity_count),1,file)==1;
        if(ok){
            const long payload_start=std::ftell(file);
            if(payload_start<0||std::fseek(file,0,SEEK_END)!=0)ok=false;
            else{
                const long file_end=std::ftell(file);
                if(file_end<payload_start)ok=false;
                else{
                    const unsigned long long available=(unsigned long long)(file_end-payload_start);
                    const unsigned long long required=(unsigned long long)entity_count*sizeof(EditorEntity);
                    if(required>available)ok=false;
                    else if(std::fseek(file,payload_start,SEEK_SET)!=0)ok=false;
                }
            }
            if(ok){
                loaded_entities.resize((size_t)entity_count);
                if(entity_count>0)
                    ok=std::fread(loaded_entities.data(),sizeof(EditorEntity),entity_count,file)==entity_count;
            }
        }
    }
    std::fclose(file);
    if(!ok)return 0;
    std::memcpy(g_level_tiles,loaded,sizeof(g_level_tiles));
    g_entities.swap(loaded_entities);
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
        maker_load_sprite_categories();
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

extern "C" int mtlb_editor_sprite_asset_category(int index)
{
    mtlb_editor_prepare_rom_assets();
    if(index<0||index>=g_rom_sprite_asset_count)return 0;
    return (int)g_rom_sprite_categories[index];
}

extern "C" int mtlb_editor_sprite_asset_set_category(int index,int category)
{
    mtlb_editor_prepare_rom_assets();
    if(index<0||index>=g_rom_sprite_asset_count||category<0||category>4)return 0;
    g_rom_sprite_categories[index]=(uint8_t)category;
    return maker_save_sprite_categories()?1:0;
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


extern "C" void mtlb_map_set_cursor(int x,int y)
{
    g_selected_x=std::max(0,std::min(kEditorMapCols-1,x));
    g_selected_y=std::max(0,std::min(kEditorMapRows-1,y));
}
extern "C" void mtlb_editor_push_undo(void) { push_level_undo(); }
extern "C" void mtlb_editor_undo(void) { undo_level_edit(); }
extern "C" void mtlb_editor_redo(void) { redo_level_edit(); }
extern "C" int mtlb_editor_entity_count(void) { return (int)g_entities.size(); }

extern "C" int mtlb_editor_place_entity(float x,float y,int type,int sprite_asset_index)
{
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
    g_entities.push_back(entity);
    g_selected_entity=(int)g_entities.size()-1;
    g_document_dirty=true;
    return g_selected_entity;
}

extern "C" int mtlb_editor_entity_info(int index,float *x,float *y,int *type,int *hp,
                                         uint16_t *tile_attr,int *width_tiles,int *height_tiles)
{
    if(index<0||(size_t)index>=g_entities.size())return 0;
    const EditorEntity &entity=g_entities[(size_t)index];
    if(x)*x=entity.x;if(y)*y=entity.y;if(type)*type=entity.type;if(hp)*hp=entity.hp;
    if(tile_attr)*tile_attr=entity.tile_attr;
    if(width_tiles)*width_tiles=entity.width_tiles;if(height_tiles)*height_tiles=entity.height_tiles;
    return 1;
}


