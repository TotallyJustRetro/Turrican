#!/usr/bin/env python3
"""Add independent Player 1 / Player 2 launcher bindings and Genesis port-2 input."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path.cwd()
LAUNCHER=ROOT/"launcher"
RUNTIME=ROOT/"runtime"
HTML=LAUNCHER/"index.html"
MAIN=LAUNCHER/"main.js"
SDL=RUNTIME/"sdl_main.c"
HARNESS=RUNTIME/"harness.c"

for p in (HTML,MAIN,SDL,HARNESS):
    if not p.is_file():
        raise SystemExit(f"dual-controller patch: required file missing: {p}")

MAP_KEYS=["up","down","left","right","a","b","c","start"]
DEFAULT_MAP=[12,13,14,15,2,0,1,9]

def once(src,old,new,label):
    n=src.count(old)
    if n!=1: raise SystemExit(f"dual-controller patch: {label}: expected one match, found {n}")
    return src.replace(old,new,1)

def func_span(src,pattern,label):
    m=re.search(pattern,src)
    if not m: raise SystemExit(f"dual-controller patch: {label} not found")
    start=m.start()
    brace=src.find("{",m.end())
    if brace<0: raise SystemExit(f"dual-controller patch: {label} has no body")
    depth=0;state="code";esc=False;i=brace
    while i<len(src):
        ch=src[i];nxt=src[i+1] if i+1<len(src) else ""
        if state=="line":
            if ch=="\n":state="code"
        elif state=="block":
            if ch=="*" and nxt=="/":state="code";i+=1
        elif state in ("str","char"):
            if esc:esc=False
            elif ch=="\\":esc=True
            elif (state=="str" and ch=='"') or (state=="char" and ch=="'"):state="code"
        else:
            if ch=="/" and nxt=="/":state="line";i+=1
            elif ch=="/" and nxt=="*":state="block";i+=1
            elif ch=='"':state="str"
            elif ch=="'":state="char"
            elif ch=="{":depth+=1
            elif ch=="}":
                depth-=1
                if depth==0:return start,i+1
        i+=1
    raise SystemExit(f"dual-controller patch: unterminated {label}")

def replace_func(src,pattern,body,label):
    a,b=func_span(src,pattern,label)
    return src[:a]+body+src[b:]

# 1. Versioned settings now retain two independent controller layouts.
main=MAIN.read_text(encoding="utf-8-sig")
settings_start=main.find("const controllerSettingsFile =")
launch_marker=main.find("// Launch the native port",settings_start)
if settings_start<0 or launch_marker<0:
    raise SystemExit("dual-controller patch: controller settings IPC block not found")
settings_block=r'''
const controllerSettingsFile = path.join(portableConfigDirectory, 'controller-settings.json');
const MAP_KEYS = ['up','down','left','right','a','b','c','start'];
const defaultControllerSettings = {
  version: 4,
  padMap: [12, 13, 14, 15, 2, 0, 1, 9],
  pad2Map: [12, 13, 14, 15, 2, 0, 1, 9]
};
function validControllerMap(value) {
  return Array.isArray(value) && value.length === 8 &&
    value.every(v => Number.isInteger(Number(v)) && Number(v) >= -8 && Number(v) <= 15);
}
function normalizeControllerSettings(value) {
  const p1 = validControllerMap(value?.padMap) ? value.padMap.map(Number) : defaultControllerSettings.padMap.slice();
  const p2 = validControllerMap(value?.pad2Map) ? value.pad2Map.map(Number) :
    (value?.version === 3 && validControllerMap(value?.padMap) ? value.padMap.map(Number) : defaultControllerSettings.pad2Map.slice());
  return { version: 4, padMap: p1, pad2Map: p2 };
}
function syncControllerSettingsFromConfig(configPath) {
  try {
    const text = fs.readFileSync(configPath, 'utf8');
    const current = new Map();
    for (const line of text.split(/\r?\n/)) {
      const at = line.indexOf('=');
      if (at > 0) current.set(line.slice(0, at).trim(), line.slice(at + 1).trim());
    }
    const readMap = prefix => MAP_KEYS.map((key, i) => {
      const value = Number(current.get(prefix + key));
      return Number.isInteger(value) && value >= -8 && value <= 15
        ? value : defaultControllerSettings.padMap[i];
    });
    const normalized = { version: 4, padMap: readMap('pad_'), pad2Map: readMap('pad2_') };
    fs.mkdirSync(path.dirname(controllerSettingsFile), { recursive: true });
    const temporary = controllerSettingsFile + '.tmp';
    fs.writeFileSync(temporary, JSON.stringify(normalized, null, 2), 'utf8');
    fs.renameSync(temporary, controllerSettingsFile);
  } catch (error) {
    console.warn('Could not synchronize P1/P2 controller settings:', error.message);
  }
}
ipcMain.handle('controller-settings-load', async () => {
  try {
    const parsed = JSON.parse(fs.readFileSync(controllerSettingsFile, 'utf8'));
    if ((parsed.version === 3 || parsed.version === 4) && validControllerMap(parsed.padMap)) {
      return normalizeControllerSettings(parsed);
    }
  } catch (_) {}
  return normalizeControllerSettings(defaultControllerSettings);
});
ipcMain.handle('controller-settings-save', async (_event, settings = {}) => {
  const normalized = normalizeControllerSettings(settings);
  if (!validControllerMap(normalized.padMap) || !validControllerMap(normalized.pad2Map)) {
    return { ok: false, error: 'P1 or P2 controller mapping contains an invalid input.' };
  }
  fs.mkdirSync(path.dirname(controllerSettingsFile), { recursive: true });
  const temporary = controllerSettingsFile + '.tmp';
  fs.writeFileSync(temporary, JSON.stringify(normalized, null, 2), 'utf8');
  fs.renameSync(temporary, controllerSettingsFile);
  return { ok: true, version: 4 };
});

'''
main=main[:settings_start]+settings_block+main[launch_marker:]

# Add the two binding sets immediately before the generated config.ini is written.
# This avoids depending on the formatting or closing syntax of the existing cfg array.
write_anchor="fs.writeFileSync(configPath,"
if main.count(write_anchor)!=1:
    raise SystemExit("dual-controller patch: config.ini write site not found uniquely")
inject=r"""
  // Keep P1's original config.ini mapping and pass P2's independent map
  // to the child process without depending on the private config parser.
  const dualControllerSettingsForLaunch = normalizeControllerSettings(settings);
  const dualPadActionsForLaunch = [
    ['up',0],['down',1],['left',2],['right',3],
    ['a',4],['b',5],['c',6],['start',7]
  ];
  const dualPadConfigForLaunch = dualPadActionsForLaunch.map(([key,index]) =>
    'pad_' + key + '=' + dualControllerSettingsForLaunch.padMap[index]);
  const dualPadKeysForLaunch = new Set(dualPadActionsForLaunch.map(([key]) => 'pad_' + key));
  for (const [key] of dualPadActionsForLaunch) dualPadKeysForLaunch.add('pad2_' + key);
  for (let i = cfg.length - 1; i >= 0; i--) {
    const entry = String(cfg[i]);
    const at = entry.indexOf('=');
    if (at > 0 && dualPadKeysForLaunch.has(entry.slice(0, at))) cfg.splice(i, 1);
  }
  cfg.push(...dualPadConfigForLaunch);
  process.env.MEGATURRICAN_PAD2_MAP = dualControllerSettingsForLaunch.pad2Map.join(',');
