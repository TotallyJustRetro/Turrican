#!/usr/bin/env python3
"""Install a persistent, correctly mapped Genesis controller panel and SDL input path."""
from __future__ import annotations

import re
import sys
from pathlib import Path

CSS = r"""
/* User reference: rounded Genesis controller with circular D-pad and slanted three-button pod */
.controller-layout{display:grid;grid-template-columns:minmax(330px,1.12fr) minmax(285px,.88fr);gap:16px;align-items:start}
.controller-card,.binding-card{background:linear-gradient(155deg,#18202b,#0a0e14);border:1px solid #344153;border-radius:8px;padding:14px;box-shadow:inset 0 1px #ffffff0b,0 10px 28px #0005}
.controller-toolbar{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:8px}
.controller-toolbar select{min-width:175px;max-width:100%}
.genesis-pad{display:block;width:100%;max-width:650px;margin:0 auto;filter:drop-shadow(0 12px 12px #0008)}
.genesis-shell{fill:#f7fbfc;stroke:#08b5c6;stroke-width:5;stroke-linejoin:round}
.genesis-outline{fill:none;stroke:#08b5c6;stroke-width:4}
.genesis-dpad{fill:#f7fbfc;stroke:#08b5c6;stroke-width:4}
.genesis-face{fill:#f7fbfc;stroke:#08b5c6;stroke-width:4}
.genesis-start{fill:#f7fbfc;stroke:#08b5c6;stroke-width:4}
.genesis-cable{fill:#f7fbfc;stroke:#08b5c6;stroke-width:4}
.genesis-label{fill:#087e8d;font:800 18px 'Segoe UI',sans-serif;text-anchor:middle;dominant-baseline:central;pointer-events:none}
.pad-active{fill:#ffb23e!important;stroke:#ffdf9a!important;filter:drop-shadow(0 0 7px #ff9b20)}
.pad-live{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;min-height:28px}
.pad-live span{border:1px solid #354153;border-radius:4px;padding:3px 7px;color:#8e9bae;font-size:11px;background:#080c12}
.pad-live span.on{background:#ffb23e;color:#111;border-color:#ffe09a;font-weight:800}
.pad-status{font-size:12px;color:var(--mut);min-height:34px;line-height:1.45}
.pad-status strong{color:#f3b34b}
.pad-divider{height:1px;background:#354153;margin:12px 0}
.binding-list{display:grid;gap:7px}
.binding-row{display:grid;grid-template-columns:105px minmax(0,1fr);gap:10px;align-items:center}
.binding-key{font:900 12px Impact,'Arial Black',sans-serif;letter-spacing:1px;color:#ffad3b}
.binding-row select{width:100%;min-width:0}
.binding-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px}
.binding-help{font-size:11px;color:var(--mut);line-height:1.45;margin:10px 0 0}
@media(max-width:760px){.controller-layout{grid-template-columns:1fr}.controller-card,.binding-card{padding:11px}}
"""

MARKUP = '''<section class="tab" id="t-ctl"><div class="controller-layout">
 <div class="controller-card">
  <div class="controller-toolbar"><div><h3 style="margin-bottom:2px">Live Genesis controller</h3><div class="mut" id="padName">Connect a controller and press any button…</div></div><select id="controllerSelect" aria-label="Active controller"><option value="-1">No controller detected</option></select></div>
  <svg class="genesis-pad" id="genesisPad" viewBox="0 0 860 620" role="img" aria-label="Genesis three-button controller with live input indicators">
   <path class="genesis-cable" d="M420 22 H440 V58 H445 L451 118 H409 L415 58 H420 Z"/>
   <path class="genesis-shell" d="M430 118 C300 118 184 145 112 210 C52 266 52 366 82 435 C112 505 184 550 244 548 C292 547 299 508 330 458 C355 417 390 397 430 397 C470 397 505 417 530 458 C561 508 568 547 616 548 C676 550 748 505 778 435 C808 366 808 266 748 210 C676 145 560 118 430 118 Z"/>
   <circle class="genesis-outline" cx="255" cy="330" r="102"/>
   <circle class="genesis-outline" cx="255" cy="330" r="72"/>
   <g transform="translate(255 330)">
    <rect class="genesis-dpad" data-action="up" x="-18" y="-59" width="36" height="51" rx="7"/>
    <rect class="genesis-dpad" data-action="down" x="-18" y="8" width="36" height="51" rx="7"/>
    <rect class="genesis-dpad" data-action="left" x="-59" y="-18" width="51" height="36" rx="7"/>
    <rect class="genesis-dpad" data-action="right" x="8" y="-18" width="51" height="36" rx="7"/>
    <circle cx="0" cy="0" r="22" fill="#f7fbfc" stroke="#08b5c6" stroke-width="3"/>
   </g>
   <g transform="translate(605 345) rotate(-24)">
    <rect class="genesis-outline" x="-135" y="-76" width="270" height="152" rx="76"/>
    <rect class="genesis-outline" x="-119" y="-61" width="238" height="122" rx="61"/>
    <circle class="genesis-face" data-action="a" cx="-76" cy="0" r="34"/>
    <circle class="genesis-face" data-action="b" cx="0" cy="0" r="34"/>
    <circle class="genesis-face" data-action="c" cx="76" cy="0" r="34"/>
    <text class="genesis-label" x="-76" y="1">A</text><text class="genesis-label" x="0" y="1">B</text><text class="genesis-label" x="76" y="1">C</text>
   </g>
   <g transform="translate(565 205) rotate(-24)">
    <rect class="genesis-start" data-action="start" x="-43" y="-13" width="86" height="26" rx="13"/>
   </g>
   <text class="genesis-label" x="255" y="474" style="font-size:13px">D-PAD</text>
   <text class="genesis-label" x="605" y="475" style="font-size:13px">FIRE · JUMP · ROPE</text>
  </svg>
  <div class="pad-divider"></div>
  <div id="padStatus" class="pad-status">The turquoise controls light up when their mapped physical inputs are pressed.</div>
  <div id="padLive" class="pad-live"><span>Waiting for controller input</span></div>
 </div>
 <div class="binding-card">
  <h3>Game controls</h3>
  <div class="mut" style="margin:-4px 0 12px">These mappings are applied to the actual gamepad input in the native Windows core and saved to this PC.</div>
  <div id="map" class="binding-list"></div>
  <div class="binding-actions"><button class="b" id="resetPad" type="button">Restore Genesis defaults</button><span id="mapSaved" class="mut">Loading saved controls…</span></div>
  <p class="binding-help">Defaults: D-pad directions, Square = A / Fire, Cross = B / Jump, Circle = C / Rope, Options = Start / Pause. Left-stick directions and trigger buttons can also be assigned.</p>
 </div>
</div></section>'''

