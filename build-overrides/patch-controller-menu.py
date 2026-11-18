#!/usr/bin/env python3
"""Patch the Mega Turrican launcher with a live Genesis pad and real SDL bindings."""
from __future__ import annotations
import re
import sys
from pathlib import Path

CSS = r'''
/* Genesis controller panel */
.controller-layout{display:grid;grid-template-columns:minmax(320px,1.15fr) minmax(270px,.85fr);gap:18px;align-items:start}
.controller-card,.binding-card{background:linear-gradient(155deg,#18202b,#0a0e14);border:1px solid #344153;border-radius:8px;padding:14px;box-shadow:inset 0 1px #ffffff0b,0 10px 28px #0005}
.controller-toolbar{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:8px}
.controller-toolbar select{min-width:180px;max-width:100%}
.genesis-pad{display:block;width:100%;max-width:620px;margin:0 auto;filter:drop-shadow(0 12px 12px #0008)}
.genesis-body{fill:url(#padBody);stroke:#414854;stroke-width:3}
.pad-detail{fill:#444a53;stroke:#222832;stroke-width:2}
.pad-dpad{fill:#242a32;stroke:#0b0d11;stroke-width:3;cursor:default}
.pad-dpad.active,.pad-face.active,.pad-start.active{fill:#ff9b20;stroke:#ffe09a;filter:drop-shadow(0 0 7px #ff9b20)}
.pad-face{fill:#b3282a;stroke:#481417;stroke-width:4;cursor:default}
.pad-start{fill:#303640;stroke:#10141a;stroke-width:3;cursor:default}
.pad-label{fill:#f6f0e7;font:900 17px 'Arial Black',sans-serif;text-anchor:middle;dominant-baseline:central;pointer-events:none}
.pad-label-dark{fill:#c4c9d0;font:700 10px 'Segoe UI',sans-serif;text-anchor:middle;dominant-baseline:central;pointer-events:none}
.pad-divider{height:1px;background:#354153;margin:12px 0}
.pad-status{font-size:12px;color:var(--mut);min-height:34px;line-height:1.45}
.pad-status strong{color:#f3b34b}
.pad-live{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;min-height:28px}
.pad-live span{border:1px solid #354153;border-radius:4px;padding:3px 7px;color:#8e9bae;font-size:11px;background:#080c12}
.pad-live span.on{background:#ff9b20;color:#111;border-color:#ffe09a;font-weight:800}
.binding-list{display:grid;gap:7px}
.binding-row{display:grid;grid-template-columns:76px minmax(0,1fr);gap:10px;align-items:center}
.binding-key{font:900 13px Impact,'Arial Black',sans-serif;letter-spacing:1.5px;color:#ffad3b}
.binding-row select{width:100%;min-width:0}
.binding-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px}
.binding-help{font-size:11px;color:var(--mut);line-height:1.45;margin:10px 0 0}
@media(max-width:760px){.controller-layout{grid-template-columns:1fr}.controller-card,.binding-card{padding:11px}}
'''