"""MAIN.write_text(main,encoding="utf-8")

# 2. Launcher profile switch and JS keep the two maps independent.
html=HTML.read_text(encoding="utf-8-sig")
if 'id="p2Profile"' not in html:
    html=once(html,'<h3>Game controls</h3>',
      '<div class="pad-profile-switch"><button class="b active" id="p1Profile" type="button">PLAYER 1 · CONTROLLER 1</button><button class="b" id="p2Profile" type="button">PLAYER 2 · CONTROLLER 2</button></div>\n  <h3 id="mapProfileTitle">PLAYER 1 · GAME CONTROLS</h3>',
      "P1/P2 profile tabs")
    html=html.replace(
      "These mappings are applied to the actual gamepad input in the native Windows core and saved to this PC.",
      "Configure each Genesis controller independently. P1 uses the first detected controller; P2 uses the second. Both profiles are saved on this PC.",1)
    html=html.replace(
      ".controller-layout{display:grid;",
      ".pad-profile-switch{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}.pad-profile-switch button.active{background:#e59b36;color:#141414;border-color:#ffe0a5}.controller-layout{display:grid;",1)

gamepad_js=r'''/* Dual Genesis controller profiles: independent P1/P2 maps. */
const PAD_VERSION=4;
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
let activePadProfile=1,lastPadSignature="",livePad=null,selectedGamepadIndex={1:-1,2:-1};
function validPadMap(v){return Array.isArray(v)&&v.length===8&&v.every(x=>Number.isInteger(Number(x))&&Number(x)>=-8&&Number(x)<=15);}
function mapForProfile(player){return player===2?S.pad2Map:S.padMap;}
function savePadMap(){
 S.padMapVersion=PAD_VERSION;
 S.padMap=GENESIS_ACTIONS.map((_,i)=>Number(S.padMap[i]));
 S.pad2Map=GENESIS_ACTIONS.map((_,i)=>Number(S.pad2Map[i]));
 save();
 $("mapSaved").textContent="Saving P1/P2 controls…";
 const payload={version:PAD_VERSION,padMap:S.padMap,pad2Map:S.pad2Map};
 if(window.GenesisSettings&&window.GenesisSettings.save){
  window.GenesisSettings.save(payload).then(result=>{
   $("mapSaved").textContent=result&&result.ok?"Both controller profiles saved on this PC ✓":"Saved in launcher session";
  }).catch(()=>{$("mapSaved").textContent="Saved in launcher session";});
 }else $("mapSaved").textContent="Saved in launcher session";
}
function setPadProfile(player){
 activePadProfile=player===2?2:1;
 $("p1Profile").classList.toggle("active",activePadProfile===1);
 $("p2Profile").classList.toggle("active",activePadProfile===2);
 $("mapProfileTitle").textContent=activePadProfile===1?"PLAYER 1 · CONTROLLER 1 BINDINGS":"PLAYER 2 · CONTROLLER 2 BINDINGS";
 const pads=getPads(),wanted=activePadProfile===1?0:1;
 if(selectedGamepadIndex[activePadProfile]<0&&pads[wanted])selectedGamepadIndex[activePadProfile]=pads[wanted].index;
 if(!pads.some(p=>p.index===selectedGamepadIndex[activePadProfile]))selectedGamepadIndex[activePadProfile]=pads[wanted]?.index??-1;
 refreshPadChoices(pads);renderBindings();paintController();
}
function renderBindings(){
 const host=$("map"),map=mapForProfile(activePadProfile);
 host.replaceChildren();
 GENESIS_ACTIONS.forEach((action,i)=>{
  const row=document.createElement("label");row.className="binding-row";
  const name=document.createElement("span");name.className="binding-key";name.textContent=action.label;
  const select=document.createElement("select");select.dataset.action=action.key;select.setAttribute("aria-label",action.action+" controller input");
  PAD_OPTIONS.forEach(([value,label])=>{const option=document.createElement("option");option.value=String(value);option.textContent=label;select.append(option);});
  select.value=String(map[i]);
  if(!PAD_OPTIONS.some(x=>x[0]===map[i]))select.value=String(action.def);
  select.addEventListener("change",()=>{map[i]=Number(select.value);savePadMap();paintController();});
  row.append(name,select);host.append(row);
 });
}
$("p1Profile").addEventListener("click",()=>setPadProfile(1));
$("p2Profile").addEventListener("click",()=>setPadProfile(2));
$("resetPad").addEventListener("click",()=>{
 const map=mapForProfile(activePadProfile);
 for(let i=0;i<8;i++)map[i]=DEFAULT_PAD_MAP[i];
 renderBindings();savePadMap();paintController();
});
function getPads(){try{return [...(navigator.getGamepads?.()||[])].filter(Boolean);}catch(_){return [];}}
function refreshPadChoices(pads){
 const signature=pads.map(p=>p.index+":"+p.id).join("|");
 const select=$("controllerSelect"),previous=selectedGamepadIndex[activePadProfile];
 if(signature===lastPadSignature&&select.options.length){
  select.value=String(previous);
  return;
 }
 lastPadSignature=signature;
 select.replaceChildren();
 if(!pads.length){
  const option=document.createElement("option");option.value="-1";option.textContent="No controller detected";select.append(option);
  selectedGamepadIndex[activePadProfile]=-1;return;
 }
 pads.forEach((pad,n)=>{
  const option=document.createElement("option");option.value=String(pad.index);
  option.textContent=(n+1)+" · "+pad.id.slice(0,58);select.append(option);
 });
 const fallback=activePadProfile===1?pads[0]:(pads[1]||null);
 selectedGamepadIndex[activePadProfile]=pads.some(p=>p.index===previous)?previous:(fallback?fallback.index:-1);
 select.value=String(selectedGamepadIndex[activePadProfile]);
}
$("controllerSelect").addEventListener("change",()=>{
 selectedGamepadIndex[activePadProfile]=Number($("controllerSelect").value);paintController();
});
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
 livePad=pads.find(p=>p.index===selectedGamepadIndex[activePadProfile])||null;
 const name=$("padName"),status=$("padStatus"),live=$("padLive"),map=mapForProfile(activePadProfile);
 document.querySelectorAll("#genesisPad [data-action]").forEach(el=>{
  const i=GENESIS_ACTIONS.findIndex(a=>a.key===el.dataset.action);
  el.classList.toggle("pad-active",i>=0&&readMappedInput(livePad,Number(map[i])));
 });
 live.replaceChildren();
 if(!livePad){
  name.textContent=activePadProfile===1?"P1 · No controller detected":"P2 · No controller detected";
  status.textContent=activePadProfile===1?"Connect Player 1's controller. P1 is the first detected controller by default.":"Connect Player 2's controller. P2 is the second detected controller by default.";
  const span=document.createElement("span");span.textContent="Waiting for controller input";live.append(span);return;
 }
 name.textContent=(activePadProfile===1?"P1 · ":"P2 · ")+livePad.id+(livePad.mapping==="standard"?" · standard mapping":" · raw controller mapping");
 const pressed=[];
 livePad.buttons.forEach((button,index)=>{if(button&&(button.pressed||button.value>.65))pressed.push("Button "+index);});
 livePad.axes.forEach((axis,index)=>{if(Math.abs(axis)>.55)pressed.push("Axis "+index+": "+(axis<0?"−":"+"));});
 if(!pressed.length){const span=document.createElement("span");span.textContent="Controller connected · no input held";live.append(span);}
 else pressed.forEach(label=>{const span=document.createElement("span");span.className="on";span.textContent=label;live.append(span);});
 const active=GENESIS_ACTIONS.filter((action,i)=>readMappedInput(livePad,Number(map[i]))).map(x=>x.action);
 status.innerHTML=active.length?"Genesis output: <strong>"+active.join(" · ")+"</strong>":"Press a physical control to see this player's live Genesis assignment.";
}
async function initControllerSettings(){
 let saved=null;
 try{if(window.GenesisSettings&&window.GenesisSettings.load)saved=await window.GenesisSettings.load();}catch(_){}
 if(saved&&validPadMap(saved.padMap)){
  S.padMap=saved.padMap.map(Number);
  S.pad2Map=validPadMap(saved.pad2Map)?saved.pad2Map.map(Number):DEFAULT_PAD_MAP.slice();
 }else{
  if(!validPadMap(S.padMap))S.padMap=DEFAULT_PAD_MAP.slice();
  if(!validPadMap(S.pad2Map))S.pad2Map=DEFAULT_PAD_MAP.slice();
 }
 S.padMapVersion=PAD_VERSION;
 renderBindings();$("mapSaved").textContent=saved&&saved.version===4?"Loaded separate P1/P2 controller profiles ✓":"P1/P2 controller profiles ready";
 setPadProfile(1);
 (function controllerPoll(){paintController();requestAnimationFrame(controllerPoll);})();
}
window.addEventListener("gamepadconnected",()=>{lastPadSignature="";paintController();});
window.addEventListener("gamepaddisconnected",()=>{lastPadSignature="";paintController();});
initControllerSettings();
'''
start=html.find("/* Genesis controller + live Gamepad API mapping */")
if start<0: raise SystemExit("dual-controller patch: current controller JavaScript marker missing")
end_marker="initControllerSettings();"
end=html.find(end_marker,start)
if end<0: raise SystemExit("dual-controller patch: current controller initialization marker missing")
end+=len(end_marker)
html=html[:start]+gamepad_js+html[end:]
# Keep P2's profile intact in the launch-time settings round trip.
old_launch_save="await window.GenesisSettings.save({version:PAD_VERSION,padMap:S.padMap});"
new_launch_save="await window.GenesisSettings.save({version:PAD_VERSION,padMap:S.padMap,pad2Map:S.pad2Map});"
if old_launch_save in html:
    html=html.replace(old_launch_save,new_launch_save,1)
elif new_launch_save not in html:
    raise SystemExit("dual-controller patch: launch-time controller settings save site not found")
if "pad2Map:S.pad2Map" not in html:
    raise SystemExit("dual-controller patch: P2 bindings are not preserved on launch")
HTML.write_text(html,encoding="utf-8")

# 3. SDL: second controller handle, independent mappings, and live P2 mask.
s=SDL.read_text(encoding="utf-8-sig")
for header in ("#include <stdlib.h>","#include <stdio.h>"):
    if header not in s:
        first_include=re.search(r"(?m)^#include[^\\n]*\\n",s)
        if not first_include: raise SystemExit("dual-controller patch: SDL include section missing")
        s=s[:first_include.end()]+header+"\\n"+s[first_include.end():]
if "static SDL_GameController *pad2 = NULL;" not in s:
    decl=re.search(r"(?m)^\s*static\s+SDL_GameController\s*\*\s*pad\s*(?:=\s*NULL)?\s*;",s)
    if not decl: raise SystemExit("dual-controller patch: SDL primary pad declaration not found")
    s=s[:decl.end()]+"\nstatic SDL_GameController *pad2 = NULL;\n"+s[decl.end():]
if "static int pad2_map[8]" not in s:
    decl=re.search(r"(?m)^\s*static\s+int\s+pad_map\s*\[\s*8\s*\]\s*=\s*\{[^}]*\}\s*;",s)
    if not decl: raise SystemExit("dual-controller patch: P1 pad_map declaration not found")
    s=s[:decl.end()]+"\nstatic int pad2_map[8] = {12,13,14,15,2,0,1,9};\nint md_player2_live_mask=0;\nint md_player2_connected=0;\nint md_local_coop_enabled=0;"+s[decl.end():]

# Parse P2 map keys from config.ini.
# P2 mapping is read from MEGATURRICAN_PAD2_MAP during open_pad().
# Make mapping helper device-agnostic and keep the existing P1 function.
if "mapped_controller_button_for" not in s:
    a,b=func_span(s,r"static\s+int\s+mapped_controller_button\s*\(\s*int\s+binding\s*\)","mapped_controller_button")
    block=s[a:b]
    block=block.replace("mapped_controller_button(int binding)","mapped_controller_button_for(SDL_GameController *device,int binding)",1)
    block=block.replace("SDL_GameControllerGetButton(pad,","SDL_GameControllerGetButton(device,")
    block=block.replace("SDL_GameControllerGetAxis(pad,","SDL_GameControllerGetAxis(device,")
    s=s[:a]+block+s[b:]
s=s.replace("mapped_controller_button(pad_map[i])","mapped_controller_button_for(pad,pad_map[i])")
if "static int readpad2(void)" not in s:
    reader=r"""
