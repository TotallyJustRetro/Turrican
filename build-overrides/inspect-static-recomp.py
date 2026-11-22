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

  # A value loaded from a fixed RAM slot and immediately dispatched through
  # rt_call_addr is a runtime callback candidate. Record the slot and call PC;
  # the live Maker snapshot will supply the pointer value for this run.
  indirect=[]
  current_fn="(global)"
  fn_ref2=re.compile(r"^\s*(?:(?:static|inline)\s+)*(?:void|int|bool|uint32_t)\s+(f_[0-9A-Fa-f]+)\s*\(")
  slot_ref=re.compile(r"0xFFFF((?:BC|BD|BE|BF)[0-9A-Fa-f]{2})u")
  for i,line in enumerate(lines):
   fm=fn_ref2.search(line)
   if fm: current_fn=fm.group(1)
   m=slot_ref.search(line)
   if not m or "RD32" not in line: continue
   context=" ".join(lines[i:min(len(lines),i+10)])
   if "rt_call_addr" not in context: continue
   slot=m.group(1).upper()
   call_pc=""
   for candidate in lines[i:min(len(lines),i+10)]:
    pc=re.search(r"L_([0-9A-Fa-f]+):",candidate)
    if pc and "rt_call_addr" in candidate:
     call_pc=pc.group(1).upper()
     break
   item=(current_fn,slot,call_pc,i+1)
   if item not in indirect: indirect.append(item)
  emit("INDIRECT_RAM_CALLBACK_CANDIDATES")
  for fn,slot,pc,line_no in indirect:
   emit(f"RAM_CALLBACK function={fn} slot=$FF{slot} call_pc=0x{pc or '?'} source_line={line_no}")

  # Resolve constant assignments into the callback slots. This reveals which
  # generated ROM routines can occupy a given dispatcher slot without needing
  # to sample a running level. Values copied from another structure remain
  # explicitly marked dynamic rather than guessed.
  assignment=[]
  current_fn="(global)"
  fn_def=re.compile(r"^\s*(?:(?:static|inline)\s+)*(?:void|int|bool|uint32_t)\s+(f_[0-9A-Fa-f]+)\s*\(")
  slot_pat=re.compile(r"(?:d|e)\s*=\s*0xFFFF(BC[0-9A-Fa-f]{2})u")
  target_pat=re.compile(r"(?:v|r)\s*=\s*0x([0-9A-Fa-f]{3,6})u")
  for n,line in enumerate(lines,1):
   fm=fn_def.search(line)
   if fm: current_fn=fm.group(1)
   if "WR32" not in line: continue
   sm=slot_pat.search(line)
   if not sm: continue
   vm=target_pat.search(line)
   slot=sm.group(1).upper()
   target=vm.group(1).upper() if vm else "DYNAMIC"
   row=(current_fn,slot,target,n,line.strip()[:260])
   if row not in assignment: assignment.append(row)
  emit("CALLBACK_SLOT_STATIC_ASSIGNMENTS")
  for fn,slot,target,n,code in assignment:
   handler=("f_"+target) if target!="DYNAMIC" else "dynamic/copied"
   emit(f"CALLBACK_SLOT_WRITE function={fn} slot=$FF{slot} target={target} handler={handler} source_line={n} code={code}")
  emit("CALLBACK_SLOT_TARGET_SUMMARY")
  slot_summary={}
  for fn,slot,target,n,code in assignment:
   slot_summary.setdefault(slot,set()).add(target)
  for slot,targets in sorted(slot_summary.items()):
   emit(f"CALLBACK_SLOT $FF{slot} possible_static_targets={','.join(sorted(targets))}")

  # Preserve the exact functions that install callback handlers. Those routines
  # are the bridge from a runtime object descriptor into the frame dispatcher.
  setter_names=set(fn for fn,slot,target,n,code in assignment if target!="DYNAMIC")
  emit("CALLBACK_HANDLER_INSTALLER_BODIES")
  emitted=set()
  definition=re.compile(r"^\s*(?:(?:static|inline)\s+)*(?:void|int|bool|uint32_t)\s+(f_[0-9A-Fa-f]+)\s*\([^;]*\)\s*\{")
  for n,line in enumerate(lines):
   match=definition.match(line)
   if not match: continue
   name=match.group(1)
   if name not in setter_names or name in emitted: continue
   depth=0; end=-1; opened=False
   for q in range(n,len(lines)):
    if "{" in lines[q]: opened=True
    if opened:
     depth+=lines[q].count("{")-lines[q].count("}")
     if depth==0:
      end=q+1; break
   if end<=n: continue
   emitted.add(name)
   emit(f"CALLBACK_INSTALLER_BODY {name} source_lines={n+1}-{end}")
   for q in range(n,min(end,n+220)):
    emit(f"  {q+1}: {lines[q][:280]}")
   if end-n>220: emit(f"  ... clipped {end-n-220} further source lines ...")

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
  if m and (re.search(r"read|write|memory|ram|save|load|frame|reset|state|execute|run|boot|snapshot|draw|sprite|plane|shade|audio|sound|sample|ym|mix|timer|hud|present|render|input|restart|quit",m.group(1),re.I) or (rel=="runtime/harness.c" and re.search(r"vdp_dma_read|bus_rd|bus_wr|rd8_raw",m.group(1),re.I)) or (rel=="runtime/vdp.c" and re.search(r"dma|write_data|write_ctrl",m.group(1),re.I))):
   params=re.sub(r"\s+"," ",m.group(2).strip())
   emit(f"FUNCTION line={n} name={m.group(1)} params={params[:120] or '-'}")
   if (rel=="runtime/harness.c" and m.group(1) in ("md_boot","md_load_rom","md_audio_read","md_frame_hook","readpad","sound_tick")) or (rel=="runtime/ym2612.c" and re.search(r"ym_(?:write|sample|init)",m.group(1))) or (rel=="runtime/vdp.c" and re.search(r"sprite|plane|shade|render|window|dma|write_data|write_ctrl",m.group(1),re.I)) or (rel=="runtime/sdl_main.c" and re.search(r"shade|draw_str|present|frame|input|event",m.group(1),re.I)) or (rel=="runtime/harness.c" and re.search(r"vdp_dma_read|bus_rd|bus_wr|rd8_raw",m.group(1),re.I)):
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


 # The original game writes tile/sprite data through the Mega Drive VDP ports.
 # Group those writes by generated ROM routine to locate upload/decompression
 # paths and distinguish graphics transfer code from ordinary gameplay logic.
 emit("[GENERATED_VDP_DATA_CONTROL_WRITES]")
 vdp_port=re.compile(r"0xC000(?:00|02|04|06|08|0A|0C|0E|11|13|15|17)",re.I)
 fn_name=re.compile(r"^\s*static\s+void\s+(f_[0-9A-Fa-f]+)\s*\(")
 current_fn="(global)"
 vdp_summary={}
 vdp_count=0
 for i,line in enumerate(lines,1):
  fm=fn_name.search(line)
  if fm: current_fn=fm.group(1)
  ports=sorted(set(m.group(0).upper() for m in vdp_port.finditer(line)))
  if not ports: continue
  pc=re.search(r"L_([0-9A-Fa-f]+):",line)
  writes=bool(re.search(r"\bWR(?:8|16|32)\s*\(",line))
  vdp_summary.setdefault(current_fn,set()).update(ports)
  emit(f"VDP_PORT_ACCESS function={current_fn} pc=0x{pc.group(1).upper() if pc else '?'} ports={','.join(ports)} write={int(writes)} code={line[:280]}")
  vdp_count+=1
  if vdp_count>=500:
   emit("VDP_PORT_ACCESS_LIMIT 500")
   break
 emit("VDP_FUNCTION_PORT_SUMMARY")
 for name,ports in sorted(vdp_summary.items(),key=lambda item:(-len(item[1]),item[0])):
  emit(f"VDP_FUNCTION {name} ports={','.join(sorted(ports))}")

 # Functions touching both the VDP control and data ports are the strongest
 # static candidates for upload helpers. Emit their complete bounded bodies.
 emit("VDP_DMA_UPLOAD_FUNCTION_BODIES")
 candidates=[name for name,ports in vdp_summary.items()
             if "0XC00000" in ports and "0XC00004" in ports]
 candidates=sorted(candidates)
 for name in candidates[:24]:
  pat=re.compile(r"(?m)^\s*(?:(?:static|inline)\s+)*(?:void|int|bool|uint8_t|uint16_t|uint32_t)\s+"+re.escape(name)+r"\s*\([^;{}]*\)\s*\{")
  source="\n".join(lines)
  hit=pat.search(source)
  if not hit: continue
  brace=source.find("{",hit.start()); depth=0; end=-1
  for pos in range(brace,len(source)):
   if source[pos]=="{": depth+=1
   elif source[pos]=="}":
    depth-=1
    if depth==0: end=pos+1; break
  if end<=brace: continue
  block=source[hit.start():end]
  block_lines=block.splitlines()
  emit(f"VDP_UPLOAD_BODY {name} source_lines={source.count(chr(10),0,hit.start())+1}-{source.count(chr(10),0,end)+1}")
  for line in block_lines[:180]: emit("  "+line[:280])
  if len(block_lines)>180: emit(f"  ... clipped {len(block_lines)-180} further lines ...")

 # Inspect the small routines called by the VDP transfer helpers. These often
 # own the RAM staging buffer fill, pointer advancement, or decompression step.
 emit("[VDP_TRANSFER_SUPPORT_ROUTINES]")
 support_names=[
  "f_6BD6","f_763C","f_76EA","f_72E2","f_7360","f_D0004","f_D0008",
  "f_DC4","f_6DE","f_4BA","f_4FE","f_12976","f_D0014","f_D0018",
  "f_6C3E","f_D75E","f_D7A0","f_D7B4","f_D7C8",
  "f_7B72","f_8BE","f_5BC","f_7D60","f_7C46","f_7E5A",
  "f_7636","f_760A","f_D0010","f_4A8","f_5EC","f_6D6",
  "f_554","f_76C","f_652","f_7AB6","f_7D04","f_7B8A"
 ]
 support_def=re.compile(r"(?m)^\s*static\s+void\s+(f_[0-9A-Fa-f]+)\s*\([^;{}]*\)\s*\{")
 support_emitted=set()
 for name in support_names:
  pat=re.compile(r"(?m)^\s*static\s+void\s+"+re.escape(name)+r"\s*\([^;{}]*\)\s*\{")
  hit=pat.search(source)
  if not hit:
   emit(f"TRANSFER_SUPPORT_MISSING {name}")
   continue
  brace=source.find("{",hit.start()); depth=0; end=-1
  for pos in range(brace,len(source)):
   if source[pos]=="{": depth+=1
   elif source[pos]=="}":
    depth-=1
    if depth==0: end=pos+1; break
  if end<=brace: continue
  block=source[hit.start():end]
  block_lines=block.splitlines()
  support_emitted.add(name)
  emit(f"TRANSFER_SUPPORT_BODY {name} source_lines={source.count(chr(10),0,hit.start())+1}-{source.count(chr(10),0,end)+1}")
  for line in block_lines[:220]: emit("  "+line[:280])
  if len(block_lines)>220: emit(f"  ... clipped {len(block_lines)-220} further lines ...")

 # For transfer helper/support functions, list fixed ROM pointers and static
 # RAM buffers used as sources or destinations.
 emit("[TRANSFER_SUPPORT_FIXED_POINTERS]")
 support_set=set(support_names)
 current_support=""
 ptr_pat=re.compile(r"0x([0-9A-Fa-f]{4,6})u")
 support_start=re.compile(r"^\s*static\s+void\s+(f_[0-9A-Fa-f]+)\s*\(")
 for n,line in enumerate(lines,1):
  sm=support_start.search(line)
  if sm: current_support=sm.group(1)
  if current_support not in support_set: continue
  values=sorted(set(int(m.group(1),16) for m in ptr_pat.finditer(line)))
  if not values: continue
  emit(f"TRANSFER_POINTER function={current_support} line={n} values="+",".join(f"0x{x:X}" for x in values)+" code={line[:280]}")



 # Locate direct call sites and immediate setup for each transfer helper.
 # A helper body is not enough: its callers reveal which asset/job class feeds it.
 emit("[VDP_TRANSFER_HELPER_CALLERS]")
 helper_names=set(candidates)
 call_re=re.compile(r"\b(f_[0-9A-Fa-f]+)\s*\(c\)")
 caller=""
 for n,line in enumerate(lines,1):
  fnm=definition.match(line)
  if fnm: caller=fnm.group(1)
  called=sorted(set(m.group(1) for m in call_re.finditer(line)) & helper_names)
  for target in called:
   emit(f"VDP_HELPER_CALL caller={caller or '(global)'} target={target} line={n} code={line[:280]}")
   for q in range(max(1,n-5),min(len(lines),n+5)+1):
    emit(f"  {q}: {lines[q-1][:240]}")

 # Trace the low work-RAM staging locations seen in the VDP upload helpers.
 # These are not the actor RAM window: they hold transfer queues, source
 # pointers and temporary graphics staging fields used by startup/streaming code.
 emit("[VDP_STAGING_RAM_REFERENCES]")
 low_ram=re.compile(r"0xFFFF(085[0-9A-F]|086[0-9A-F]|9A8[0-9A-F]|17D[0-9A-F])u",re.I)
 active_fn="(global)"
 low_summary={}
 low_count=0
 fn_decl=re.compile(r"^\s*static\s+(?:void|int|uint8_t|uint16_t|uint32_t)\s+(f_[0-9A-Fa-f]+)\s*\(")
 for i,line in enumerate(lines,1):
  fm=fn_decl.search(line)
  if fm: active_fn=fm.group(1)
  refs=sorted(set(m.group(1).upper() for m in low_ram.finditer(line)))
  if not refs: continue
  for address in refs:
   low_summary.setdefault(address,{}).setdefault(active_fn,0)
   low_summary[address][active_fn]+=1
  emit(f"STAGING_REF function={active_fn} line={i} addresses={','.join(refs)} code={line[:280]}")
  low_count+=1
  if low_count>=400:
   emit("STAGING_REF_LIMIT 400")
   break
 emit("STAGING_ADDRESS_SUMMARY")
 for address,functions in sorted(low_summary.items()):
  emit(f"STAGING_ADDRESS $FF{address} function_counts="+",".join(f"{fn}:{count}" for fn,count in sorted(functions.items(),key=lambda item:(-item[1],item[0]))))
 
report="\n".join(OUT)+"\n"
Path("runtime-state-report.txt").write_text(report,encoding="utf-8")
print(report)