MARKUP = '''<section class="tab" id="t-ctl"><div class="controller-layout">
 <div class="controller-card">
  <div class="controller-toolbar"><div><h3 style="margin-bottom:2px">Live controller</h3><div class="mut" id="padName">Connect a controller and press any button…</div></div><select id="controllerSelect" aria-label="Active controller"><option value="-1">No controller detected</option></select></div>
  <svg class="genesis-pad" id="genesisPad" viewBox="0 0 700 310" role="img" aria-label="Three-button Sega Genesis controller with live input lights">
   <defs><linearGradient id="padBody" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c7c9ca"/><stop offset=".38" stop-color="#8e9399"/><stop offset="1" stop-color="#565c65"/></linearGradient><linearGradient id="padFace" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e34b4d"/><stop offset="1" stop-color="#8e171d"/></linearGradient></defs>
   <path class="genesis-body" d="M82 95 Q112 36 205 46 L493 46 Q588 36 618 95 L678 226 Q690 256 657 270 Q628 282 593 257 L535 220 Q350 251 165 220 L107 257 Q72 282 43 270 Q10 256 22 226 Z"/>
   <path class="pad-detail" d="M106 96 Q130 69 184 76 L229 84 L213 118 Q162 126 111 119 Z" opacity=".52"/><path class="pad-detail" d="M594 96 Q570 69 516 76 L471 84 L487 118 Q538 126 589 119 Z" opacity=".52"/>
   <g transform="translate(170 145)"><rect class="pad-dpad" data-action="up" x="-22" y="-57" width="44" height="54" rx="6"/><rect class="pad-dpad" data-action="down" x="-22" y="3" width="44" height="54" rx="6"/><rect class="pad-dpad" data-action="left" x="-57" y="-22" width="54" height="44" rx="6"/><rect class="pad-dpad" data-action="right" x="3" y="-22" width="54" height="44" rx="6"/><circle cx="0" cy="0" r="22" fill="#181d24" stroke="#090c10" stroke-width="4"/></g>
   <g transform="translate(363 183) rotate(-18)"><rect class="pad-start" data-action="start" x="-38" y="-13" width="76" height="26" rx="13"/><text class="pad-label-dark" x="0" y="1">START</text></g>
   <g transform="translate(530 145) rotate(-18)"><circle class="pad-face" data-action="a" cx="-60" cy="-9" r="29"/><circle class="pad-face" data-action="b" cx="0" cy="-9" r="29"/><circle class="pad-face" data-action="c" cx="60" cy="-9" r="29"/><text class="pad-label" x="-60" y="-8">A</text><text class="pad-label" x="0" y="-8">B</text><text class="pad-label" x="60" y="-8">C</text></g>
   <text x="350" y="86" class="pad-label-dark" style="font-size:12px;letter-spacing:4px">16-BIT · SEGA</text>
   <text x="350" y="102" class="pad-label-dark" style="font-size:9px;letter-spacing:2px">CONTROL PAD</text>
  </svg>
  <div class="pad-divider"></div>
  <div id="padStatus" class="pad-status">The highlighted buttons show the Genesis actions currently being pressed.</div>
  <div id="padLive" class="pad-live"><span>Waiting for controller input</span></div>
 </div>
 <div class="binding-card">
  <h3>Genesis button mapping</h3>
  <div class="mut" style="margin:-4px 0 12px">Choose which physical controller input triggers each Genesis control. Changes are saved and passed to the game when it launches.</div>
  <div id="map" class="binding-list"></div>
  <div class="binding-actions"><button class="b" id="resetPad" type="button">Restore Genesis defaults</button><span id="mapSaved" class="mut">Saved locally</span></div>
  <p class="binding-help">For DualSense: the default profile is D-pad directions, Square = A, Cross = B, Circle = C, Options = Start. You can remap any action. Left-stick directions are available too.</p>
 </div>
</div></section>'''

