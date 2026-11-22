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
static int native_modern_lives=0, native_modern_continues=0, native_modern_no_timer=0;
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

static int reborn_game_options_visible(void);
static int reborn_title_scene_visible(void);

extern void md_set_custom_gameplay_options(int,int,int,int,int,int);
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
    return red[0]>12 && red[1]>8 && red[2]>12;
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
    if(native_title_gameplay_hud_visible())return 0;
    return native_title_tile_row_matches(16,13,start_tiles,sizeof start_tiles/sizeof start_tiles[0]) &&
           native_title_tile_row_matches(18,12,options_tiles,sizeof options_tiles/sizeof options_tiles[0]) &&
           native_title_tile_row_matches(22,10,copyright_year,sizeof copyright_year/sizeof copyright_year[0]) &&
           native_title_tile_row_matches(23,3,published_by,sizeof published_by/sizeof published_by[0]) &&
           native_title_tile_row_matches(24,10,licensed,sizeof licensed/sizeof licensed[0]) &&
           native_title_tile_row_matches(25,5,sega,sizeof sega/sizeof sega[0]);
}
static int native_title_text_width(const char *s) {
    int n=(int)strlen(s);
    return n>0 ? n*9-1 : 0; /* native 8x8 glyph plus one pixel tracking */
}
static uint32_t native_title_cram_rgb(int palette,unsigned index) {
    uint16_t color=vdp.cram[(palette&3)*16+(index&15u)];
    int r=(color>>1)&7, g=(color>>5)&7, b=(color>>9)&7;
    return ((uint32_t)(r*255/7)<<16)|((uint32_t)(g*255/7)<<8)|(uint32_t)(b*255/7);
}
static void native_title_draw_text_at(int x,int y,const char *s,int selected,int blink_on) {
    int palette=(selected && blink_on)?2:1; /* original active red / inactive pale-blue palettes */
    int W=vdp.width?vdp.width:320, H=vdp.height?vdp.height:224;
    for(int i=0;s[i];i++) {
        uint16_t tile=native_options_font_tile(s[i]);
        if(s[i]!=' ') {
            for(int sy=0;sy<8;sy++) {
                int py=y+sy;
                if(py<0 || py>=H)continue;
                uint32_t *row=&vdp.fb[py*320];
                for(int sx=0;sx<8;sx++) {
                    int px=x+i*9+sx;
                    if(px<0 || px>=W)continue;
                    uint8_t packed=vdp.vram[(size_t)tile*32u+(size_t)sy*4u+(size_t)(sx>>1)];
                    unsigned index=(sx&1)?(packed&15u):(packed>>4);
                    if(index)row[px]=native_title_cram_rgb(palette,index);
                }
            }
        }
    }
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

    /* Clear only the menu strip beneath REBORN. Preserve the cartridge's
       copyright lines at Window Plane rows 22-25 (pixels 176-207). */
    int clear_top=(H*465/1000)+20;
    if(clear_top<124)clear_top=124;
    if(clear_top>174)clear_top=174;
    for(int y=clear_top;y<175;y++) {
        uint32_t *row=&vdp.fb[y*320];
        for(int x=0;x<W;x++)row[x]=0;
    }

    int blink_on=(native_title_blink_ticks%120u)<60u;
    int left_center=W*26/100;
    int right_center=W*74/100;
    if(!native_title_page_mode) {
        native_title_draw_text_column("START",left_center,134,native_title_menu_selection==0,blink_on);
        native_title_draw_text_column("OPTIONS",right_center,134,native_title_menu_selection==1,blink_on);
        native_title_draw_text_column("GAME OPTIONS",left_center,148,native_title_menu_selection==2,blink_on);
        native_title_draw_text_column("LEVEL BUILDER",right_center,148,native_title_menu_selection==3,blink_on);
        native_title_draw_text_column("CHEATS",left_center,162,native_title_menu_selection==4,blink_on);
        native_title_draw_text_column("SAVES",right_center,162,native_title_menu_selection==5,blink_on);
        return;
    }

    native_title_draw_text_center("GAME OPTIONS",134,0,blink_on);
    native_title_draw_text_column("VANILLA GAME",W*32/100,148,native_title_game_options_focus==0,blink_on);
    native_title_draw_text_column("MODERN",W*74/100,148,native_title_game_options_focus==1,blink_on);
    if(native_game_level_modern) {
        char lives[20],continues[20],timer[24];
        snprintf(lives,sizeof lives,"LIVES %s",native_modern_lives?"ON":"OFF");
        snprintf(continues,sizeof continues,"CONT %s",native_modern_continues?"ON":"OFF");
        snprintf(timer,sizeof timer,"NO TIME %s",native_modern_no_timer?"ON":"OFF");
        const char *toggles[]={lives,continues,timer};
        int widths[3],total=14;
        for(int i=0;i<3;i++){widths[i]=native_title_text_width(toggles[i]);total+=widths[i];}
        int x=(W-total)/2;
        for(int i=0;i<3;i++) {
            native_title_draw_text_at(x,162,toggles[i],
                native_title_game_options_focus==i+2,blink_on);
            x+=widths[i]+7;
        }
    }
}
static void native_title_open_selected(void) {
    native_extras_parent=0;
    native_menu_sel=0;
    if(native_title_menu_selection==2) {
        native_title_page_mode=1;
        native_title_game_options_focus=native_game_level_modern?1:0;
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
        native_game_level_modern && native_modern_lives,
        native_game_level_modern && native_modern_continues,
        native_game_level_modern && native_modern_no_timer);
}
static void native_custom_save_config(void) {
    FILE *f=fopen("custom-game-options.ini.tmp","w");
    if(!f)return;
    fprintf(f,"game_level=%d\ncheat_energy=%d\ncheat_lives=%d\ncheat_timer=%d\n"
              "modern_lives=%d\nmodern_continues=%d\nmodern_no_timer=%d\n",
        native_game_level_modern,native_cheat_energy,native_cheat_lives,native_cheat_timer,
        native_modern_lives,native_modern_continues,native_modern_no_timer);
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
            else if(!strcmp(line,"modern_lives"))native_modern_lives=!!v;
            else if(!strcmp(line,"modern_continues"))native_modern_continues=!!v;
            else if(!strcmp(line,"modern_no_timer"))native_modern_no_timer=!!v;
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
        if(item==0)native_modern_lives^=1;
        else if(item==1)native_modern_continues^=1;
        else if(item==2)native_modern_no_timer^=1;
    }
    native_custom_save_config();
}
static void render_native_toggle_page(int state) {
    const char *title=state==9?"CHEATS":"MODERN OPTIONS";
    const char *labels[4]={"INFINITE ENERGY","INFINITE LIVES","NO TIMER","BACK"};
    if(state==12) {
        labels[0]="INFINITE LIVES";
        labels[1]="INFINITE CONTINUES";
        labels[2]="NO TIMER";
    }
    int pw=234,ph=144,px,py;
    native_menu_panel(pw,ph,&px,&py);
    native_menu_title(px+(pw-str_w(title,2))/2,py+8,title,2);
    for(int i=0;i<4;i++) {
        char row[56];
        if(i==3)snprintf(row,sizeof row,"BACK");
        else {
            int on=state==9?(i==0?native_cheat_energy:i==1?native_cheat_lives:native_cheat_timer):
                (i==0?native_modern_lives:i==1?native_modern_continues:native_modern_no_timer);
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
    int pw=246,ph=188,px,py; native_menu_panel(pw,ph,&px,&py);
    native_menu_title(px+(pw-str_w("SAVE SLOTS",2))/2,py+7,"SAVE SLOTS",2);
    for(int i=0;i<7;i++) {
        char row[64];
        if(i<6) {
            int slot=i/2+1,save=(i%2)==0;
            snprintf(row,sizeof row,"%s SLOT %d  %s",save?"SAVE":"LOAD",slot,
                     md_save_slot_exists(slot)?"SAVED":"EMPTY");
        } else snprintf(row,sizeof row,"BACK");
        native_menu_item(px+10,py+30+i*20,row,i==native_menu_sel,2);
    }
    native_menu_title(px+10,py+174,"LOAD REQUIRES SAME ROM",1);
}
static void proc_native_saves(SDL_Event *e) {
    const int n=7;
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
    if(native_menu_sel==6){native_custom_page_back(3);return;}
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
    path.write_text(s,encoding="utf-8",newline="\n")

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
    static const char *items[]={"RESUME GAME","OPTIONS","EXTRAS","CONTROLS","ACHIEVEMENTS","QUIT GAME"};
    int n=6, scale=2;
    int pw=202,ph=n*22+30;
    int px,py; native_menu_panel(pw,ph,&px,&py);
    native_menu_title(px+(pw-str_w("PAUSED",scale+1))/2,py+8,"PAUSED",scale+1);
    for(int i=0;i<n;i++)
        native_menu_item(px+(pw-str_w(items[i],scale))/2,py+34+i*22,items[i],i==native_menu_sel,scale);
}'''
    s=replace_function(s,"static void render_native_pause_main(void)",pause_render,"pause menu Extras row")

    pause_proc=r'''static void proc_pause_main(SDL_Event *e) {
    int n=6;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP: native_menu_sel=(native_menu_sel-1+n)%n; break;
        case SDLK_DOWN: native_menu_sel=(native_menu_sel+1)%n; break;
        case SDLK_RETURN: case SDLK_x: goto confirm;
        case SDLK_ESCAPE: native_menu_state=0; break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel-1+n)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A||e->cbutton.button==SDL_CONTROLLER_BUTTON_START)goto confirm;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B)native_menu_state=0;
    }
    return;
