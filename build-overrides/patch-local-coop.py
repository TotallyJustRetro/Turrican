#!/usr/bin/env python3
"""Add an opt-in second local player using Mega Turrican's own player update/render routines."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path.cwd()
RECOMP=ROOT/"recomp_gen.c"
SDL=ROOT/"runtime"/"sdl_main.c"

for p in (RECOMP,SDL):
    if not p.is_file():
        raise SystemExit(f"local co-op patch: required file missing: {p}")

def once(src: str, old: str, new: str, label: str) -> str:
    n=src.count(old)
    if n!=1:
        raise SystemExit(f"local co-op patch: {label}: expected one match, found {n}")
    return src.replace(old,new,1)

def func_span(src: str, pattern: str, label: str):
    m=re.search(pattern,src)
    if not m:
        raise SystemExit(f"local co-op patch: {label} function not found")
    start=m.start()
    brace=src.find("{",m.end())
    if brace<0:
        raise SystemExit(f"local co-op patch: {label} function has no body")
    depth=0; state="code"; esc=False; i=brace
    while i<len(src):
        ch=src[i]; nxt=src[i+1] if i+1<len(src) else ""
        if state=="line":
            if ch=="\n": state="code"
        elif state=="block":
            if ch=="*" and nxt=="/": state="code"; i+=1
        elif state in ("str","char"):
            if esc: esc=False
            elif ch=="\\": esc=True
            elif (state=="str" and ch=='"') or (state=="char" and ch=="'"): state="code"
        else:
            if ch=="/" and nxt=="/": state="line"; i+=1
            elif ch=="/" and nxt=="*": state="block"; i+=1
            elif ch=='"': state="str"
            elif ch=="'": state="char"
            elif ch=="{": depth+=1
            elif ch=="}":
                depth-=1
                if depth==0: return start,i+1
        i+=1
    raise SystemExit(f"local co-op patch: unterminated {label} function")

# A. Add an independent shadow copy of the player's native RAM context.
# The actual player logic touches $FFBC70-$FFBD26 and uses the shared stage,
# camera, object pool and renderer queue outside that range. The input bytes
# are remapped from P2's already-polled Genesis port into the native player
# routine's expected $FFBC90/$FFBC91 locations for the duration of its call.
r=RECOMP.read_text(encoding="utf-8-sig")
decls="""extern int md_local_coop_enabled;
extern int md_player2_connected;
"""
if "extern int md_local_coop_enabled;" not in r:
    m=re.search(r"(?m)^#include [^\n]+\n",r)
    if not m:
        raise SystemExit("local co-op patch: generated recomp include section not found")
    r=r[:m.end()]+decls+r[m.end():]

a,b=func_span(r,r"(?m)^static\s+void\s+f_156A\s*\(\s*M68K\s*\*\s*c\s*\)(?=\s*\{)","f_156A")
block=r[a:b]
if "coop_p2_player_state" not in block:
    sig=re.search(r"static\s+void\s+f_156A\s*\(\s*M68K\s*\*\s*c\s*\)\s*\{",block)
    if not sig:
        raise SystemExit("local co-op patch: f_156A declaration could not be anchored")
    local_decls="""
  /* Opt-in P2 shadow context. The shared render output and world/object state
     stay native; only the main player-local RAM window is swapped. */
  static uint8_t coop_p2_player_state[0xB7];
  static int coop_p2_player_initialized=0;
  M68K coop_player_call_entry;
  int coop_player_call_entry_valid=0;
