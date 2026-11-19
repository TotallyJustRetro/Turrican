#!/usr/bin/env python3
"""Install persistent launcher audio settings, channel tests, and the supplied Windows game icon."""
from __future__ import annotations
import json, re, shutil, sys
from pathlib import Path

CSS = r"""
.audio-grid{display:grid;grid-template-columns:minmax(260px,.9fr) minmax(300px,1.1fr);gap:16px;align-items:start}
.audio-card{background:linear-gradient(155deg,#18202b,#0a0e14);border:1px solid #344153;border-radius:8px;padding:15px}
.audio-card h3{margin:0 0 10px;color:#f0b04b}
.audio-field{display:grid;gap:7px;margin:12px 0}
.audio-field label{font-size:12px;font-weight:800;letter-spacing:.6px}
.audio-field select,.audio-field input{width:100%}
.audio-note{font-size:12px;color:var(--mut);line-height:1.5}
.audio-channel-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.audio-channel{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px;border:1px solid #354153;border-radius:6px;background:#090e15;font-size:12px}
.audio-status{min-height:34px;margin-top:10px;padding:9px 10px;border:1px solid #354153;border-radius:5px;background:#080c12;color:#bbc7d6;font-size:12px}
.audio-status.warn{border-color:#9a6c2e;color:#f3d09a}
.audio-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
@media(max-width:760px){.audio-grid{grid-template-columns:1fr}.audio-channel-list{grid-template-columns:1fr}}
"""
MARKUP = r'''<section class="tab" id="t-audio">
 <div class="audio-grid">
  <div class="audio-card">
   <h3>Audio output</h3>
   <div class="audio-field"><label for="audioMode">OUTPUT MODE</label>
    <select id="audioMode"><option value="mono">Mono · 1 channel</option><option value="stereo">Stereo · 2 channels</option><option value="surround">Surround · 5.1 channels</option></select>
   </div>
   <div class="audio-field"><label for="audioVolume">MASTER VOLUME <strong id="audioVolumeLabel">100%</strong></label>
    <input id="audioVolume" type="range" min="0" max="100" value="100" step="1">
   </div>
   <p class="audio-note" id="audioModeNote"></p>
   <p class="audio-note">Mode and volume changes apply the next time the game is launched.</p>
   <p class="audio-note">The original game audio is a stereo FM/PSG mix. 5.1 mode preserves front left/right and creates center, subwoofer and delayed rear ambience from that stereo mix; it is an upmix, not original discrete 5.1 recordings. Windows must be configured for 5.1 speakers.</p>
   <div class="audio-status" id="audioSaveStatus" role="status" aria-live="polite">Audio preferences are saved on this PC.</div>
  </div>
  <div class="audio-card">
   <h3>Speaker / channel test</h3>
   <p class="audio-note">Test each available output channel independently, or run the complete sequence.</p>
   <div class="audio-channel-list" id="audioChannels"></div>
   <div class="audio-actions"><button class="b" id="audioTestAll" type="button">TEST ALL CHANNELS</button><button class="b" id="audioTestStop" type="button">STOP TEST</button></div>
   <div class="audio-status" id="audioTestStatus" role="status" aria-live="polite">Choose an output mode, then test your speakers.</div>
  </div>
 </div>
</section>'''

