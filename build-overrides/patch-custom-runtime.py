#!/usr/bin/env python3
"""Install game-state-backed cheats, modern options, and three real save slots."""
from __future__ import annotations
import re
import sys
from pathlib import Path

def once(s: str, old: str, new: str, label: str) -> str:
    n=s.count(old)
    if n!=1: raise RuntimeError(f"{label}: expected 1 anchor, found {n}")
    return s.replace(old,new,1)

def add_include(s: str, header: str) -> str:
    if f'#include "{header}"' in s: return s
    m=re.search(r'(?m)^#include [^\n]+\n',s)
    if not m: raise RuntimeError(f"Cannot find include section for {header}")
    return s[:m.end()]+f'#include "{header}"\n'+s[m.end():]

def add_system_include(s: str, header: str) -> str:
    if f"#include <{header}>" in s: return s
    m=re.search(r'(?m)^#include [^\n]+\n',s)
    if not m: raise RuntimeError(f"Cannot find include section for <{header}>")
    return s[:m.end()]+f"#include <{header}>\n"+s[m.end():]

RUNTIME_API = r'''
/* -------------------------------------------------------------------------
 * Mega Turrican Reborn custom gameplay settings and native save slots.
 * Work RAM is the real Mega Drive 64 KiB RAM window; these options are
 * applied at the game frame boundary and do not replace the original game.
 * ------------------------------------------------------------------------- */
int md_infinite_continues_enabled = 0;
static int md_cheat_energy = 0;
static int md_cheat_lives = 0;
static int md_cheat_timer = 0;
static int md_modern_hide_timer_hud = 0;
static int md_modern_checkpoints = 0;
static int md_modern_iframes = 0;
int md_modern_persistent_weapon_enabled = 0;

static uint16_t md_modern_last_health = 0;
static uint16_t md_modern_iframe_health = 0;
static unsigned int md_modern_iframe_frames = 0;
static unsigned int md_modern_flash_frames = 0;
static int md_modern_health_initialized = 0;
static int md_modern_stage_initialized = 0;
static uint8_t md_modern_last_stage = 0;
static uint8_t md_modern_pending_stage = 0;
static unsigned int md_modern_stage_stable_frames = 0;
static int md_modern_stage_save_pending = 0;

int md_save_slot(int slot);

void md_set_custom_gameplay_options(int energy,int lives,int timer,
                                    int modern_continues,int hide_timer_hud,
                                    int persistent_weapon,int checkpoints,
                                    int hit_iframes) {
    md_cheat_energy = energy ? 1 : 0;
    md_cheat_lives = lives ? 1 : 0;
    md_cheat_timer = timer ? 1 : 0;
    md_infinite_continues_enabled = modern_continues ? 1 : 0;
    md_modern_hide_timer_hud = hide_timer_hud ? 1 : 0;
    md_modern_persistent_weapon_enabled = persistent_weapon ? 1 : 0;
    md_modern_checkpoints = checkpoints ? 1 : 0;
    md_modern_iframes = hit_iframes ? 1 : 0;
}

/* Infinite time is deliberately not reasserted for Modern Mode: NO TIMER HUD
 * removes the timer artwork in the display path while the game clock continues. */
void md_apply_custom_gameplay_options(void) {
    if (md_cheat_energy) {
        ram[0xBF20] = 0x00; ram[0xBF21] = 0x40;
    }
    if (md_cheat_lives) {
        ram[0xBF26] = 0x00; ram[0xBF27] = 0x03;
    }
    if (md_cheat_timer) {
        ram[0xBF28] = 0x00; ram[0xBF29] = 0x72;
    }
}

static void md_modern_flash_frame(void) {
    if(!md_modern_flash_frames)return;
    for(int y=0;y<vdp.height;y++) {
        uint32_t *row=&vdp.fb[y*320];
        for(int x=0;x<vdp.width;x++) {
            uint32_t p=row[x];
            unsigned r=(p>>16)&255,g=(p>>8)&255,b=p&255;
            r=r+(255-r)/5; g=g+(255-g)/5; b=b+(255-b)/5;
            row[x]=(r<<16)|(g<<8)|b;
        }
    }
    md_modern_flash_frames--;
}

/* The first hit still lands. For the next 45 frames, repeated hazard/enemy
 * drains are ignored, preventing a single overlap from emptying the energy bar. */
static void md_modern_apply_hit_iframes(void) {
    uint16_t hp=(uint16_t)(((uint16_t)ram[0xBF20]<<8)|ram[0xBF21]);
    if(!md_modern_iframes) {
        md_modern_health_initialized=0;
        md_modern_iframe_frames=0;
        md_modern_flash_frames=0;
        return;
    }
    if(!md_modern_health_initialized) {
        md_modern_last_health=hp;
        md_modern_health_initialized=1;
    } else if(hp>0 && md_modern_last_health>hp && md_modern_iframe_frames==0) {
        md_modern_iframe_health=hp;
        md_modern_iframe_frames=45;
        md_modern_flash_frames=2;
    }
    if(md_modern_iframe_frames>0) {
        if(hp>0 && hp<md_modern_iframe_health) {
            ram[0xBF20]=(uint8_t)(md_modern_iframe_health>>8);
            ram[0xBF21]=(uint8_t)md_modern_iframe_health;
            hp=md_modern_iframe_health;
        }
        md_modern_iframe_frames--;
    }
    md_modern_last_health=hp;
    md_modern_flash_frame();
}

/* The ROM's stage modifier at $FFBF1F identifies the loaded stage (0-6).
 * An autosave is written to a separate hidden slot after the new stage settles. */
static void md_modern_stage_autosave(void) {
    uint8_t stage=ram[0xBF1F];
    if(stage>6)return;
    if(!md_modern_stage_initialized) {
        md_modern_last_stage=stage;
        md_modern_stage_initialized=1;
        return;
    }
    if(stage!=md_modern_last_stage) {
        if(!md_modern_stage_save_pending || md_modern_pending_stage!=stage) {
            md_modern_pending_stage=stage;
            md_modern_stage_stable_frames=0;
            md_modern_stage_save_pending=1;
        }
    }
    if(md_modern_stage_save_pending) {
        if(stage!=md_modern_pending_stage) {
            md_modern_pending_stage=stage;
            md_modern_stage_stable_frames=0;
        } else if(++md_modern_stage_stable_frames>=90) {
            if(md_save_slot(4))md_modern_last_stage=stage;
            md_modern_stage_save_pending=0;
            md_modern_stage_stable_frames=0;
        }
    }
}

void md_modern_runtime_frame(void) {
    md_apply_custom_gameplay_options();
    md_modern_apply_hit_iframes();
    if(md_modern_checkpoints)md_modern_stage_autosave();
    else {
        md_modern_stage_initialized=0;
        md_modern_stage_save_pending=0;
        md_modern_stage_stable_frames=0;
    }
}

extern uint32_t rt_shadow[65536];
extern int rt_sp;

extern size_t md_ym_state_size(void);
extern void md_ym_state_save(void *dst);
extern int md_ym_state_load(const void *src, size_t bytes);
extern size_t md_psg_state_size(void);
extern void md_psg_state_save(void *dst);
extern int md_psg_state_load(const void *src, size_t bytes);

typedef struct MDRebornSaveHeader {
    char magic[8];
    uint32_t version;
    uint32_t core_bytes;
    uint32_t ym_bytes;
    uint32_t psg_bytes;
    uint64_t rom_hash;
} MDRebornSaveHeader;

typedef struct MDRebornCoreState {
    M68K cpu;
    Z80 z80;
    VDP video;
    uint8_t main_ram[0x10000];
    uint8_t sound_ram[0x2000];
    uint32_t recomp_shadow[65536];
    int32_t recomp_sp;
    int64_t frame_number;
    int32_t zbank, zbusreq, zreset, z80_over;
    double fm_accumulator, psg_accumulator;
    int32_t infinite_continues;
} MDRebornCoreState;

static uint64_t md_reborn_rom_hash(void) {
    uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i=0; i<romlen; ++i) {
        h ^= rom[i];
        h *= UINT64_C(1099511628211);
    }
    return h;
}

static int md_reborn_save_dir(void) {
#ifdef _WIN32
    if (_mkdir("saves") != 0 && errno != EEXIST) return 0;
#else
    if (mkdir("saves",0775) != 0 && errno != EEXIST) return 0;
#endif
    return 1;
}

static int md_reborn_slot_path(char *dst,size_t cap,int slot,int temporary) {
    if(slot<1||slot>4) return 0;
    int n=snprintf(dst,cap,"saves/slot%d.%s",slot,temporary?"tmp":"mts");
    return n>0 && (size_t)n<cap;
}

int md_save_slot_exists(int slot) {
    char path[64];
    if(!md_reborn_slot_path(path,sizeof path,slot,0)) return 0;
    FILE *f=fopen(path,"rb");
    if(!f) return 0;
    MDRebornSaveHeader h;
    int ok=fread(&h,sizeof h,1,f)==1 &&
           memcmp(h.magic,"MTRSAVE1",8)==0 && h.version==1 &&
           h.rom_hash==md_reborn_rom_hash();
    fclose(f);
    return ok;
}

int md_save_slot(int slot) {
    if(!CPU || !rom || !romlen || !md_reborn_save_dir()) return 0;
    char path[64],temp[64];
    if(!md_reborn_slot_path(path,sizeof path,slot,0) ||
       !md_reborn_slot_path(temp,sizeof temp,slot,1)) return 0;

    size_t ym_bytes=md_ym_state_size(), psg_bytes=md_psg_state_size();
    if(!ym_bytes || !psg_bytes || ym_bytes>65536 || psg_bytes>65536) return 0;
    void *ym_blob=malloc(ym_bytes), *psg_blob=malloc(psg_bytes);
    if(!ym_blob || !psg_blob){free(ym_blob);free(psg_blob);return 0;}

    MDRebornCoreState *s=(MDRebornCoreState*)calloc(1,sizeof *s);
    if(!s){free(ym_blob);free(psg_blob);return 0;}
    s->cpu=*CPU; s->z80=zcpu; s->video=vdp;
    memcpy(s->main_ram,ram,sizeof ram); memcpy(s->sound_ram,zram,sizeof zram);
    memcpy(s->recomp_shadow,rt_shadow,sizeof s->recomp_shadow);
    s->recomp_sp=rt_sp; s->frame_number=frame;
    s->zbank=zbank; s->zbusreq=zbusreq; s->zreset=zreset; s->z80_over=z80_over;
    s->fm_accumulator=fm_acc; s->psg_accumulator=psg_acc;
    s->infinite_continues=md_infinite_continues_enabled;
    md_ym_state_save(ym_blob); md_psg_state_save(psg_blob);

    MDRebornSaveHeader h={{'M','T','R','S','A','V','E','1'},1,
        (uint32_t)sizeof *s,(uint32_t)ym_bytes,(uint32_t)psg_bytes,
        md_reborn_rom_hash()};

    FILE *f=fopen(temp,"wb");
    int ok=f!=NULL;
    if(ok) {
        ok=fwrite(&h,sizeof h,1,f)==1 &&
           fwrite(s,sizeof *s,1,f)==1 &&
           fwrite(ym_blob,ym_bytes,1,f)==1 &&
           fwrite(psg_blob,psg_bytes,1,f)==1;
        if(fflush(f)!=0) ok=0;
        if(fclose(f)!=0) ok=0;
    }
    if(ok) {
        remove(path);
        if(rename(temp,path)!=0) ok=0;
    }
    if(!ok) remove(temp);
    free(s);free(ym_blob);free(psg_blob);
    return ok;
}

int md_load_slot(int slot) {
    if(!CPU || !rom || !romlen) return 0;
    char path[64];
    if(!md_reborn_slot_path(path,sizeof path,slot,0)) return 0;
    FILE *f=fopen(path,"rb"); if(!f) return 0;

    MDRebornSaveHeader h;
    MDRebornCoreState *s=(MDRebornCoreState*)malloc(sizeof *s);
    void *ym_blob=NULL,*psg_blob=NULL;
    int ok=s && fread(&h,sizeof h,1,f)==1 &&
        memcmp(h.magic,"MTRSAVE1",8)==0 && h.version==1 &&
        h.core_bytes==sizeof *s && h.rom_hash==md_reborn_rom_hash() &&
        h.ym_bytes==md_ym_state_size() && h.psg_bytes==md_psg_state_size();
    if(ok) {
        ym_blob=malloc(h.ym_bytes); psg_blob=malloc(h.psg_bytes);
        ok=ym_blob && psg_blob &&
           fread(s,sizeof *s,1,f)==1 &&
           fread(ym_blob,h.ym_bytes,1,f)==1 &&
           fread(psg_blob,h.psg_bytes,1,f)==1;
    }
    fclose(f);
    if(ok) ok=md_ym_state_load(ym_blob,h.ym_bytes) &&
              md_psg_state_load(psg_blob,h.psg_bytes);
    if(ok) {
        *CPU=s->cpu; zcpu=s->z80; vdp=s->video;
        memcpy(ram,s->main_ram,sizeof ram); memcpy(zram,s->sound_ram,sizeof zram);
        memcpy(rt_shadow,s->recomp_shadow,sizeof s->recomp_shadow);
        rt_sp=s->recomp_sp; frame=(long)s->frame_number;
        zbank=s->zbank; zbusreq=s->zbusreq; zreset=s->zreset; z80_over=s->z80_over;
        fm_acc=s->fm_accumulator; psg_acc=s->psg_accumulator;
        md_infinite_continues_enabled=s->infinite_continues ? 1 : 0;
        /* Discard stale queued PCM; the restored synth state generates fresh audio. */
        ar=aw;
    }
    free(s);free(ym_blob);free(psg_blob);
    return ok;
}
'''