GAMEPAD_JS = r'''/* Genesis controller + live Gamepad API mapping */
const PAD_VERSION=3;
const GENESIS_ACTIONS=[
 {key:"up",label:"UP",def:12,action:"Move up"},
 {key:"down",label:"DOWN",def:13,action:"Move down"},
 {key:"left",label:"LEFT",def:14,action:"Move left"},
 {key:"right",label:"RIGHT",def:15,action:"Move right"},
 {key:"a",label:"A · FIRE",def:2,action:"Fire"},
 {key:"b",label:"B · JUMP",def:0,action:"Jump"},
 {key:"c",label:"C · ROPE",def:1,action:"Rope"},
 {key:"start",label:"START / PAUSE",def:9,action:"Pause"}
];
const PAD_OPTIONS=[
 [0,"South button · Cross"],[1,"East button · Circle"],[2,"West button · Square"],[3,"North button · Triangle"],
 [4,"L1 / Left bumper"],[5,"R1 / Right bumper"],[6,"L2 / Left trigger"],[7,"R2 / Right trigger"],
 [8,"Back / Create"],[9,"Start / Options"],[10,"L3 / Left-stick click"],[11,"R3 / Right-stick click"],
 [12,"D-pad Up"],[13,"D-pad Down"],[14,"D-pad Left"],[15,"D-pad Right"],
 [-1,"Left stick Up"],[-2,"Left stick Down"],[-3,"Left stick Left"],[-4,"Left stick Right"],
 [-5,"Right stick Up"],[-6,"Right stick Down"],[-7,"Right stick Left"],[-8,"Right stick Right"]
];
const DEFAULT_PAD_MAP=GENESIS_ACTIONS.map(x=>x.def);
let selectedGamepadIndex=-1,lastPadSignature="",livePad=null;
function validPadMap(v){return Array.isArray(v)&&v.length===8&&v.every(x=>Number.isInteger(Number(x))&&Number(x)>=-8&&Number(x)<=15);}
function savePadMap(){
 S.padMapVersion=PAD_VERSION;S.padMap=GENESIS_ACTIONS.map((_,i)=>Number(S.padMap[i]));
 save();
 $("mapSaved").textContent="Saving controls…";
 const payload={version:PAD_VERSION,padMap:S.padMap};
 if(window.GenesisSettings&&window.GenesisSettings.save){
  window.GenesisSettings.save(payload).then(result=>{
   $("mapSaved").textContent=result&&result.ok?"Saved on this PC ✓":"Saved in launcher session";
  }).catch(()=>{$("mapSaved").textContent="Saved in launcher session";});
 }else $("mapSaved").textContent="Saved in launcher session";
}
function renderBindings(){
 const host=$("map");host.replaceChildren();
 GENESIS_ACTIONS.forEach((action,i)=>{
  const row=document.createElement("label");row.className="binding-row";
  const name=document.createElement("span");name.className="binding-key";name.textContent=action.label;
  const select=document.createElement("select");select.dataset.action=action.key;select.setAttribute("aria-label",action.action+" controller input");
  PAD_OPTIONS.forEach(([value,label])=>{const option=document.createElement("option");option.value=String(value);option.textContent=label;select.append(option);});
  select.value=String(S.padMap[i]);
  if(!PAD_OPTIONS.some(x=>x[0]===S.padMap[i]))select.value=String(action.def);
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
 pads.forEach((pad,n)=>{const option=document.createElement("option");option.value=String(pad.index);option.textContent=(n+1)+" · "+pad.id.slice(0,58);select.append(option);});
 selectedGamepadIndex=pads.some(p=>p.index===previous)?previous:pads[0].index;
 select.value=String(selectedGamepadIndex);
}
$("controllerSelect").addEventListener("change",()=>{selectedGamepadIndex=Number($("controllerSelect").value);paintController();});
function readMappedInput(pad,binding){
 if(!pad)return false;
 if(binding>=0){const b=pad.buttons?.[binding];return !!(b&&(b.pressed||b.value>.55));}
 const axes=pad.axes||[],threshold=.48;
 if(binding===-1)return (axes[1]||0)<-threshold;
 if(binding===-2)return (axes[1]||0)>threshold;
 if(binding===-3)return (axes[0]||0)<-threshold;
 if(binding===-4)return (axes[0]||0)>threshold;
 if(binding===-5)return (axes[3]||0)<-threshold;
 if(binding===-6)return (axes[3]||0)>threshold;
 if(binding===-7)return (axes[2]||0)<-threshold;
 if(binding===-8)return (axes[2]||0)>threshold;
 return false;
}
function paintController(){
 const pads=getPads();refreshPadChoices(pads);
 livePad=pads.find(p=>p.index===selectedGamepadIndex)||null;
 const name=$("padName"),status=$("padStatus"),live=$("padLive");
 document.querySelectorAll("[data-action]").forEach(el=>{
  const i=GENESIS_ACTIONS.findIndex(a=>a.key===el.dataset.action);
  el.classList.toggle("pad-active",i>=0&&readMappedInput(livePad,Number(S.padMap[i])));
 });
 live.replaceChildren();
 if(!livePad){
  name.textContent="No controller detected";
  status.textContent="Connect a controller by USB or Bluetooth, then press any button. The game also supports keyboard arrows, Z/X/C and Enter.";
  const span=document.createElement("span");span.textContent="Waiting for controller input";live.append(span);return;
 }
 name.textContent=livePad.id+(livePad.mapping==="standard"?" · standard mapping":" · raw controller mapping");
 const pressed=[];
 livePad.buttons.forEach((button,index)=>{if(button&&(button.pressed||button.value>.65))pressed.push("Button "+index);});
 livePad.axes.forEach((axis,index)=>{if(Math.abs(axis)>.55)pressed.push("Axis "+index+": "+(axis<0?"−":"+"));});
 if(!pressed.length){const span=document.createElement("span");span.textContent="Controller connected · no input held";live.append(span);}
 else pressed.forEach(label=>{const span=document.createElement("span");span.className="on";span.textContent=label;live.append(span);});
 const active=GENESIS_ACTIONS.filter((action,i)=>readMappedInput(livePad,Number(S.padMap[i]))).map(x=>x.action);
 status.innerHTML=active.length?"Genesis output: <strong>"+active.join(" · ")+"</strong>":"Press a physical control to see its live Genesis assignment.";
}
async function initControllerSettings(){
 let saved=null;
 try{if(window.GenesisSettings&&window.GenesisSettings.load)saved=await window.GenesisSettings.load();}catch(_){}
 if(saved&&saved.version===PAD_VERSION&&validPadMap(saved.padMap)){
  S.padMap=saved.padMap.map(Number);S.padMapVersion=PAD_VERSION;
 }else if(S.padMapVersion!==PAD_VERSION||!validPadMap(S.padMap)){
  S.padMap=DEFAULT_PAD_MAP.slice();S.padMapVersion=PAD_VERSION;
 }
 renderBindings();
 if(!saved||saved.version!==PAD_VERSION||!validPadMap(saved.padMap))savePadMap();
 else $("mapSaved").textContent="Loaded saved controls ✓";
 (function controllerPoll(){paintController();requestAnimationFrame(controllerPoll);})();
}
window.addEventListener("gamepadconnected",()=>{lastPadSignature="";paintController();});
window.addEventListener("gamepaddisconnected",()=>{lastPadSignature="";paintController();});
initControllerSettings();
'''

