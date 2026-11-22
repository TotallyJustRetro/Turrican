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

  # Keep a source-level cross-reference from each absolute game-RAM address
  # to the generated 68000 routine using it. This is the static half of actor
  # discovery; live snapshots provide the corresponding runtime values.
  ram_ref=re.compile(r"0xFFFF((?:BC|BD|BE|BF)[0-9A-Fa-f]{2})",re.I)
  fn_ref=re.compile(r"\b(?:static\s+)?(?:void|int|bool|uint8_t|uint16_t|uint32_t)\s+(f_[0-9A-Fa-f]+)\s*\(")
  current_fn="(global)"
  fn_summary={}
  emit("RAM_ABSOLUTE_REFERENCES_BY_FUNCTION")
  for n,line in enumerate(lines,1):
   fm=fn_ref.search(line)
   if fm: current_fn=fm.group(1)
   refs=sorted(set(m.group(1).upper() for m in ram_ref.finditer(line)))
   if not refs: continue
   fn_summary.setdefault(current_fn,set()).update(refs)
   emit(f"RAM_REF line={n} function={current_fn} addresses={','.join(refs)} code={line[:280]}")
  emit("RAM_FUNCTION_ADDRESS_SUMMARY")
  for name,addresses in sorted(fn_summary.items(),key=lambda item:(-len(item[1]),item[0])):
   emit(f"RAM_FUNCTION {name} unique_addresses={len(addresses)} addresses={','.join(sorted(addresses))}")

  # Include bounded source excerpts for the most RAM-connected routines. These
  # reveal relative-pointer accesses and call edges omitted by the address-only
  # index, without exporting the full decrypted game source bundle.
  targets=set(name for name,_ in sorted(fn_summary.items(),
      key=lambda item:(-len(item[1]),item[0]))[:8])
  definition=re.compile(r"^\s*(?:(?:static|inline)\s+)*(?:void|int|bool|uint32_t)\s+(f_[0-9A-Fa-f]+)\s*\([^;]*\)\s*\{")
  emitted=set()
  for n,line in enumerate(lines):
   match=definition.match(line)
   if not match: continue
   name=match.group(1)
   if name not in targets or name in emitted: continue
   depth=0; end=-1; opened=False
   for q in range(n,len(lines)):
    if "{" in lines[q]: opened=True
    if opened:
     depth+=lines[q].count("{")-lines[q].count("}")
     if depth==0:
      end=q+1; break
   if end<=n: continue
   emitted.add(name)
   emit(f"RAM_FUNCTION_BODY {name} source_lines={n+1}-{end}")
   limit=min(end,n+700)
   for q in range(n,limit):
    emit(f"  {q+1}: {lines[q][:280]}")
   if limit<end: emit(f"  ... clipped {end-limit} further source lines ...")
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
   if (rel=="runtime/harness.c" and m.group(1) in ("md_boot","md_load_rom","md_audio_read","md_frame_hook","readpad","sound_tick")) or (rel=="runtime/ym2612.c" and re.search(r"ym_(?:write|sample|init)",m.group(1))) or (rel=="runtime/vdp.c" and re.search(r"sprite|plane|shade|render|window",m.group(1),re.I)) or (rel=="runtime/sdl_main.c" and re.search(r"shade|draw_str|present|frame|input|event",m.group(1),re.I)):
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
# Scan generated 68000 output for accesses to the standard Mega Drive sound
# command/mailbox and YM interfaces. Context helps identify the original SFX call.
gen=ROOT/"recomp_gen.c"
if gen.exists():
 lines=gen.read_text(encoding="utf-8",errors="replace").splitlines()
 emit("[GENERATED_SOUND_WRITE_SITES]")
 pat=re.compile(r"0xFFFFA000|0xFFFFA040|0xFFFFC000|0xA00000|0xA04000|0xC00011",re.I)
 count=0
 for i,line in enumerate(lines):
  if pat.search(line):
   emit(f"SOUND_ACCESS line={i+1} {line[:300]}")
   for j in range(max(0,i-3),min(len(lines),i+4)):
    emit(f"  {j+1}: {lines[j][:260]}")
   count+=1
   if count>=80:break
 emit(f"SOUND_ACCESS_CONTEXTS {count}")

report="\n".join(OUT)+"\n"
Path("runtime-state-report.txt").write_text(report,encoding="utf-8")
print(report)