def patch_audio_state(path: Path, prefix: str, symbol: str) -> None:
    s=path.read_text(encoding="utf-8-sig")
    if f"{prefix}_state_size(void)" in s: return
    s=add_system_include(s,"string.h")
    s=add_system_include(s,"stddef.h")
    s += f"""

/* Opaque snapshot API: the core saves this chip's complete synthesis state
 * without duplicating private operator/channel structure definitions. */
size_t {prefix}_state_size(void) {{ return sizeof {symbol}; }}
void {prefix}_state_save(void *dst) {{ if(dst) memcpy(dst,&{symbol},sizeof {symbol}); }}
int {prefix}_state_load(const void *src,size_t bytes) {{
    if(!src || bytes!=sizeof {symbol}) return 0;
    memcpy(&{symbol},src,sizeof {symbol});
    return 1;
}}
"""
    path.write_text(s,encoding="utf-8")

def patch_harness(project: Path) -> None:
    path=project/"runtime"/"harness.c"
    s=path.read_text(encoding="utf-8-sig")
    if "int md_infinite_continues_enabled = 0;" not in s:
        # The harness already includes these core types, and the frame/RAM/sound
        # objects are translation-unit globals so the serializer lives here.
        s=add_system_include(s,"errno.h")
        s=add_system_include(s,"sys/stat.h")
        if "#include <direct.h>" not in s:
            s=once(s,'#include <sys/stat.h>\n',
                   '#include <sys/stat.h>\n#ifdef _WIN32\n#include <direct.h>\n#endif\n',
                   "portable save directory header")
        api=RUNTIME_API
        s=s.rstrip()+"\n\n"+api+"\n"
        if "void md_modern_runtime_frame(void);" not in s:
        s=once(s,"void md_frame_hook(void);","void md_frame_hook(void); void md_modern_runtime_frame(void);",
               "Modern runtime frame hook declaration")
    s=once(s,"void md_frame_hook(void){}","void md_frame_hook(void){ md_modern_runtime_frame(); }",
           "Modern runtime per-frame hook")
    path.write_text(s,encoding="utf-8")
    # Assert that the state globals used by the snapshot are actually declared.
    for name in ["ram[0x10000]","zram[0x2000]","static M68K *CPU","static Z80 zcpu",
                 "zbank","zbusreq","zreset","fm_acc","psg_acc","z80_over"]:
        if name not in s: raise RuntimeError(f"Save-state runtime anchor missing: {name}")