SDL_READER = r'''static int mapped_controller_button(int binding){
    switch(binding){
    case 0: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_A);
    case 1: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_B);
    case 2: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_X);
    case 3: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_Y);
    case 4: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_LEFTSHOULDER);
    case 5: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER);
    case 6: return SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_TRIGGERLEFT) > 16000;
    case 7: return SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_TRIGGERRIGHT) > 16000;
    case 8: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_BACK);
    case 9: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_START);
    case 10: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_LEFTSTICK);
    case 11: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_RIGHTSTICK);
    case 12: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_DPAD_UP);
    case 13: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_DPAD_DOWN);
    case 14: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_DPAD_LEFT);
    case 15: return SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_DPAD_RIGHT);
    default: break;
    }
    int ax = SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_LEFTX);
    int ay = SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_LEFTY);
    int rx = SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_RIGHTX);
    int ry = SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_RIGHTY);
    switch(binding){
    case -1: return ay < -12000; case -2: return ay > 12000;
    case -3: return ax < -12000; case -4: return ax > 12000;
    case -5: return ry < -12000; case -6: return ry > 12000;
    case -7: return rx < -12000; case -8: return rx > 12000;
    default: return 0;
    }
}

static int readpad(void){
    int m = 0; const uint8_t *k = SDL_GetKeyboardState(NULL);
    if(k[SDL_SCANCODE_UP]) m |= B_U;
    if(k[SDL_SCANCODE_DOWN]) m |= B_D;
    if(k[SDL_SCANCODE_LEFT]) m |= B_L;
    if(k[SDL_SCANCODE_RIGHT]) m |= B_R;
    if(k[SDL_SCANCODE_Z]) m |= B_A;
    if(k[SDL_SCANCODE_X]) m |= B_B;
    if(k[SDL_SCANCODE_C]) m |= B_C;
    if(k[SDL_SCANCODE_RETURN]) m |= B_S;
    if(pad){
        static const int bits[8] = { B_U, B_D, B_L, B_R, B_A, B_B, B_C, B_S };
        for(int i=0;i<8;i++) if(mapped_controller_button(pad_map[i])) m |= bits[i];
    }
    return m;
}
'''

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_rom_persistence(project: Path) -> None:
    """Remember the last valid ROM and reopen the file picker in its directory."""
    html_path = project / "launcher" / "index.html"
    html = html_path.read_text(encoding="utf-8-sig")

    status_anchor = '<p class="mut" id="launchStatus" role="status" aria-live="polite">Choose a valid Mega Drive ROM to enable Play.</p>'
    settings_markup = '''
 <div id="romRememberSettings" class="mut" style="display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-top:8px;overflow-wrap:anywhere">
  <span id="romDirectoryStatus">Your last valid ROM and its folder will be remembered on this PC.</span>
  <button class="b" id="forgetRom" type="button">Forget saved ROM</button>
 </div>'''
    if 'id="romRememberSettings"' not in html:
        html = replace_once(html, status_anchor, status_anchor + settings_markup, "remembered ROM settings UI")

    pick_old = 'const pick=()=>$("romIn").click();$("drop").onclick=pick;'
    pick_new = r'''function setRomDirectoryStatus(message){
 const status=$("romDirectoryStatus");if(status)status.textContent=message;
}
async function rememberRomPath(filePath){
 if(!filePath||!window.GenesisRom?.remember)return;
 try{
  const result=await window.GenesisRom.remember(filePath);
  if(result?.ok)setRomDirectoryStatus("Remembered ROM folder: "+result.lastRomDirectory);
  else setRomDirectoryStatus(result?.error||"The ROM folder could not be saved.");
 }catch(error){setRomDirectoryStatus("Could not save ROM location: "+(error?.message||String(error)));}
}
async function rememberRomFile(file){
 try{
  const filePath=window.GenesisRom?.pathForFile?.(file);
  if(filePath)await rememberRomPath(filePath);
 }catch(error){setRomDirectoryStatus("Could not read the selected ROM location: "+(error?.message||String(error)));}
}
async function chooseRom(){
 if(!window.GenesisRom?.choose){$("romIn").click();return;}
 try{
  const selected=await window.GenesisRom.choose();
  if(!selected||selected.canceled)return;
  if(!selected.ok)throw new Error(selected.error||"The ROM could not be opened.");
  const bytes=selected.bytes instanceof Uint8Array?selected.bytes:new Uint8Array(selected.bytes);
  const buffer=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
  load(buffer,selected.name||"Selected ROM");
  if(rom)await rememberRomPath(selected.path);
 }catch(error){
  $("launchStatus").textContent="Could not open ROM: "+(error?.message||String(error));
 }
}
const pick=()=>chooseRom();
$("drop").onclick=pick;'''
    if "async function chooseRom()" not in html:
        html = replace_once(html, pick_old, pick_new, "native ROM file picker")

    input_old = '$("romIn").onchange=e=>{const f=e.target.files[0];if(f)f.arrayBuffer().then(b=>load(b,f.name)).catch(err=>rejectROM("Could not read that file: "+err.message));};'
    input_new = r'''$("romIn").onchange=e=>{
 const f=e.target.files[0];if(!f)return;
 f.arrayBuffer().then(async b=>{
  load(b,f.name);
  if(rom)await rememberRomFile(f);
 }).catch(err=>rejectROM("Could not read that file: "+err.message));
};'''
    if input_old in html:
        html = replace_once(html, input_old, input_new, "ROM file input persistence")
    elif 'rememberRomFile(f)' not in html:
        raise RuntimeError("Could not find ROM file input handler for persistence patch.")

    drop_old = '$("drop").ondrop=e=>{e.preventDefault();const f=e.dataTransfer.files[0];if(f)f.arrayBuffer().then(b=>load(b,f.name)).catch(err=>rejectROM("Could not read that file: "+err.message));};'
    drop_new = r'''$("drop").ondrop=e=>{
 e.preventDefault();const f=e.dataTransfer.files[0];if(!f)return;
 f.arrayBuffer().then(async b=>{
  load(b,f.name);
  if(rom)await rememberRomFile(f);
 }).catch(err=>rejectROM("Could not read that file: "+err.message));
};
$("forgetRom").addEventListener("click",async()=>{
 try{
  const result=await window.GenesisRom?.forget?.();
  if(result?.ok)setRomDirectoryStatus("Saved ROM forgotten. Your current game selection remains loaded until you close the launcher.");
  else setRomDirectoryStatus("Could not clear the saved ROM location.");
 }catch(error){setRomDirectoryStatus("Could not clear saved ROM: "+(error?.message||String(error)));}
});
async function restoreRememberedROM(){
 try{
  const settings=await window.GenesisRom?.settings?.();
  if(settings?.lastRomDirectory)setRomDirectoryStatus("Remembered ROM folder: "+settings.lastRomDirectory);
  const saved=await window.GenesisRom?.loadLast?.();
  if(saved?.ok&&saved.bytes){
   const bytes=saved.bytes instanceof Uint8Array?saved.bytes:new Uint8Array(saved.bytes);
   const buffer=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
   load(buffer,saved.name||"Saved ROM");
   if(rom){
    setRomDirectoryStatus("Remembered ROM folder: "+(saved.lastRomDirectory||settings?.lastRomDirectory||""));
    $("launchStatus").textContent="Restored your saved ROM: "+(saved.name||"Mega Drive ROM")+". Ready to play.";
   }
  }else if(saved&&!saved.empty&&saved.error){
   setRomDirectoryStatus(saved.error+(saved.lastRomDirectory?" Saved folder: "+saved.lastRomDirectory:""));
  }else if(!settings?.lastRomDirectory){
   setRomDirectoryStatus("No ROM saved yet. Choose a ROM and its location will be remembered.");
  }
 }catch(error){setRomDirectoryStatus("Could not restore saved ROM: "+(error?.message||String(error)));}
}
'''
    if '$("forgetRom").addEventListener' not in html:
        html = replace_once(html, drop_old, drop_new, "ROM drop handler and remembered ROM startup")
    elif drop_old in html:
        html = replace_once(html, drop_old, drop_new, "ROM drop handler update")

    startup_anchor = "/* tile decode */"
    if "restoreRememberedROM,{once:true}" not in html:
        startup = '''if(document.readyState==="loading"){
 window.addEventListener("DOMContentLoaded",restoreRememberedROM,{once:true});
}else{
 Promise.resolve().then(restoreRememberedROM);
}
'''
        html = replace_once(html, startup_anchor, startup + startup_anchor, "automatic ROM restoration")

    html_path.write_text(html, encoding="utf-8")
    print("Installed remembered ROM path, automatic ROM restoration, and last-folder file picker.")