GAMEPAD_JS = r'''/* Genesis controller + live Gamepad API mapping */
const GENESIS_ACTIONS=[
 {key:"up",label:"Up",bit:1,def:11},
 {key:"down",label:"Down",bit:2,def:12},
 {key:"left",label:"Left",bit:4,def:13},
 {key:"right",label:"Right",bit:8,def:14},
 {key:"a",label:"A",bit:16,def:2},
 {key:"b",label:"B",bit:32,def:0},
 {key:"c",label:"C",bit:64,def:1},
 {key:"start",label:"Start",bit:128,def:6}
];
const PAD_OPTIONS=[
 [11,"D-pad Up"],[12,"D-pad Down"],[13,"D-pad Left"],[14,"D-pad Right"],
 [2,"Square / West"],[0,"Cross / South"],[1,"Circle / East"],[3,"Triangle / North"],
 [9,"L1 / Left bumper"],[10,"R1 / Right bumper"],[4,"Create / Back"],[6,"Options / Start"],
 [7,"L3 / Left-stick click"],[8,"R3 / Right-stick click"],[20,"Touchpad click"],
 [-1,"Left stick Up"],[-2,"Left stick Down"],[-3,"Left stick Left"],[-4,"Left stick Right"]
];
const BROWSER_BUTTON_FOR_SDL={0:0,1:1,2:2,3:3,4:8,6:9,7:10,8:11,9:4,10:5,11:12,12:13,13:14,14:15,20:17};
const DEFAULT_PAD_MAP=GENESIS_ACTIONS.map(x=>x.def);
if(!Array.isArray(S.padMap)||S.padMap.length!==8)S.padMap=DEFAULT_PAD_MAP.slice();
else S.padMap=S.padMap.map((x,i)=>Number.isInteger(Number(x))?Number(x):DEFAULT_PAD_MAP[i]);
let selectedGamepadIndex=-1,lastPadSignature="",livePad=null;
function savePadMap(){save();$("mapSaved").textContent="Saved locally ✓";}
function renderBindings(){
 const host=$("map");host.replaceChildren();
 GENESIS_ACTIONS.forEach((action,i)=>{
  const row=document.createElement("label");row.className="binding-row";
  const name=document.createElement("span");name.className="binding-key";name.textContent=action.label;
  const select=document.createElement("select");select.dataset.action=action.key;select.setAttribute("aria-label",action.label+" controller binding");
  PAD_OPTIONS.forEach(([value,label])=>{const option=document.createElement("option");option.value=String(value);option.textContent=label;select.append(option);});
  select.value=String(S.padMap[i]);
  if(!PAD_OPTIONS.some(x=>x[0]===S.padMap[i]))select.value=String(DEFAULT_PAD_MAP[i]);
  select.addEventListener("change",()=>{S.padMap[i]=Number(select.value);savePadMap();paintController();});
  row.append(name,select);host.append(row);
 });
}
$("resetPad").addEventListener("click",()=>{S.padMap=DEFAULT_PAD_MAP.slice();renderBindings();savePadMap();paintController();});
function getPads(){try{return [...(navigator.getGamepads?.()||[])].filter(Boolean);}catch(_){return [];}}
function refreshPadChoices(pads){
 const signature=pads.map(p=>p.index+":"+p.id).join("|");
 if(signature===lastPadSignature)return;
 lastPadSignature=signature;
 const select=$("controllerSelect"),previous=selectedGamepadIndex;
 select.replaceChildren();
 if(!pads.length){const option=document.createElement("option");option.value="-1";option.textContent="No controller detected";select.append(option);selectedGamepadIndex=-1;return;}
 pads.forEach((pad,n)=>{const option=document.createElement("option");option.value=String(pad.index);option.textContent=(n+1)+" · "+pad.id.slice(0,54);select.append(option);});
 selectedGamepadIndex=pads.some(p=>p.index===previous)?previous:pads[0].index;
 select.value=String(selectedGamepadIndex);
}
$("controllerSelect").addEventListener("change",()=>{selectedGamepadIndex=Number($("controllerSelect").value);paintController();});
function bindingPressed(pad,binding){
 if(!pad)return false;
 if(binding>=0){const index=BROWSER_BUTTON_FOR_SDL[binding];const b=index===undefined?null:pad.buttons[index];return !!(b&&(b.pressed||b.value>.55));}
 const x=pad.axes?.[0]||0,y=pad.axes?.[1]||0;
 if(binding===-1)return y<-.45;if(binding===-2)return y>.45;if(binding===-3)return x<-.45;if(binding===-4)return x>.45;
 return false;
}
function paintController(){
 const pads=getPads();refreshPadChoices(pads);
 livePad=pads.find(p=>p.index===selectedGamepadIndex)||null;
 const status=$("padName"),padStatus=$("padStatus"),live=$("padLive");
 document.querySelectorAll("[data-action]").forEach(el=>{
  const i=GENESIS_ACTIONS.findIndex(a=>a.key===el.dataset.action);
  const active=i>=0&&bindingPressed(livePad,S.padMap[i]);
  el.classList.toggle("active",active);
 });
 live.replaceChildren();
 if(!livePad){
  status.textContent="No controller detected";
  padStatus.textContent="Connect your controller by USB or Bluetooth, then press any button. Keyboard controls remain available in-game.";
  const span=document.createElement("span");span.textContent="Waiting for controller input";live.append(span);
  return;
 }
 status.textContent=livePad.id+(livePad.mapping==="standard"?" · standard mapping":" · browser-reported custom mapping");
 const pressed=[];
 livePad.buttons.forEach((button,index)=>{if(button&&(button.pressed||button.value>.65))pressed.push("Button "+index);});
 livePad.axes.forEach((axis,index)=>{if(Math.abs(axis)>.55)pressed.push("Axis "+index+": "+(axis<0?"−":"+"));});
 if(!pressed.length){const span=document.createElement("span");span.textContent="Controller connected · no input currently held";live.append(span);}
 else pressed.forEach(label=>{const span=document.createElement("span");span.className="on";span.textContent=label;live.append(span);});
 const active=GENESIS_ACTIONS.filter((action,i)=>bindingPressed(livePad,S.padMap[i])).map(x=>x.label);
 padStatus.innerHTML=active.length?"Live Genesis output: <strong>"+active.join(" · ")+"</strong>":"Controller connected. Press buttons or move the D-pad/stick to test the highlighted Genesis pad.";
}
(function controllerPoll(){paintController();requestAnimationFrame(controllerPoll);})();
window.addEventListener("gamepadconnected",()=>{lastPadSignature="";paintController();});
window.addEventListener("gamepaddisconnected",()=>{lastPadSignature="";paintController();});
renderBindings();
'''

