#!/usr/bin/env python3
"""Add a persistent launcher Video tab and pass the selected SDL renderer to Windows."""
from __future__ import annotations
import json, re, sys
from pathlib import Path

CSS = r"""
.video-grid{display:grid;grid-template-columns:minmax(260px,.9fr) minmax(300px,1.1fr);gap:16px;align-items:start}
.video-card{background:linear-gradient(155deg,#18202b,#0a0e14);border:1px solid #344153;border-radius:8px;padding:15px}
.video-card h3{margin:0 0 10px;color:#f0b04b}
.video-field{display:grid;gap:7px;margin:12px 0}
.video-field label{font-size:12px;font-weight:800;letter-spacing:.6px}
.video-field select{width:100%}
.video-note{font-size:12px;color:var(--mut);line-height:1.5}
.video-status{min-height:34px;margin-top:10px;padding:9px 10px;border:1px solid #354153;border-radius:5px;background:#080c12;color:#bbc7d6;font-size:12px}
@media(max-width:760px){.video-grid{grid-template-columns:1fr}}
"""
MARKUP = r'''<section class="tab" id="t-video">
 <div class="video-grid">
  <div class="video-card">
   <h3>Graphics renderer</h3>
   <div class="video-field"><label for="videoRenderer">RENDERER</label>
    <select id="videoRenderer">
     <option value="auto">Automatic · Recommended</option>
     <option value="direct3d11">Direct3D 11 · Windows</option>
     <option value="opengl">OpenGL</option>
    </select>
   </div>
   <p class="video-note" id="videoRendererNote"></p>
   <p class="video-note">Renderer changes take effect the next time Mega Turrican is launched. The current game window must be closed and reopened.</p>
   <div class="video-status" id="videoSaveStatus" role="status" aria-live="polite">Video preferences are saved on this PC.</div>
  </div>
  <div class="video-card">
   <h3>About renderers</h3>
   <p class="video-note"><strong>Automatic</strong> lets SDL choose the best accelerated renderer available on this PC. This is the safest option.</p>
   <p class="video-note"><strong>Direct3D 11</strong> asks SDL to use its Direct3D 11 renderer when the installed SDL build and graphics driver support it.</p>
   <p class="video-note"><strong>OpenGL</strong> asks SDL to use its OpenGL renderer when available. This can help compare driver behavior on different systems.</p>
   <p class="video-note">These choices change the existing SDL presentation renderer. They do not replace the Genesis CPU/VDP simulation or enable a separate Vulkan/Direct3D 12 backend.</p>
  </div>
 </div>
</section>'''

JS = r'''(() => {
 "use strict";
 const KEY="megaTurricanVideoSettings.v1";
 const valid=new Set(["auto","direct3d11","opengl"]);
 let renderer="auto";
 const $=id=>document.getElementById(id);
 function load(){try{const s=JSON.parse(localStorage.getItem(KEY)||"{}");if(valid.has(s.renderer))renderer=s.renderer;}catch(_){}}
 function note(){return renderer==="direct3d11"?"Requests SDL's Direct3D 11 renderer. If it is unavailable or cannot initialize, SDL falls back to its normal default renderer.":renderer==="opengl"?"Requests SDL's OpenGL renderer. If it is unavailable or cannot initialize, SDL falls back to its normal default renderer.":"SDL chooses the available renderer automatically.";}
 function save(){localStorage.setItem(KEY,JSON.stringify({renderer}));$("videoSaveStatus").textContent="Saved on this PC · "+$("videoRenderer").selectedOptions[0].textContent;}
 function init(){load();$("videoRenderer").value=renderer;$("videoRendererNote").textContent=note();save();$("videoRenderer").addEventListener("change",e=>{renderer=valid.has(e.target.value)?e.target.value:"auto";$("videoRendererNote").textContent=note();save();});}
 window.getMegaTurricanVideoSettings=()=>({renderer});
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();'''

def once(s: str, old: str, new: str, label: str) -> str:
    n=s.count(old)
    if n!=1: raise RuntimeError(f"{label}: expected one anchor, found {n}")
    return s.replace(old,new,1)