static int readpad2(void){
    int m=0;
    if(!pad2||!SDL_GameControllerGetAttached(pad2))return 0;
    static const int bits[8]={B_U,B_D,B_L,B_R,B_A,B_B,B_C,B_S};
    for(int i=0;i<8;i++)if(mapped_controller_button_for(pad2,pad2_map[i]))m|=bits[i];
    return m;
}
"""
    a,b=func_span(s,r"static\s+int\s+readpad\s*\(\s*void\s*\)","readpad")
    s=s[:b]+reader+s[b:]

open_pad=r"""static void open_pad(void){
    static int p2_map_env_loaded=0;
    if(!p2_map_env_loaded){
        const char *map=getenv("MEGATURRICAN_PAD2_MAP");
        if(map){
            int values[8];
            if(sscanf(map,"%d,%d,%d,%d,%d,%d,%d,%d",
                      &values[0],&values[1],&values[2],&values[3],
                      &values[4],&values[5],&values[6],&values[7])==8){
                for(int i=0;i<8;i++)if(values[i]>=-8&&values[i]<=15)pad2_map[i]=values[i];
            }
        }
        p2_map_env_loaded=1;
    }
    if(pad){SDL_GameControllerClose(pad);pad=NULL;}
    if(pad2){SDL_GameControllerClose(pad2);pad2=NULL;}
    for(int i=0;i<SDL_NumJoysticks();i++){
        if(!SDL_IsGameController(i))continue;
        SDL_GameController *candidate=SDL_GameControllerOpen(i);
        if(!candidate)continue;
        if(!pad)pad=candidate;
        else if(!pad2)pad2=candidate;
        else SDL_GameControllerClose(candidate);
        if(pad&&pad2)break;
    }
    md_player2_connected=(pad2&&SDL_GameControllerGetAttached(pad2))?1:0;
}"""
s=replace_func(s,r"\bstatic\s+void\s+open_pad\s*\(\s*void\s*\)",open_pad,"open_pad")
s=re.sub(r"if\s*\(\s*e\.type\s*==\s*SDL_CONTROLLERDEVICEREMOVED\s*&&\s*pad\s*\)\s*\{[^{}]*open_pad\(\)\s*;[^{}]*\}",
         "if(e.type==SDL_CONTROLLERDEVICEREMOVED){open_pad();}",s)
if "md_player2_live_mask=md_player2_connected?readpad2():0;" not in s:
    m=re.search(r"(?m)^(\s*)md_live_mask\s*=\s*[^;]*readpad\(\)[^;]*;",s)
    if not m: raise SystemExit("dual-controller patch: md_frame_hook P1 input line not found")
    indent=m.group(1)
    s=s[:m.end()]+f"\n{indent}md_player2_connected=(pad2&&SDL_GameControllerGetAttached(pad2))?1:0;\n{indent}md_player2_live_mask=md_player2_connected?readpad2():0;"+s[m.end():]
SDL.write_text(s,encoding="utf-8")

# 4. Expose controller port 2 through the emulator's existing pad_read(int p).
h=HARNESS.read_text(encoding="utf-8-sig")
if "extern int md_player2_live_mask;" not in h:
    m=re.search(r"(?m)^int\s+md_live_mask\s*=\s*0\s*;",h)
    if not m: raise SystemExit("dual-controller patch: harness md_live_mask declaration not found")
    h=h[:m.end()]+"\nextern int md_player2_live_mask;"+h[m.end():]
a,b=func_span(h,r"static\s+uint8_t\s+pad_read\s*\(\s*int\s+p\s*\)","pad_read")
block=h[a:b]
if "int b = (p==1) ? md_player2_live_mask : buttons();" not in block:
    block2,n=re.subn(r"\bint\s+b\s*=\s*buttons\s*\(\s*\)\s*;",
       "int b = (p==1) ? md_player2_live_mask : buttons();",block,count=1)
    if n!=1: raise SystemExit("dual-controller patch: could not route P2 Genesis port separately")
    h=h[:a]+block2+h[b:]
HARNESS.write_text(h,encoding="utf-8")

# Static contract checks before native compilation.
checks={
 "launcher settings preserve P1/P2 maps": "pad2Map" in main and "pad2_up" in main,
 "launcher offers separate profile tabs": 'id="p1Profile"' in html and 'id="p2Profile"' in html,
 "SDL opens two controller handles": "static SDL_GameController *pad2 = NULL;" in s and "SDL_GameControllerOpen(i)" in s,
 "SDL has independent P2 input reader": "static int readpad2(void)" in s,
 "P2 mask is sampled each frame": "md_player2_live_mask=md_player2_connected?readpad2():0;" in s,
 "Genesis port 2 consumes P2 mask": "int b = (p==1) ? md_player2_live_mask : buttons();" in h
}
for label,ok in checks.items():
    if not ok: raise SystemExit("dual-controller verification failed: "+label)
print("Installed two independent Genesis controller profiles and separate physical port-2 input.")
