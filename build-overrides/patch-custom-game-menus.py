#!/usr/bin/env python3
"""Add native Extras, Cheats, Modern Mode, Saves, and tilemap editor pages."""
from __future__ import annotations
import re
import sys
from pathlib import Path

def once(s: str, old: str, new: str, label: str) -> str:
    n=s.count(old)
    if n!=1: raise RuntimeError(f"{label}: expected one match, found {n}")
    return s.replace(old,new,1)

def replace_function(s: str, signature: str, replacement: str, label: str) -> str:
    a=s.find(signature)
    if a<0: raise RuntimeError(f"{label}: function not found")
    b=s.find("{",a)
    depth=0; end=-1
    for i in range(b,len(s)):
        if s[i]=="{": depth+=1
        elif s[i]=="}":
            depth-=1
            if depth==0: end=i+1; break
    if end<0: raise RuntimeError(f"{label}: unterminated function")
    return s[:a]+replacement+s[end:]

CUSTOM_GLOBALS = r'''
/* Reborn title menu state. The original ROM START/OPTIONS page remains intact;
   the added menu is composed into the completed VDP framebuffer each frame. */
static int native_extras_parent=1;
static int native_game_level_modern=0;
static int native_cheat_energy=0, native_cheat_lives=0, native_cheat_timer=0;
static int native_modern_continues=0;
static int native_modern_map=0, native_modern_no_timer_hud=0;
static int native_modern_persistent_weapon=0, native_modern_checkpoints=0, native_modern_iframes=0;
static int native_modern_scroll_offset=0;
static int native_custom_cfg_loaded=0;
static int native_save_selection=0;
static int native_editor_x=12, native_editor_y=10, native_editor_tile=1;
static int native_title_menu_selection=0;
static int native_title_page_mode=0;
static int native_title_game_options_focus=0;
static int native_title_scene_active=0;
static int native_title_transition_guard=0;
static int native_title_input_block=0;
static int native_title_compose_enabled=0;
static unsigned int native_title_blink_ticks=0;
static int native_title_last_selection=-1, native_title_last_page=-1, native_title_last_focus=-1;
static uint32_t native_title_options_backdrop[320*240];
static int native_title_options_backdrop_valid=0;
static unsigned int native_pause_anim_ticks=0;
static int native_pause_keep_title_audio=0;
static int native_title_checkpoint_saved=0;
static int native_pause_achievement_first=0;
static uint8_t native_pause_font_cache[43][32];
static int native_pause_font_cache_valid=0;
static void native_pause_font_capture(void);
static int native_pause_confirm_action=0,native_pause_confirm_choice=1;
static int native_pause_request_title=0,native_pause_skip_backdrop_restore=0;
static int native_pause_no_checkpoint=0;
static int native_pause_control_config=0,native_pause_rapid_fire=0;
static int native_pause_sound_track=-1;
static void native_pause_draw_text(int x,int y,const char *s,uint32_t color);
static void native_pause_enter_confirm(int action);
static void native_pause_audio_pump(void);
static void native_pause_apply_control_config(void);
static void native_title_menu_sfx(int confirm);
static void render_native_pause_video_settings(void);
static void render_native_pause_audio_settings(void);
static void render_native_pause_controller_setup(void);
static void render_native_pause_controls(void);
static void render_native_pause_achievements(void);
static void proc_native_pause_video_settings(SDL_Event *e);
static void proc_native_pause_audio_settings(SDL_Event *e);
static void proc_native_pause_controller_setup(SDL_Event *e);
static void proc_native_pause_info_back(SDL_Event *e);
static void native_custom_save_config(void);
extern void md_set_ram_byte(uint32_t address,uint8_t value);
extern void md_pause_fm_test_start(int track);
extern void md_pause_fm_test_stop(void);
extern void md_pause_fm_test_render(int16_t *dst,int frames,int channels);

static int reborn_game_options_visible(void);
static int reborn_title_scene_visible(void);
static void native_menu_pause_loop(void);

extern void md_set_custom_gameplay_options(int,int,int,int,int,int,int,int);
extern void md_apply_custom_gameplay_options(void);
extern void md_copy_main_ram(uint8_t *dst);
extern uint32_t md_cpu_state_size(void);
extern void md_copy_cpu_state(void *dst, uint32_t bytes);
extern int md_save_slot(int slot);
extern int md_load_slot(int slot);
extern int md_save_slot_exists(int slot);
'''