JS = r'''(() => {
 "use strict";
 const KEY="megaTurricanAudioSettings.v1", defaults={mode:"stereo",volume:100};
 const layouts={
  mono:[["Mono output",440]],
  stereo:[["Front Left",440],["Front Right",554]],
  surround:[["Front Left",440],["Front Right",494],["Center",554],["LFE / Subwoofer",82],["Surround Left",659],["Surround Right",784]]
 };
 const $=id=>document.getElementById(id);
 let state={...defaults}, context=null, source=null;
 function load(){try{const s=JSON.parse(localStorage.getItem(KEY)||"{}");if(layouts[s.mode])state.mode=s.mode;if(Number.isFinite(Number(s.volume)))state.volume=Math.max(0,Math.min(100,Math.round(Number(s.volume))));}catch(_){}}
 function status(id,msg,warn){const e=$(id);if(e){e.textContent=msg;e.className="audio-status"+(warn?" warn":"");}}
 function save(){localStorage.setItem(KEY,JSON.stringify(state));status("audioSaveStatus","Saved on this PC · "+state.mode.toUpperCase()+" · "+state.volume+"% volume");}
 function note(){return state.mode==="mono"?"Mono combines the original left and right mix into one output channel.":state.mode==="surround"?"5.1 uses six channels: front left/right, center, LFE and delayed rear ambience.":"Stereo preserves the original left/right game mix.";}
 function render(){ $("audioMode").value=state.mode;$("audioVolume").value=state.volume;$("audioVolumeLabel").textContent=state.volume+"%";$("audioModeNote").textContent=note();const host=$("audioChannels");host.replaceChildren();layouts[state.mode].forEach((ch,i)=>{const row=document.createElement("div"),name=document.createElement("strong"),b=document.createElement("button");row.className="audio-channel";name.textContent=ch[0];b.className="b";b.type="button";b.textContent="TEST";b.addEventListener("click",()=>play([i]));row.append(name,b);host.append(row);});}
 function stop(){try{if(source)source.stop();}catch(_){}try{if(source)source.disconnect();}catch(_){}source=null;if(context){const c=context;context=null;c.close().catch(()=>{});}}
 async function play(selected){stop();if(state.volume===0){status("audioTestStatus","Master volume is 0%. Raise it to hear the test.",true);return;}const chans=layouts[state.mode],count=chans.length,AC=window.AudioContext||window.webkitAudioContext;if(!AC){status("audioTestStatus","Audio testing is unavailable in this launcher.",true);return;}let c;try{c=new AC({latencyHint:"interactive"});context=c;if(count===6&&c.destination.maxChannelCount<6){status("audioTestStatus","Windows exposes only "+c.destination.maxChannelCount+" output channels. Configure the playback device for 5.1 in Windows Sound settings, then reopen the launcher.",true);stop();return;}c.destination.channelCountMode="explicit";c.destination.channelInterpretation="speakers";c.destination.channelCount=count;await c.resume();}catch(e){status("audioTestStatus","Could not open "+count+" output channels: "+(e.message||e),true);stop();return;}
  const seq=selected===null?chans.map((_,i)=>i):selected,rate=c.sampleRate,tone=.48,gap=.18,block=tone+gap,buf=c.createBuffer(count,Math.ceil(block*seq.length*rate),rate),amp=.2*state.volume/100;
  seq.forEach((ix,j)=>{const data=buf.getChannelData(ix),start=Math.floor(j*block*rate),n=Math.floor(tone*rate),hz=chans[ix][1];for(let i=0;i<n;i++){const t=i/rate,edge=Math.min(1,t/.025,(tone-t)/.045);data[start+i]=Math.sin(2*Math.PI*hz*t)*amp*Math.max(0,edge);}});
  const s=c.createBufferSource();s.buffer=buf;s.channelCount=count;s.channelCountMode="explicit";s.channelInterpretation="speakers";s.connect(c.destination);source=s;s.onended=()=>{s.disconnect();if(source===s)source=null;if(context===c){context=null;c.close().catch(()=>{});}status("audioTestStatus","Channel test finished.");};status("audioTestStatus","Playing: "+seq.map(i=>chans[i][0]).join(" → "));s.start();
 }
 function init(){load();render();save();$("audioMode").addEventListener("change",e=>{if(layouts[e.target.value]){state.mode=e.target.value;save();render();status("audioTestStatus","Output mode saved. Test your speakers.");}});$("audioVolume").addEventListener("input",e=>{state.volume=Math.max(0,Math.min(100,Number(e.target.value)||0));$("audioVolumeLabel").textContent=state.volume+"%";save();});$("audioTestAll").addEventListener("click",()=>play(null));$("audioTestStop").addEventListener("click",()=>{stop();status("audioTestStatus","Channel test stopped.");});window.addEventListener("beforeunload",stop);}
 window.getMegaTurricanAudioSettings=()=>({...state});
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();'''

