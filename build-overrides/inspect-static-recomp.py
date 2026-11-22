#!/usr/bin/env python3
"""Emit only runtime type/field names needed for native save-state integration."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT=Path(sys.argv[1]).resolve()
FILES=[
 "recomp_gen.c","runtime/harness.c","runtime/sdl_main.c","runtime/vdp.c","runtime/vdp.h",
 "runtime/m68k_rt.h","runtime/m68k_interp.c","runtime/z80.h",
 "runtime/ym2612.h","runtime/ym2612.c","runtime/psg.h","runtime/psg.c",
]
OUT=[]
def emit(s=""): OUT.append(s)

field=re.compile(r"^\s*(?:unsigned\s+)?(?:u?int(?:8|16|32|64)_t|char|short|int|long|size_t|bool|double|float|struct\s+\w+|[A-Z]\w*)\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*[,;]")
func=re.compile(r"^\s*(?:(?:static|inline|extern)\s+)*(?:void|int|bool|char|short|long|size_t|u?int(?:8|16|32|64)_t|[A-Z]\w*)\s+([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*[;{]")
for rel in FILES:
 p=ROOT/rel
 emit(f"[{rel}]")
 if not p.exists():
  emit("MISSING")
  continue
 lines=p.read_text(encoding="utf-8",errors="replace").splitlines()
 if rel=="recomp_gen.c":
  import collections
  src="\\n".join(lines)
  counts=collections.Counter(m.group(1).upper() for m in re.finditer(r"0xFFFF((?:BC|BD|BE|BF)[0-9A-Fa-f]{2})",src))
  emit("RAM_ADDRESS_COUNTS (generated absolute RAM references)")
  for address,count in sorted(counts.items()):
   emit(f"RAM_ADDRESS {address} count={count}")
  emit("RAM_ADDRESS_WRITE_CONTEXTS")
  for n,line in enumerate(lines,1):
   if re.search(r"WR(?:8|16|32)\(.*0xFFFF(?:BC|BD|BE|BF)",line):
    emit(f"RAM_WRITE line={n} {line[:300]}")
    for k in range(max(0,n-4),min(len(lines),n+4)):
     emit(f"  {k+1}: {lines[k][:240]}")

  # Build the generated 68k call graph around the actual chip-write routines.
  # Earlier scans found only Z80 driver uploads; a title click usually enters a
  # shared high-level routine which queues a cue for the per-frame sound engine.
  fn_starts=[]
  fn_re=re.compile(r"^\\s*static\\s+void\\s+(f_[A-Za-z0-9_]+)\\s*\\(M68K\\s*\\*c\\)")
  for i,line in enumerate(lines):
   m=fn_re.match(line)
   if m: fn_starts.append((i,m.group(1)))
  fn_data={}
  calls_by_name={}
  callers_by_name={}
  for fi,(start,name) in enumerate(fn_starts):
   end=fn_starts[fi+1][0] if fi+1<len(fn_starts) else len(lines)
   body=lines[start:end]
   fn_data[name]=(start,end,body)
   calls=[]
   for k,line in enumerate(body):
    for target in re.findall(r"\\b(f_[A-Za-z0-9_]+)\\s*\\(c\\)",line):
     if target!=name and target not in calls:calls.append(target)
     callers_by_name.setdefault(target,[]).append((name,start+k,line))
   calls_by_name[name]=calls

  sound_re=re.compile(r"0x(?:FFFF)?(?:A0400[0-3]|C00011|A000[0-9A-Fa-f]{4}|A11100|A11200)",re.I)
  sound_state_re=re.compile(r"0xFFFF(?:B[0-9A-Fa-f][0-9A-Fa-f]{2}|08[0-9A-Fa-f]{2})",re.I)
  emit("GENERATED_SOUND_CHIP_WRITERS")
  sound_targets=set()
  for name,(start,end,body) in fn_data.items():
   hits=[(start+k,line) for k,line in enumerate(body) if sound_re.search(line)]
   if not hits:continue
   sound_targets.add(name)
   emit(f"CHIP_FUNCTION name={name} declaration_line={start+1} accesses={len(hits)}")
   for idx,line in hits:
    emit(f"  {idx+1}: {line[:360]}")
    for q in range(max(start,idx-2),min(end,idx+3)):
     if q!=idx:emit(f"    {q+1}: {lines[q][:300]}")

  emit("GENERATED_SOUND_STATE_RAM_WRITERS")
  for name,(start,end,body) in fn_data.items():
   hits=[(start+k,line) for k,line in enumerate(body) if sound_state_re.search(line)]
   writes=[(idx,line) for idx,line in hits if re.search(r"\\bWR(?:8|16|32)\\s*\\(",line)]
   if not writes:continue
   emit(f"SOUND_STATE_FUNCTION name={name} declaration_line={start+1} state_refs={len(hits)} writes={len(writes)}")
   for idx,line in writes[:48]:
    emit(f"  {idx+1}: {line[:360]}")
    for q in range(max(start,idx-2),min(end,idx+3)):
     if q!=idx:emit(f"    {q+1}: {lines[q][:300]}")

  # Walk backwards from known YM/PSG port writers. This reveals whether a
  # call is initialization, per-frame music service, or a higher-level cue
  # request, and captures the RAM arguments at each call site.
  emit("GENERATED_SOUND_CALLER_CHAINS")
  seeds=sorted(sound_targets)
  for seed in seeds:
   frontier=[(seed,0,[seed])]
   seen={seed}
   emit(f"SOUND_CALLER_CHAIN seed={seed}")
   while frontier:
    target,depth,path=frontier.pop(0)
    if depth>=6:continue
    parents=callers_by_name.get(target,[])
    for parent,idx,line in parents:
     if parent in path:continue
     emit(f"  DEPTH={depth+1} caller={parent} line={idx+1} calls={target}")
     emit(f"    {line[:420]}")
     if parent not in seen and depth<5:
      seen.add(parent)
      frontier.append((parent,depth+1,path+[parent]))
   emit(f"  UNIQUE_CALLERS={len(seen)-1}")

  # Also show controller-poll and title/menu functions that share the sound
  # state variables, even when the request is indirect through a RAM queue.
  emit("GENERATED_CONTROLLER_SOUND_STATE_FUNCTIONS")
  controller_re=re.compile(r"0xA1000[0-7]|0xFFFF(?:B[0-3][0-9A-Fa-f]{2}|08[0-9A-Fa-f]{2})",re.I)
  controller_functions=[]
  for name,(start,end,body) in fn_data.items():
   hits=[(start+k,line) for k,line in enumerate(body) if controller_re.search(line)]
   if any(re.search(r"0xA1000[0-7]",line,re.I) for _,line in hits) and any(sound_state_re.search(line) for _,line in hits):
    controller_functions.append(name)
    emit(f"CONTROLLER_SOUND_STATE_FUNCTION name={name} declaration_line={start+1} hits={len(hits)}")
    for idx,line in hits[:80]:emit(f"  {idx+1}: {line[:360]}")

 in_struct=False
 struct_depth=0
 for n,line in enumerate(lines,1):
  t=line.strip()
  if re.search(r"\b(?:typedef\s+)?struct\b",t):
   in_struct=True
   struct_depth+=t.count("{")-t.count("}")
   emit(f"TYPE line={n} {t[:110]}")
   continue
  if in_struct:
   struct_depth+=t.count("{")-t.count("}")
   if ";" in t and not t.startswith(("/*","*","//")):
    if rel.endswith(".h"):
     emit(f"STRUCT_FIELD line={n} {t[:220]}")
    else:
     m=field.match(line)
     if m:
      emit(f"FIELD line={n} name={m.group(1)} array={m.group(2) or '-'}")
   if struct_depth<=0 and "}" in t: in_struct=False
  if rel in ("runtime/ym2612.c","runtime/psg.c") and n<=55:
   if re.search(r"typedef|struct|static|const|\b(?:ym|psg)\b",t,re.I):
    emit(f"STATE_DECL line={n} {t[:220]}")
  if rel=="recomp_gen.c":
   if re.search(r"\b(?:uint32_t\s+rt_shadow|int\s+rt_sp)\b",t):
    emit(f"RECOMP_GLOBAL line={n} {t[:220]}")
   if "L_192C" in t:
    emit(f"CONTINUES_PATCH_SITE line={n} {t[:320]}")
   if "L_1796" in t or "L_17A0" in t:
    lo=max(0,n-5); hi=min(len(lines),n+18)
    emit(f"WEAPON_DEATH_CONTEXT line={n}")
    for k in range(lo,hi):
     emit(f"  {k+1}: {lines[k][:260]}")
  if rel in ("runtime/ym2612.c","runtime/psg.c") and n<=80:
   if re.search(r"typedef|struct|static|const|\b(?:ym|psg)\b",t,re.I):
    emit(f"STATE_DECL line={n} {t[:220]}")
  m=func.match(line)
  if m and re.search(r"read|write|memory|ram|save|load|frame|reset|state|execute|run|boot|snapshot|draw|sprite|plane|shade|audio|sound|sample|ym|mix|timer|hud|present|render|input|restart|quit",m.group(1),re.I):
   params=re.sub(r"\s+"," ",m.group(2).strip())
   emit(f"FUNCTION line={n} name={m.group(1)} params={params[:120] or '-'}")
   if (rel=="runtime/harness.c" and m.group(1) in ("md_boot","md_load_rom","md_audio_read","md_frame_hook","readpad","sound_tick")) or (rel=="runtime/sdl_main.c" and m.group(1) in ("md_frame_hook","readpad")) or (rel=="runtime/ym2612.c" and re.search(r"ym_(?:write|sample|init)",m.group(1))) or (rel=="runtime/vdp.c" and re.search(r"sprite|plane|shade|render|window",m.group(1),re.I)) or (rel=="runtime/sdl_main.c" and re.search(r"shade|draw_str|present|frame|input|event",m.group(1),re.I)):
    depth=0; brace=-1; end=-1
    for q in range(n-1,min(len(lines),n+300)):
     if "{" in lines[q] and brace<0: brace=q
     if brace>=0:
      depth+=lines[q].count("{")-lines[q].count("}")
      if depth==0:
       end=q+1;break
    if brace>=0 and end>brace:
     emit(f"FUNCTION_BODY {m.group(1)} lines={n}-{end}")
     limit=250 if m.group(1)=="md_frame_hook" else 140 if m.group(1)=="readpad" else 90
     for q in range(n-1,min(end,n+limit)):
      emit(f"  {q+1}: {lines[q][:260]}")
  if rel in ("runtime/sdl_main.c","runtime/vdp.c","runtime/vdp.h","runtime/ym2612.c"):
   if re.search(r"md_frame_hook|shade\s*\(|draw_(?:plane|sprite)|sprite.*(?:draw|render)|(?:draw|render).*sprite|ym_(?:init|write|sample)|YM2612|SDL_.*Audio|timer|window plane|window.*plane|hscroll|vscroll|sprite_table|sat_base|SAT",t,re.I):
    emit(f"RENDER_AUDIO_HOOK line={n} {t[:260]}")
  if rel=="runtime/harness.c" and re.search(r"\b(?:static\s+)?(?:M68K\s*\*CPU|uint8_t\s+ram|static\s+Z80\s+zcpu|zbank|zbusreq|zreset|fm_acc|psg_acc|z80_over|long\s+frame|md_frame_hook)\b",t):
   emit(f"RUNTIME line={n} {t[:180]}")

# Keep the native pause-page mapping grounded in the real SDL source instead of
# guessed byte offsets. Emit the precise config declaration and legacy handlers
# so subsequent patches can call the correct fields while keeping the new UI.
sdl_path=ROOT/"runtime"/"sdl_main.c"
if sdl_path.exists():
 source=sdl_path.read_text(encoding="utf-8",errors="replace")
 lines=source.splitlines()
 emit("[SDL_NATIVE_MENU_SOURCE]")
 m=re.search(r"static\s+struct\s*\{[^}]*\}\s*cfg\b[^;]*;",source,re.S)
 if m:
  emit("CONFIG_STRUCT_SOURCE")
  emit(m.group(0))
 for name in (
  "render_native_options_video","proc_options_video","adjust_video",
  "render_native_options_audio","proc_options_audio","adjust_audio",
  "render_native_pause_video_settings","proc_native_pause_video_settings",
  "render_native_pause_audio_settings","proc_native_pause_audio_settings",
  "native_menu_pause_loop","native_pause_enter_confirm","proc_native_pause_confirm",
  "native_title_menu_sfx","native_title_menu_update","native_title_game_options_move",
  "native_title_game_options_confirm","proc_native_title_game_options",
 ):
  pat=re.compile(r"(?m)^\s*(?:(?:static|inline|extern)\s+)*(?:void|int|bool|char|short|long|size_t|u?int(?:8|16|32|64)_t|[A-Z]\w*)\s+"+re.escape(name)+r"\s*\([^;{}]*\)\s*\{")
  hit=pat.search(source)
  if not hit:
   emit(f"MENU_FUNCTION_MISSING {name}")
   continue
  brace=source.find("{",hit.start()); depth=0; end=-1
  for pos in range(brace,len(source)):
   if source[pos]=="{":depth+=1
   elif source[pos]=="}":
    depth-=1
    if depth==0:
     end=pos+1;break
  if end>brace:
   block=source[hit.start():end]
   emit(f"MENU_FUNCTION_SOURCE {name} lines {source.count(chr(10),0,hit.start())+1}-{source.count(chr(10),0,end)+1}")
   for line in block.splitlines()[:150]:emit("  "+line[:260])
 else:
  emit("CONFIG_STRUCT_NOT_FOUND")
# Scan the complete 68k-to-Z80 sound-RAM window, not only YM registers.
# Mega Drive game SFX are usually requested through bytes in Z80 RAM; a search
# for $A04000 alone misses the driver's command mailbox at $A00000-$A01FFF.
gen=ROOT/"recomp_gen.c"
if gen.exists():
 lines=gen.read_text(encoding="utf-8",errors="replace").splitlines()
 emit("[GENERATED_Z80_SOUND_RAM_ACCESS]")
 zpat=re.compile(r"0x(?:FFFF)?A0(?:0[0-9A-Fa-f]{3}|1[0-9A-Fa-f]{3})",re.I)
 hits=[]
 for i,line in enumerate(lines):
  if zpat.search(line):
   hits.append(i)
 for i in hits[:240]:
  emit(f"Z80_RAM_ACCESS line={i+1} {lines[i][:360]}")
  for j in range(max(0,i-5),min(len(lines),i+6)):
   if j!=i:emit(f"  {j+1}: {lines[j][:300]}")
 emit(f"Z80_RAM_ACCESS_CONTEXTS {len(hits)}")

 # Associate each literal sound-RAM access with its generated 68k function.
 # This reveals whether an address is used only for initial Z80-driver upload,
 # or by a routine that writes gameplay/title sound commands.
 function_starts=[]
 for i,line in enumerate(lines):
  if re.match(r"^\s*(?:static\s+)?(?:void|int)\s+f_[A-Za-z0-9_]+\s*\(",line):
   function_starts.append(i)
 function_hits={}
 for i in hits:
  owner=None
  for start in reversed(function_starts):
   if start<=i:
    owner=start;break
  if owner is not None:
   name=re.search(r"\b(f_[A-Za-z0-9_]+)\s*\(",lines[owner]).group(1)
   function_hits.setdefault((owner,name),[]).append(i)
 emit("[GENERATED_Z80_SOUND_FUNCTIONS]")
 for (owner,name),indices in function_hits.items():
  emit(f"Z80_SOUND_FUNCTION name={name} declaration_line={owner+1} access_lines={','.join(str(x+1) for x in indices)}")
  for i in indices[:16]:
   emit(f"  ACCESS {i+1}: {lines[i][:300]}")
   for j in range(max(owner,i-2),min(len(lines),i+3)):
    if j!=i:emit(f"    {j+1}: {lines[j][:240]}")

 # Show VBlank/frame-hook placement and reset entry details. The title return
 # implementation must only reset the core at a safe frame boundary.
 for rel in ("runtime/harness.c","runtime/m68k_rt.h"):
  p=ROOT/rel
  emit(f"[FRAME_RESET_CONTEXT {rel}]")
  if not p.exists():
   emit("MISSING")
   continue
  src=p.read_text(encoding="utf-8",errors="replace").splitlines()
  keys=("md_frame_hook();","void md_boot(void)","rt_call_addr","#define RT_POLL","RT_POLL(")
  seen=set()
  for i,line in enumerate(src):
   if any(k in line for k in keys):
    if any((i,d) in seen for d in (0,)):
     continue
    emit(f"CONTEXT line={i+1}")
    for j in range(max(0,i-8),min(len(src),i+10)):
     emit(f"  {j+1}: {src[j][:260]}")
    seen.add((i,0))

report="\n".join(OUT)+"\n"
Path("runtime-state-report.txt").write_text(report,encoding="utf-8")
print(report)
