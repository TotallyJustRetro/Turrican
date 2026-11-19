#!/usr/bin/env python3
"""Emit narrowly scoped input-mask expressions and bit definitions; never dump private source."""
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
files = [root / "recomp_gen.c", root / "runtime" / "harness.c",
         root / "runtime" / "sdl_main.c"]
report = []
for path in files:
    if not path.is_file():
        continue
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()
    report.append(f"FILE {path.name}")
    ref_lines = [i for i, line in enumerate(lines) if "md_live_mask" in line]
    report.append(f"md_live_mask reference lines: {len(ref_lines)}")
    for i in ref_lines:
        for j in range(max(0, i-1), min(len(lines), i+2)):
            line = re.sub(r"\s+", " ", lines[j]).strip()
            if line:
                report.append(f"  L{j+1}: {line[:260]}")
    # Extract the complete small hardware-controller read function only.
    match = re.search(r"static\s+uint8_t\s+pad_read\s*\([^)]*\)\s*\{", source)
    if match:
        start = match.start()
        brace = source.find("{", match.start())
        depth = 0
        end = brace
        for end in range(brace, min(len(source), brace + 2400)):
            if source[end] == "{":
                depth += 1
            elif source[end] == "}":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
        excerpt = re.sub(r"\s+", " ", source[start:end]).strip()
        report.append("pad_read implementation: " + excerpt[:1800])
    report.append("input/button enum or define lines:")
    for i, line in enumerate(lines):
        if re.search(r"\b(enum|#\s*define)\b", line) and re.search(r"\b(B_[A-Z0-9_]+|BTN_[A-Z0-9_]+|PAD_[A-Z0-9_]+|BUTTON_[A-Z0-9_]+)\b", line):
            report.append(f"  L{i+1}: {re.sub(r'\s+', ' ', line).strip()[:260]}")
        elif re.search(r"\b(B_[A-Z0-9_]+|BTN_[A-Z0-9_]+|PAD_[A-Z0-9_]+|BUTTON_[A-Z0-9_]+)\s*=", line):
            report.append(f"  L{i+1}: {re.sub(r'\s+', ' ', line).strip()[:260]}")
    report.append("")

out = "\n".join(report) + "\n"
Path("input-mask-report.txt").write_text(out, encoding="utf-8")
print(out)
