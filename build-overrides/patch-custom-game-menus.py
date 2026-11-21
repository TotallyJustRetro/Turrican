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
/* Reborn Extras: stored beside the portable game, separate from launcher config. */
static int native_extras_parent=1;
static int native_game_level_modern=0;
static int native_cheat_energy=0, native_cheat_lives=0, native_cheat_timer=0;
static int native_modern_lives=0, native_modern_continues=0, native_modern_no_timer=0;
static int native_custom_cfg_loaded=0;
static int native_save_selection=0;
static int native_editor_x=12, native_editor_y=10, native_editor_tile=1;

extern void md_set_custom_gameplay_options(int,int,int,int,int,int);
extern void md_apply_custom_gameplay_options(void);
extern int md_save_slot(int slot);
extern int md_load_slot(int slot);
extern int md_save_slot_exists(int slot);
'''

CUSTOM_PAGES = r'''
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
            else {native_menu_state=8;native_menu_sel=state==9?2:1;}
            break;
        case SDLK_ESCAPE:native_menu_state=8;native_menu_sel=state==9?2:1;break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+n-1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if((e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT||e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT)&&native_menu_sel<3)
            native_toggle_option(state,native_menu_sel);
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A) {
            if(native_menu_sel<3)native_toggle_option(state,native_menu_sel);
            else {native_menu_state=8;native_menu_sel=state==9?2:1;}
        }
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B){native_menu_state=8;native_menu_sel=state==9?2:1;}
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
        case SDLK_ESCAPE:native_menu_state=8;native_menu_sel=3;break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel+n-1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A)goto confirm;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B){native_menu_state=8;native_menu_sel=3;}
    }
    return;
confirm:
    if(native_menu_sel==6){native_menu_state=8;native_menu_sel=3;return;}
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
    draw_str(4,(vdp.height?vdp.height:224)-5,"TILEMAP ONLY - COLLISION AND OBJECTS NOT EDITED",1,0x99,0xB4,0xC8);
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
        case SDLK_ESCAPE:native_menu_state=8;native_menu_sel=4;break;
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
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B){native_menu_state=8;native_menu_sel=4;}
    }
}
'''

def patch_sdl(project: Path) -> None:
    path=project/"runtime"/"sdl_main.c"
    s=path.read_text(encoding="utf-8-sig")
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
        if(reborn_game_options_visible() && e.type==SDL_KEYDOWN && !e.key.repeat &&
           e.key.keysym.sym==SDLK_F6) {
            native_extras_parent=0; native_menu_state=8; native_menu_sel=0;
            continue;
        }
        if(reborn_game_options_visible() && e.type==SDL_CONTROLLERBUTTONDOWN &&
           e.cbutton.button==SDL_CONTROLLER_BUTTON_X) {
            native_extras_parent=0; native_menu_state=8; native_menu_sel=0;
            continue;
        }
'''
    global_anchor="        /* global hotkeys (always active) */"
    s=once(s,global_anchor,title_event+"\n"+global_anchor,"title-screen Extras entry")

    # Load/save custom flags and apply gameplay modifiers at the emulated frame boundary.
    frame_anchor="    native_menu_pause_loop();"
    s=once(s,frame_anchor,"    if(!native_custom_cfg_loaded)native_custom_load_config();\n"+frame_anchor,
           "load persistent Extras options")
    title_draw=r'''
    if(reborn_game_options_visible()) {
        int W=vdp.width?vdp.width:320, H=vdp.height?vdp.height:224;
        char mode[40];
        snprintf(mode,sizeof mode,"GAME LEVEL: %s",native_game_level_modern?"MODERN":"ORIGINAL");
        draw_str((W-str_w(mode,1))/2,H*28/100,mode,1,0xFF,0xAE,0x1F);
        const char *extra="EXTRAS  [F6 / X]";
        draw_str((W-str_w(extra,1))/2,H*79/100,extra,1,0xFF,0xAE,0x1F);
    }
'''
    after_title="    reborn_title_update();"
    s=once(s,after_title,after_title+"\n"+title_draw,
           "draw title Options Extras entry")
    sync_anchor="    native_menu_resume_guard=0;"
    if sync_anchor in s:
        s=once(s,sync_anchor,sync_anchor+"\n    if(native_menu_state==0)md_apply_custom_gameplay_options();",
               "apply custom gameplay modifiers")
    else:
        raise RuntimeError("Could not locate custom gameplay frame boundary hook.")
    path.write_text(s,encoding="utf-8",newline="\n")

def main() -> int:
    if len(sys.argv)!=2: raise SystemExit("usage: patch-custom-game-menus.py PROJECT_ROOT")
    patch_sdl(Path(sys.argv[1]).resolve())
    print("Installed native Extras, Modern Options, Cheats, full save slots, and tilemap editor pages.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