CUSTOM_PAGES = r'''
static unsigned int native_menu_trace_index=0;
/* Always place diagnostic captures beside the running game executable.
   The process working directory may be inherited from the launcher and can
   point somewhere completely different. SDL_GetBasePath returns the EXE path. */
static int native_menu_trace_fullpath(char *dst,size_t capacity,const char *filename) {
    char *base=SDL_GetBasePath();
    if(!base)return 0;
    int written=snprintf(dst,capacity,"%s%s",base,filename);
    SDL_free(base);
    return written>=0 && (size_t)written<capacity;
}
static void native_menu_dump_snapshot(const char *scene) {
    uint8_t ram_snapshot[0x10000], cpu_snapshot[128];
    char filename[96], fullpath[4096];
    snprintf(filename,sizeof filename,"menu-trace-%s-%02u.bin",scene,++native_menu_trace_index);
    if(!native_menu_trace_fullpath(fullpath,sizeof fullpath,filename)) {
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR,"Mega Turrican menu trace",
                                 "Could not resolve the game executable folder.",NULL);
        return;
    }
    FILE *f=fopen(fullpath,"wb");
    if(!f) {
        char message[4608];
        snprintf(message,sizeof message,"Could not create the diagnostic capture:\n%s\n\nCheck that the game folder is writable.",fullpath);
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR,"Mega Turrican menu trace",message,NULL);
        return;
    }
    static const uint8_t magic[8]={'M','T','M','E','N','U','2',0};
    uint32_t dims[2]={(uint32_t)vdp.width,(uint32_t)vdp.height};
    uint32_t cpu_bytes=md_cpu_state_size();
    if(cpu_bytes>sizeof cpu_snapshot)cpu_bytes=0;
    if(cpu_bytes)md_copy_cpu_state(cpu_snapshot,cpu_bytes);
    int ok=fwrite(magic,1,sizeof magic,f)==sizeof magic &&
           fwrite(dims,sizeof dims,1,f)==1 &&
           fwrite(&cpu_bytes,sizeof cpu_bytes,1,f)==1 &&
           fwrite(vdp.reg,sizeof vdp.reg,1,f)==1 &&
           fwrite(vdp.cram,sizeof vdp.cram,1,f)==1 &&
           fwrite(vdp.vsram,sizeof vdp.vsram,1,f)==1 &&
           fwrite(vdp.vram,sizeof vdp.vram,1,f)==1;
    if(ok && cpu_bytes)ok=fwrite(cpu_snapshot,1,cpu_bytes,f)==cpu_bytes;
    md_copy_main_ram(ram_snapshot);
    if(ok)ok=fwrite(ram_snapshot,sizeof ram_snapshot,1,f)==1;
    if(ok)ok=fwrite(vdp.fb,sizeof vdp.fb,1,f)==1;
    if(fclose(f)!=0)ok=0;
    if(!ok)remove(fullpath);
    char message[4608];
    if(ok)snprintf(message,sizeof message,"Saved diagnostic capture to:\n%s\n\nThis is the exact file location. Zip the menu-trace-*.bin files from this folder and attach them here.",fullpath);
    else snprintf(message,sizeof message,"Could not finish writing:\n%s\n\nCheck free disk space and folder permissions.",fullpath);
    SDL_ShowSimpleMessageBox(ok?SDL_MESSAGEBOX_INFORMATION:SDL_MESSAGEBOX_ERROR,
                             "Mega Turrican menu trace",message,NULL);
}

static uint32_t native_options_window_base(void) {
    return ((uint32_t)vdp.reg[3] & 0x3Eu) << 10;
}
static int native_options_window_cols(void) {
    return (vdp.reg[16] & 0x02) ? 64 : 32;
}
static uint16_t native_options_font_tile(char ch) {
    if(ch>='A' && ch<='Z') return (uint16_t)(0x531 + (ch-'A'));
    if(ch==' ') return 0x530;
    if(ch=='-') return 0x55A;
    if(ch>='0' && ch<='9') return (uint16_t)(0x54B + (ch-'0'));
    return 0x530;
}
static int native_title_tile_row_matches(int row,int col,const uint16_t *tiles,size_t count) {
    int cols=native_options_window_cols();
    if(row<0 || row>=64 || col<0 || col+(int)count>cols)return 0;
    uint32_t base=native_options_window_base();
    for(size_t i=0;i<count;i++) {
        uint32_t at=(base+((uint32_t)row*(uint32_t)cols+(uint32_t)col+(uint32_t)i)*2u)&0xFFFFu;
        uint16_t entry=(uint16_t)(((uint16_t)vdp.vram[at]<<8)|vdp.vram[(at+1u)&0xFFFFu]);
        if((entry&0x07FFu)!=tiles[i])return 0;
    }
    return 1;
}
/* These exact title-row strings are present in the uploaded title trace.
   Unlike logo/pixel thresholds, they identify the menu as soon as the ROM
   creates it and remain valid while its selection highlight changes. */
static int native_title_gameplay_hud_visible(void) {
    int W=vdp.width?vdp.width:320, H=vdp.height?vdp.height:224;
    if(W<256 || W>320 || H<200 || H>240)return 0;
    int red[3]={0,0,0};
    const int x0[3]={W*2/100,W*41/100,W*77/100};
    const int x1[3]={W*25/100,W*60/100,W*99/100};
    for(int y=H*3/100;y<H*14/100;y++) {
        const uint32_t *row=&vdp.fb[y*320];
        for(int z=0;z<3;z++)for(int x=x0[z];x<x1[z];x++) {
            uint32_t p=row[x];
            int r=(p>>16)&255,g=(p>>8)&255,b=p&255;
            if(r>145 && g<115 && b<105 && r>g+45 && r>b+55)red[z]++;
        }
    }
    /* SCORE, TIME and ENERGY are three separate red HUD labels in demos/levels.
       The title card has no such three-part top HUD. */
    return red[0]>12 && red[2]>12;
}
int md_modern_timer_hud_present(void) {
    return native_title_gameplay_hud_visible();
}
static int native_title_menu_scene_visible(void) {
    static const uint16_t start_tiles[]={0x543,0x544,0x531,0x542,0x544};
    static const uint16_t options_tiles[]={0x53F,0x540,0x544,0x539,0x53F,0x53E,0x543};
    static const uint16_t copyright_year[]={0x54C,0x554,0x554,0x54F}; /* 1994 */
    static const uint16_t published_by[]={0x540,0x545,0x532,0x53C,0x539,0x543,0x538,0x535,
        0x534,0x530,0x532,0x549,0x530,0x534,0x531,0x544,0x531,0x530,
        0x535,0x531,0x543,0x544,0x530,0x545,0x543,0x531}; /* PUBLISHED BY DATA EAST USA */
    static const uint16_t licensed[]={0x53C,0x539,0x533,0x535,0x53E,0x543,0x535,0x534}; /* LICENSED */
    static const uint16_t sega[]={0x543,0x535,0x537,0x531,0x530,0x535,0x53E,0x544,
        0x535,0x542,0x540,0x542,0x539,0x543,0x535,0x543}; /* SEGA ENTERPRISES */
    if(vdp.width<256 || vdp.width>320 || vdp.height<200 || vdp.height>240)return 0;
    if(native_menu_state>0 || native_title_gameplay_hud_visible())return 0;
    return native_title_tile_row_matches(16,13,start_tiles,sizeof start_tiles/sizeof start_tiles[0]) &&
           native_title_tile_row_matches(18,12,options_tiles,sizeof options_tiles/sizeof options_tiles[0]) &&
           native_title_tile_row_matches(22,10,copyright_year,sizeof copyright_year/sizeof copyright_year[0]) &&
           native_title_tile_row_matches(23,3,published_by,sizeof published_by/sizeof published_by[0]) &&
           native_title_tile_row_matches(24,10,licensed,sizeof licensed/sizeof licensed[0]) &&
           native_title_tile_row_matches(25,5,sega,sizeof sega/sizeof sega[0]);
}
static int native_title_text_width(const char *s) {
    int n=(int)strlen(s);
    return n>0 ? n*8 : 0; /* exact original 8-pixel character cells */
}
static uint32_t native_title_cram_rgb(int palette,unsigned index) {
    uint16_t color=vdp.cram[(palette&3)*16+(index&15u)];
    int r=(color>>1)&7, g=(color>>5)&7, b=(color>>9)&7;
    return ((uint32_t)(r*255/7)<<16)|((uint32_t)(g*255/7)<<8)|(uint32_t)(b*255/7);
}
static void native_title_draw_text_at_palette(int x,int y,const char *s,int palette) {
    int W=vdp.width?vdp.width:320, H=vdp.height?vdp.height:224;
    for(int i=0;s[i];i++) {
        uint16_t tile=native_options_font_tile(s[i]);
        if(s[i]!=' ') {
            for(int sy=0;sy<8;sy++) {
                int py=y+sy;
                if(py<0 || py>=H)continue;
                uint32_t *row=&vdp.fb[py*320];
                for(int sx=0;sx<8;sx++) {
                    int px=x+i*8+sx;
                    if(px<0 || px>=W)continue;
                    uint8_t packed=vdp.vram[(size_t)tile*32u+(size_t)sy*4u+(size_t)(sx>>1)];
                    unsigned index=(sx&1)?(packed&15u):(packed>>4);
                    if(index)row[px]=native_title_cram_rgb(palette,index);
                }
            }
        }
    }
}
static void native_title_draw_text_at(int x,int y,const char *s,int selected,int blink_on) {
    native_title_draw_text_at_palette(x,y,s,(selected && blink_on)?2:1);
}
static void native_title_draw_text_center_palette(const char *s,int y,int palette) {
    int center=(vdp.width?vdp.width:320)/2;
    native_title_draw_text_at_palette(center-native_title_text_width(s)/2,y,s,palette);
}
static void native_title_draw_text_center(const char *s,int y,int selected,int blink_on) {
    int center=(vdp.width?vdp.width:320)/2;
    native_title_draw_text_at(center-native_title_text_width(s)/2,y,s,selected,blink_on);
}
static void native_title_draw_text_column(const char *s,int center,int y,int selected,int blink_on) {
    native_title_draw_text_at(center-native_title_text_width(s)/2,y,s,selected,blink_on);
}
static void native_title_compose_frame(void) {
    if(!native_title_compose_enabled)return;
    int W=vdp.width?vdp.width:320,H=vdp.height?vdp.height:224;
    if(W<256 || W>320 || H<200 || H>240)return;

    /* Extra title buttons only. GAME OPTIONS is a separate modal native page,
       rendered by state 13; no retired title-screen Modern overlay remains. */
    int clear_top=(H*465/1000)+20;
    if(clear_top<124)clear_top=124;
    if(clear_top>174)clear_top=174;
    for(int y=clear_top;y<175;y++) {
        uint32_t *row=&vdp.fb[y*320];
        for(int x=0;x<W;x++)row[x]=0;
    }
    int blink_on=(native_title_blink_ticks%120u)<60u;
    int left_center=W*26/100,right_center=W*74/100;
    native_title_draw_text_column("START",left_center,134,native_title_menu_selection==0,blink_on);
    native_title_draw_text_column("OPTIONS",right_center,134,native_title_menu_selection==1,blink_on);
    native_title_draw_text_column("GAME OPTIONS",left_center,148,native_title_menu_selection==2,blink_on);
    native_title_draw_text_column("LEVEL BUILDER",right_center,148,native_title_menu_selection==3,blink_on);
    native_title_draw_text_column("CHEATS",left_center,162,native_title_menu_selection==4,blink_on);
    native_title_draw_text_column("SAVES",right_center,162,native_title_menu_selection==5,blink_on);
}
static void native_title_open_selected(void) {
    /* Keep the SDL audio device running while the branded-title modal opens,
       so the newly queued navigation/confirm cue is not suspended at entry. */
    native_pause_keep_title_audio=1;
    native_extras_parent=0;
    native_menu_sel=0;
    if(native_title_menu_selection==2) {
        /* State 13 runs inside native_menu_pause_loop: emulation and demos stop. */
        native_title_page_mode=0;
        native_title_compose_enabled=0;
        native_title_input_block=1;
        native_title_game_options_focus=native_game_level_modern?1:0;
        /* Preserve the real title frame before an attract demo can advance. */
        memcpy(native_title_options_backdrop,vdp.fb,sizeof native_title_options_backdrop);
        native_title_options_backdrop_valid=1;
        native_menu_state=13;
        native_menu_pause_loop();
    } else if(native_title_menu_selection==3) {
        native_menu_state=11;
    } else if(native_title_menu_selection==4) {
        native_menu_state=9;
    } else if(native_title_menu_selection==5) {
        native_menu_state=10;
    }
}
static void native_title_menu_update(void) {
    if(native_menu_state>0) {
        native_title_compose_enabled=0;
        native_title_input_block=1;
        return;
    }
    /* Once the separate Game Options page is open, keep it latched until the
       user backs out. Do not let an underlying ROM menu redraw peek through. */
    if(native_title_page_mode && native_title_scene_active) {
        native_title_blink_ticks=(native_title_blink_ticks+1u)%120u;
        native_title_input_block=1;
        native_title_compose_enabled=1;
        return;
    }
    if(!native_title_menu_scene_visible()) {
        native_title_scene_active=0;
        native_title_page_mode=0;
        native_title_menu_selection=0;
        native_title_transition_guard=0;
        native_title_input_block=0;
        native_title_compose_enabled=0;
        native_title_last_selection=-1;
        native_title_last_page=-1;
        native_title_last_focus=-1;
        return;
    }
    native_pause_font_capture();
    /* Keep a private, full-core checkpoint of the branded title screen. Returning
       from gameplay can then restore the actual Mega Turrican Reborn title state
       without running the reset vector and showing the SEGA boot logo again. */
    if(!native_title_checkpoint_saved && md_save_slot(5))native_title_checkpoint_saved=1;
    if(!native_title_scene_active) {
        native_title_scene_active=1;
        native_title_menu_selection=0;
        native_title_page_mode=0;
        native_title_game_options_focus=native_game_level_modern?1:0;
        native_title_blink_ticks=0;
    }
    if(native_title_menu_selection!=native_title_last_selection ||
       native_title_page_mode!=native_title_last_page ||
       native_title_game_options_focus!=native_title_last_focus) {
        native_title_blink_ticks=0;
        native_title_last_selection=native_title_menu_selection;
        native_title_last_page=native_title_page_mode;
        native_title_last_focus=native_title_game_options_focus;
    } else {
        native_title_blink_ticks=(native_title_blink_ticks+1u)%120u;
    }
    native_title_input_block=(native_title_page_mode || native_title_menu_selection>=2 ||
                              native_title_transition_guard) ? 1 : 0;
    native_title_transition_guard=0;
    native_title_compose_enabled=1;
}
static void native_custom_page_back(int extras_selection) {
    if(native_extras_parent==0) {
        native_menu_state=0;
    } else {
        native_menu_state=8;
        native_menu_sel=extras_selection;
    }
}

static void native_custom_apply(void) {
    md_set_custom_gameplay_options(native_cheat_energy,native_cheat_lives,native_cheat_timer,
        native_game_level_modern && native_modern_continues,
        native_game_level_modern && native_modern_no_timer_hud,
        native_game_level_modern && native_modern_persistent_weapon,
        native_game_level_modern && native_modern_checkpoints,
        native_game_level_modern && native_modern_iframes);
}
static void native_custom_save_config(void) {
    FILE *f=fopen("custom-game-options.ini.tmp","w");
    if(!f)return;
    fprintf(f,"game_level=%d\ncheat_energy=%d\ncheat_lives=%d\ncheat_timer=%d\n"
              "modern_continues=%d\nmodern_map=%d\nmodern_no_timer_hud=%d\n"
              "modern_persistent_weapon=%d\nmodern_checkpoints=%d\nmodern_iframes=%d\n"
              "pause_rapid_fire=%d\npause_control_config=%d\n",
        native_game_level_modern,native_cheat_energy,native_cheat_lives,native_cheat_timer,
        native_modern_continues,native_modern_map,native_modern_no_timer_hud,
        native_modern_persistent_weapon,native_modern_checkpoints,native_modern_iframes,
        native_pause_rapid_fire,native_pause_control_config);
    if(fclose(f)!=0){remove("custom-game-options.ini.tmp");return;}
    remove("custom-game-options.ini");
    rename("custom-game-options.ini.tmp","custom-game-options.ini");
    native_custom_apply();
}
static void native_custom_load_config(void) {
    FILE *f=fopen("custom-game-options.ini","r");
    if(f) {
        char line[160];
        while(fgets(line,sizeof line,f)) {
            char *eq=strchr(line,'='); if(!eq)continue; *eq=0;
            int v=atoi(eq+1);
            if(!strcmp(line,"game_level"))native_game_level_modern=!!v;
            else if(!strcmp(line,"cheat_energy"))native_cheat_energy=!!v;
            else if(!strcmp(line,"cheat_lives"))native_cheat_lives=!!v;
            else if(!strcmp(line,"cheat_timer"))native_cheat_timer=!!v;
            else if(!strcmp(line,"modern_continues"))native_modern_continues=!!v;
            else if(!strcmp(line,"modern_map"))native_modern_map=!!v;
            else if(!strcmp(line,"modern_no_timer_hud"))native_modern_no_timer_hud=!!v;
            else if(!strcmp(line,"modern_persistent_weapon"))native_modern_persistent_weapon=!!v;
            else if(!strcmp(line,"modern_checkpoints"))native_modern_checkpoints=!!v;
            else if(!strcmp(line,"modern_iframes"))native_modern_iframes=!!v;
            else if(!strcmp(line,"pause_rapid_fire"))native_pause_rapid_fire=!!v;
            else if(!strcmp(line,"pause_control_config"))native_pause_control_config=(v%3+3)%3;
        }
        fclose(f);
    }
    native_custom_cfg_loaded=1;
    native_custom_apply();
}

static void native_custom_enter_parent(void) {
    native_menu_state=native_extras_parent;
    native_menu_sel=native_extras_parent==1?2:0;
}

static void render_native_extras(void) {
    static const char *items[]={"GAME LEVEL","MODERN OPTIONS","CHEATS","SAVES","LEVEL BUILDER","BACK"};
    const int n=6,scale=2,pw=244,ph=178;
    int px,py; native_menu_panel(pw,ph,&px,&py);
    native_menu_title(px+(pw-str_w("EXTRAS",2))/2,py+7,"EXTRAS",2);
    for(int i=0;i<n;i++) {
        char row[48];
        if(i==0)snprintf(row,sizeof row,"GAME LEVEL: %s",native_game_level_modern?"MODERN":"ORIGINAL");
        else snprintf(row,sizeof row,"%s",items[i]);
        native_menu_item(px+10,py+30+i*23,row,i==native_menu_sel,scale);
    }
    native_menu_title(px+10,py+168,"LEFT/RIGHT CHANGE  ENTER SELECT",1);
}
static void proc_native_extras(SDL_Event *e) {
    const int n=6;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP:native_menu_sel=(native_menu_sel+n-1)%n;break;
        case SDLK_DOWN:native_menu_sel=(native_menu_sel+1)%n;break;
        case SDLK_LEFT:case SDLK_RIGHT:
            if(native_menu_sel==0){native_game_level_modern^=1;native_custom_save_config();}
            break;
        case SDLK_RETURN:case SDLK_x:goto confirm;
        case SDLK_ESCAPE:native_custom_enter_parent();break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+n-1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT||e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT) {
            if(native_menu_sel==0){native_game_level_modern^=1;native_custom_save_config();}
        }
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A)goto confirm;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B)native_custom_enter_parent();
    }
    return;
confirm:
    switch(native_menu_sel) {
    case 0:native_game_level_modern^=1;native_custom_save_config();break;
    case 1:native_menu_state=12;native_menu_sel=0;break;
    case 2:native_menu_state=9;native_menu_sel=0;break;
    case 3:native_menu_state=10;native_menu_sel=0;break;
    case 4:native_menu_state=11;native_menu_sel=0;break;
    default:native_custom_enter_parent();break;
    }
}

static void native_toggle_option(int state,int item) {
    if(state==9) {
        if(item==0)native_cheat_energy^=1;
        else if(item==1)native_cheat_lives^=1;
        else if(item==2)native_cheat_timer^=1;
    } else if(state==12) {
        if(item==0)native_modern_map^=1;
        else if(item==1)native_modern_no_timer_hud^=1;
        else if(item==2)native_modern_persistent_weapon^=1;
    }
    native_custom_save_config();
}
static void render_native_toggle_page(int state) {
    const char *title=state==9?"CHEATS":"MODERN OPTIONS";
    const char *cheat_labels[4]={"INFINITE ENERGY","INFINITE LIVES","FREEZE TIMER","BACK"};
    const char *modern_labels[4]={"MAP KEY M","HIDE TIMER HUD","ONE-TIER DROP","BACK"};
    const char **labels=state==9?cheat_labels:modern_labels;
    int pw=234,ph=144,px,py;
    native_menu_panel(pw,ph,&px,&py);
    native_menu_title(px+(pw-str_w(title,2))/2,py+8,title,2);
    for(int i=0;i<4;i++) {
        char row[56];
        if(i==3)snprintf(row,sizeof row,"BACK");
        else {
            int on=state==9?(i==0?native_cheat_energy:i==1?native_cheat_lives:native_cheat_timer):
                (i==0?native_modern_map:i==1?native_modern_no_timer_hud:native_modern_persistent_weapon);
            snprintf(row,sizeof row,"%s: %s",labels[i],on?"ON":"OFF");
        }
        native_menu_item(px+10,py+36+i*23,row,i==native_menu_sel,2);
    }
    if(state==12 && !native_game_level_modern)
        native_menu_title(px+10,py+130,"SELECT MODERN GAME LEVEL TO USE THESE",1);
}
static void proc_native_toggle_page(SDL_Event *e,int state) {
    const int n=4;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP:native_menu_sel=(native_menu_sel+n-1)%n;break;
        case SDLK_DOWN:native_menu_sel=(native_menu_sel+1)%n;break;
        case SDLK_LEFT:case SDLK_RIGHT:
            if(native_menu_sel<3)native_toggle_option(state,native_menu_sel);
            break;
        case SDLK_RETURN:case SDLK_x:
            if(native_menu_sel<3)native_toggle_option(state,native_menu_sel);
            else native_custom_page_back(state==9?2:1);
            break;
        case SDLK_ESCAPE:native_custom_page_back(state==9?2:1);break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+n-1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if((e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT||e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT)&&native_menu_sel<3)
            native_toggle_option(state,native_menu_sel);
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A) {
            if(native_menu_sel<3)native_toggle_option(state,native_menu_sel);
            else native_custom_page_back(state==9?2:1);
        }
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B)native_custom_page_back(state==9?2:1);
    }
}

static void render_native_saves(void) {
    int pw=246,ph=198,px,py;
    native_menu_panel(pw,ph,&px,&py);
    native_menu_title(px+(pw-str_w("SAVE SLOTS",2))/2,py+7,"SAVE SLOTS",2);
    for(int i=0;i<8;i++) {
        char row[64];
        int y=py+29+i*18;
        if(i<6) {
            int slot=i/2+1,save=(i%2)==0;
            snprintf(row,sizeof row,"%s SLOT %d  %s",save?"SAVE":"LOAD",slot,
                     md_save_slot_exists(slot)?"SAVED":"EMPTY");
            native_menu_item(px+10,y,row,i==native_menu_sel,2);
        } else if(i==6) {
            snprintf(row,sizeof row,"AUTO CHECKPOINT: %s",
                     md_save_slot_exists(4)?"READY":"EMPTY");
            native_menu_item(px+10,y,row,i==native_menu_sel,1);
        } else {
            native_menu_item(px+10,y,"BACK",i==native_menu_sel,2);
        }
    }
    native_menu_title(px+10,py+181,"LOAD REQUIRES SAME ROM",1);
}
static void proc_native_saves(SDL_Event *e) {
    const int n=8;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP:native_menu_sel=(native_menu_sel+n-1)%n;break;
        case SDLK_DOWN:native_menu_sel=(native_menu_sel+1)%n;break;
        case SDLK_RETURN:case SDLK_x:goto confirm;
        case SDLK_ESCAPE:native_custom_page_back(3);break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+n-1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A)goto confirm;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B)native_custom_page_back(3);
    }
    return;
confirm:
    if(native_menu_sel==7){native_custom_page_back(3);return;}
    if(native_menu_sel==6) {
        int success=md_save_slot_exists(4) && md_load_slot(4);
        if(success && native_menu_state>0)memcpy(native_pause_backdrop,vdp.fb,sizeof native_pause_backdrop);
        return;
    }
    {
        int slot=native_menu_sel/2+1;
        int success=(native_menu_sel%2)==0?md_save_slot(slot):md_load_slot(slot);
        if(success && native_menu_state>0)memcpy(native_pause_backdrop,vdp.fb,sizeof native_pause_backdrop);
    }
}
static int native_level_cols(void) {
    static const int sizes[4]={32,64,64,128}; return sizes[vdp.reg[16]&3];
}
static int native_level_rows(void) {
    static const int sizes[4]={32,64,64,128}; return sizes[(vdp.reg[16]>>4)&3];
}
static uint32_t native_level_plane_a(void) {
    return (uint32_t)(vdp.reg[2]&0x38)<<10;
}
static void native_level_paint(void) {
    int cols=native_level_cols(),rows=native_level_rows();
    if(native_editor_x<0||native_editor_x>=cols||native_editor_y<0||native_editor_y>=rows)return;
    uint32_t at=native_level_plane_a()+(uint32_t)(native_editor_y*cols+native_editor_x)*2;
    at&=0xFFFF;
    uint16_t old=(uint16_t)((vdp.vram[at]<<8)|vdp.vram[(at+1)&0xFFFF]);
    uint16_t value=(old&0xF800)|(native_editor_tile&0x7FF);
    vdp.vram[at]=(uint8_t)(value>>8);vdp.vram[(at+1)&0xFFFF]=(uint8_t)value;
}
static int native_level_export(void) {
    int cols=native_level_cols(),rows=native_level_rows();
    uint32_t base=native_level_plane_a();
    FILE *f=fopen("levels/slot1.mtl.tmp","wb"); if(!f)return 0;
    const char magic[8]={'M','T','L','M','A','P','1',0};
    uint32_t dims[3]={(uint32_t)cols,(uint32_t)rows,(uint32_t)(cols*rows*2)};
    int ok=fwrite(magic,8,1,f)==1 && fwrite(dims,sizeof dims,1,f)==1;
    for(int i=0;ok&&i<cols*rows;i++) {
        uint32_t at=(base+(uint32_t)i*2)&0xFFFF;
        uint8_t word[2]={vdp.vram[at],vdp.vram[(at+1)&0xFFFF]};
        ok=fwrite(word,2,1,f)==1;
    }
    if(fclose(f)!=0)ok=0;
    if(ok){remove("levels/slot1.mtl");if(rename("levels/slot1.mtl.tmp","levels/slot1.mtl")!=0)ok=0;}
    if(!ok)remove("levels/slot1.mtl.tmp");
    return ok;
}
static int native_level_import(void) {
    int cols=native_level_cols(),rows=native_level_rows();
    FILE *f=fopen("levels/slot1.mtl","rb"); if(!f)return 0;
    char magic[8];uint32_t dims[3];
    int ok=fread(magic,8,1,f)==1 && fread(dims,sizeof dims,1,f)==1 &&
           memcmp(magic,"MTLMAP1",7)==0 && dims[0]==(uint32_t)cols &&
           dims[1]==(uint32_t)rows && dims[2]==(uint32_t)(cols*rows*2);
    uint32_t base=native_level_plane_a();
    for(int i=0;ok&&i<cols*rows;i++) {
        uint8_t word[2];ok=fread(word,2,1,f)==1;
        if(ok){uint32_t at=(base+(uint32_t)i*2)&0xFFFF;vdp.vram[at]=word[0];vdp.vram[(at+1)&0xFFFF]=word[1];}
    }
    fclose(f);return ok;
}
static void render_native_level_builder(void) {
    int px=native_editor_x*8,py=native_editor_y*8;
    native_menu_rect(px,py,8,8,0xFF,0xAE,0x1F,255);
    native_menu_rect(px+1,py+1,6,6,0x07,0x09,0x0D,220);
    char a[80],b[96];
    snprintf(a,sizeof a,"LEVEL BUILDER  TILE %03X  CELL %d,%d",native_editor_tile,native_editor_x,native_editor_y);
    snprintf(b,sizeof b,"ARROWS MOVE  +/- TILE  ENTER PAINT  F5 SAVE  F6 LOAD");
    native_menu_rect(0,(vdp.height?vdp.height:224)-28,vdp.width?vdp.width:320,28,0x07,0x09,0x0D,230);
    draw_str(4,(vdp.height?vdp.height:224)-25,a,1,0xFF,0xAE,0x1F);
    draw_str(4,(vdp.height?vdp.height:224)-15,b,1,0xCC,0xD6,0xE0);
    draw_str(4,(vdp.height?vdp.height:224)-7,"TILEMAP ONLY - COLLISION AND OBJECTS NOT EDITED",1,0x99,0xB4,0xC8);
}
static void proc_native_level_builder(SDL_Event *e) {
    int cols=native_level_cols(),rows=native_level_rows();
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP:if(native_editor_y>0)native_editor_y--;break;
        case SDLK_DOWN:if(native_editor_y+1<rows)native_editor_y++;break;
        case SDLK_LEFT:if(native_editor_x>0)native_editor_x--;break;
        case SDLK_RIGHT:if(native_editor_x+1<cols)native_editor_x++;break;
        case SDLK_EQUALS:case SDLK_PLUS:case SDLK_PAGEUP:native_editor_tile=(native_editor_tile+1)&0x7FF;break;
        case SDLK_MINUS:case SDLK_PAGEDOWN:native_editor_tile=(native_editor_tile+0x7FF)&0x7FF;break;
        case SDLK_RETURN:case SDLK_x:native_level_paint();break;
        case SDLK_F5:
#ifdef _WIN32
            _mkdir("levels");
#else
            mkdir("levels",0775);
#endif
            native_level_export();break;
        case SDLK_F6:native_level_import();break;
        case SDLK_ESCAPE:native_custom_page_back(4);break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP&&native_editor_y>0)native_editor_y--;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN&&native_editor_y+1<rows)native_editor_y++;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT&&native_editor_x>0)native_editor_x--;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT&&native_editor_x+1<cols)native_editor_x++;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A)native_level_paint();
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_X)native_editor_tile=(native_editor_tile+1)&0x7FF;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_Y)native_level_export();
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B)native_custom_page_back(4);
    }
}
static const char *native_modern_option_labels[6]={
    "MAP (M KEY)","HIDE TIMER HUD","ONE-TIER WEAPON LOSS","CHECKPOINT AUTO-SAVE",
    "HIT I-FRAMES","UNLIMITED CONTINUES"
};
static int native_modern_option_value(int item) {
    switch(item) {
    case 0:return native_modern_map;
    case 1:return native_modern_no_timer_hud;
    case 2:return native_modern_persistent_weapon;
    case 3:return native_modern_checkpoints;
    case 4:return native_modern_iframes;
    case 5:return native_modern_continues;
    default:return 0;
    }
}
static void native_modern_option_toggle(int item) {
    switch(item) {
    case 0:native_modern_map^=1;break;
    case 1:native_modern_no_timer_hud^=1;break;
    case 2:native_modern_persistent_weapon^=1;break;
    case 3:native_modern_checkpoints^=1;break;
    case 4:native_modern_iframes^=1;break;
    case 5:native_modern_continues^=1;break;
    }
    native_custom_save_config();
}
static void native_title_scroll_ensure_visible(void) {
    int item=native_title_game_options_focus-2;
    if(item<0)return;
    if(item<native_modern_scroll_offset)native_modern_scroll_offset=item;
    if(item>=native_modern_scroll_offset+4)native_modern_scroll_offset=item-3;
    if(native_modern_scroll_offset<0)native_modern_scroll_offset=0;
    if(native_modern_scroll_offset>2)native_modern_scroll_offset=2;
}
static void native_title_game_options_move(int delta) {
    int next=native_title_game_options_focus+delta;
    if(next<0)next=8;
    if(next>8)next=0;
    if(!native_game_level_modern && next>=2 && next<=7)
        next=(delta>0)?8:1;
    native_title_game_options_focus=next;
    native_title_scroll_ensure_visible();
}
static void render_native_title_game_options(void) {
    int W=vdp.width?vdp.width:320, H=vdp.height?vdp.height:224;
    if(W<256 || W>320 || H<200 || H>240)return;
    for(int y=0;y<H;y++) {
        uint32_t *row=&vdp.fb[y*320];
        for(int x=0;x<W;x++)row[x]=0;
    }

    native_title_draw_text_center_palette("GAME OPTIONS",H*7/100,3);
    native_title_draw_text_center("VANILLA GAME",H*19/100,
                                  native_title_game_options_focus==0,1);
    native_title_draw_text_center("MODERN",H*29/100,
                                  native_title_game_options_focus==1,1);

    if(native_game_level_modern) {
        native_title_draw_text_center_palette("MODERN SETTINGS",H*38/100,1);
        const int first_y=H*45/100;
        const int row_step=H*7/100;
        for(int row=0;row<4;row++) {
            int item=native_modern_scroll_offset+row;
            if(item>=6)break;
            char text[48];
            snprintf(text,sizeof text,"%s: %s",native_modern_option_labels[item],
                     native_modern_option_value(item)?"ON":"OFF");
            native_title_draw_text_center(text,first_y+row*row_step,
                native_title_game_options_focus==item+2,1);
        }
        char scroll[24];
        snprintf(scroll,sizeof scroll,"SCROLL %d/3",native_modern_scroll_offset+1);
        native_title_draw_text_center_palette(scroll,H*78/100,1);
    }

    native_title_draw_text_center("EXIT",H*91/100,
                                  native_title_game_options_focus==8,1);
}
static void native_title_game_options_exit(void) {
    native_title_page_mode=0;
    native_title_menu_selection=2;
    native_title_scene_active=1;
    native_title_compose_enabled=0;
    native_title_input_block=0;
    native_title_transition_guard=0;
    native_menu_state=0;
    native_menu_sel=0;
}
static void native_title_game_options_confirm(void) {
    switch(native_title_game_options_focus) {
    case 0:
        native_game_level_modern=0;
        native_custom_save_config();
        native_title_game_options_focus=0;
        break;
    case 1:
        native_game_level_modern=1;
        native_custom_save_config();
        native_title_game_options_focus=2;
        native_modern_scroll_offset=0;
        break;
    case 2:case 3:case 4:case 5:case 6:case 7:
        if(native_game_level_modern)
            native_modern_option_toggle(native_title_game_options_focus-2);
        break;
    case 8:
        native_title_game_options_exit();
        break;
    }
}
static void proc_native_title_game_options(SDL_Event *e) {
    if(e->type==SDL_KEYDOWN && !e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP:native_title_game_options_move(-1);break;
        case SDLK_DOWN:native_title_game_options_move(1);break;
        case SDLK_LEFT:case SDLK_RIGHT:
            if(native_title_game_options_focus==0) {
                native_game_level_modern=1;native_custom_save_config();
                native_title_game_options_focus=2;native_modern_scroll_offset=0;
            } else if(native_title_game_options_focus==1) {
                native_game_level_modern=0;native_custom_save_config();
                native_title_game_options_focus=0;
            } else if(native_title_game_options_focus>=2 && native_title_game_options_focus<=7) {
                native_modern_option_toggle(native_title_game_options_focus-2);
            }
            break;
        case SDLK_RETURN:case SDLK_x:native_title_game_options_confirm();break;
        case SDLK_ESCAPE:native_title_game_options_exit();break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        switch(e->cbutton.button) {
        case SDL_CONTROLLER_BUTTON_DPAD_UP:native_title_game_options_move(-1);break;
        case SDL_CONTROLLER_BUTTON_DPAD_DOWN:native_title_game_options_move(1);break;
        case SDL_CONTROLLER_BUTTON_DPAD_LEFT:case SDL_CONTROLLER_BUTTON_DPAD_RIGHT:
            if(native_title_game_options_focus==0) {
                native_game_level_modern=1;native_custom_save_config();
                native_title_game_options_focus=2;native_modern_scroll_offset=0;
            } else if(native_title_game_options_focus==1) {
                native_game_level_modern=0;native_custom_save_config();
                native_title_game_options_focus=0;
            } else if(native_title_game_options_focus>=2 && native_title_game_options_focus<=7) {
                native_modern_option_toggle(native_title_game_options_focus-2);
            }
            break;
        case SDL_CONTROLLER_BUTTON_A:native_title_game_options_confirm();break;
        case SDL_CONTROLLER_BUTTON_B:
        case SDL_CONTROLLER_BUTTON_START:native_title_game_options_exit();break;
        }
    }
}

/* Decode VDP tile entries into a compact top-down area overview. */
static uint32_t native_map_tile_sample(uint32_t map_base,int cols,int row,int col) {
    uint32_t at=(map_base+(uint32_t)(row*cols+col)*2u)&0xFFFFu;
    uint16_t entry=(uint16_t)(((uint16_t)vdp.vram[at]<<8)|vdp.vram[(at+1u)&0xFFFFu]);
    unsigned tile=entry&0x07FFu,palette=(entry>>13)&3u;
    int hflip=(entry&0x0800u)!=0,vflip=(entry&0x1000u)!=0;
    unsigned accum_r=0,accum_g=0,accum_b=0,count=0;
    for(int sy=1;sy<8;sy+=2)for(int sx=1;sx<8;sx+=2) {
        int tx=hflip?7-sx:sx,ty=vflip?7-sy:sy;
        unsigned bit=(unsigned)(7-tx),base=tile*32u+(unsigned)ty*4u,index=0;
        for(unsigned plane=0;plane<4;plane++)
            index|=((vdp.vram[(base+plane)&0xFFFFu]>>bit)&1u)<<plane;
        if(index) {
            uint32_t rgb=native_title_cram_rgb((int)palette,index);
            accum_r+=(rgb>>16)&255;accum_g+=(rgb>>8)&255;accum_b+=rgb&255;count++;
        }
    }
    if(!count)return 0;
    return ((accum_r/count)<<16)|((accum_g/count)<<8)|(accum_b/count);
}
static uint32_t native_map_plane_b_pixel(int x,int y) {
    int cols=native_level_cols(),rows=native_level_rows();
    uint32_t base=(uint32_t)(vdp.reg[4]&7u)<<13;
    uint32_t hbase=(uint32_t)(vdp.reg[13]&0x3Fu)<<10;
    int hscroll=(int16_t)(((uint16_t)vdp.vram[(hbase+2u)&0xFFFFu]<<8)|
                           vdp.vram[(hbase+3u)&0xFFFFu]);
    int vscroll=(int16_t)vdp.vsram[1];
    int world_x=(x-hscroll)%(cols*8),world_y=(y-vscroll)%(rows*8);
    if(world_x<0)world_x+=cols*8;
    if(world_y<0)world_y+=rows*8;
    int tx=world_x&7,ty=world_y&7;
    uint32_t at=(base+(uint32_t)(((world_y>>3)*cols+(world_x>>3))*2))&0xFFFFu;
    uint16_t entry=(uint16_t)(((uint16_t)vdp.vram[at]<<8)|vdp.vram[(at+1u)&0xFFFFu]);
    unsigned tile=entry&0x07FFu,palette=(entry>>13)&3u;
    if(entry&0x0800u)tx=7-tx;
    if(entry&0x1000u)ty=7-ty;
    unsigned bit=(unsigned)(7-tx),tile_base=tile*32u+(unsigned)ty*4u,index=0;
    for(unsigned plane=0;plane<4;plane++)
        index|=((vdp.vram[(tile_base+plane)&0xFFFFu]>>bit)&1u)<<plane;
    return native_title_cram_rgb((int)palette,index);
}
static void native_modern_apply_frame_features(void) {
    /* Disabled until timer suppression is moved into the real VDP plane/sprite
       composition path. Never sample arbitrary VRAM tiles into the framebuffer. */
}
static void render_native_area_map(void) {
    int W=vdp.width?vdp.width:320,H=vdp.height?vdp.height:224;
    int cols=native_level_cols(),rows=native_level_rows();
    uint32_t plane_a=(uint32_t)(vdp.reg[2]&0x38u)<<10;
    uint32_t plane_b=(uint32_t)(vdp.reg[4]&7u)<<13;
    int cellx=(W-24)/cols,celly=(H-48)/rows,cell=cellx<celly?cellx:celly;
    if(cell<1)cell=1;
    if(cell>4)cell=4;
    int mw=cols*cell,mh=rows*cell,mx=(W-mw)/2,my=(H-mh)/2;
    for(int y=0;y<H;y++) {
        uint32_t *row=&vdp.fb[y*320];
        for(int x=0;x<W;x++)row[x]=0;
    }
    native_title_draw_text_center_palette("CURRENT AREA MAP",5,3);
    for(int row=0;row<rows;row++)for(int col=0;col<cols;col++) {
        uint32_t rgb=native_map_tile_sample(plane_a,cols,row,col);
        if(!rgb)rgb=native_map_tile_sample(plane_b,cols,row,col);
        if(!rgb)continue;
        int r=(rgb>>16)&255,g=(rgb>>8)&255,b=rgb&255;
        native_menu_rect(mx+col*cell,my+row*cell,cell,cell,(uint8_t)r,(uint8_t)g,(uint8_t)b,255);
    }
    uint32_t hbase=(uint32_t)(vdp.reg[13]&0x3Fu)<<10;
    int hscroll=(int16_t)(((uint16_t)vdp.vram[(hbase+2u)&0xFFFFu]<<8)|vdp.vram[(hbase+3u)&0xFFFFu]);
    int vscroll=(int16_t)vdp.vsram[1];
    int vx=mx+(((hscroll%(cols*8))+cols*8)%(cols*8))/8*cell;
    int vy=my+(((vscroll%(rows*8))+rows*8)%(rows*8))/8*cell;
    int vw=(W/8)*cell,vh=(H/8)*cell;
    native_menu_rect(vx,vy,vw,1,0xA8,0xE8,0xFF,255);
    native_menu_rect(vx,vy+vh-1,vw,1,0xA8,0xE8,0xFF,255);
    native_menu_rect(vx,vy,1,vh,0xA8,0xE8,0xFF,255);
    native_menu_rect(vx+vw-1,vy,1,vh,0xA8,0xE8,0xFF,255);
}
static void proc_native_area_map(SDL_Event *e) {
    if(e->type==SDL_KEYDOWN&&!e->key.repeat &&
       (e->key.keysym.sym==SDLK_m||e->key.keysym.sym==SDLK_ESCAPE||
        e->key.keysym.sym==SDLK_RETURN||e->key.keysym.sym==SDLK_x))
        native_menu_state=0;
    if(e->type==SDL_CONTROLLERBUTTONDOWN &&
       (e->cbutton.button==SDL_CONTROLLER_BUTTON_B||
        e->cbutton.button==SDL_CONTROLLER_BUTTON_START||
        e->cbutton.button==SDL_CONTROLLER_BUTTON_A))
        native_menu_state=0;
}


static void native_pause_font_capture(void) {
    if(native_pause_font_cache_valid)return;
    /* Cache the ROM's title-menu glyph patterns while they are resident in VRAM.
       Gameplay reuses those tile slots for scenery, so reading them live during
       pause produces the rectangular texture blocks seen in the broken menu. */
    for(unsigned tile=0x530u;tile<=0x55Au;tile++)
        memcpy(native_pause_font_cache[tile-0x530u],&vdp.vram[tile*32u],32u);
    native_pause_font_cache_valid=1;
}
static void native_pause_draw_text(int x,int y,const char *s,uint32_t color) {
    int W=vdp.width?vdp.width:320,H=vdp.height?vdp.height:224;
    if(!native_pause_font_cache_valid)return;
    uint8_t r=(uint8_t)(color>>16),g=(uint8_t)(color>>8),b=(uint8_t)color;
    for(int i=0;s[i];i++) {
        if(s[i]==' ')continue;
        uint16_t tile=native_options_font_tile(s[i]);
        if(tile<0x530u||tile>0x55Au)continue;
        const uint8_t *glyph=native_pause_font_cache[tile-0x530u];
        for(int sy=0;sy<8;sy++) {
            int py=y+sy;if(py<0||py>=H)continue;
            uint32_t *row=&vdp.fb[py*320];
            for(int sx=0;sx<8;sx++) {
                int px=x+i*8+sx;if(px<0||px>=W)continue;
                uint8_t packed=glyph[(size_t)sy*4u+(size_t)(sx>>1)];
                unsigned ink=(sx&1)?(packed&15u):(packed>>4);
                if(ink)row[px]=((uint32_t)r<<16)|((uint32_t)g<<8)|b;
            }
        }
    }
}
static void native_pause_panel(const char *title) {
    int W=vdp.width?vdp.width:320,H=vdp.height?vdp.height:224;
    int x=10,y=8,w=W-20,h=H-16;
    native_menu_rect(x,y,w,h,0x6A,0x74,0x88,255);
    native_menu_rect(x+2,y+2,w-4,h-4,0x08,0x0D,0x17,255);
    native_menu_rect(x+4,y+4,w-8,h-8,0x1A,0x22,0x2E,176);
    for(int i=0;i<w-12;i++) {
        int t=i*255/(w-13);
        native_menu_rect(x+6+i,y+6,1,18,
            (uint8_t)(105+150*t/255),(uint8_t)(8+118*t/255),(uint8_t)(18+18*t/255),255);
    }
    native_menu_rect(x+6,y+24,w-12,2,0xE8,0xA8,0x46,255);
    native_pause_draw_text(x+14,y+10,title,0xFFF0CF);
    for(int i=0;i<4;i++) {
        int on=((native_pause_anim_ticks/12u+i*3u)&1u)!=0;
        native_menu_rect(x+w-34+i*6,y+8,4,4,on?0xF3:0x54,on?0x24:0x1C,on?0xDC:0x42,255);
    }
    const int rx[4]={x+7,x+w-12,x+7,x+w-12};
    const int ry[4]={y+7,y+7,y+h-12,y+h-12};
    for(int i=0;i<4;i++) {
        native_menu_rect(rx[i],ry[i],5,5,0xB7,0xC1,0xCE,255);
        native_menu_rect(rx[i]+1,ry[i]+1,3,3,0x2C,0x35,0x42,255);
    }
}
static void native_pause_enter_confirm(int action) {
    native_pause_confirm_action=action;
    native_pause_confirm_choice=1;
    native_pause_no_checkpoint=0;
    native_menu_state=17;
    native_menu_sel=1;
}
static void render_native_suit_status(void) {
    uint8_t ram_snapshot[0x10000];
    md_copy_main_ram(ram_snapshot);
    unsigned energy=((unsigned)ram_snapshot[0xBF20]<<8)|ram_snapshot[0xBF21];
    unsigned lives=((unsigned)ram_snapshot[0xBF26]<<8)|ram_snapshot[0xBF27];
    unsigned bombs=ram_snapshot[0xBD0D];
    unsigned weapon=ram_snapshot[0xBD0E]%3u;
    unsigned multiple=ram_snapshot[0xBD17],laser=ram_snapshot[0xBD18],rebound=ram_snapshot[0xBD19];
    if(energy>0x40)energy=0x40;
    native_pause_panel("SUIT STATUS AND ARSENAL");
    const int x=24;
    char row[56];
    snprintf(row,sizeof row,"ENERGY %u / 64",energy);
    native_pause_draw_text(x,36,row,0xE8D7B0);
    native_menu_rect(x,47,116,7,0x40,0x34,0x42,255);
    if(energy)native_menu_rect(x,47,(int)(116*energy/64),7,0xE8,0xA5,0x25,255);
    snprintf(row,sizeof row,"LIVES %u",lives);native_pause_draw_text(x,61,row,0xD7E0EB);
    snprintf(row,sizeof row,"SMART BOMBS %u",bombs);native_pause_draw_text(x,76,row,0xD7E0EB);
    native_pause_draw_text(x,91,"DIAMONDS --",0xAAB8C7);
    native_pause_draw_text(x,106,"HOMING MISSILES --",0xAAB8C7);
    native_pause_draw_text(x,123,"PRIMARY WEAPON LEFT RIGHT",0xF0B7E7);
    const char *weapon_name[3]={"MULTIPLE","LASER","REBOUND"};
    const unsigned levels[3]={multiple,laser,rebound};
    for(int i=0;i<3;i++) {
        snprintf(row,sizeof row,"%s  LV %u",weapon_name[i],levels[i]);
        int yy=138+i*15;
        if(i==(int)weapon) {
            native_menu_rect(x-4,yy-2,170,13,0x78,0x13,0x68,190);
            native_menu_rect(x-4,yy-2,2,13,0xF0,0x26,0xD8,255);
        }
        native_pause_draw_text(x,yy,row,i==(int)weapon?0xFFF0D0:0xCDD6E2);
    }
    native_pause_draw_text(x,186,"PLASMA ROPE --   ENERGY WHEEL --",0xAAB8C7);
    native_pause_draw_text(x,202,"B ESC BACK",0xAAB8C7);
}
static void proc_native_suit_status(SDL_Event *e) {
    uint8_t ram_snapshot[0x10000];md_copy_main_ram(ram_snapshot);
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        if(e->key.keysym.sym==SDLK_LEFT||e->key.keysym.sym==SDLK_RIGHT) {
            unsigned current=ram_snapshot[0xBD0E]%3u;
            current=(current+(e->key.keysym.sym==SDLK_RIGHT?1u:2u))%3u;
            /* $FFBD0E is the selected weapon index read by the game's death/weapon routine. */
            md_set_ram_byte(0xBD0E,(uint8_t)current);
        } else if(e->key.keysym.sym==SDLK_ESCAPE||e->key.keysym.sym==SDLK_RETURN||e->key.keysym.sym==SDLK_x) {
            native_menu_state=1;native_menu_sel=1;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT||e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT) {
            unsigned current=ram_snapshot[0xBD0E]%3u;
            current=(current+(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT?1u:2u))%3u;
            md_set_ram_byte(0xBD0E,(uint8_t)current);
        }
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B||e->cbutton.button==SDL_CONTROLLER_BUTTON_START)
            {native_menu_state=1;native_menu_sel=1;}
    }
}
static void native_pause_apply_control_config(void) {
    static const int layouts[3][8]={
        {12,13,14,15,2,0,1,9},
        {12,13,14,15,0,2,1,9},
        {12,13,14,15,2,1,0,9}
    };
    for(int i=0;i<8;i++)pad_map[i]=layouts[native_pause_control_config%3][i];
    save_cfg();
}
static void render_native_pause_options(void) {
    native_pause_panel("OPTIONS AND SOUND TEST");
    static const char *items[]={"RAPID FIRE","CONTROL CONFIG","FM SOUND TEST 1",
        "FM SOUND TEST 2","FM SOUND TEST 3","FM SOUND TEST 4","BACK"};
    const int n=7;
    for(int i=0;i<n;i++) {
        int y=34+i*22;
        if(i==native_menu_sel) {
            native_menu_rect(18,y-2,(vdp.width?vdp.width:320)-36,17,0x72,0x12,0x68,190);
            native_menu_rect(18,y-2,2,17,0xF0,0x26,0xD8,255);
        }
        char row[56];
        if(i==0)snprintf(row,sizeof row,"RAPID FIRE %s",native_pause_rapid_fire?"ON":"OFF");
        else if(i==1)snprintf(row,sizeof row,"CONTROL CONFIG TYPE %c",'A'+(native_pause_control_config%3));
        else snprintf(row,sizeof row,"%s",items[i]);
        native_pause_draw_text(26,y,row,i==native_menu_sel?0xFFF0D0:0xC9D4E0);
    }
    native_pause_draw_text(22,202,"B ESC BACK   A ENTER SELECT",0xAAB8C7);
}
static void proc_native_pause_options(SDL_Event *e) {
    const int n=7;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP:native_menu_sel=(native_menu_sel+n-1)%n;break;
        case SDLK_DOWN:native_menu_sel=(native_menu_sel+1)%n;break;
        case SDLK_LEFT:case SDLK_RIGHT:
            if(native_menu_sel==0) {native_pause_rapid_fire^=1;native_custom_save_config();}
            else if(native_menu_sel==1) {
                native_pause_control_config=(native_pause_control_config+
                    (e->key.keysym.sym==SDLK_RIGHT?1:2))%3;
                native_pause_apply_control_config();native_custom_save_config();
            } else if(native_menu_sel>=2&&native_menu_sel<=5) {
                native_pause_sound_track=native_menu_sel-2;
                md_pause_fm_test_start(native_pause_sound_track);
            }
            break;
        case SDLK_RETURN:case SDLK_x:goto confirm;
        case SDLK_ESCAPE:
            md_pause_fm_test_stop();native_pause_sound_track=-1;
            native_menu_state=1;native_menu_sel=2;break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+n-1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT||e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT) {
            if(native_menu_sel==0) {native_pause_rapid_fire^=1;native_custom_save_config();}
            else if(native_menu_sel==1) {
                native_pause_control_config=(native_pause_control_config+
                    (e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT?1:2))%3;
                native_pause_apply_control_config();native_custom_save_config();
            } else if(native_menu_sel>=2&&native_menu_sel<=5) {
                native_pause_sound_track=native_menu_sel-2;
                md_pause_fm_test_start(native_pause_sound_track);
            }
        }
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A)goto confirm;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B) {
            md_pause_fm_test_stop();native_pause_sound_track=-1;
            native_menu_state=1;native_menu_sel=2;
        }
    }
    return;
confirm:
    if(native_menu_sel==0) {native_pause_rapid_fire^=1;native_custom_save_config();}
    else if(native_menu_sel==1) {
        native_pause_control_config=(native_pause_control_config+1)%3;
        native_pause_apply_control_config();native_custom_save_config();
    } else if(native_menu_sel>=2&&native_menu_sel<=5) {
        native_pause_sound_track=native_menu_sel-2;
        md_pause_fm_test_start(native_pause_sound_track);
    } else {
        md_pause_fm_test_stop();native_pause_sound_track=-1;
        native_menu_state=1;native_menu_sel=2;
    }
}
static void render_native_pause_confirm(void) {
    native_pause_panel(native_pause_confirm_action==0?"RESTART STAGE":
        native_pause_confirm_action==1?"QUIT TO TITLE SCREEN":"QUIT GAME");
    int W=vdp.width?vdp.width:320,H=vdp.height?vdp.height:224;
    native_pause_draw_text(W/2-48,H/2-30,"ARE YOU SURE",0xFFF0CF);
    native_pause_draw_text(W/2-42,H/2+3,"YES",native_pause_confirm_choice==0?0xFF52E8:0xDDE6F1);
    native_pause_draw_text(W/2+28,H/2+3,"NO",native_pause_confirm_choice==1?0xFF52E8:0xDDE6F1);
    if(native_pause_no_checkpoint)
        native_pause_draw_text(W/2-88,H/2+22,"NO CHECKPOINT SAVED",0xF4A944);
}
static void proc_native_pause_confirm(SDL_Event *e) {
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        if(e->key.keysym.sym==SDLK_LEFT||e->key.keysym.sym==SDLK_RIGHT||
           e->key.keysym.sym==SDLK_UP||e->key.keysym.sym==SDLK_DOWN)
            native_pause_confirm_choice^=1;
        else if(e->key.keysym.sym==SDLK_RETURN||e->key.keysym.sym==SDLK_x) {
            if(native_pause_confirm_choice) {native_menu_state=1;native_menu_sel=1;}
            else if(native_pause_confirm_action==0) {
                if(md_save_slot_exists(4)&&md_load_slot(4))native_menu_state=0;
                else native_pause_no_checkpoint=1;
            } else if(native_pause_confirm_action==1) {
                native_pause_request_title=1;native_menu_state=0;
            } else exit(0);
        } else if(e->key.keysym.sym==SDLK_ESCAPE) {native_menu_state=1;native_menu_sel=1;}
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT||
           e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT||
           e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP||
           e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)
            native_pause_confirm_choice^=1;
        else if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A) {
            if(native_pause_confirm_choice) {native_menu_state=1;native_menu_sel=1;}
            else if(native_pause_confirm_action==0) {
                if(md_save_slot_exists(4)&&md_load_slot(4))native_menu_state=0;
                else native_pause_no_checkpoint=1;
            } else if(native_pause_confirm_action==1) {
                native_pause_request_title=1;native_menu_state=0;
            } else exit(0);
        } else if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B)
            {native_menu_state=1;native_menu_sel=1;}
    }
}




static int native_pause_cfg_value(int offset) {
    int value=0;
    memcpy(&value,((const uint8_t *)&cfg)+offset,sizeof value);
    return value;
}
static void native_pause_option_row(int y,const char *label,const char *value,int selected) {
    int W=vdp.width?vdp.width:320;
    if(selected) {
        native_menu_rect(18,y-2,W-36,17,0x72,0x12,0x68,190);
        native_menu_rect(18,y-2,2,17,0xF0,0x26,0xD8,255);
    }
    native_pause_draw_text(26,y,label,selected?0xFFF0D0:0xC9D4E0);
    int len=(int)strlen(value);
    int vx=W-26-len*8;
    if(vx<166)vx=166;
    native_pause_draw_text(vx,y,value,selected?0xF4C6ED:0xAAB8C7);
}
static void native_pause_page_back(int root_selection) {
    native_menu_state=1;
    native_menu_sel=root_selection;
}
static void render_native_pause_video_settings(void) {
    static const char *labels[]={"ASPECT","SHADER","SCANLINE STR","INTEGER SCALE","FULLSCREEN","SCANLINES","BACK"};
    static const char *aspects[]={"4 3 BARS","NATIVE 10 7","STRETCH","WIDESCREEN"};
    static const char *shaders[]={"BILINEAR","SCANLINES","COMPOSITE","BOTH"};
    char value[32];
    native_pause_panel("VIDEO SETTINGS");
    for(int i=0;i<7;i++) {
        if(i==6)snprintf(value,sizeof value,"");
        else if(i==0)snprintf(value,sizeof value,"%s",aspects[native_pause_cfg_value(0)%4]);
        else if(i==1)snprintf(value,sizeof value,"%s",shaders[native_pause_cfg_value(4)%4]);
        else if(i==2)snprintf(value,sizeof value,"%d PCT",native_pause_cfg_value(0x24));
        else snprintf(value,sizeof value,"%s",native_pause_cfg_value(i==3?0x08:i==4?0x0C:0x10)?"ON":"OFF");
        native_pause_option_row(36+i*22,labels[i],value,i==native_menu_sel);
    }
    native_pause_draw_text(22,202,"LEFT RIGHT CHANGE  ENTER SELECT  ESC BACK",0xAAB8C7);
}
static void proc_native_pause_video_settings(SDL_Event *e) {
    const int n=7;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP:native_menu_sel=(native_menu_sel+n-1)%n;break;
        case SDLK_DOWN:native_menu_sel=(native_menu_sel+1)%n;break;
        case SDLK_LEFT:if(native_menu_sel<6)adjust_video(native_menu_sel,-1);break;
        case SDLK_RIGHT:if(native_menu_sel<6)adjust_video(native_menu_sel,1);break;
        case SDLK_RETURN:case SDLK_x:
            if(native_menu_sel==6)native_pause_page_back(1);
            else adjust_video(native_menu_sel,1);
            break;
        case SDLK_ESCAPE:native_pause_page_back(1);break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+n-1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT&&native_menu_sel<6)adjust_video(native_menu_sel,-1);
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT&&native_menu_sel<6)adjust_video(native_menu_sel,1);
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A) {
            if(native_menu_sel==6)native_pause_page_back(1);
            else adjust_video(native_menu_sel,1);
        }
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B||e->cbutton.button==SDL_CONTROLLER_BUTTON_START)
            native_pause_page_back(1);
    }
}
static void render_native_pause_audio_settings(void) {
    char value[32];
    native_pause_panel("AUDIO SETTINGS");
    for(int i=0;i<3;i++) {
        if(i==0)snprintf(value,sizeof value,"%s",native_pause_cfg_value(0x18)?"ON":"OFF");
        else if(i==1)snprintf(value,sizeof value,"%d PCT",native_pause_cfg_value(0x1C));
        else value[0]=0;
        native_pause_option_row(42+i*30,i==0?"AUDIO":i==1?"VOLUME":"BACK",value,i==native_menu_sel);
    }
    native_pause_draw_text(22,202,"LEFT RIGHT CHANGE  ENTER SELECT  ESC BACK",0xAAB8C7);
}
static void proc_native_pause_audio_settings(SDL_Event *e) {
    const int n=3;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP:native_menu_sel=(native_menu_sel+n-1)%n;break;
        case SDLK_DOWN:native_menu_sel=(native_menu_sel+1)%n;break;
        case SDLK_LEFT:if(native_menu_sel<2)adjust_audio(native_menu_sel,-1);break;
        case SDLK_RIGHT:if(native_menu_sel<2)adjust_audio(native_menu_sel,1);break;
        case SDLK_RETURN:case SDLK_x:
            if(native_menu_sel==2)native_pause_page_back(2);
            else adjust_audio(native_menu_sel,1);
            break;
        case SDLK_ESCAPE:native_pause_page_back(2);break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+n-1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT&&native_menu_sel<2)adjust_audio(native_menu_sel,-1);
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT&&native_menu_sel<2)adjust_audio(native_menu_sel,1);
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A) {
            if(native_menu_sel==2)native_pause_page_back(2);
            else adjust_audio(native_menu_sel,1);
        }
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B||e->cbutton.button==SDL_CONTROLLER_BUTTON_START)
            native_pause_page_back(2);
    }
}
static void render_native_pause_controller_setup(void) {
    static const char *actions[]={"UP","DOWN","LEFT","RIGHT","FIRE A","JUMP B","ROPE C","START PAUSE"};
    native_pause_panel("CONTROLLER SETUP");
    for(int i=0;i<11;i++) {
        char row[56];
        if(i<8)snprintf(row,sizeof row,"%s  %s",actions[i],native_binding_name(pad_map[i]));
        else if(i==8)snprintf(row,sizeof row,"DUALSENSE PROFILE WIP");
        else if(i==9)snprintf(row,sizeof row,"RESTORE DEFAULTS");
        else snprintf(row,sizeof row,"BACK");
        int y=34+i*14;
        if(i==native_menu_sel) {
            native_menu_rect(18,y-2,(vdp.width?vdp.width:320)-36,13,0x72,0x12,0x68,190);
            native_menu_rect(18,y-2,2,13,0xF0,0x26,0xD8,255);
        }
        native_pause_draw_text(26,y,row,i==native_menu_sel?0xFFF0D0:0xC9D4E0);
    }
    native_pause_draw_text(22,202,"LEFT RIGHT REBIND  A RESTORE  B BACK",0xAAB8C7);
}
static void proc_native_pause_controller_setup(SDL_Event *e) {
    native_menu_state=7;
    proc_native_controller_options(e);
    if(native_menu_state==6)native_pause_page_back(3);
    else if(native_menu_state==7)native_menu_state=20;
}
static void render_native_pause_controls(void) {
    static const char *lines[]={"KEYBOARD","ARROWS MOVE","X FIRE","Z JUMP","C ROPE",
        "ENTER START","ESC PAUSE","GAMEPAD","DPAD MOVE","CROSS JUMP",
        "SQUARE FIRE","CIRCLE ROPE","OPTIONS PAUSE"};
    native_pause_panel("CONTROLS");
    for(int i=0;i<13;i++)
        native_pause_draw_text(28,34+i*12,lines[i],i==0||i==7?0xEDB5E8:0xD5DFEA);
    native_pause_draw_text(22,202,"ENTER OR B TO RETURN",0xAAB8C7);
}
static void render_native_pause_achievements(void) {
    int count=(int)(sizeof achievements/sizeof achievements[0]);
    int show=count>9?9:count,unlocked=0;
    char header[40],row[64];
    for(int i=0;i<count;i++)if(achievements[i].unlocked)unlocked++;
    if(native_pause_achievement_first<0)native_pause_achievement_first=0;
    if(native_pause_achievement_first>count-show)native_pause_achievement_first=count-show;
    if(native_menu_sel>=count)native_menu_sel=0;
    if(native_menu_sel<native_pause_achievement_first)native_pause_achievement_first=native_menu_sel;
    if(native_menu_sel>=native_pause_achievement_first+show)
        native_pause_achievement_first=native_menu_sel-show+1;
    native_pause_panel("ACHIEVEMENTS");
    snprintf(header,sizeof header,"%d OF %d UNLOCKED",unlocked,count);
    native_pause_draw_text(24,34,header,0xE8C0E8);
    for(int i=0;i<show;i++) {
        int index=native_pause_achievement_first+i;
        snprintf(row,sizeof row,"%s %s",achievements[index].unlocked?"UNLOCKED":"LOCKED",achievements[index].name);
        int y=51+i*15;
        if(index==native_menu_sel) {
            native_menu_rect(18,y-2,(vdp.width?vdp.width:320)-36,14,0x72,0x12,0x68,190);
            native_menu_rect(18,y-2,2,14,0xF0,0x26,0xD8,255);
        }
        native_pause_draw_text(26,y,row,index==native_menu_sel?0xFFF0D0:0xC9D4E0);
    }
    native_pause_draw_text(22,202,"UP DOWN SELECT  B BACK",0xAAB8C7);
}
static void proc_native_pause_info_back(SDL_Event *e) {
    if(native_menu_state==22) {
        int count=(int)(sizeof achievements/sizeof achievements[0]);
        if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
            if(e->key.keysym.sym==SDLK_UP)native_menu_sel=(native_menu_sel+count-1)%count;
            else if(e->key.keysym.sym==SDLK_DOWN)native_menu_sel=(native_menu_sel+1)%count;
            else if(e->key.keysym.sym==SDLK_ESCAPE||e->key.keysym.sym==SDLK_RETURN||e->key.keysym.sym==SDLK_x)
                native_pause_page_back(5);
        }
        if(e->type==SDL_CONTROLLERBUTTONDOWN) {
            if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+count-1)%count;
            else if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%count;
            else if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B||e->cbutton.button==SDL_CONTROLLER_BUTTON_A||
                    e->cbutton.button==SDL_CONTROLLER_BUTTON_START)native_pause_page_back(5);
        }
        return;
    }
    if(e->type==SDL_KEYDOWN&&!e->key.repeat &&
       (e->key.keysym.sym==SDLK_ESCAPE||e->key.keysym.sym==SDLK_RETURN||e->key.keysym.sym==SDLK_x))
        native_pause_page_back(4);
    if(e->type==SDL_CONTROLLERBUTTONDOWN &&
       (e->cbutton.button==SDL_CONTROLLER_BUTTON_B||e->cbutton.button==SDL_CONTROLLER_BUTTON_A||
        e->cbutton.button==SDL_CONTROLLER_BUTTON_START))
        native_pause_page_back(4);
}

static void native_title_menu_sfx(int confirm) {
    if(!adev)return;
    /* The FM core is shared with the title music callback. Quiesce that callback
       while the short cue is rendered, restore the exact YM state, then queue
       the samples and resume immediately. */
    int was_paused=(SDL_GetAudioDeviceStatus(adev)==SDL_AUDIO_PAUSED);
    SDL_PauseAudioDevice(adev,1);
    int16_t samples[2400*2];
    md_pause_fm_test_start(confirm?2:0);
    md_pause_fm_test_render(samples,2400,2);
    md_pause_fm_test_stop();
    SDL_QueueAudio(adev,samples,(Uint32)sizeof samples);
    if(!was_paused)SDL_PauseAudioDevice(adev,0);
}

static int native_pause_audio_active=0;
static void native_pause_audio_pump(void) {
    int wanted=(native_menu_state==16 && native_pause_sound_track>=0 && adev!=0);
    if(wanted) {
        if(!native_pause_audio_active) {
            SDL_ClearQueuedAudio(adev);
            SDL_PauseAudioDevice(adev,0);
            native_pause_audio_active=1;
        }
        if(SDL_GetQueuedAudioSize(adev)<4096u) {
            int16_t samples[512];
            md_pause_fm_test_render(samples,256,2);
            SDL_QueueAudio(adev,samples,(Uint32)sizeof samples);
        }
    } else if(native_pause_audio_active) {
        md_pause_fm_test_stop();
        SDL_ClearQueuedAudio(adev);
        SDL_PauseAudioDevice(adev,1);
        native_pause_audio_active=0;
    }
}

'''