def patch_html(project: Path) -> None:
    html_path = project / "launcher" / "index.html"
    html = html_path.read_text(encoding="utf-8-sig")
    if "genesis-shell" not in html:
        html = replace_once(html, "</style>", CSS + "\n</style>", "Genesis controller styles")
        html, n = re.subn(r'<section class="tab" id="t-ctl">.*?</section>', MARKUP, html, count=1, flags=re.S)
        if n != 1:
            raise RuntimeError("Could not replace the existing Controls tab markup.")
    else:
        html, n = re.subn(r'<section class="tab" id="t-ctl">.*?</section>', MARKUP, html, count=1, flags=re.S)
        if n != 1:
            raise RuntimeError("Could not update the Genesis controller markup.")
    if "/* Genesis controller + live Gamepad API mapping */" in html:
        html, n = re.subn(
            r'/\* Genesis controller \+ live Gamepad API mapping \*/.*?(?:initControllerSettings\(\);|renderBindings\(\);)',
            GAMEPAD_JS,
            html,
            count=1,
            flags=re.S
        )
        if n != 1:
            raise RuntimeError("Could not replace the existing controller JavaScript.")
    else:
        html, n = re.subn(r'/\* gamepad \*/.*?requestAnimationFrame\(poll\)\}\)\(\);', GAMEPAD_JS, html, count=1, flags=re.S)
        if n != 1:
            raise RuntimeError("Could not replace the old controller JavaScript.")
    launch_marker = "const result=await window.GenesisCore.run(rom,S);"
    if launch_marker in html and "await window.GenesisSettings.save" not in html:
        html = html.replace(
            launch_marker,
            "if(window.GenesisSettings&&window.GenesisSettings.save) await window.GenesisSettings.save({version:PAD_VERSION,padMap:S.padMap});\n  " + launch_marker,
            1
        )
    html_path.write_text(html, encoding="utf-8")

