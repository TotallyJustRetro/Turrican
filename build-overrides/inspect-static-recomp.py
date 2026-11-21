#!/usr/bin/env python3
"""Emit only runtime type/field names needed for native save-state integration."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT=Path(sys.argv[1]).resolve()
FILES=[
 "recomp_gen.c","runtime/harness.c","runtime/m68k_rt.h","runtime/m68k_interp.c",
 "runtime/z80.h","runtime/ym2612.h","runtime/psg.h","runtime/vdp.h",
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
  if rel=="recomp_gen.c" and re.search(r"rt_shadow|rt_sp|recomp_reset_pc",t):
   emit(f"RECOMP_STATE line={n} {t[:180]}")
  m=func.match(line)
  if m and re.search(r"read|write|memory|ram|save|load|frame|reset|state|execute|run|boot|snapshot",m.group(1),re.I):
   params=re.sub(r"\s+"," ",m.group(2).strip())
   emit(f"FUNCTION line={n} name={m.group(1)} params={params[:100] or '-'}")
  if rel=="runtime/harness.c" and re.search(r"\b(?:static\s+)?(?:M68K\s*\*CPU|uint8_t\s+ram|static\s+Z80\s+zcpu|zbank|zbusreq|zreset|fm_acc|psg_acc|z80_over|long\s+frame|md_frame_hook)\b",t):
   emit(f"RUNTIME line={n} {t[:180]}")
report="\n".join(OUT)+"\n"
Path("runtime-state-report.txt").write_text(report,encoding="utf-8")
print(report)
