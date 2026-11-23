#!/usr/bin/env python3
"""Generate a build-time index of original Mega Turrican sprite descriptors.

This only inspects the static recompiler output. It does not execute game code,
read mutable RAM, or add any runtime diagnostic hooks.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: generate-maker-asset-catalog.py PROJECT_ROOT")

root = Path(sys.argv[1]).resolve()
source_path = root / "recomp_gen.c"
out_path = root / "runtime" / "mt_maker_asset_catalog.h"
if not source_path.is_file():
    raise SystemExit(f"Generated recompiler source missing: {source_path}")

lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
fn_re = re.compile(r"^\s*static\s+void\s+(f_[0-9A-Fa-f]+)\s*\(")
write30_re = re.compile(
    r"\buint32_t\s+d\s*=\s*A\(([0-7])\)\s*\+\s*\(int32_t\)30\s*;"
    r".*?\bWR32\s*\(\s*d\s*,\s*v\s*\)"
)
imm_v_re = re.compile(r"\buint32_t\s+v\s*=\s*0x([0-9A-Fa-f]+)u")
read_v_re = re.compile(r"\buint32_t\s+v\s*=\s*RD32\s*\(\s*s\s*\)")
s_expr_re = re.compile(r"\buint32_t\s+s\s*=\s*([^;]+);")
temp_re = re.compile(r"\buint32_t\s+([A-Za-z_]\w*)\s*=\s*0x([0-9A-Fa-f]+)u")
areg_re = re.compile(r"\bA\(([0-7])\)\s*=\s*([A-Za-z_]\w*|0x[0-9A-Fa-f]+u)")
number_re = re.compile(r"0x([0-9A-Fa-f]+)u|(?<![A-Za-z_])(\d+)(?![A-Za-z_])")
areg_ref_re = re.compile(r"A\(([0-7])\)")
dynamic_re = re.compile(r"\b(?:D|A)\([0-7]\)\b")

owner = "(global)"
registers: dict[int, int] = {}
temps: dict[str, int] = {}
static_descriptors: set[tuple[int, int]] = set()
pointer_tables: dict[tuple[int, int], int] = {}

def resolve_rom_source(expr: str) -> tuple[int | None, bool]:
    """Resolve a ROM base plus optional dynamic indexing from a source expr."""
    expr = expr.strip()
    dynamic = bool(re.search(r"\bD\([0-7]\)", expr))
    match = areg_ref_re.search(expr)
    if match:
        reg = int(match.group(1))
        if reg not in registers:
            return None, dynamic
        base = registers[reg]
        # Add only literal displacements; variable index terms are deliberately
        # left for the runtime table walker to enumerate with strict bounds.
        tail = expr[match.end():]
        for item in re.finditer(r"\+\s*\(int32_t\)\s*(\d+)", tail):
            base += int(item.group(1))
        return (base if 0 <= base < 0x400000 else None), dynamic
    value = re.fullmatch(r"\s*0x([0-9A-Fa-f]+)u\s*", expr)
    if value:
        base = int(value.group(1), 16)
        return (base if 0 <= base < 0x400000 else None), False
    return None, dynamic

for line in lines:
    fm = fn_re.search(line)
    if fm:
        owner = fm.group(1)
        registers = {}
        temps = {}

    # Remember simple immediate temporaries and address-register setup. This
    # recovers common ROM pointer-table bases used by indexed descriptor reads.
    for tm in temp_re.finditer(line):
        temps[tm.group(1)] = int(tm.group(2), 16)
    for am in areg_re.finditer(line):
        reg = int(am.group(1))
        value = am.group(2)
        if value.startswith("0x"):
            registers[reg] = int(value[:-1], 16)
        elif value in temps:
            registers[reg] = temps[value]
        else:
            registers.pop(reg, None)

    if not write30_re.search(line):
        continue

    vm = imm_v_re.search(line)
    if vm:
        descriptor = int(vm.group(1), 16)
        owner_pc = int(owner[2:], 16) if owner.startswith("f_") else 0
        if 0x200 <= descriptor < 0x400000:
            static_descriptors.add((owner_pc, descriptor))
        continue

    if not read_v_re.search(line):
        continue
    sm = s_expr_re.search(line)
    if not sm:
        continue
    base, indexed = resolve_rom_source(sm.group(1),)
    if base is None:
        continue
    owner_pc = int(owner[2:], 16) if owner.startswith("f_") else 0
    # A dynamic register index means this is a pointer table; a fixed address
    # is a single pointer cell. Runtime validation filters non-descriptor data.
    max_entries = 32 if indexed else 1
    key = (owner_pc, base)
    pointer_tables[key] = max(pointer_tables.get(key, 0), max_entries)

static_rows = sorted(static_descriptors)
table_rows = sorted((owner_pc, base, count) for (owner_pc, base), count in pointer_tables.items())

header = [
    "#pragma once",
    "/* Generated from recomp_gen.c by generate-maker-asset-catalog.py. */",
    "#include <stdint.h>",
    "typedef struct MTMakerStaticSpriteDescriptor { uint32_t owner_pc; uint32_t descriptor_pc; } MTMakerStaticSpriteDescriptor;",
    "typedef struct MTMakerSpritePointerTable { uint32_t owner_pc; uint32_t table_pc; uint32_t entry_limit; } MTMakerSpritePointerTable;",
]
header.append("static const MTMakerStaticSpriteDescriptor kMTMakerStaticSpriteDescriptors[] = {")
if static_rows:
    for owner_pc, descriptor in static_rows:
        header.append(f"    {{0x{owner_pc:X}u, 0x{descriptor:X}u}},")
else:
    header.append("    {0u, 0u},")
header.append("};")
header.append(f"static const uint32_t kMTMakerStaticSpriteDescriptorCount = {len(static_rows)}u;")
header.append("static const MTMakerSpritePointerTable kMTMakerSpritePointerTables[] = {")
if table_rows:
    for owner_pc, base, count in table_rows:
        header.append(f"    {{0x{owner_pc:X}u, 0x{base:X}u, {count}u}},")
else:
    header.append("    {0u, 0u, 0u},")
header.append("};")
header.append(f"static const uint32_t kMTMakerSpritePointerTableCount = {len(table_rows)}u;")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text("\n".join(header) + "\n", encoding="utf-8")
print(
    f"Generated Maker sprite index: {len(static_rows)} constant descriptor "
    f"references, {len(table_rows)} ROM pointer-table sources -> {out_path}"
)