def patch_preload(project: Path) -> None:
    path = project / "launcher" / "preload.js"
    preload = r'''const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('GenesisCore', {
  run: (rom, settings) => {
    let bytes;
    if (rom instanceof Uint8Array) bytes = new Uint8Array(rom);
    else if (rom instanceof ArrayBuffer) bytes = new Uint8Array(rom);
    else if (ArrayBuffer.isView(rom)) bytes = new Uint8Array(rom.buffer, rom.byteOffset, rom.byteLength);
    else if (Array.isArray(rom)) bytes = Uint8Array.from(rom);
    else throw new TypeError('The selected ROM data could not be transferred to the game core.');
    return ipcRenderer.invoke('md-launch', bytes, settings || {});
  }
});

contextBridge.exposeInMainWorld('GenesisSettings', {
  load: () => ipcRenderer.invoke('controller-settings-load'),
  save: settings => ipcRenderer.invoke('controller-settings-save', settings || {})
});

contextBridge.exposeInMainWorld('GenesisRom', {
  pathForFile: file => {
    try { return webUtils.getPathForFile(file); } catch (_) { return ''; }
  },
  remember: filePath => ipcRenderer.invoke('rom-settings-remember', filePath),
  settings: () => ipcRenderer.invoke('rom-settings-load'),
  loadLast: () => ipcRenderer.invoke('rom-settings-load-last'),
  choose: () => ipcRenderer.invoke('rom-choose'),
  forget: () => ipcRenderer.invoke('rom-settings-forget')
});
'''
    path.write_text(preload, encoding="utf-8")