C_AUDIO = r'''/* ---- audio output: stereo chip mix, mono fold-down, or six-channel 5.1 upmix ---- */
static SDL_AudioDeviceID adev;
static int audio_channels=2;
static char audio_status[80]="stereo";
static int16_t audio_sat(double v){if(v>32767.0)v=32767.0;if(v< -32768.0)v=-32768.0;return (int16_t)v;}
static void audio_open(void){
 if(!cfg.audio){snprintf(audio_status,sizeof audio_status,"audio disabled");return;}
 int requested=cfg.audio_mode==0?1:cfg.audio_mode==2?6:2;
 SDL_AudioSpec want,have;memset(&want,0,sizeof want);want.freq=48000;want.format=AUDIO_S16SYS;want.channels=(Uint8)requested;want.samples=1024;
 adev=SDL_OpenAudioDevice(NULL,0,&want,&have,0);int fallback=0;
 if(!adev&&requested!=2){requested=2;want.channels=2;adev=SDL_OpenAudioDevice(NULL,0,&want,&have,0);fallback=1;}
 if(!adev){snprintf(audio_status,sizeof audio_status,"audio unavailable");fprintf(stderr,"audio: %s\n",SDL_GetError());return;}
 audio_channels=have.channels;
 if(audio_channels!=1&&audio_channels!=2&&audio_channels!=6){SDL_CloseAudioDevice(adev);adev=0;audio_channels=2;snprintf(audio_status,sizeof audio_status,"unsupported output layout");return;}
 if(audio_channels==1)snprintf(audio_status,sizeof audio_status,"mono");
 else if(audio_channels==6&&!fallback)snprintf(audio_status,sizeof audio_status,"5.1 surround upmix");
 else if(fallback&&cfg.audio_mode==2)snprintf(audio_status,sizeof audio_status,"stereo fallback (5.1 unavailable)");
 else if(fallback&&cfg.audio_mode==0)snprintf(audio_status,sizeof audio_status,"stereo fallback (mono unavailable)");
 else snprintf(audio_status,sizeof audio_status,"stereo");
 SDL_PauseAudioDevice(adev,0);
}
static void audio_pump(void){
 if(!adev)return;
 static int16_t in[(4096+1)*2],out[8192*6],last[2]={0,0},dl[1024]={0},dr[1024]={0};
 static double pos=0;static float lfe=0;static int delay_pos=0;
 int n=md_audio_read(in+2,4096);if(n<=0)return;in[0]=last[0];in[1]=last[1];
 const double step=53267.0/48000.0;int m=0,vol=cfg.volume;if(vol<0)vol=0;if(vol>100)vol=100;
 for(;;){double p=pos+m*step;int i=(int)p;if(i>=n||m>=8192)break;double f=p-i;
  double left=(in[i*2]+(in[(i+1)*2]-in[i*2])*f)*vol/100.0;
  double right=(in[i*2+1]+(in[(i+1)*2+1]-in[i*2+1])*f)*vol/100.0;
  if(audio_channels==1)out[m]=audio_sat((left+right)*.5);
  else if(audio_channels==2){double ml=left,mr=right;if(cfg.audio_mode==0){ml=mr=(left+right)*.5;}out[m*2]=audio_sat(ml);out[m*2+1]=audio_sat(mr);}
  else{
   int rp=(delay_pos+1024-576)&1023;double rl=dl[rp]*.24,rr=dr[rp]*.24;
   dl[delay_pos]=audio_sat(left);dr[delay_pos]=audio_sat(right);delay_pos=(delay_pos+1)&1023;
   double mid=(left+right)*.5;lfe+=.0156f*((float)mid-lfe);
   /* SDL 5.1 order: FL, FR, FC, LFE, SL, SR. */
   out[m*6]=audio_sat(left);out[m*6+1]=audio_sat(right);out[m*6+2]=audio_sat(mid*.70);
   out[m*6+3]=audio_sat(lfe*.65);out[m*6+4]=audio_sat(rl);out[m*6+5]=audio_sat(rr);
  }m++;
 }
 pos=pos+m*step-n;last[0]=in[n*2];last[1]=in[n*2+1];
 if(SDL_GetQueuedAudioSize(adev)>(Uint32)(48000*audio_channels*2/5))SDL_ClearQueuedAudio(adev);
 SDL_QueueAudio(adev,out,(Uint32)(m*audio_channels*sizeof(int16_t)));
}'''