def ensure_sdl_headers(source: str) -> str:
    if "#include <sys/stat.h>" not in source:
        source=once(source,'#include <math.h>\n','#include <math.h>\n#include <sys/stat.h>\n',"level builder mkdir header")
    if "#include <direct.h>" not in source:
        source=once(source,'#include <sys/stat.h>\n','#include <sys/stat.h>\n#ifdef _WIN32\n#include <direct.h>\n#endif\n',"Windows level builder mkdir header")
    return source

def patch_harness(project: Path) -> None:
    path=project/"runtime"/"harness.c"
    s=path.read_text(encoding="utf-8-sig")
    anchor="int md_infinite_continues_enabled = 0;"
    if "void md_copy_main_ram(uint8_t *dst)" not in s:
        if s.count(anchor)!=1:
            raise RuntimeError("Cannot locate custom runtime RAM export anchor.")
        helper=r"""
void md_copy_main_ram(uint8_t *dst) {
    if(!dst)return;
    for(unsigned i=0;i<0x10000u;i++)dst[i]=ram[i];
}
"""
        s=s.replace(anchor,anchor+"\n"+helper,1)
    if "void md_copy_cpu_state(void *dst, uint32_t bytes)" not in s:
        marker="void md_copy_main_ram(uint8_t *dst) {\n    if(!dst)return;\n    for(unsigned i=0;i<0x10000u;i++)dst[i]=ram[i];\n}"
        if s.count(marker)!=1:
            raise RuntimeError("Cannot locate RAM snapshot helper for CPU-state instrumentation.")
        helper=r"""
uint32_t md_cpu_state_size(void) { return (uint32_t)sizeof(M68K); }
void md_copy_cpu_state(void *dst, uint32_t bytes) {
    if(!dst)return;
    memset(dst,0,bytes);
    if(CPU && bytes>=sizeof *CPU)memcpy(dst,CPU,sizeof *CPU);
}
"""
        s=s.replace(marker,marker+"\n"+helper,1)
    path.write_text(s,encoding="utf-8")

