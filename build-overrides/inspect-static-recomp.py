#!/usr/bin/env python3
"""Print a compact, non-sensitive map of the private static-recomp runtime."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT=Path(sys.argv[1]).resolve()
FILES=["recomp_gen.c","runtime/harness.c","runtime/m68k_interp.c",
       "runtime/vdp.h","runtime/vdp.c","runtime/m68k_rt.h","runtime/z80.h",
       "runtime/z80.c","runtime/ym2612.h","runtime/ym2612.c",
       "runtime/psg.h","runtime/psg.c"]

PATTERNS=[
    r"\b(?:work_ram|wram|main_ram|m68k_ram|ram|memory|mem)\b",
    r"\b(?:read|write|mem_read|mem_write|m68k_read|m68k_write|md_read|md_write)\w*\b",
    r"\b(?:cpu|m68k|z80)_[A-Za-z0-9_]*\b",
    r"0x[fF][fF][bB][fF](?:20|26|28)",
    r"\b(?:rom|romlen|md_live_mask|md_frame_hook)\b",
]
compiled=[re.compile(p,re.I) for p in PATTERNS]
decl=re.compile(r"^\s*(?:(?:static|extern|volatile|const)\s+)*(?:unsigned\s+)?(?:u?int(?:8|16|32|64)_t|char|short|int|long|size_t|bool|struct\s+\w+)\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*(?:=|;|,)")
func=re.compile(r"^\s*(?:(?:static|inline|extern)\s+)*(?:void|int|bool|char|short|long|size_t|u?int(?:8|16|32|64)_t|[A-Z]\w*)\s+([A-Za-z_]\w*)\s*\(")

for rel in FILES:
    p=ROOT/rel
    if not p.exists():
        print(f"\n[{rel}] MISSING")
        continue
    lines=p.read_text(encoding="utf-8",errors="replace").splitlines()
    print(f"\n[{rel}] {len(lines)} lines")
    found=[]
    for no,line in enumerate(lines,1):
        if any(rx.search(line) for rx in compiled):
            found.append((no,line.strip()))
    for no,line in found[:100]:
        print(f"  MATCH {no}: {line[:230]}")
    if len(found)>100:
        print(f"  ... {len(found)-100} additional matching lines omitted")
    if rel in ("runtime/harness.c","runtime/m68k_interp.c","runtime/vdp.h"):
        for no,line in enumerate(lines,1):
            if decl.match(line) or (func.match(line) and re.search(r"read|write|memory|ram|save|load|frame|reset|state|execute|run|boot",line,re.I)):
                print(f"  DECL  {no}: {line.strip()[:230]}")