def once(s, old, new, label):
    n=s.count(old)
    if n!=1: raise RuntimeError("Expected one "+label+" anchor, found "+str(n))
    return s.replace(old,new,1)


def upscale_ico_to_256(data: bytes) -> bytes:
    """Resize the supplied small PNG/DIB ICO into a 256x256 Windows icon."""
    from io import BytesIO
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate the 256px launcher icon.") from exc
    try:
        with Image.open(BytesIO(data)) as original:
            image = original.convert("RGBA")
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            image = image.resize((256, 256), resampling)
            output = BytesIO()
            image.save(output, format="ICO", sizes=[(256, 256)])
            result = output.getvalue()
    except Exception as exc:
        raise RuntimeError("Could not resize the supplied Mega Turrican ICO: " + str(exc)) from exc
    if len(result) < 22 or result[2:4] != b"\\x01\\x00":
        raise RuntimeError("Pillow did not produce a valid Windows ICO.")
    width = result[6]
    height = result[7]
    if width not in (0, 256) or height not in (0, 256):
        raise RuntimeError("Generated launcher icon is not 256x256.")
    return result

def patch_icon(project):
    icon=Path(__file__).resolve().parent/"MegaTurrican.ico"
    if not icon.is_file(): raise RuntimeError("build-overrides/MegaTurrican.ico is missing")
    large_icon=Path(__file__).resolve().parent/"MegaTurrican-build.ico"
    large_icon.write_bytes(upscale_ico_to_256(icon.read_bytes()))
    d=project/"launcher"/"build";d.mkdir(parents=True,exist_ok=True);shutil.copy2(large_icon,d/"MegaTurrican.ico")
    p=project/"launcher"/"package.json";pkg=json.loads(p.read_text(encoding="utf-8-sig"))
    build=pkg.setdefault("build",{});build.setdefault("win",{})["icon"]="build/MegaTurrican.ico"
    if isinstance(build.get("files"),list) and "audio-settings.js" not in build["files"]:build["files"].append("audio-settings.js")
    p.write_text(json.dumps(pkg,indent=2)+"\\n",encoding="utf-8")
    print("Generated 256x256 icon and installed it for the launcher and native executable.")

def patch_sdl(project):
    p=project/"runtime"/"sdl_main.c";s=p.read_text(encoding="utf-8-sig")
    if "audio_mode" not in s:
        s,n=re.subn(r"int\s+fullscreen\s*,\s*vsync\s*,\s*audio\s*,\s*volume\s*;","int fullscreen, vsync, audio, volume, audio_mode;",s,count=1)
        if n!=1:raise RuntimeError("Could not add native audio mode setting.")
        m=re.search(r"}\s*cfg\s*=\s*\{([^}]*)\};",s)
        if not m:raise RuntimeError("Could not locate native config defaults.")
        vals=[x.strip() for x in m.group(1).split(",")]
        if len(vals)==10:vals.insert(8,"1")
        elif len(vals)!=11:raise RuntimeError("Unexpected SDL config default field count: "+str(len(vals)))
        s=s[:m.start()]+"} cfg = { "+", ".join(vals)+" };"+s[m.end():]
    if '"audio_mode"' not in s:
        pat=re.compile(r'((?:else\s+)?if\(!strcmp\(l,\s*"volume"\)\)\s*cfg\.volume\s*=\s*atoi\(v\);)')
        s,n=pat.subn(lambda m:m.group(1)+' else if(!strcmp(l, "audio_mode")) cfg.audio_mode = atoi(v);',s,count=1)
        if n!=1:raise RuntimeError("Could not locate native volume config parser.")
    if "stereo chip mix, mono fold-down" not in s:
        start=s.find("/* ---- audio:");end=s.find("static void toggle_fs",start)
        if start<0 or end<0:raise RuntimeError("Could not locate native SDL audio block.")
        s=s[:start]+C_AUDIO+"\n\n"+s[end:]
    if "audio_status);" not in s:
        a=s.find("static void title(");b=s.find("\nvoid md_frame_hook",a)
        if a<0 or b<a:raise RuntimeError("Could not locate native game title function.")
        block=s[a:b]
        pat=re.compile(r'snprintf\s*\(\s*t\s*,\s*sizeof\s+t\s*,.*?\);',re.S)
        rep='snprintf(t, sizeof t, "Mega Turrican  |  %s  |  shader %d  |  %s%s  |  %s", aspect_name[cfg.aspect], cfg.shader, cfg.integer ? "integer" : "fit", cfg.linear ? " +linear" : "", audio_status);'
        block,n=pat.subn(rep,block,count=1)
        if n!=1:raise RuntimeError("Could not append negotiated audio status to game title.")
        s=s[:a]+block+s[b:]
    p.write_text(s,encoding="utf-8")
    print("Installed native mono, stereo and six-channel 5.1 audio routing.")

