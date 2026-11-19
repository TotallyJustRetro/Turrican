#!/usr/bin/env python3
"""Report only input-mask metadata from the decrypted private build kit; never print source."""
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
    report.append(f"FILE {path.name}")
    hits = list(re.finditer(r"\\bmd_live_mask\\b", source))
    report.append(f"md_live_mask references: {len(hits)}")
    seen = set()
    for hit in hits:
        start = max(0, hit.start() - 260)
        end = min(len(source), hit.end() + 260)
        window = source[start:end]
        # Keep only the nearest function identifier and numeric mask literals.
        funcs = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\\s*\\([^;{}]*\\)\\s*\\{", source[:hit.start()])
        func = funcs[-1] if funcs else "(unknown function)"
        nums = re.findall(r"0[xX][0-9A-Fa-f]+|\\b\\d+\\b", window)
        key = (func, tuple(nums))
        if key not in seen:
            seen.add(key)
            report.append(f"  function={func}; nearby numeric constants={','.join(nums[:24]) or '(none)'}")
    # Report likely input-related symbolic definitions, values only.
    for line in source.splitlines():
        if re.search(r"#\\s*define\\s+.*(BUTTON|INPUT|PAD|KEY)", line, re.I):
            m = re.match(r"\\s*#\\s*define\\s+([A-Za-z_][A-Za-z0-9_]*)\\s+(.+)", line)
            if m:
                value = re.sub(r"[^0-9A-Fa-fxX+*/()|&<> -]", "", m.group(2))
                report.append(f"  define {m.group(1)} = {value.strip()[:80]}")
    report.append("")

out = "\\n".join(report) + "\\n"
Path("input-mask-report.txt").write_text(out, encoding="utf-8")
print(out)