def patch_main(project: Path) -> None:
    path = project / "launcher" / "main.js"
    main = path.read_text(encoding="utf-8-sig")
    if "rom-settings-load-last" not in main:
        rom_handlers = r'''
const romSettingsFile = path.join(app.getPath('userData'), 'rom-settings.json');
function readRomSettings() {
  try {
    const saved = JSON.parse(fs.readFileSync(romSettingsFile, 'utf8'));
    return {
      version: 1,
      lastRomPath: typeof saved.lastRomPath === 'string' ? saved.lastRomPath : '',
      lastRomDirectory: typeof saved.lastRomDirectory === 'string' ? saved.lastRomDirectory : ''
    };
  } catch (_) {
    return { version: 1, lastRomPath: '', lastRomDirectory: '' };
  }
}
function writeRomSettings(settings) {
  fs.mkdirSync(path.dirname(romSettingsFile), { recursive: true });
  const temporary = romSettingsFile + '.tmp';
  fs.writeFileSync(temporary, JSON.stringify(settings, null, 2), 'utf8');
  fs.renameSync(temporary, romSettingsFile);
}
ipcMain.handle('rom-settings-load', async () => readRomSettings());
ipcMain.handle('rom-settings-remember', async (_event, filePath) => {
  if (typeof filePath !== 'string' || !filePath.trim() || !path.isAbsolute(filePath)) {
    return { ok: false, error: 'The selected ROM path is invalid.' };
  }
  const resolved = path.resolve(filePath);
  try {
    if (!fs.statSync(resolved).isFile()) return { ok: false, error: 'The selected ROM is not a file.' };
  } catch (_) {
    return { ok: false, error: 'The selected ROM file could not be found.' };
  }
  const settings = readRomSettings();
  settings.lastRomPath = resolved;
  settings.lastRomDirectory = path.dirname(resolved);
  writeRomSettings(settings);
  return { ok: true, lastRomPath: settings.lastRomPath, lastRomDirectory: settings.lastRomDirectory };
});
ipcMain.handle('rom-settings-load-last', async () => {
  const settings = readRomSettings();
  if (!settings.lastRomPath) {
    return { ok: false, empty: true, lastRomDirectory: settings.lastRomDirectory };
  }
  try {
    const stat = fs.statSync(settings.lastRomPath);
    if (!stat.isFile() || stat.size <= 0x200 || stat.size > 0x400000) {
      throw new Error('The saved file is not a supported Mega Drive ROM size.');
    }
    const data = fs.readFileSync(settings.lastRomPath);
    return {
      ok: true,
      path: settings.lastRomPath,
      name: path.basename(settings.lastRomPath),
      lastRomDirectory: settings.lastRomDirectory,
      bytes: Uint8Array.from(data)
    };
  } catch (_) {
    return {
      ok: false,
      error: 'The saved ROM is unavailable or is not a supported size. Choose it again to update the saved location.',
      lastRomDirectory: settings.lastRomDirectory
    };
  }
});
ipcMain.handle('rom-settings-forget', async () => {
  writeRomSettings({ version: 1, lastRomPath: '', lastRomDirectory: '' });
  return { ok: true };
});
ipcMain.handle('rom-choose', async () => {
  const settings = readRomSettings();
  try {
    const result = await require('electron').dialog.showOpenDialog({
      title: 'Choose your Mega Drive ROM',
      defaultPath: settings.lastRomDirectory || app.getPath('documents'),
      properties: ['openFile'],
      filters: [
        { name: 'Mega Drive ROMs', extensions: ['md', 'bin', 'gen', 'smd'] },
        { name: 'All files', extensions: ['*'] }
      ]
    });
    if (result.canceled || !result.filePaths || !result.filePaths.length) {
      return { ok: false, canceled: true };
    }
    const selectedPath = path.resolve(result.filePaths[0]);
    const stat = fs.statSync(selectedPath);
    if (!stat.isFile() || stat.size <= 0x200 || stat.size > 0x400000) {
      return { ok: false, error: 'That file is not a supported Mega Drive ROM size (up to 4 MiB).' };
    }
    const data = fs.readFileSync(selectedPath);
    return {
      ok: true,
      path: selectedPath,
      name: path.basename(selectedPath),
      bytes: Uint8Array.from(data)
    };
  } catch (error) {
    return { ok: false, error: 'Could not open the selected ROM: ' + error.message };
  }
});

'''
        marker = "// Launch the native port"
        if marker not in main:
            raise RuntimeError("Could not find native launcher IPC insertion point for ROM settings.")
        main = main.replace(marker, rom_handlers + marker, 1)

    if "controller-settings-load" not in main:
        handlers = r'''
const controllerSettingsFile = path.join(app.getPath('userData'), 'controller-settings.json');
const defaultControllerSettings = { version: 3, padMap: [12, 13, 14, 15, 2, 0, 1, 9] };
function syncControllerSettingsFromConfig(configPath) {
  try {
    const text = fs.readFileSync(configPath, 'utf8');
    const keys = ['pad_up','pad_down','pad_left','pad_right','pad_a','pad_b','pad_c','pad_start'];
    const current = new Map();
    for (const line of text.split(/\r?\n/)) {
      const at = line.indexOf('=');
      if (at > 0) current.set(line.slice(0, at).trim(), line.slice(at + 1).trim());
    }
    const padMap = keys.map((key, i) => {
      const value = Number(current.get(key));
      return Number.isInteger(value) && value >= -8 && value <= 15
        ? value : defaultControllerSettings.padMap[i];
    });
    const normalized = { version: 3, padMap };
    fs.mkdirSync(path.dirname(controllerSettingsFile), { recursive: true });
    const temporary = controllerSettingsFile + '.tmp';
    fs.writeFileSync(temporary, JSON.stringify(normalized, null, 2), 'utf8');
    fs.renameSync(temporary, controllerSettingsFile);
  } catch (error) {
    console.warn('Could not synchronize native game controller settings:', error.message);
  }
}
ipcMain.handle('controller-settings-load', async () => {
  try {
    const parsed = JSON.parse(fs.readFileSync(controllerSettingsFile, 'utf8'));
    if (parsed.version === 3 && Array.isArray(parsed.padMap) && parsed.padMap.length === 8 &&
        parsed.padMap.every(v => Number.isInteger(v) && v >= -8 && v <= 15)) return parsed;
  } catch (_) {}
  return defaultControllerSettings;
});
ipcMain.handle('controller-settings-save', async (_event, settings = {}) => {
  const padMap = Array.isArray(settings.padMap) && settings.padMap.length === 8
    ? settings.padMap.map(Number) : defaultControllerSettings.padMap;
  if (!padMap.every(v => Number.isInteger(v) && v >= -8 && v <= 15)) {
    return { ok: false, error: 'Controller mapping contains an invalid button index.' };
  }
  const normalized = { version: 3, padMap };
  fs.mkdirSync(path.dirname(controllerSettingsFile), { recursive: true });
  const temporary = controllerSettingsFile + '.tmp';
  fs.writeFileSync(temporary, JSON.stringify(normalized, null, 2), 'utf8');
  fs.renameSync(temporary, controllerSettingsFile);
  return { ok: true };
});

'''
        marker = "// Launch the native port"
        if marker not in main:
            raise RuntimeError("Could not find native launcher IPC insertion point in main.js.")
        main = main.replace(marker, handlers + marker, 1)

    if "const padMap = Array.isArray(settings.padMap)" not in main:
        anchor = "  const cfg = ["
        normalized = """  const padMap = Array.isArray(settings.padMap) && settings.padMap.length === 8
    ? settings.padMap.map(Number) : defaultControllerSettings.padMap;
"""
        main = replace_once(main, anchor, normalized + anchor, "controller config normalization")
        tick = chr(96)
        dollar = chr(36)
        lines = []
        for key, idx in [("pad_up",0),("pad_down",1),("pad_left",2),("pad_right",3),
                         ("pad_a",4),("pad_b",5),("pad_c",6),("pad_start",7)]:
            lines.append("    " + tick + key + "=" + dollar + "{padMap[" + str(idx) + "]}" + tick + ",")
        config_anchor = "    " + tick + "vsync=" + dollar + "{settings.vsync === false ? 0 : 1}" + tick + ","
        if config_anchor not in main:
            raise RuntimeError("Could not find the vsync line for controller config injection.")
        main = main.replace(config_anchor, config_anchor + "\n" + "\n".join(lines), 1)

    # The game writes native Video/Audio options to config.ini on exit.
    # The launcher used to rebuild config.ini from stale UI defaults on every
    # launch, immediately undoing those changes. Merge the existing file into
    # the generated cfg array before it is written: saved values win, and any
    # native/forward-compatible keys missing from the current launcher array
    # are retained at the end of the file.
    preserve_marker = "// preserve-native-config-before-launch"
    if preserve_marker not in main:
        write_anchor = "fs.writeFileSync(configPath,"
        if main.count(write_anchor) != 1:
            raise RuntimeError(f"Expected one config.ini write site, found {main.count(write_anchor)}.")
        preserve_code = r'''
  // preserve-native-config-before-launch
  if (Array.isArray(cfg)) {
    const savedNativeConfig = new Map();
    try {
      const savedText = fs.readFileSync(configPath, 'utf8');
      for (const line of savedText.split(/\r?\n/)) {
        const at = line.indexOf('=');
        if (at > 0) savedNativeConfig.set(line.slice(0, at).trim(), line.slice(at + 1).trim());
      }
    } catch (_) {
      // First launch: there is no existing config.ini yet.
    }
    if (savedNativeConfig.size) {
      const retainedKeys = new Set();
      const mergedConfig = cfg.map(entry => {
        const line = String(entry);
        const at = line.indexOf('=');
        if (at <= 0) return entry;
        const key = line.slice(0, at).trim();
        if (!savedNativeConfig.has(key)) return entry;
        retainedKeys.add(key);
        return key + '=' + savedNativeConfig.get(key);
      });
      for (const [key, value] of savedNativeConfig) {
        if (!retainedKeys.has(key)) mergedConfig.push(key + '=' + value);
      }
      cfg.splice(0, cfg.length, ...mergedConfig);
    }
  }
'''
        main = main.replace(write_anchor, preserve_code + "\n  " + write_anchor, 1)

    exit_anchor = "child.once('exit', (code, signal) => {"
    if "syncControllerSettingsFromConfig(configPath)" not in main:
        main = replace_once(
            main,
            exit_anchor,
            exit_anchor + "\n      syncControllerSettingsFromConfig(configPath);",
            "launcher controller-settings round-trip on game exit"
        )

    # electron-builder's portable wrapper exposes the true outer EXE folder.
    # It differs from app.getPath('exe') when the app is unpacked to a temp folder.
    portable_anchor = "const romSettingsFile = path.join(app.getPath('userData'), 'rom-settings.json');"
    portable_definition = "const portableConfigDirectory = process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(app.getPath('exe'));\n"
    if "const portableConfigDirectory =" not in main:
        if portable_anchor in main:
            main = main.replace(portable_anchor, portable_definition + portable_anchor, 1)
        else:
            controller_anchor = "const controllerSettingsFile = path.join(app.getPath('userData'), 'controller-settings.json');"
            if controller_anchor not in main:
                raise RuntimeError("Could not find settings-file anchor for portable config directory.")
            main = main.replace(controller_anchor, portable_definition + controller_anchor, 1)
    main = main.replace("app.getPath('userData')", "portableConfigDirectory")
    main = main.replace('app.getPath("userData")', "portableConfigDirectory")
    config_decl = re.compile(r'(\b(?:const|let|var)\s+configPath\s*=\s*)[^;]+;')
    config_matches = list(config_decl.finditer(main))
    if len(config_matches) != 1:
        raise RuntimeError(f"Expected one native configPath declaration, found {len(config_matches)}.")
    match = config_matches[0]
    main = main[:match.start()] + match.group(1) + "path.join(portableConfigDirectory, 'config.ini');" + main[match.end():]
    if "path.join(portableConfigDirectory, 'config.ini')" not in main:
        raise RuntimeError("Native config.ini is not configured beside the portable launcher.")
    path.write_text(main, encoding="utf-8")