def patch_main(project):
    p=project/"launcher"/"main.js";s=p.read_text(encoding="utf-8-sig")
    if "audio_mode=" not in s:
        bt=chr(96)
        anchor="    "+bt+"vsync="+"$"+"{settings.vsync === false ? 0 : 1}"+bt+","
        rows=[
          "    "+bt+"audio=1"+bt+",",
          "    "+bt+"audio_mode="+"$"+"{settings.audioMode === 'mono' ? 0 : settings.audioMode === 'surround' ? 2 : 1}"+bt+",",
          "    "+bt+"volume="+"$"+"{Math.max(0, Math.min(100, Number(settings.volume ?? 100) || 0))}"+bt+","
        ]
        s=once(s,anchor,anchor+"\n"+"\n".join(rows),"native audio config")
    p.write_text(s,encoding="utf-8")

def patch_html(project):
    p=project/"launcher"/"index.html";s=p.read_text(encoding="utf-8-sig")
    if ".audio-grid" not in s:s=once(s,"</style>",CSS+"\n</style>","audio stylesheet")
    if '["audio","Audio"]' not in s:
        tabs_match=re.search(r'const\s+tabs\s*=\s*\[(.*?)\];',s,re.S)
        if not tabs_match:raise RuntimeError("Could not locate launcher tab registry.")
        entries=tabs_match.group(1)
        entries_new,n=re.subn(r'(\[\s*["\']ctl["\']\s*,\s*["\']Controls["\']\s*\]\s*,?)',lambda m:m.group(1)+'["audio","Audio"],',entries,count=1)
        if n!=1:raise RuntimeError("Could not add Audio to the launcher tab registry.")
        s=s[:tabs_match.start(1)]+entries_new+s[tabs_match.end(1):]
    if 'id="t-audio"' not in s:
        m=re.search(r'<section\b[^>]*id=["\']t-ctl["\'][^>]*>.*?</section>',s,re.S)
        if not m:raise RuntimeError("Could not locate Controls tab.")
        s=s[:m.end()]+"\n"+MARKUP+s[m.end():]
    if "audio-settings.js" not in s:s=s.replace("</body>",'<script src="audio-settings.js"></script>\n</body>',1)
    launch="const result=await window.GenesisCore.run(rom,S);"
    if "getMegaTurricanAudioSettings()" not in s:
        replacement='const audioPrefs=window.getMegaTurricanAudioSettings?window.getMegaTurricanAudioSettings():{mode:"stereo",volume:100};\n  const launchSettings={...S,audioMode:audioPrefs.mode,volume:audioPrefs.volume};\n  const result=await window.GenesisCore.run(rom,launchSettings);'
        s=once(s,launch,replacement,"launcher audio settings handoff")
    p.write_text(s,encoding="utf-8")
    (project/"launcher"/"audio-settings.js").write_text(JS,encoding="utf-8")
    print("Added persistent Audio tab and real per-output-channel tests.")

def patch(project):
    patch_icon(project);patch_sdl(project);patch_main(project);patch_html(project)
    print("Mega Turrican audio/icon patch completed.")

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: patch-audio.py PROJECT_ROOT")
    patch(Path(sys.argv[1]).resolve())