def patch_recompiled_continues(project: Path) -> None:
    path=project/"recomp_gen.c"
    s=path.read_text(encoding="utf-8-sig")
    if "extern int md_infinite_continues_enabled;" not in s:
        m=re.search(r'(?m)^#include [^\n]+\n',s)
        if not m: raise RuntimeError("Could not find generated recomp include section.")
        s=s[:m.end()]+"extern int md_infinite_continues_enabled;\nextern int md_modern_persistent_weapon_enabled;\n"+s[m.end():]
    if "extern int md_modern_persistent_weapon_enabled;" not in s:
        s=s.replace("extern int md_infinite_continues_enabled;","extern int md_infinite_continues_enabled;\nextern int md_modern_persistent_weapon_enabled;",1)
    pattern=re.compile(
        r'(L_192C:\s*\{\s*RT_POLL\(0x192C\);\s*)'
        r'D\(1\)=\(uint32_t\)\(int32_t\)\(int8_t\)1;'
        r'(\s*fl_logic\(c,D\(1\),32\);\s*\})'
    )
    if "md_infinite_continues_enabled ? 0 : 1" not in s:
        s,n=pattern.subn(
            r'\g<1>D(1)=(uint32_t)(int32_t)(int8_t)(md_infinite_continues_enabled ? 0 : 1);\g<2>',
            s
        )
        if n!=2: raise RuntimeError(f"Expected two generated L_192C blocks, found {n}")
    # Game Genie BAMT-AA60 decodes to ROM word 0x001796:0x6008:
    # BRA.s $17A0, bypassing the weapon downgrade-on-death instruction.
    weapon_pattern=re.compile(r'(L_1796:\\s*\\{\\s*RT_POLL\\(0x1796\\);)')
    if "md_modern_persistent_weapon_enabled" not in s:
        s,n=weapon_pattern.subn(
            r'\\g<1>if(md_modern_persistent_weapon_enabled)goto L_17A0; ',
            s
        )
        if n<1: raise RuntimeError("Could not find generated L_1796 instruction for persistent weapon-level patch.")
    path.write_text(s,encoding="utf-8",newline="\\n")

def patch(project: Path) -> None:
    patch_audio_state(project/"runtime"/"ym2612.c","md_ym","ym")
    patch_audio_state(project/"runtime"/"psg.c","md_psg","psg")
    patch_harness(project)
    patch_recompiled_continues(project)
    print("Installed real USA-ROM RAM cheats, conditional infinite-continues instruction, YM/PSG snapshots, and 3-slot full-state save/load.")

if __name__=="__main__":
    if len(sys.argv)!=2: raise SystemExit("usage: patch-custom-runtime.py PROJECT_ROOT")
    patch(Path(sys.argv[1]).resolve())