def patch_sdl(project: Path) -> None:
    path = project / "runtime" / "sdl_main.c"
    sdl = path.read_text(encoding="utf-8-sig")
    if "static int pad_map[8]" not in sdl:
        cfg_end = re.search(r'} cfg = \{[^;]*\};', sdl)
        if not cfg_end:
            raise RuntimeError("Could not find native SDL config declaration.")
        sdl = sdl[:cfg_end.end()] + "\nstatic int pad_map[8] = { 12, 13, 14, 15, 2, 0, 1, 9 };\n" + sdl[cfg_end.end():]
    if 'else if(!strcmp(l, "pad_up"))' not in sdl and 'else if(!strcmp(l,"pad_up"))' not in sdl:
        background = 'else if(!strcmp(l, "background")) strncpy(cfg.bg, v, sizeof cfg.bg - 1);'
        pad_parser = '''else if(!strcmp(l, "pad_up")) pad_map[0] = atoi(v);
        else if(!strcmp(l, "pad_down")) pad_map[1] = atoi(v);
        else if(!strcmp(l, "pad_left")) pad_map[2] = atoi(v);
        else if(!strcmp(l, "pad_right")) pad_map[3] = atoi(v);
        else if(!strcmp(l, "pad_a")) pad_map[4] = atoi(v);
        else if(!strcmp(l, "pad_b")) pad_map[5] = atoi(v);
        else if(!strcmp(l, "pad_c")) pad_map[6] = atoi(v);
        else if(!strcmp(l, "pad_start")) pad_map[7] = atoi(v);
        ''' + background
        sdl = replace_once(sdl, background, pad_parser, "native SDL controller config parser")
    if "static int mapped_controller_button(int binding)" not in sdl:
        readpad = re.compile(r'static int readpad\s*\(void\)\s*\{.*?\n\s*static void open_pad\s*\(void\)\s*\{', re.S)
        sdl, n = readpad.subn(SDL_READER + "\nstatic void open_pad(void){", sdl, count=1)
        if n != 1:
            raise RuntimeError("Could not replace SDL's hard-coded controller input reader.")
    path.write_text(sdl, encoding="utf-8")