def patch_html(project: Path) -> None:
    p=project/"launcher"/"index.html"
    s=p.read_text(encoding="utf-8-sig")
    if ".video-grid" not in s:
        s=once(s,"</style>",CSS+"\n</style>","video stylesheet")
    if '["video","Video"]' not in s:
        m=re.search(r'const\s+tabs\s*=\s*\[(.*?)\];',s,re.S)
        if not m: raise RuntimeError("Could not locate launcher tab registry.")
        entries=m.group(1)
        if re.search(r'\[\s*["\']audio["\']',entries):
            entries_new=re.sub(r'(\[\s*["\']audio["\']\s*,\s*["\']Audio["\']\s*\]\s*,?)',lambda x:x.group(1)+'["video","Video"],',entries,count=1)
        else:
            entries_new=re.sub(r'(\[\s*["\']ctl["\']\s*,\s*["\']Controls["\']\s*\]\s*,?)',lambda x:x.group(1)+'["video","Video"],',entries,count=1)
        if entries_new==entries: raise RuntimeError("Could not add Video to the launcher tab registry.")
        s=s[:m.start(1)]+entries_new+s[m.end(1):]
    if 'id="t-video"' not in s:
        m=re.search(r'<section\b[^>]*id=["\']t-audio["\'][^>]*>.*?</section>',s,re.S)
        if not m: m=re.search(r'<section\b[^>]*id=["\']t-ctl["\'][^>]*>.*?</section>',s,re.S)
        if not m: raise RuntimeError("Could not locate Audio or Controls tab for Video insertion.")
        s=s[:m.end()]+"\n"+MARKUP+s[m.end():]
    if "video-settings.js" not in s:
        s=once(s,"</body>",'<script src="video-settings.js"></script>\n</body>',"video settings script include")
    launch='const result=await window.GenesisCore.run(rom,launchSettings);'
    if "getMegaTurricanVideoSettings()" not in s:
        replacement='const videoPrefs=window.getMegaTurricanVideoSettings?window.getMegaTurricanVideoSettings():{renderer:"auto"};\n  launchSettings.renderer=videoPrefs.renderer;\n  const result=await window.GenesisCore.run(rom,launchSettings);'
        s=once(s,launch,replacement,"video settings handoff")
    p.write_text(s,encoding="utf-8")
    (project/"launcher"/"video-settings.js").write_text(JS,encoding="utf-8")
    pkg_path=project/"launcher"/"package.json"
    pkg=json.loads(pkg_path.read_text(encoding="utf-8-sig"))
    files=pkg.setdefault("build",{}).setdefault("files",[])
    if isinstance(files,list) and "video-settings.js" not in files: files.append("video-settings.js")
    pkg_path.write_text(json.dumps(pkg,indent=2)+"\n",encoding="utf-8")

def patch_main(project: Path) -> None:
    p=project/"launcher"/"main.js"
    s=p.read_text(encoding="utf-8-sig")
    # Build a clean child-process environment. In Automatic mode we remove
    # inherited SDL_RENDER_DRIVER instead of passing the string "undefined".
    # That guarantees SDL can perform its normal renderer selection.
    spawn_anchor="    const child = spawn(exe, [romPath, configPath], {"
    setup="""    const childEnv = {
      ...process.env,
      MEGATURRICAN_CONFIG_DIR: process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(app.getPath('exe'))
    };
    if (settings.renderer === 'opengl') childEnv.SDL_RENDER_DRIVER = 'opengl';
    else if (settings.renderer === 'direct3d11') childEnv.SDL_RENDER_DRIVER = 'direct3d11';
    else delete childEnv.SDL_RENDER_DRIVER;
"""
    if "const childEnv = {" not in s:
        s=once(s,spawn_anchor,setup+spawn_anchor,"native process environment setup")
    old="env: { ...process.env, MEGATURRICAN_CONFIG_DIR: process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(app.getPath('exe')) },"
    new="env: childEnv,"
    if old in s:
        s=s.replace(old,new,1)
    elif "env: childEnv," not in s:
        raise RuntimeError("Could not connect renderer preferences to the native game process environment.")
    p.write_text(s,encoding="utf-8")

def patch(project: Path) -> None:
    patch_html(project)
    patch_main(project)
    print("Added persistent Video tab: Automatic, Direct3D 11, and OpenGL.")

if __name__=="__main__":
    if len(sys.argv)!=2: raise SystemExit("usage: patch-video-renderer.py PROJECT_ROOT")
    patch(Path(sys.argv[1]).resolve())