SDL_READER = r'''static int readpad(void){
    int m = 0; const uint8_t *k = SDL_GetKeyboardState(NULL);
    if(k[SDL_SCANCODE_UP]) m |= B_U; if(k[SDL_SCANCODE_DOWN]) m |= B_D; if(k[SDL_SCANCODE_LEFT]) m |= B_L; if(k[SDL_SCANCODE_RIGHT]) m |= B_R;
    if(k[SDL_SCANCODE_Z]) m |= B_A; if(k[SDL_SCANCODE_X]) m |= B_B; if(k[SDL_SCANCODE_C]) m |= B_C; if(k[SDL_SCANCODE_RETURN]) m |= B_S;
    if(pad){
        static const int bits[8] = { B_U, B_D, B_L, B_R, B_A, B_B, B_C, B_S };
        int ax = SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_LEFTX);
        int ay = SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_LEFTY);
        for(int i = 0; i < 8; i++){
            int binding = pad_map[i], pressed = 0;
            if(binding >= 0 && binding < SDL_CONTROLLER_BUTTON_MAX)
                pressed = SDL_GameControllerGetButton(pad, (SDL_GameControllerButton)binding);
            else if(binding == -1) pressed = ay < -12000;
            else if(binding == -2) pressed = ay > 12000;
            else if(binding == -3) pressed = ax < -12000;
            else if(binding == -4) pressed = ax > 12000;
            if(pressed) m |= bits[i];
        }
    }
    return m;
}
'''

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)