confirm:
    switch(native_menu_sel) {
    case 0:native_menu_state=0;break;
    case 1:native_menu_state=6;native_menu_sel=0;break;
    case 2:native_extras_parent=1;native_menu_state=8;native_menu_sel=0;break;
    case 3:native_menu_state=4;native_menu_sel=0;break;
    case 4:native_menu_state=5;native_menu_sel=0;break;
    case 5:exit(0);
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
        "    case 12: render_native_toggle_page(12); break;",
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
        "    else if(native_menu_state==12)proc_native_toggle_page(e,12);",
        "native Extras event routing")

    # Allow an Extras entry from the original GAME OPTIONS menu, while preserving the original screen.
    title_event=r'''
        if(e.type==SDL_KEYDOWN && !e.key.repeat && e.key.keysym.sym==SDLK_F8) {
            if(reborn_title_scene_visible()) native_menu_dump_snapshot("title");
            else if(reborn_game_options_visible()) native_menu_dump_snapshot("options");
            else native_menu_dump_snapshot("other");
            continue;
        }

        if(native_menu_state==0 && native_title_menu_scene_visible()) {
            if(native_title_page_mode) {
                if(e.type==SDL_KEYDOWN && !e.key.repeat) {
                    switch(e.key.keysym.sym) {
                    case SDLK_UP:
                        if(native_title_game_options_focus>=2)native_title_game_options_focus=1;
                        else native_title_game_options_focus=0;
                        break;
                    case SDLK_DOWN:
                        if(native_title_game_options_focus==0)native_title_game_options_focus=1;
                        else if(native_title_game_options_focus==1 && native_game_level_modern)
                            native_title_game_options_focus=2;
                        break;
                    case SDLK_LEFT:
                        if(native_title_game_options_focus>=2)
                            native_title_game_options_focus=2+(native_title_game_options_focus-2+2)%3;
                        else native_title_game_options_focus=1-native_title_game_options_focus;
                        break;
                    case SDLK_RIGHT:
                        if(native_title_game_options_focus>=2)
                            native_title_game_options_focus=2+(native_title_game_options_focus-1+3)%3;
                        else native_title_game_options_focus=1-native_title_game_options_focus;
                        break;
                    case SDLK_RETURN: case SDLK_x:
                        if(native_title_game_options_focus==0) {
                            native_game_level_modern=0;
                            native_custom_save_config();
                            native_title_game_options_focus=0;
                        } else if(native_title_game_options_focus==1) {
                            native_game_level_modern=1;
                            native_custom_save_config();
                            native_title_game_options_focus=2;
                        } else {
                            native_toggle_option(12,native_title_game_options_focus-2);
                        }
                        break;
                    case SDLK_ESCAPE:
                        native_title_page_mode=0;
                        native_title_game_options_focus=native_game_level_modern?1:0;
                        break;
                    }
                    continue;
                }
                if(e.type==SDL_CONTROLLERBUTTONDOWN) {
                    if(e.cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP) {
                        if(native_title_game_options_focus>=2)native_title_game_options_focus=1;
                        else native_title_game_options_focus=0;
                    }
                    if(e.cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN) {
                        if(native_title_game_options_focus==0)native_title_game_options_focus=1;
                        else if(native_title_game_options_focus==1 && native_game_level_modern)
                            native_title_game_options_focus=2;
                    }
                    if(e.cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT) {
                        if(native_title_game_options_focus>=2)
                            native_title_game_options_focus=2+(native_title_game_options_focus-2+2)%3;
                        else native_title_game_options_focus=1-native_title_game_options_focus;
                    }
                    if(e.cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT) {
                        if(native_title_game_options_focus>=2)
                            native_title_game_options_focus=2+(native_title_game_options_focus-1+3)%3;
                        else native_title_game_options_focus=1-native_title_game_options_focus;
                    }
                    if(e.cbutton.button==SDL_CONTROLLER_BUTTON_A) {
                        if(native_title_game_options_focus==0) {
                            native_game_level_modern=0;
                            native_custom_save_config();
                            native_title_game_options_focus=0;
                        } else if(native_title_game_options_focus==1) {
                            native_game_level_modern=1;
                            native_custom_save_config();
                            native_title_game_options_focus=2;
                        } else {
                            native_toggle_option(12,native_title_game_options_focus-2);
                        }
                    }
                    if(e.cbutton.button==SDL_CONTROLLER_BUTTON_B) {
                        native_title_page_mode=0;
                        native_title_game_options_focus=native_game_level_modern?1:0;
                    }
                    continue;
                }
            } else {
                if(e.type==SDL_KEYDOWN && !e.key.repeat) {
                    switch(e.key.keysym.sym) {
                    case SDLK_UP:
                        if(native_title_menu_selection==1) {
                            native_title_menu_selection=0; /* original OPTIONS -> START */
                        } else if(native_title_menu_selection>=2) {
                            native_title_menu_selection--;
                            if(native_title_menu_selection==1)native_title_transition_guard=1;
                            continue;
                        } else {
                            continue;
                        }
                        break;
                    case SDLK_DOWN:
                        if(native_title_menu_selection==0) {
                            native_title_menu_selection=1; /* original START -> OPTIONS */
                        } else if(native_title_menu_selection==1) {
                            native_title_menu_selection=2;
                            native_title_transition_guard=1;
                            continue;
                        } else if(native_title_menu_selection<5) {
                            native_title_menu_selection++;
                            continue;
                        } else {
                            continue;
                        }
                        break;
                    case SDLK_RETURN: case SDLK_x:
                        if(native_title_menu_selection>=2) {
                            native_title_open_selected();
                            continue;
                        }
                        break; /* vanilla START/OPTIONS confirm stays with the cartridge */
                    case SDLK_ESCAPE:
                        if(native_title_menu_selection>=2) {
                            native_title_menu_selection=1;
                            native_title_transition_guard=1;
                            continue;
                        }
                        break;
                    }
                }
                if(e.type==SDL_CONTROLLERBUTTONDOWN) {
                    if(e.cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP) {
                        if(native_title_menu_selection==1) {
                            native_title_menu_selection=0;
                        } else if(native_title_menu_selection>=2) {
                            native_title_menu_selection--;
                            if(native_title_menu_selection==1)native_title_transition_guard=1;
                            continue;
                        } else {
                            continue;
                        }
                    }
                    if(e.cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN) {
                        if(native_title_menu_selection==0) {
                            native_title_menu_selection=1;
                        } else if(native_title_menu_selection==1) {
                            native_title_menu_selection=2;
                            native_title_transition_guard=1;
                            continue;
                        } else if(native_title_menu_selection<5) {
                            native_title_menu_selection++;
                            continue;
                        } else {
                            continue;
                        }
                    }
                    if(e.cbutton.button==SDL_CONTROLLER_BUTTON_A ||
                       e.cbutton.button==SDL_CONTROLLER_BUTTON_START) {
                        if(native_title_menu_selection>=2) {
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
        hook=hook[:at]+"native_title_compose_frame(); "+hook[at:]
        s=s[:hook_start]+hook+s[hook_end:]

    # Title-screen updates and first-run settings load run before md_live_mask.
    frame_anchor="    native_menu_pause_loop();"
    if s.count(frame_anchor)!=1:
        raise RuntimeError("Could not locate the native pause frame hook.")

    sync_anchor="    native_menu_resume_guard=0;"
    if sync_anchor in s:
        s=once(s,sync_anchor,sync_anchor+"\n    if(native_menu_state==0)md_apply_custom_gameplay_options();",
               "apply custom gameplay modifiers")
    else:
        raise RuntimeError("Could not locate custom gameplay frame boundary hook.")
    # Match the original VDP menu's cool-blue selected treatment, not the old gold accent.
    s=s.replace("0xFF,0xAE,0x1F","0x00,0x48,0xFC")
    path.write_text(s,encoding="utf-8",newline="\n")

def main() -> int:
    if len(sys.argv)!=2: raise SystemExit("usage: patch-custom-game-menus.py PROJECT_ROOT")
    root=Path(sys.argv[1]).resolve()
    patch_harness(root)
    patch_sdl(root)
    print("Installed native-font title buttons, Vanilla/Modern Game Options, and title-entry access to Level Builder, Cheats, and Saves; kept the original cartridge OPTIONS menu vanilla.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