def patch_sdl(project: Path) -> None:
    path=project/"runtime"/"sdl_main.c"
    s=path.read_text(encoding="utf-8-sig")
    s=ensure_sdl_headers(s)
    if "static void render_native_extras(void)" in s:
        print("Native Extras pages already installed.")
        return
    # Add the persistent custom flags beside the native menu state globals.
    anchor="static uint32_t native_menu_last_move = 0;"
    if anchor not in s: raise RuntimeError("Cannot locate native menu global state.")
    s=once(s,anchor,anchor+"\n"+CUSTOM_GLOBALS,"custom menu state globals")

    # Pause main menu now exposes Extras and retains all prior entries.
    pause_render=r'''static void render_native_pause_main(void) {
    int W=vdp.width?vdp.width:320,H=vdp.height?vdp.height:224;
    int x=8,y=7,w=W-16,h=H-14;
    native_menu_rect(x,y,w,h,0x6A,0x74,0x88,255);
    native_menu_rect(x+2,y+2,w-4,h-4,0x08,0x0D,0x17,255);
    native_menu_rect(x+4,y+4,w-8,h-8,0x1A,0x22,0x2E,176);
    for(int i=0;i<w-12;i++) {
        int t=i*255/(w-13);
        native_menu_rect(x+6+i,y+6,1,20,
            (uint8_t)(105+150*t/255),(uint8_t)(8+118*t/255),(uint8_t)(18+18*t/255),255);
    }
    native_menu_rect(x+6,y+26,w-12,2,0xE8,0xA8,0x46,255);
    native_pause_draw_text(x+16,y+12,"MISSION PAUSED",0xFFF0C8);
    native_pause_draw_text(x+w-112,y+12,"BREN MCGUIRE",0xFFF0C8);
    const int rx[4]={x+7,x+w-12,x+7,x+w-12};
    const int ry[4]={y+7,y+7,y+h-12,y+h-12};
    for(int i=0;i<4;i++) {
        native_menu_rect(rx[i],ry[i],5,5,0xB6,0xC0,0xCE,255);
        native_menu_rect(rx[i]+1,ry[i]+1,3,3,0x34,0x3B,0x48,255);
    }
    for(int i=0;i<4;i++) {
        int on=((native_pause_anim_ticks/12u+i*3u)&1u)!=0;
        native_menu_rect(x+w-32+i*6,y+9,4,4,on?0xF4:0x65,on?0x28:0x18,on?0xDA:0x47,255);
    }
    /* Every destination opens inside this redesigned pause UI. The older
       Options overlay is not used as a nested menu. */
    static const char *items[]={"RESUME MISSION","VIDEO SETTINGS","AUDIO SETTINGS",
        "CONTROLLER SETUP","CONTROLS","ACHIEVEMENTS","SUIT STATUS ARSENAL",
        "OPTIONS SOUND TEST","ABORT RESTART STAGE","QUIT TO TITLE SCREEN","QUIT GAME"};
    for(int i=0;i<11;i++) {
        int iy=y+36+i*14;
        if(i==native_menu_sel) {
            native_menu_rect(x+10,iy-2,174,12,0x9C,0x0A,0x7B,190);
            native_menu_rect(x+12,iy-1,170,10,0x24,0x0F,0x2C,245);
            native_menu_rect(x+10,iy-2,2,12,0xF0,0x26,0xD8,255);
        }
        native_pause_draw_text(x+20,iy,items[i],i==native_menu_sel?0xFFF0D0:0xC4CFDA);
    }
    uint8_t ram_snapshot[0x10000];md_copy_main_ram(ram_snapshot);
    unsigned energy=((unsigned)ram_snapshot[0xBF20]<<8)|ram_snapshot[0xBF21];
    if(energy>0x40)energy=0x40;
    if(W>=300) {
        int bx=x+186,by=y+42,bw=w-198;
        native_menu_rect(bx,by,bw,85,0x05,0x08,0x11,255);
        native_menu_rect(bx,by,bw,1,0x9D,0x18,0x83,255);
        native_pause_draw_text(bx+8,by+8,"SUIT STATUS",0xEDB5E8);
        native_pause_draw_text(bx+8,by+25,"ENERGY",0xDCE5EF);
        native_menu_rect(bx+8,by+39,bw-16,8,0x3A,0x30,0x44,255);
        if(energy)native_menu_rect(bx+8,by+39,(bw-16)*(int)energy/0x40,8,0xE9,0xA5,0x25,255);
        native_pause_draw_text(bx+8,by+54,"MISSION LIVE",0xA9B5C6);
        native_menu_rect(bx+8,by+69,bw-16,1,0xB7,0x1D,0x9D,255);
        native_pause_draw_text(bx+8,by+76,"FM READY",0xC7B0D0);
    }
    native_pause_draw_text(x+16,y+h-17,"ARROWS SELECT  ENTER OK  ESC BACK",0xAAB8C7);
}'''
    s=replace_function(s,"static void render_native_pause_main(void)",pause_render,"pause menu Extras row")

    pause_proc=r'''static void proc_pause_main(SDL_Event *e) {
    const int n=11;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP:native_menu_sel=(native_menu_sel+n-1)%n;break;
        case SDLK_DOWN:native_menu_sel=(native_menu_sel+1)%n;break;
        case SDLK_RETURN:case SDLK_x:goto confirm;
        case SDLK_ESCAPE:native_menu_state=0;break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+n-1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A)goto confirm;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B)native_menu_state=0;
    }
    return;
confirm:
    switch(native_menu_sel) {
    case 0:native_menu_state=0;break;
    case 1:native_menu_state=18;native_menu_sel=0;break; /* Video Settings */
    case 2:native_menu_state=19;native_menu_sel=0;break; /* Audio Settings */
    case 3:native_menu_state=20;native_menu_sel=0;break; /* Controller Setup */
    case 4:native_menu_state=21;native_menu_sel=0;break; /* Controls */
    case 5:native_menu_state=22;native_menu_sel=0;break; /* Achievements */
    case 6:native_menu_state=15;native_menu_sel=0;break;
    case 7:native_menu_state=16;native_menu_sel=0;native_pause_apply_control_config();break;
    case 8:native_pause_enter_confirm(0);break;
    case 9:native_pause_enter_confirm(1);break;
    case 10:native_pause_enter_confirm(2);break;
    }
}'''
    s=replace_function(s,"static void proc_pause_main(SDL_Event *e)",pause_proc,"pause menu Extras action")

    # Put page functions after the pause backdrop is declared, but before menu present/event helpers.
    anchor="static int native_menu_resume_guard=0;"
    s=once(s,anchor,anchor+"\n"+CUSTOM_PAGES,"Extras/Cheats/Modern/Saves/Level Builder pages")

    # Extend VDP framebuffer menu drawing dispatch.
    s=once(s,"    case 7: render_native_controller_options(); break;",
        "    case 7: render_native_controller_options(); break;\n"
        "    case 8: render_native_extras(); break;\n"
        "    case 9: render_native_toggle_page(9); break;\n"
        "    case 10: render_native_saves(); break;\n"
        "    case 11: render_native_level_builder(); break;\n"
        "    case 12: render_native_toggle_page(12); break;\n"
        "    case 13: render_native_title_game_options(); break;\n"
        "    case 14: render_native_area_map(); break;\n"
        "    case 15: render_native_suit_status(); break;\n"
        "    case 16: render_native_pause_options(); break;\n"
        "    case 17: render_native_pause_confirm(); break;\n"
        "    case 18: render_native_pause_video_settings(); break;\n"
        "    case 19: render_native_pause_audio_settings(); break;\n"
        "    case 20: render_native_pause_controller_setup(); break;\n"
        "    case 21: render_native_pause_controls(); break;\n"
        "    case 22: render_native_pause_achievements(); break;",
        "native Extras page render dispatch")

    s=once(s,"md_live_mask = (native_menu_state==0 && !native_menu_resume_guard) ? readpad() : 0;\n    native_menu_resume_guard=0;",
           "if(!native_custom_cfg_loaded)native_custom_load_config();\n    native_title_menu_update();\n    md_live_mask = (native_menu_state==0 && !native_menu_resume_guard && !native_title_input_block) ? readpad() : 0;\n    native_menu_resume_guard=0;",
           "install title-screen menu and gate original input for custom entries")

    # Route the new page states.
    s=once(s,"    else if(native_menu_state==7)proc_native_controller_options(e);",
        "    else if(native_menu_state==7)proc_native_controller_options(e);\n"
        "    else if(native_menu_state==8)proc_native_extras(e);\n"
        "    else if(native_menu_state==9)proc_native_toggle_page(e,9);\n"
        "    else if(native_menu_state==10)proc_native_saves(e);\n"
        "    else if(native_menu_state==11)proc_native_level_builder(e);\n"
        "    else if(native_menu_state==12)proc_native_toggle_page(e,12);\n"
        "    else if(native_menu_state==13)proc_native_title_game_options(e);\n"
        "    else if(native_menu_state==14)proc_native_area_map(e);\n"
        "    else if(native_menu_state==15)proc_native_suit_status(e);\n"
        "    else if(native_menu_state==16)proc_native_pause_options(e);\n"
        "    else if(native_menu_state==17)proc_native_pause_confirm(e);\n"
        "    else if(native_menu_state==18)proc_native_pause_video_settings(e);\n"
        "    else if(native_menu_state==19)proc_native_pause_audio_settings(e);\n"
        "    else if(native_menu_state==20)proc_native_pause_controller_setup(e);\n"
        "    else if(native_menu_state==21)proc_native_pause_info_back(e);\n"
        "    else if(native_menu_state==22)proc_native_pause_info_back(e);",
        "native Extras event routing")

    # Allow an Extras entry from the original GAME OPTIONS menu, while preserving the original screen.
    title_event=r'''
        if(e.type==SDL_KEYDOWN && !e.key.repeat && e.key.keysym.sym==SDLK_F8) {
            if(reborn_title_scene_visible()) native_menu_dump_snapshot("title");
            else if(reborn_game_options_visible()) native_menu_dump_snapshot("options");
            else native_menu_dump_snapshot("other");
            continue;
        }

        /* The map is available only in Modern Mode and only when the gameplay HUD is present. */
        if(native_menu_state==0 && native_game_level_modern && native_modern_map &&
           e.type==SDL_KEYDOWN && !e.key.repeat && e.key.keysym.sym==SDLK_m &&
           native_title_gameplay_hud_visible()) {
            native_menu_state=14;
            native_menu_pause_loop();
            continue;
        }

        if(native_menu_state==0 && native_title_menu_scene_visible()) {
            if(e.type==SDL_KEYDOWN && !e.key.repeat) {
                switch(e.key.keysym.sym) {
                case SDLK_UP:
                    if(native_title_menu_selection==1) {
                        native_title_menu_selection=0;
                    } else if(native_title_menu_selection>=2) {
                        native_title_menu_selection--;
                        native_title_menu_sfx(0);
                        if(native_title_menu_selection==1)native_title_transition_guard=1;
                        continue;
                    } else continue;
                    break;
                case SDLK_DOWN:
                    if(native_title_menu_selection==0) {
                        native_title_menu_selection=1;
                    } else if(native_title_menu_selection==1) {
                        native_title_menu_selection=2;
                        native_title_transition_guard=1;
                        native_title_menu_sfx(0);
                        continue;
                    } else if(native_title_menu_selection<5) {
                        native_title_menu_selection++;
                        native_title_menu_sfx(0);
                        continue;
                    } else continue;
                    break;
                case SDLK_RETURN:case SDLK_x:
                    if(native_title_menu_selection>=2) {
                        native_title_menu_sfx(1);
                        native_title_open_selected();
                        continue;
                    }
                    break; /* vanilla START/OPTIONS confirmation remains with the cartridge */
                case SDLK_ESCAPE:
                    if(native_title_menu_selection>=2) {
                        native_title_menu_selection=1;
                        native_title_transition_guard=1;
                        native_title_menu_sfx(0);
                        continue;
                    }
                    break;
                }
            }
            if(e.type==SDL_CONTROLLERBUTTONDOWN) {
                if(e.cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP) {
                    if(native_title_menu_selection==1)native_title_menu_selection=0;
                    else if(native_title_menu_selection>=2) {
                        native_title_menu_selection--;
                        native_title_menu_sfx(0);
                        if(native_title_menu_selection==1)native_title_transition_guard=1;
                        continue;
                    } else continue;
                }
                if(e.cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN) {
                    if(native_title_menu_selection==0)native_title_menu_selection=1;
                    else if(native_title_menu_selection==1) {
                        native_title_menu_selection=2;
                        native_title_transition_guard=1;
                        native_title_menu_sfx(0);
                        continue;
                    } else if(native_title_menu_selection<5) {
                        native_title_menu_selection++;
                        native_title_menu_sfx(0);
                        continue;
                    } else continue;
                }
                if(e.cbutton.button==SDL_CONTROLLER_BUTTON_A ||
                   e.cbutton.button==SDL_CONTROLLER_BUTTON_START) {
                    if(native_title_menu_selection>=2) {
                        native_title_menu_sfx(1);
                        native_title_open_selected();
                        continue;
                    }
                    break;
                }
                if(e.cbutton.button==SDL_CONTROLLER_BUTTON_B &&
                   native_title_menu_selection>=2) {
                    native_title_menu_selection=1;
                    native_title_transition_guard=1;
                    continue;
                }
            }
        }
'''

    global_anchor="        /* global hotkeys (always active) */"
    s=once(s,global_anchor,title_event+"\n"+global_anchor,"title-screen Extras entry")

    # Compose after the recompiled game has rendered its VDP frame, but before shade().
    hook_start=s.find("void md_frame_hook(void)")
    if hook_start<0:
        raise RuntimeError("Could not locate md_frame_hook for title framebuffer composition.")
    hook_brace=s.find("{",hook_start)
    depth=0
    hook_end=-1
    for i in range(hook_brace,len(s)):
        if s[i]=="{": depth+=1
        elif s[i]=="}":
            depth-=1
            if depth==0:
                hook_end=i+1
                break
    if hook_end<0:
        raise RuntimeError("Could not isolate md_frame_hook.")
    hook=s[hook_start:hook_end]
    if "native_title_compose_frame();" not in hook:
        shade=re.search(r"shade\s*\(\s*w\s*,\s*h\s*\)\s*;",hook)
        if not shade:
            raise RuntimeError("Could not locate shade(w,h) in md_frame_hook.")
        at=shade.start()
        hook=hook[:at]+"native_title_compose_frame(); native_modern_apply_frame_features(); "+hook[at:]
        s=s[:hook_start]+hook+s[hook_end:]

    # Title-screen updates and first-run settings load run before md_live_mask.
    frame_anchor="    native_menu_pause_loop();"
    if s.count(frame_anchor)<1:
        raise RuntimeError("Could not locate the native pause frame hook.")

    s=once(s,"    memcpy(native_pause_backdrop,vdp.fb,sizeof native_pause_backdrop);",
           "    if(native_menu_state==13 && native_title_options_backdrop_valid) {\n"
           "        memcpy(native_pause_backdrop,native_title_options_backdrop,sizeof native_pause_backdrop);\n"
           "        native_title_options_backdrop_valid=0;\n"
           "    } else {\n"
           "        memcpy(native_pause_backdrop,vdp.fb,sizeof native_pause_backdrop);\n"
           "    }",
           "freeze Game Options over captured title frame")

    sync_anchor="    native_menu_resume_guard=0;"
    if sync_anchor in s:
        s=once(s,sync_anchor,sync_anchor+"\n    if(native_menu_state==0)md_apply_custom_gameplay_options();",
               "apply custom gameplay modifiers")
    else:
        raise RuntimeError("Could not locate custom gameplay frame boundary hook.")
    # Match the original VDP menu's cool-blue selected treatment, not the old gold accent.
    s=s.replace("0xFF,0xAE,0x1F","0x00,0x48,0xFC")
    s=once(s,
        '    else if(native_menu_state==7)snprintf(hint,sizeof hint,"LEFT/RIGHT REBIND  ESC BACK");',
        '    else if(native_menu_state==7)snprintf(hint,sizeof hint,"LEFT/RIGHT REBIND  ESC BACK");\n'
        '    else if(native_menu_state==13)snprintf(hint,sizeof hint,"ARROWS SELECT  ENTER OK  EXIT");',
        "native Game Options EXIT hint")
    s=once(s,
        "    draw_str(x,y,hint,hint_scale,0x99,0xB4,0xC8);",
        "    if(native_menu_state!=1 && native_menu_state<15)draw_str(x,y,hint,hint_scale,0x99,0xB4,0xC8);",
        "hide generic footer on full-screen title Game Options page")
    # Add the game-native subpages, pause animation and sound-test pumping.
    s=once(s,"static void native_menu_draw_frame(const uint32_t *backdrop) {",
           "static void native_menu_draw_frame(const uint32_t *backdrop) {\n    native_pause_anim_ticks++;",
           "pause animation tick")
    s=once(s,"        while(SDL_PollEvent(&e))native_menu_route_event(&e);",
           "        while(SDL_PollEvent(&e))native_menu_route_event(&e);\n        native_pause_audio_pump();",
           "pause FM sound-test pump")
    s=once(s,
           "    memcpy(vdp.fb,native_pause_backdrop,sizeof native_pause_backdrop);\n"
           "    if(adev&&pause_audio)SDL_PauseAudioDevice(adev,0);\n"
           "    native_menu_resume_guard=1;",
           "    native_pause_audio_pump();\n"
           "    if(native_pause_request_title) {\n"
           "        native_pause_request_title=0;\n"
           "        if(md_save_slot_exists(5) && md_load_slot(5)) {\n"
           "            native_pause_skip_backdrop_restore=1;\n"
           "            native_title_scene_active=0; native_title_compose_enabled=0; native_title_checkpoint_saved=1;\n"
           "        } else {\n"
           "            native_pause_skip_backdrop_restore=0;\n"
           "            native_pause_no_checkpoint=1; native_menu_state=1; native_menu_sel=9;\n"
           "            SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR,\n"
           "                \"Mega Turrican Reborn\",\n"
           "                \"The branded title checkpoint could not be restored. The mission has not been reset.\",NULL);\n"
           "        }\n"
           "    }\n"
           "    if(!native_pause_skip_backdrop_restore)memcpy(vdp.fb,native_pause_backdrop,sizeof native_pause_backdrop);\n"
           "    native_pause_skip_backdrop_restore=0;\n"
           "    if(adev&&pause_audio)SDL_PauseAudioDevice(adev,0);\n"
           "    native_menu_resume_guard=1;",
           "pause checkpoint/title transition restore")
    path.write_text(s,encoding="utf-8")

def main() -> int:
    if len(sys.argv)!=2: raise SystemExit("usage: patch-custom-game-menus.py PROJECT_ROOT")
    root=Path(sys.argv[1]).resolve()
    patch_harness(root)
    patch_sdl(root)
    print("Installed native-font title buttons, Vanilla/Modern Game Options, and title-entry access to Level Builder, Cheats, and Saves; kept the original cartridge OPTIONS menu vanilla.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
