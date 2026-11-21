#!/usr/bin/env python3
"""Inspect the decrypted Mega Turrican recomp source for native title/intro assets and flow."""
from __future__ import annotations
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
interesting = re.compile(
    r"splash|intro|title|logo|sega|copyright|tile.?map|plane.?a|plane.?b|"
    r"vdp|rom|asset|sprite|font|menu|screen",
    re.I,
)
code_ext = {".c", ".h", ".hpp", ".cpp", ".s", ".asm", ".inc", ".txt", ".json"}
lines = ["MEGA TURRICAN RECOMP SOURCE INSPECTION", f"root={root}", "", "SOURCE FILES"]
files = sorted(p for p in root.rglob("*") if p.is_file())
for p in files:
    rel = p.relative_to(root).as_posix()
    if ".git" not in p.parts and rel.endswith((".c", ".h", ".hpp", ".cpp", ".s", ".asm", ".inc", ".bin", ".rom", ".md", ".txt", ".json")):
        try: size = p.stat().st_size
        except OSError: size = -1
        lines.append(f"{size:>12}  {rel}")

lines += ["", "TITLE / INTRO / VDP SYMBOL MATCHES"]
seen = 0
for p in files:
    if p.suffix.lower() not in code_ext or "launcher" in p.parts or "node_modules" in p.parts:
        continue
    try: src_lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError: continue
    for n, line in enumerate(src_lines, 1):
        if not interesting.search(line) or re.search(r"(?:0x[0-9a-fA-F]{2},\s*){8,}", line):
            continue
        txt = line.strip()
        if txt:
            lines.append(f"{p.relative_to(root).as_posix()}:{n}: {txt[:260]}")
            seen += 1
        if seen >= 420:
            lines.append("... match limit reached ...")
            break
    if seen >= 420:
        break

for rel in ("runtime/sdl_main.c", "runtime/vdp.h", "runtime/vdp.c", "runtime/harness.c", "runtime/m68k_rt.h"):
    p = root / rel
    if p.exists():
        data = p.read_text(encoding="utf-8", errors="ignore")
        lines += ["", f"--- {rel} ({len(data)} chars) ---", data[:42000]]
        if len(data) > 42000: lines.append("... file truncated at 42k chars ...")

report = "\n".join(lines) + "\n"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(report, encoding="utf-8")
print(report.encode('ascii', 'backslashreplace').decode('ascii'))