"""
    block=block[:sig.end()]+local_decls+block[sig.end():]

    render_marker="L_165C: { RT_POLL(0x165C);"
    if block.count(render_marker)!=1:
        raise SystemExit("local co-op patch: f_156A player-render insertion point not unique")
    render_code=r"""
    if(!md_local_coop_enabled) {
        coop_p2_player_initialized=0;
    } else if(md_player2_connected) {
        uint8_t coop_p1_ram[0xB7];
        if(!coop_p2_player_initialized) {
            for(unsigned int i=0;i<0xB7u;i++)
                coop_p2_player_state[i]=(uint8_t)RD8(0xFFFFBC70u+i);
            /* Start beside P1, keeping both current and previous X in sync. */
            uint16_t x=(uint16_t)(((uint16_t)coop_p2_player_state[0xAE]<<8)|
                                  coop_p2_player_state[0xAF]);
            int16_t delta=(x<0x109u)?32:-32;
            int32_t nx=(int32_t)x+delta;
            if(nx<0x20)nx=0x20;
            if(nx>0x128)nx=0x128;
            delta=(int16_t)(nx-(int32_t)x);
            x=(uint16_t)nx;
            coop_p2_player_state[0xAE]=(uint8_t)(x>>8);
            coop_p2_player_state[0xAF]=(uint8_t)x;
            uint16_t oldx=(uint16_t)(((uint16_t)coop_p2_player_state[0x4C]<<8)|
                                     coop_p2_player_state[0x4D]);
            oldx=(uint16_t)(oldx+delta);
            coop_p2_player_state[0x4C]=(uint8_t)(oldx>>8);
            coop_p2_player_state[0x4D]=(uint8_t)oldx;
            coop_p2_player_initialized=1;
        }
        for(unsigned int i=0;i<0xB7u;i++)
            coop_p1_ram[i]=(uint8_t)RD8(0xFFFFBC70u+i);
        M68K coop_render_cpu=*c;
        for(unsigned int i=0;i<0xB7u;i++)
            WR8(0xFFFFBC70u+i,coop_p2_player_state[i]);
        {
            uint32_t _r=0x165Cu;
            uint32_t _t=0x5DB2u;
            A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r;
            rt_call_addr(c,_t);
            rt_sp--;
            if(c->ret!=_r && !rt_fix_ret(c,_r)) {
                coop_p2_player_initialized=0;
            } else {
                /* Append was accepted; preserve P2 state after its draw pass. */
                for(unsigned int i=0;i<0xB7u;i++)
                    coop_p2_player_state[i]=(uint8_t)RD8(0xFFFFBC70u+i);
            }
            for(unsigned int i=0;i<0xB7u;i++)
                WR8(0xFFFFBC70u+i,coop_p1_ram[i]);
            *c=coop_render_cpu;
        }
        /* f_5DB2 appends P2's native multi-part sprite to the shared render queue. */
        for(unsigned int i=0;i<0xB7u;i++)
            coop_p2_player_state[i]=(uint8_t)RD8(0xFFFFBC70u+i);
        for(unsigned int i=0;i<0xB7u;i++)
            WR8(0xFFFFBC70u+i,coop_p1_ram[i]);
        *c=coop_render_cpu;
    }
    """
    block=block.replace(render_marker,render_marker+render_code,1)

    # Save the correct callback entry register context for the second invocation.
    load_callback="uint32_t s=0xFFFFBC62u; uint32_t v=RD32(s); A(0)=v;"
    block=once(block,load_callback,
        load_callback+"\n    coop_player_call_entry_valid=(md_local_coop_enabled && md_player2_connected && coop_p2_player_initialized);\n    if(coop_player_call_entry_valid)coop_player_call_entry=*c;",
        "P1 callback context capture")

    update_marker="L_1662: { RT_POLL(0x1662);"
    if block.count(update_marker)!=1:
        raise SystemExit("local co-op patch: f_156A P2 update insertion point not unique")
    update_code=r"""
    if(coop_player_call_entry_valid) {
        uint8_t coop_p1_ram[0xB7];
        for(unsigned int i=0;i<0xB7u;i++)
            coop_p1_ram[i]=(uint8_t)RD8(0xFFFFBC70u+i);
        M68K coop_p1_after_cpu=*c;
        *c=coop_player_call_entry;
        for(unsigned int i=0;i<0xB7u;i++)
            WR8(0xFFFFBC70u+i,coop_p2_player_state[i]);
        /* The ROM polls port 2 into $FFBC92/$FFBC93; the player routine
           consumes the equivalent port-1 input bytes at $FFBC90/$FFBC91. */
        WR8(0xFFFFBC90u,RD8(0xFFFFBC92u));
        WR8(0xFFFFBC91u,RD8(0xFFFFBC93u));
        uint32_t _r=0x1662u;
        uint32_t _t=A(0);
        A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r;
        rt_call_addr(c,_t);
        rt_sp--;
        int coop_player_call_ok=(c->ret==_r || rt_fix_ret(c,_r));
        for(unsigned int i=0;i<0xB7u;i++)
            coop_p2_player_state[i]=(uint8_t)RD8(0xFFFFBC70u+i);
        for(unsigned int i=0;i<0xB7u;i++)
            WR8(0xFFFFBC70u+i,coop_p1_ram[i]);
        *c=coop_p1_after_cpu;
        coop_player_call_entry_valid=0;
        if(!coop_player_call_ok)coop_p2_player_initialized=0;
    }
    """
    block=block.replace(update_marker,update_marker+update_code,1)

    # Guard against accidentally patching a differently shaped player path.
    for required in (
        "coop_p2_player_state[0xB7]",
        "rt_call_addr(c,_t);",
        "WR8(0xFFFFBC90u,RD8(0xFFFFBC92u));",
        "uint32_t _t=0x5DB2u;",
        "uint32_t _t=A(0);"
    ):
        if required not in block:
            raise SystemExit("local co-op patch: expected P2 actor hook missing: "+required)
    r=r[:a]+block+r[b:]
RECOMP.write_text(r,encoding="utf-8")

# B. Make Multiplayer a persistent option on the existing in-game Game Options page.
s=SDL.read_text(encoding="utf-8-sig")
if "int md_local_coop_enabled=0;" not in s:
    raise SystemExit("local co-op patch: P2 runtime enable flag from controller patch is missing")

old_format='"modern_persistent_weapon=%d\\nmodern_checkpoints=%d\\nmodern_iframes=%d\\n"\n              "pause_rapid_fire=%d\\npause_control_config=%d\\n",'
new_format='"modern_persistent_weapon=%d\\nmodern_checkpoints=%d\\nmodern_iframes=%d\\nmultiplayer=%d\\n"\n              "pause_rapid_fire=%d\\npause_control_config=%d\\n",'
s=once(s,old_format,new_format,"save multiplayer setting")
old_args="native_modern_persistent_weapon,native_modern_checkpoints,native_modern_iframes,\n        native_pause_rapid_fire,native_pause_control_config);"
new_args="native_modern_persistent_weapon,native_modern_checkpoints,native_modern_iframes,\n        md_local_coop_enabled,native_pause_rapid_fire,native_pause_control_config);"
s=once(s,old_args,new_args,"multiplayer config value")
s=once(s,
    'else if(!strcmp(line,"modern_iframes"))native_modern_iframes=!!v;',
    'else if(!strcmp(line,"modern_iframes"))native_modern_iframes=!!v;\n            else if(!strcmp(line,"multiplayer"))md_local_coop_enabled=!!v;',
    "load multiplayer setting")

s=once(s,
    "if(next<0)next=8;\n    if(next>8)next=0;",
    "if(next<0)next=9;\n    if(next>9)next=0;",
    "Game Options navigation")
s=once(s,
    '    native_title_draw_text_center("EXIT",H*91/100,\n                                  native_title_game_options_focus==8,1);',
    '    native_title_draw_text_center(md_local_coop_enabled?"MULTIPLAYER: ON":"MULTIPLAYER: OFF",H*84/100,\n                                  native_title_game_options_focus==8,1);\n    native_title_draw_text_center("EXIT",H*93/100,\n                                  native_title_game_options_focus==9,1);',
    "Multiplayer option display")
s=once(s,
    "    case 8:\n        native_title_game_options_exit();\n        break;",
    "    case 8:\n        md_local_coop_enabled^=1;\n        native_custom_save_config();\n        break;\n    case 9:\n        native_title_game_options_exit();\n        break;",
    "Multiplayer option confirm")
s=once(s,
    "    } else if(native_title_game_options_focus>=2 && native_title_game_options_focus<=7) {\n        native_modern_option_toggle(native_title_game_options_focus-2);\n    }",
    "    } else if(native_title_game_options_focus>=2 && native_title_game_options_focus<=7) {\n        native_modern_option_toggle(native_title_game_options_focus-2);\n    } else if(native_title_game_options_focus==8) {\n        md_local_coop_enabled^=1;\n        native_custom_save_config();\n    }",
    "Multiplayer left/right toggle")
s=once(s,
    "int exiting=(native_title_game_options_focus==8);",
    "int exiting=(native_title_game_options_focus==9);",
    "Multiplayer exit focus")
for required in (
    "multiplayer=%d",
    'else if(!strcmp(line,"multiplayer"))md_local_coop_enabled=!!v;',
    'native_title_game_options_focus==8,1);',
    'native_title_game_options_focus==9,1);',
    "md_local_coop_enabled^=1;"
):
    if required not in s:
        raise SystemExit("local co-op patch: Game Options verification failed: "+required)
SDL.write_text(s,encoding="utf-8")

print("Installed opt-in Multiplayer setting, P2 native player-state shadow update, and P2 sprite render pass.")
