#!/usr/bin/env python3
"""Move pause/options presentation into the emulated Mega Drive framebuffer.

The pause menu is rendered into vdp.fb and presented through the normal VDP
texture/scaling path. The 68000/recompiled game is held at its frame hook while
the user is paused, so gameplay state does not keep advancing behind the menu.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path


def once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def replace_function(source: str, signature: str, replacement: str, label: str) -> str:
    start = source.find(signature)
    if start < 0:
        raise RuntimeError(f"{label}: function signature not found")
    brace = source.find("{", start)
    if brace < 0:
        raise RuntimeError(f"{label}: function body not found")
    depth = 0
    end = -1
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        raise RuntimeError(f"{label}: unterminated function")
    return source[:start] + replacement + source[end:]


NATIVE_RECT = r'''static void native_menu_rect(int x,int y,int w,int h,uint8_t r,uint8_t g,uint8_t b,uint8_t a) {
    int W=vdp.width?vdp.width:320;
    int H=vdp.height?vdp.height:224;
    if(w<=0||h<=0||a==0) return;
    int x0=x<0?0:x, y0=y<0?0:y;
    int x1=x+w, y1=y+h;
    if(x1>W)x1=W; if(y1>H)y1=H;
    if(x0>=x1||y0>=y1)return;
    for(int py=y0;py<y1;py++) {
        uint32_t *row=&vdp.fb[py*320];
        for(int px=x0;px<x1;px++) {
            uint32_t old=row[px];
            unsigned or=(old>>16)&255, og=(old>>8)&255, ob=old&255;
            unsigned nr=(or*(255-a)+(unsigned)r*a)/255;
            unsigned ng=(og*(255-a)+(unsigned)g*a)/255;
            unsigned nb=(ob*(255-a)+(unsigned)b*a)/255;
            row[px]=(nr<<16)|(ng<<8)|nb;
        }
    }
}'''

NATIVE_OPTIONS_ROOT = r'''
static void render_native_options_root(void) {
    static const char *items[]={"VIDEO OPTIONS","AUDIO OPTIONS","CONTROLLER SETUP","BACK"};
    int n=4,scale=2,pw=218,ph=n*24+38,px,py;
    native_menu_panel(pw,ph,&px,&py);
    native_menu_title(px+(pw-str_w("OPTIONS",scale))/2,py+8,"OPTIONS",scale);
    for(int i=0;i<n;i++)
        native_menu_item(px+12,py+34+i*24,items[i],i==native_menu_sel,scale);
}

static void proc_native_options_root(SDL_Event *e) {
    const int n=4;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP: native_menu_sel=(native_menu_sel-1+n)%n; break;
        case SDLK_DOWN: native_menu_sel=(native_menu_sel+1)%n; break;
        case SDLK_RETURN: case SDLK_x: goto confirm;
        case SDLK_ESCAPE: native_menu_state=1; native_menu_sel=1; break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP) native_menu_sel=(native_menu_sel-1+n)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN) native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A) goto confirm;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B) {native_menu_state=1;native_menu_sel=1;}
    }
    return;
confirm:
    switch(native_menu_sel) {
    case 0: native_menu_state=2; native_menu_sel=0; break;
    case 1: native_menu_state=3; native_menu_sel=0; break;
    case 2: native_menu_state=7; native_menu_sel=0; break;
    default: native_menu_state=1; native_menu_sel=1; break;
    }
}

static const int native_binding_cycle[]={
    12,13,14,15,0,1,2,3,4,5,6,7,8,9,10,11,-1,-2,-3,-4,-5,-6,-7,-8
};
static const int native_binding_count=(int)(sizeof native_binding_cycle/sizeof native_binding_cycle[0]);

static const char *native_binding_name(int b) {
    switch(b) {
    case 0:return "CROSS"; case 1:return "CIRCLE"; case 2:return "SQUARE"; case 3:return "TRIANGLE";
    case 4:return "L1"; case 5:return "R1"; case 6:return "L2"; case 7:return "R2";
    case 8:return "CREATE"; case 9:return "OPTIONS"; case 10:return "L3"; case 11:return "R3";
    case 12:return "DPAD UP"; case 13:return "DPAD DOWN"; case 14:return "DPAD LEFT"; case 15:return "DPAD RIGHT";
    case -1:return "LEFT STICK UP"; case -2:return "LEFT STICK DOWN";
    case -3:return "LEFT STICK LEFT"; case -4:return "LEFT STICK RIGHT";
    case -5:return "RIGHT STICK UP"; case -6:return "RIGHT STICK DOWN";
    case -7:return "RIGHT STICK LEFT"; case -8:return "RIGHT STICK RIGHT";
    default:return "UNASSIGNED";
    }
}

static void native_binding_step(int action,int direction) {
    int at=-1;
    for(int i=0;i<native_binding_count;i++)
        if(native_binding_cycle[i]==pad_map[action]) {at=i;break;}
    if(at<0)at=0;
    at=(at+native_binding_count+(direction>0?1:-1))%native_binding_count;
    pad_map[action]=native_binding_cycle[at];
    save_cfg();
}

static void render_native_controller_options(void) {
    static const char *actions[]={"UP","DOWN","LEFT","RIGHT","FIRE / A","JUMP / B","ROPE / C","START / PAUSE"};
    int n=11,scale=1,pw=244,ph=190,px,py;
    native_menu_panel(pw,ph,&px,&py);
    native_menu_title(px+(pw-str_w("CONTROLLER SETUP",2))/2,py+7,"CONTROLLER SETUP",2);
    for(int i=0;i<8;i++) {
        char line[64];
        snprintf(line,sizeof line,"%s  < %s >",actions[i],native_binding_name(pad_map[i]));
        native_menu_item(px+8,py+29+i*12,line,i==native_menu_sel,scale);
    }
    native_menu_item(px+8,py+29+8*12,"DUALSENSE PROFILE: WIP",native_menu_sel==8,scale);
    native_menu_item(px+8,py+29+9*12,"RESTORE GENESIS DEFAULTS",native_menu_sel==9,scale);
    native_menu_item(px+8,py+29+10*12,"BACK",native_menu_sel==10,scale);
    native_menu_rect(px+8,py+168,pw-16,1,0xA0,0xA0,0xA0,100);
    native_menu_title(px+10,py+174,"LEFT/RIGHT TO REBIND",1);
}

static void proc_native_controller_options(SDL_Event *e) {
    const int n=11;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat) {
        switch(e->key.keysym.sym) {
        case SDLK_UP: native_menu_sel=(native_menu_sel-1+n)%n; break;
        case SDLK_DOWN: native_menu_sel=(native_menu_sel+1)%n; break;
        case SDLK_LEFT: if(native_menu_sel<8)native_binding_step(native_menu_sel,-1); break;
        case SDLK_RIGHT: if(native_menu_sel<8)native_binding_step(native_menu_sel,+1); break;
        case SDLK_RETURN: case SDLK_x:
            if(native_menu_sel<8)native_binding_step(native_menu_sel,+1);
            else if(native_menu_sel==9) {
                static const int defaults[8]={12,13,14,15,2,0,1,9};
                for(int i=0;i<8;i++)pad_map[i]=defaults[i];
                save_cfg();
            } else if(native_menu_sel==10) {native_menu_state=6;native_menu_sel=2;}
            break;
        case SDLK_ESCAPE: native_menu_state=6; native_menu_sel=2; break;
        }
    }
    if(e->type==SDL_CONTROLLERBUTTONDOWN) {
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_UP)native_menu_sel=(native_menu_sel-1+n)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_DOWN)native_menu_sel=(native_menu_sel+1)%n;
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_LEFT&&native_menu_sel<8)native_binding_step(native_menu_sel,-1);
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_DPAD_RIGHT&&native_menu_sel<8)native_binding_step(native_menu_sel,+1);
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_A) {
            if(native_menu_sel<8)native_binding_step(native_menu_sel,+1);
            else if(native_menu_sel==9) {
                static const int defaults[8]={12,13,14,15,2,0,1,9};
                for(int i=0;i<8;i++)pad_map[i]=defaults[i];
                save_cfg();
            } else if(native_menu_sel==10) {native_menu_state=6;native_menu_sel=2;}
        }
        if(e->cbutton.button==SDL_CONTROLLER_BUTTON_B) {native_menu_state=6;native_menu_sel=2;}
    }
}
'''

PAUSE_LOOP = r'''
/* The game reaches this hook at its frame boundary. Holding here freezes the
 * emulated CPU/game state. The pause UI is written into the same VDP framebuffer
 * as the cartridge picture, then goes through the ordinary game presentation. */
static uint32_t native_pause_backdrop[320*240];
static int native_menu_resume_guard=0;

static void native_menu_present_frame(void) {
    int w=vdp.width?vdp.width:320, h=vdp.height?vdp.height:224;
    ws_update();
    int tw=w+g_ws_margin*2;
    if(!tex||texture_width!=tw)make_texture();
    shade(w,h);
    SDL_Rect src={0,0,tw,h};
    SDL_UpdateTexture(tex,NULL,outbuf,tw*4);
    int ww,wh;compute_dst(&ww,&wh);
    SDL_SetRenderDrawColor(ren,0,0,0,255);
    SDL_RenderClear(ren);
    if(bgtex)SDL_RenderCopy(ren,bgtex,NULL,NULL);
    SDL_RenderCopy(ren,tex,&src,&game_dst);
    SDL_RenderPresent(ren);
}

static void native_menu_draw_frame(const uint32_t *backdrop) {
    int w=vdp.width?vdp.width:320, h=vdp.height?vdp.height:224;
    memcpy(vdp.fb,backdrop,sizeof native_pause_backdrop);
    for(int y=0;y<h;y++) {
        uint32_t *row=&vdp.fb[y*320];
        for(int x=0;x<w;x++) {
            uint32_t p=row[x];
            row[x]=(((p>>16)&255)*150/255<<16)|
                   (((p>>8)&255)*150/255<<8)|
                   ((p&255)*150/255);
        }
    }
    switch(native_menu_state) {
    case 1: render_native_pause_main(); break;
    case 2: render_native_options_video(); break;
    case 3: render_native_options_audio(); break;
    case 4: render_native_controls_info(); break;
    case 5: render_native_achievements(); break;
    case 6: render_native_options_root(); break;
    case 7: render_native_controller_options(); break;
    }
    char hint[64];
    if(native_menu_state==1)snprintf(hint,sizeof hint,"UP/DN SELECT  ENTER OK  ESC RESUME");
    else if(native_menu_state==7)snprintf(hint,sizeof hint,"LEFT/RIGHT REBIND  ESC BACK");
    else snprintf(hint,sizeof hint,"ARROWS SELECT  ENTER OK  ESC BACK");
    int hint_scale=1;
    int y=h-10;
    int x=(w-str_w(hint,hint_scale))/2;
    if(x<2)x=2;
    draw_str(x,y,hint,hint_scale,0x99,0xB4,0xC8);
}

static void native_menu_route_event(SDL_Event *e) {
    if(e->type==SDL_QUIT)exit(0);
    if(e->type==SDL_CONTROLLERDEVICEADDED)open_pad();
    if(e->type==SDL_CONTROLLERDEVICEREMOVED&&pad){SDL_GameControllerClose(pad);pad=NULL;open_pad();}
    if(e->type==SDL_WINDOWEVENT&&e->window.event==SDL_WINDOWEVENT_RESIZED){ws_update();make_texture();}
    int start_press=0;
    if(e->type==SDL_KEYDOWN&&!e->key.repeat&&e->key.keysym.sym==SDLK_ESCAPE)start_press=1;
    if(e->type==SDL_CONTROLLERBUTTONDOWN&&e->cbutton.button==SDL_CONTROLLER_BUTTON_START)start_press=1;
    if(start_press) {
        if(native_menu_state==1){native_menu_state=0;return;}
        if(native_menu_state==6){native_menu_state=1;native_menu_sel=1;return;}
        if(native_menu_state==7){native_menu_state=6;native_menu_sel=2;return;}
        if(native_menu_state==2){native_menu_state=6;native_menu_sel=0;return;}
        if(native_menu_state==3){native_menu_state=6;native_menu_sel=1;return;}
        if(native_menu_state==4){native_menu_state=1;native_menu_sel=2;return;}
        if(native_menu_state==5){native_menu_state=1;native_menu_sel=3;return;}
    }
    if(native_menu_state==1)proc_pause_main(e);
    else if(native_menu_state==2)proc_options_video(e);
    else if(native_menu_state==3)proc_options_audio(e);
    else if(native_menu_state==4)proc_controls_info(e);
    else if(native_menu_state==5)proc_achievements(e);
    else if(native_menu_state==6)proc_native_options_root(e);
    else if(native_menu_state==7)proc_native_controller_options(e);
}

static void native_menu_pause_loop(void) {
    if(native_menu_state<=0)return;
    memcpy(native_pause_backdrop,vdp.fb,sizeof native_pause_backdrop);
    if(adev)SDL_PauseAudioDevice(adev,1);
    while(native_menu_state>0) {
        SDL_Event e;
        while(SDL_PollEvent(&e))native_menu_route_event(&e);
        if(native_menu_state>0) {
            native_menu_draw_frame(native_pause_backdrop);
            native_menu_present_frame();
            SDL_Delay(16);
        }
    }
    memcpy(vdp.fb,native_pause_backdrop,sizeof native_pause_backdrop);
    if(adev)SDL_PauseAudioDevice(adev,0);
    native_pause_resume_guard=1;
}
'''


def patch_sdl(project: Path) -> None:
    path=project/"runtime"/"sdl_main.c"
    s=path.read_text(encoding="utf-8-sig")

    if "static void native_menu_pause_loop(void)" in s:
        print("Native VDP pause/menu path already installed.")
        return

    # Rename the old terminology: the UI is no longer an SDL post-frame overlay.
    s=s.replace("overlay_state","native_menu_state")
    s=s.replace("overlay_sel","native_menu_sel")
    s=s.replace("overlay_last_move","native_menu_last_move")
    s=s.replace("overlay_panel","native_menu_panel")
    s=s.replace("overlay_item","native_menu_item")
    s=s.replace("overlay_title","native_menu_title")
    s=s.replace("overlay_blit_game","native_menu_blit_game")
    s=s.replace("render_pause_main","render_native_pause_main")
    s=s.replace("render_options_video","render_native_options_video")
    s=s.replace("render_options_audio","render_native_options_audio")
    s=s.replace("render_controls_info","render_native_controls_info")
    s=s.replace("render_achievements","render_native_achievements")
    s=s.replace("ov_rect","native_menu_rect")

    rect_old=r'''static void native_menu_rect(int x,int y,int w,int h,uint8_t r,uint8_t g,uint8_t b,uint8_t a) {
    SDL_SetRenderDrawColor(ren,r,g,b,a);
    SDL_Rect rc={x,y,w,h}; SDL_RenderFillRect(ren,&rc);
}'''
    s=once(s,rect_old,NATIVE_RECT,"framebuffer-native menu primitive")

    panel_old=r'''static void native_menu_panel(int pw,int ph,int *px,int *py) {
    int ww,wh; SDL_GetWindowSize(win,&ww,&wh);
    *px=(ww-pw)/2; *py=(wh-ph)/2;
    native_menu_rect(*px-4,*py-4,pw+8,ph+8, 0xFF,0xAE,0x1F,220);  /* gold border */
    native_menu_rect(*px,*py,pw,ph, 0x07,0x09,0x0D,230);            /* dark panel */
}'''
    panel_new=r'''static void native_menu_panel(int pw,int ph,int *px,int *py) {
    int ww=vdp.width?vdp.width:320,wh=vdp.height?vdp.height:224;
    *px=(ww-pw)/2; *py=(wh-ph)/2;
    native_menu_rect(*px-4,*py-4,pw+8,ph+8, 0xFF,0xAE,0x1F,220);
    native_menu_rect(*px,*py,pw,ph, 0x07,0x09,0x0D,230);
}'''
    s=once(s,panel_old,panel_new,"VDP-relative pause panel")

    # The Options item now opens an actual options root with Video, Audio and Controller.
    s=once(s,
        "case 1: native_menu_state=2; native_menu_sel=0; break;",
        "case 1: native_menu_state=6; native_menu_sel=0; break;",
        "native Options root entry")
    s=s.replace("static const char *items[]={\"RESUME GAME\",\"OPTIONS\",\"CONTROLS\",\"ACHIEVEMENTS\",\"QUIT GAME\"};",
                "static const char *items[]={\"RESUME GAME\",\"OPTIONS\",\"CONTROLS\",\"ACHIEVEMENTS\",\"QUIT GAME\"};")
    if "static void render_native_options_root(void)" not in s:
        anchor="/* ---- Render each native_menu_state ---- */"
        if anchor not in s:
            anchor="/* ---- Render each overlay state ---- */"
        s=once(s,anchor,anchor+"\n"+NATIVE_OPTIONS_ROOT,"native Options and controller screens")

    # Return from Video/Audio to the Options root rather than skipping the root.
    for signature, selection in [
        ("static void proc_options_video(SDL_Event *e)",0),
        ("static void proc_options_audio(SDL_Event *e)",1),
    ]:
        start=s.find(signature)
        if start<0: raise RuntimeError(f"Missing {signature}")
        brace=s.find("{",start); depth=0; end=-1
        for i in range(brace,len(s)):
            if s[i]=="{":depth+=1
            elif s[i]=="}":
                depth-=1
                if depth==0:end=i+1;break
        block=s[start:end]
        block=block.replace("native_menu_state=1; native_menu_sel=1;","native_menu_state=6; native_menu_sel="+str(selection)+";")
        block=block.replace("native_menu_state=1; native_menu_sel=1 }","native_menu_state=6; native_menu_sel="+str(selection)+" }")
        s=s[:start]+block+s[end:]

    # Insert controller configuration UI and the VDP pause-frame loop.
    anchor="/* ------------------------------------------------------------------ present */"
    if anchor not in s:
        raise RuntimeError("Could not find the VDP presentation section.")
    # Controller functions are placed before the presentation section; loop is after compute_dst.
    s=s.replace(anchor,NATIVE_OPTIONS_ROOT+anchor,1) if False else s
    # NATIVE_OPTIONS_ROOT contains the root renderer, but it must be declared after menu primitives.
    # Insert controller helpers directly before the presentation section.
    s=once(s,anchor,NATIVE_OPTIONS_ROOT+"\n"+anchor,"options root insertion")

    # Add the controller page and pause loop after compute_dst, where all presentation helpers exist.
    compute_end="game_dst.h=(int)dh;\n}"
    s=once(s,compute_end,compute_end+"\n"+NATIVE_OPTIONS_ROOT.split("static void render_native_options_root",1)[0]+PAUSE_LOOP,
           "native pause frame loop insertion")
    # The previous insertion above already installs options-root functions; remove duplicate from PAUSE_LOOP helper block.
    # Keep controller-page functions and loop; no duplicate options-root renderer.
    duplicate=NATIVE_OPTIONS_ROOT
    first=s.find(duplicate)
    second=s.find(duplicate,first+1)
    if second>=0:
        s=s[:second]+s[second+len(duplicate):]

    # Wire state 6/7 into the pause input and render dispatch.
    s=s.replace(
        "else if(native_menu_state==5)proc_native_achievements(&e);",
        "else if(native_menu_state==5)proc_native_achievements(&e);\n    else if(native_menu_state==6)proc_native_options_root(e);\n    else if(native_menu_state==7)proc_native_controller_options(e);"
    )
    # Ensure normal frame hook enters the blocking pause loop before game input is sampled.
    frame_anchor="    /* Reborn bumper runs once after the original Mega Turrican logo card. */"
    if frame_anchor not in s:
        frame_anchor="    /* Update the native title-only VDP sprite before the next emulated frame. */"
    if "native_menu_pause_loop();" not in s:
        s=once(s,frame_anchor,"    native_menu_pause_loop();\n\n"+frame_anchor,"native pause hook")

    # Remove the SDL post-frame overlay drawing completely. Menu pixels are already in vdp.fb.
    old_render=r'''    /* Draw overlay on top */
    if(native_menu_state>0) {
        SDL_SetRenderDrawBlendMode(ren,SDL_BLENDMODE_BLEND);
        native_menu_rect(0,0,ww,wh, 0,0,0, native_menu_state==1?160:120);
        switch(native_menu_state) {
        case 1: render_native_pause_main(); break;
        case 2: render_native_options_video(); break;
        case 3: render_native_options_audio(); break;
        case 4: render_native_controls_info(); break;
        case 5: render_native_achievements(); break;
        }
        /* hint bar at bottom */
        char hint[80];
        if(native_menu_state==1) snprintf(hint,sizeof hint,"UP/DN=SELECT  ENTER=CONFIRM  ESC=RESUME");
        else if(native_menu_state==2||native_menu_state==3) snprintf(hint,sizeof hint,"LT/RT=CHANGE  ESC/B=BACK");
        else snprintf(hint,sizeof hint,"ESC/B=BACK");
        draw_str((ww-str_w(hint,1))/2, wh-14, hint,1,0x55,0x66,0x77);
        SDL_SetRenderDrawBlendMode(ren,SDL_BLENDMODE_NONE);
    }
'''
    if old_render in s:
        s=once(s,old_render,"","remove SDL post-frame overlay")
    else:
        # Be strict: do not leave an SDL menu paint pass behind.
        if "Draw overlay on top" in s or "SDL_SetRenderDrawBlendMode(ren,SDL_BLENDMODE_BLEND)" in s:
            raise RuntimeError("Unrecognized SDL post-frame overlay block remains; refusing a partial migration.")

    # Use a one-frame input guard after returning from the blocking native pause.
    old_mask="md_live_mask = (native_menu_state==0 && !reborn_intro_active) ? readpad() : 0;"
    if old_mask not in s:
        old_mask="md_live_mask = (native_menu_state==0) ? readpad() : 0;"
    new_mask="md_live_mask = (native_menu_state==0 && !native_menu_resume_guard) ? readpad() : 0;\n    native_menu_resume_guard=0;"
    s=once(s,old_mask,new_mask,"resume input guard")
    if "native_menu_pause_loop();" not in s:
        raise RuntimeError("Native pause loop was not connected to md_frame_hook.")
    if "Draw overlay on top" in s:
        raise RuntimeError("SDL post-frame overlay code remains after migration.")
    path.write_text(s,encoding="utf-8",newline="\n")


def main() -> int:
    if len(sys.argv)!=2:
        print("usage: patch-native-game-menus.py PROJECT_ROOT",file=sys.stderr)
        return 2
    patch_sdl(Path(sys.argv[1]).resolve())
    print("Installed native VDP framebuffer pause UI, frame-boundary game freeze, Options root, controller remapping, and DualSense WIP status.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