def patch_harness_input(project: Path) -> None:
    """Translate the abstract input mask to the actual Mega Drive DATA register bits."""
    path = project / "runtime" / "harness.c"
    source = path.read_text(encoding="utf-8-sig")
    matches = list(re.finditer(r"static\s+uint8_t\s+pad_read\s*\(\s*int\s+p\s*\)\s*\{", source))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one native pad_read(int p), found {len(matches)}.")

    start = matches[0].start()
    open_brace = source.find("{", matches[0].start())
    depth = 0
    end = None
    for index in range(open_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        raise RuntimeError("Could not find the end of native pad_read(int p).")

    corrected = r'''static uint8_t pad_read(int p) {
    int b = buttons();
    int th = pad_latch[p] & 0x40;
    /*
     * Mega Drive DATA register:
     * D0=Up, D1=Down, D2=Left, D3=Right,
     * D4=TL, D5=TR, D6=TH. Controller signals are active-low.
     *
     * TH=1: D4=B, D5=C.
     * TH=0: D4=A, D5=Start.
     */
    int v;
    if (th) {
        v = 0x40
          | ((b & 0x01) ? 0 : 0x01)  /* Up    -> D0 */
          | ((b & 0x02) ? 0 : 0x02)  /* Down  -> D1 */
          | ((b & 0x04) ? 0 : 0x04)  /* Left  -> D2 */
          | ((b & 0x08) ? 0 : 0x08)  /* Right -> D3 */
          | ((b & 0x20) ? 0 : 0x10)  /* B     -> D4 / TL */
          | ((b & 0x40) ? 0 : 0x20); /* C     -> D5 / TR */
    } else {
        v = ((b & 0x01) ? 0 : 0x01)  /* Up    -> D0 */
          | ((b & 0x02) ? 0 : 0x02)  /* Down  -> D1 */
          | ((b & 0x10) ? 0 : 0x10)  /* A     -> D4 / TL */
          | ((b & 0x80) ? 0 : 0x20); /* Start -> D5 / TR */
    }
    return (v & ~pad_ctrl[p]) | (pad_latch[p] & pad_ctrl[p]) | 0x80;
}'''

    existing = source[start:end]
    if "D0=Up, D1=Down, D2=Left, D3=Right" not in existing:
        source = source[:start] + corrected + source[end:]
        path.write_text(source, encoding="utf-8")
        print("Corrected Mega Drive DATA-register bit order in runtime/harness.c.")
    else:
        print("Mega Drive DATA-register bit order is already corrected.")

    # Pure mapping checks: each logical action must toggle exactly one hardware bit.
    high_map = [(0x01, 0x01), (0x02, 0x02), (0x04, 0x04),
                (0x08, 0x08), (0x20, 0x10), (0x40, 0x20)]
    low_map = [(0x01, 0x01), (0x02, 0x02), (0x10, 0x10), (0x80, 0x20)]

    def encoded(mask: int, th_high: bool) -> int:
        pairs = high_map if th_high else low_map
        value = 0x40 if th_high else 0
        for source_bit, port_bit in pairs:
            if not (mask & source_bit):
                value |= port_bit
        return value | 0x80

    for pairs, th_high in ((high_map, True), (low_map, False)):
        idle = encoded(0, th_high)
        for source_bit, port_bit in pairs:
            pressed = encoded(source_bit, th_high)
            if idle ^ pressed != port_bit:
                raise RuntimeError(
                    f"Mega Drive pad mapping test failed: mask 0x{source_bit:02X}, "
                    f"expected one port bit 0x{port_bit:02X}, got 0x{idle ^ pressed:02X}."
                )
    print("Mega Drive pad mapping tests passed: every direction/button toggles one correct DATA bit.")

def patch(project: Path) -> None:
    patch_preload(project)
    patch_main(project)
    patch_sdl(project)
    patch_harness_input(project)
    patch_html(project)
    patch_rom_persistence(project)
    print("Installed reference-shaped Genesis pad, correct Fire/Jump/Rope mapping, SDL physical-input translation, and persistent controller settings.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-controller-menu.py PROJECT_ROOT")
    patch(Path(sys.argv[1]).resolve())