def patch(project: Path) -> None:
    launcher = project / "launcher"
    index_path = launcher / "index.html"
    main_path = launcher / "main.js"
    sdl_path = project / "runtime" / "sdl_main.c"
    html = index_path.read_text(encoding="utf-8-sig")
    main = main_path.read_text(encoding="utf-8-sig")
    sdl = sdl_path.read_text(encoding="utf-8-sig")

    if 'id="genesisPad"' not in html:
        html = replace_once(html, "</style>", CSS + "\n</style>", "controller CSS insertion")
        old_markup = '''<section class="tab" id="t-ctl"><div class="grid">
 <div><h3>Controller</h3><div id="padName" class="mut">Press a button on your DualSense / any pad…</div><div class="pad" id="padBtns"></div>
  <p class="mut">PS5 DualSense is read through the standard Gamepad API (USB or Bluetooth). Native Windows build: use SDL3/SDL_GameController for rumble, gyro and adaptive triggers.</p></div>
 <div><h3>Genesis mapping</h3><table id="map"></table><p class="mut">Click a dropdown to remap. Keyboard defaults: arrows, Z/X/C, Enter.</p></div>
</div></section>'''
        html = replace_once(html, old_markup, MARKUP, "controller markup")
        pattern = re.compile(r"/\* gamepad \*/.*?requestAnimationFrame\(poll\)\}\)\(\);", re.S)
        html, n = pattern.subn(GAMEPAD_JS, html, count=1)
        if n != 1:
            raise RuntimeError(f"controller JavaScript replacement: expected one match, found {n}")
        index_path.write_text(html, encoding="utf-8")

    if "settings.padMap?.[0]" not in main:
        tick = chr(96)
        vsync_expr = "$" + "{" + "settings.vsync === false ? 0 : 1" + "}"
        background_expr = "$" + "{" + "settings.bgPath || ''" + "}"
        config_anchor = "    " + tick + "vsync=" + vsync_expr + tick + ",\n    " + tick + "background=" + background_expr + tick
        config_new = "\n".join([
            "    " + tick + "vsync=" + vsync_expr + tick + ",",
            "    " + tick + "pad_up=" + "$" + "{" + "Number(settings.padMap?.[0] ?? 11)" + "}" + tick + ",",
            "    " + tick + "pad_down=" + "$" + "{" + "Number(settings.padMap?.[1] ?? 12)" + "}" + tick + ",",
            "    " + tick + "pad_left=" + "$" + "{" + "Number(settings.padMap?.[2] ?? 13)" + "}" + tick + ",",
            "    " + tick + "pad_right=" + "$" + "{" + "Number(settings.padMap?.[3] ?? 14)" + "}" + tick + ",",
            "    " + tick + "pad_a=" + "$" + "{" + "Number(settings.padMap?.[4] ?? 2)" + "}" + tick + ",",
            "    " + tick + "pad_b=" + "$" + "{" + "Number(settings.padMap?.[5] ?? 0)" + "}" + tick + ",",
            "    " + tick + "pad_c=" + "$" + "{" + "Number(settings.padMap?.[6] ?? 1)" + "}" + tick + ",",
            "    " + tick + "pad_start=" + "$" + "{" + "Number(settings.padMap?.[7] ?? 6)" + "}" + tick + ",",
            "    " + tick + "background=" + background_expr + tick
        ])
        main = replace_once(main, config_anchor, config_new, "native controller config output")
        main_path.write_text(main, encoding="utf-8")

    if "static int pad_map[8]" not in sdl:
        cfg_end = '} cfg = { 0, 0, 1, 0, 0, 1, 1, 100, 35, "" };'
        sdl = replace_once(sdl, cfg_end, cfg_end + "\n\n/* SDL_GameController logical buttons; negative values select left-stick directions. */\nstatic int pad_map[8] = { 11, 12, 13, 14, 2, 0, 1, 6 };", "native controller defaults")
        cfg_anchor = 'else if(!strcmp(l, "scanline_strength")) cfg.scan_pct = atoi(v); else if(!strcmp(l, "background")) strncpy(cfg.bg, v, sizeof cfg.bg - 1);'
        cfg_new = '''else if(!strcmp(l, "scanline_strength")) cfg.scan_pct = atoi(v);
        else if(!strcmp(l, "pad_up")) pad_map[0] = atoi(v); else if(!strcmp(l, "pad_down")) pad_map[1] = atoi(v);
        else if(!strcmp(l, "pad_left")) pad_map[2] = atoi(v); else if(!strcmp(l, "pad_right")) pad_map[3] = atoi(v);
        else if(!strcmp(l, "pad_a")) pad_map[4] = atoi(v); else if(!strcmp(l, "pad_b")) pad_map[5] = atoi(v);
        else if(!strcmp(l, "pad_c")) pad_map[6] = atoi(v); else if(!strcmp(l, "pad_start")) pad_map[7] = atoi(v);
        else if(!strcmp(l, "background")) strncpy(cfg.bg, v, sizeof cfg.bg - 1);'''
        sdl = replace_once(sdl, cfg_anchor, cfg_new, "native controller config parser")
        readpad_pattern = re.compile(r"static int readpad\(void\)\{.*?\n\s*static void open_pad\(void\)\{", re.S)
        sdl, n = readpad_pattern.subn(SDL_READER + "\nstatic void open_pad(void){", sdl, count=1)
        if n != 1:
            raise RuntimeError(f"native SDL controller reader replacement: expected one match, found {n}")
        sdl_path.write_text(sdl, encoding="utf-8")

    print("Controller UI, live inputs, persistent mappings, and native SDL bindings are installed.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-controller-menu.py PROJECT_ROOT")
    patch(Path(sys.argv[1]).resolve())
