#!/usr/bin/env python3
"""Install a read-only runtime trace for Mega Turrican's player descriptors."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
GEN = ROOT / "recomp_gen.c"
HARNESS = ROOT / "runtime" / "harness.c"
RT_HEADER = ROOT / "runtime" / "m68k_rt.h"

HARNESS_MARKER = "uint8_t bus_rd8(uint32_t a){"
HEADER_MARKER = "#define RT_POLL(pc)"
GEN_F19FA = "L_19FA: { RT_POLL(0x19FA); uint32_t v=(A(0)&0xFFFFFFFFu); uint32_t d=0xFFFFBC50u; WR32(d,v); fl_logic(c,v,32); }"
GEN_F1BDE = "L_1BDE: { RT_POLL(0x1BDE); uint32_t e=0xFFFFBC88u; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }"

TRACE_HELPER = r'''
/* Read-only co-op research trace. This does not alter emulated RAM or CPU state. */
/* These values are sampled by the existing SDL controller backend. */
extern int md_player2_live_mask;
extern int md_player2_connected;

/* Read-only trace of how often the emulated game reads Genesis controller ports. */

static uint32_t md_coop_trace_rom32(uint32_t a) {
    a &= 0xFFFFFFu;
    if (!rom || a > romlen || romlen - a < 4) return 0xFFFFFFFFu;
    return ((uint32_t)rom[a] << 24) | ((uint32_t)rom[a + 1] << 16) |
           ((uint32_t)rom[a + 2] << 8) | (uint32_t)rom[a + 3];
}

static void md_coop_trace_bytes(FILE *f, uint32_t a, unsigned count) {
    a &= 0xFFFFFFu;
    for (unsigned i = 0; i < count; ++i) {
        if (rom && a + i < romlen) fprintf(f, "%02X", rom[a + i]);
        else fputs("--", f);
        if ((i & 15u) == 15u) fputc('\n', f);
        else fputc(' ', f);
    }
    if ((count & 15u) != 0u) fputc('\n', f);
}

void md_coop_trace_capture(M68K *c, uint32_t descriptor, unsigned phase) {
    static struct { uint32_t descriptor; uint16_t selector; unsigned phase; } seen[32];
    static unsigned seen_count;
    uint16_t selector = ((uint16_t)ram[0xBF1E] << 8) | ram[0xBF1F];
    descriptor &= 0xFFFFFFu;
    for (unsigned i = 0; i < seen_count; ++i) {
        if (seen[i].descriptor == descriptor &&
            seen[i].selector == selector &&
            seen[i].phase == phase) return;
    }
    if (seen_count >= 32) return;
    seen[seen_count].descriptor = descriptor;
    seen[seen_count].selector = selector;
    seen[seen_count].phase = phase;
    ++seen_count;

    FILE *f = fopen("MegaTurrican-coop-runtime-trace.txt", "ab");
    if (!f) return;

    uint32_t table_entry = md_coop_trace_rom32(0x1994u + (uint32_t)selector * 4u);
    uint32_t table2 = md_coop_trace_rom32(descriptor + 2u);
    uint32_t table6 = md_coop_trace_rom32(descriptor + 6u);
    uint32_t callback1 = table2 == 0xFFFFFFFFu ? 0xFFFFFFFFu : md_coop_trace_rom32(table2);
    uint32_t slot3c = table2 == 0xFFFFFFFFu ? 0xFFFFFFFFu : md_coop_trace_rom32(table2 + 4u);
    uint32_t callback2 = table6 == 0xFFFFFFFFu ? 0xFFFFFFFFu : md_coop_trace_rom32(table6);
    uint32_t slot44 = table6 == 0xFFFFFFFFu ? 0xFFFFFFFFu : md_coop_trace_rom32(table6 + 4u);
    uint32_t callback3 = md_coop_trace_rom32(descriptor + 38u);

    fprintf(f, "\n=== DESCRIPTOR TRACE phase=%u selector=%04X descriptor=%06X ===\n",
            phase, selector, descriptor);
    fprintf(f, "rom_table_1994_entry=%08X bc50=%08X pc_ret=%08X a7=%08X\n",
            table_entry, descriptor, c ? c->ret : 0u, c ? c->a[7] : 0u);
    fprintf(f, "desc+00=%08X desc+02=%08X desc+06=%08X desc+10=%08X\n",
            md_coop_trace_rom32(descriptor), table2, table6,
            md_coop_trace_rom32(descriptor + 10u));
    fprintf(f, "desc+12=%08X desc+16=%08X desc+18=%08X desc+22=%08X\n",
            md_coop_trace_rom32(descriptor + 12u),
            md_coop_trace_rom32(descriptor + 16u),
            md_coop_trace_rom32(descriptor + 18u),
            md_coop_trace_rom32(descriptor + 22u));
    fprintf(f, "desc+26=%08X desc+30=%08X desc+34=%08X desc+38=%08X\n",
            md_coop_trace_rom32(descriptor + 26u),
            md_coop_trace_rom32(descriptor + 30u),
            md_coop_trace_rom32(descriptor + 34u),
            callback3);
    fprintf(f, "desc+42=%08X desc+46=%08X desc+48.byte=%02X desc+50.byte=%02X\n",
            md_coop_trace_rom32(descriptor + 42u),
            md_coop_trace_rom32(descriptor + 46u),
            (rom && descriptor + 48u < romlen) ? rom[descriptor + 48u] : 0xFFu,
            (rom && descriptor + 50u < romlen) ? rom[descriptor + 50u] : 0xFFu);
    fprintf(f, "nested+02 table_ptr=%08X raw_long_00=%08X raw_long_04=%08X\n",
            table2, callback1, slot3c);
    fprintf(f, "nested+06 table_ptr=%08X raw_long_00=%08X raw_long_04=%08X\n",
            table6, callback2, slot44);
    fprintf(f, "descriptor_bytes_00_to_3F:\n");
    md_coop_trace_bytes(f, descriptor, 64u);
    fprintf(f, "nested_table_02_bytes:\n");
    md_coop_trace_bytes(f, table2, 16u);
    fprintf(f, "nested_table_06_bytes:\n");
    md_coop_trace_bytes(f, table6, 16u);
    fprintf(f, "ram_BC50=%02X%02X%02X%02X ram_BC88=%02X ram_BF1E=%04X\n",
            ram[0xBC50], ram[0xBC51], ram[0xBC52], ram[0xBC53],
            ram[0xBC88], selector);
    fflush(f);
    fclose(f);
}


/* Sample host P2 detection, the live SDL mask, and the game's emulated port reads.
   This runs alongside the main player callback and only writes a text log. */
void md_coop_trace_input(M68K *c, uint32_t descriptor, unsigned phase) {
    static unsigned sample_count;
    static int previous_connected = -1;
    static unsigned previous_mask = 0xFFFFFFFFu;
    static unsigned previous_ram[4] = {0x100u, 0x100u, 0x100u, 0x100u};
    ++sample_count;

    int connected = md_player2_connected;
    unsigned mask = (unsigned)md_player2_live_mask;
    unsigned current_ram[4] = {
        ram[0xBC90], ram[0xBC91], ram[0xBC92], ram[0xBC93]
    };
    int changed = connected != previous_connected || mask != previous_mask;
    for (unsigned i = 0; i < 4; ++i) {
        if (current_ram[i] != previous_ram[i]) changed = 1;
    }

    if (sample_count == 1u || changed || (sample_count % 60u) == 0u) {
        FILE *f = fopen("MegaTurrican-coop-runtime-trace.txt", "ab");
        if (f) {
            fprintf(f, "\\n=== INPUT SAMPLE n=%u phase=%u descriptor=%06X ===\\n",
                    sample_count, phase, descriptor & 0xFFFFFFu);
            fprintf(f, "p2_connected=%d p2_live_mask=%08X emulated_pad_reads_port0=%u port1=%u\\n",
                    connected, mask, md_coop_pad_read_count[0], md_coop_pad_read_count[1]);
            fprintf(f, "ram_BC90_91=%02X%02X ram_BC92_93=%02X%02X\\n",
                    ram[0xBC90], ram[0xBC91], ram[0xBC92], ram[0xBC93]);
            fflush(f);
            fclose(f);
        }
    }

    previous_connected = connected;
    previous_mask = mask;
    for (unsigned i = 0; i < 4; ++i) previous_ram[i] = current_ram[i];
    (void)c;
}

/* Capture the exact runtime target before descriptor and frame-dispatch calls. */
void md_coop_trace_call(M68K *c, uint32_t target, unsigned phase) {
    static struct { uint32_t descriptor; uint32_t target; unsigned phase; } seen[96];
    static unsigned seen_count;
    if (phase == 305u) {
        uint32_t current_descriptor = ((uint32_t)ram[0xBC50] << 24) |
                                      ((uint32_t)ram[0xBC51] << 16) |
                                      ((uint32_t)ram[0xBC52] << 8) |
                                      (uint32_t)ram[0xBC53];
        md_coop_trace_input(c, current_descriptor, phase);
    }
    uint32_t descriptor = ((uint32_t)ram[0xBC50] << 24) |
                          ((uint32_t)ram[0xBC51] << 16) |
                          ((uint32_t)ram[0xBC52] << 8) |
                          (uint32_t)ram[0xBC53];
    target &= 0xFFFFFFu;
    for (unsigned i = 0; i < seen_count; ++i) {
        if (seen[i].descriptor == descriptor &&
            seen[i].target == target &&
            seen[i].phase == phase) return;
    }
    if (seen_count >= 96) return;
    seen[seen_count].descriptor = descriptor;
    seen[seen_count].target = target;
    seen[seen_count].phase = phase;
    ++seen_count;

    FILE *f = fopen("MegaTurrican-coop-runtime-trace.txt", "ab");
    if (!f) return;
    fprintf(f, "\n=== CALLBACK TARGET phase=%u descriptor=%06X target=%06X ret=%08X ===\n",
            phase, descriptor & 0xFFFFFFu, target, c ? c->ret : 0u);
    if (c) {
        for (unsigned i = 0; i < 8; ++i)
            fprintf(f, "D%u=%08X%s", i, c->d[i], (i == 7u) ? "\n" : " ");
        for (unsigned i = 0; i < 8; ++i)
            fprintf(f, "A%u=%08X%s", i, c->a[i], (i == 7u) ? "\n" : " ");
    }
    fprintf(f, "selector=%04X player_state=%02X input_p1=%02X%02X input_p2=%02X%02X pos=%04X,%04X view=%04X,%04X\n",
            (uint16_t)(((uint16_t)ram[0xBF1E] << 8) | ram[0xBF1F]),
            ram[0xBC87], ram[0xBC90], ram[0xBC91], ram[0xBC92], ram[0xBC93],
            (uint16_t)(((uint16_t)ram[0xBD1E] << 8) | ram[0xBD1F]),
            (uint16_t)(((uint16_t)ram[0xBD20] << 8) | ram[0xBD21]),
            (uint16_t)(((uint16_t)ram[0xDFD8] << 8) | ram[0xDFD9]),
            (uint16_t)(((uint16_t)ram[0xDFDA] << 8) | ram[0xDFDB]));
    fflush(f);
    fclose(f);
}
'''

def replace_once(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if old not in source:
        raise SystemExit(f"Expected patch anchor not found in {path}: {old[:100]!r}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8", newline="\n")

for path in (GEN, HARNESS, RT_HEADER):
    if not path.is_file():
        raise SystemExit(f"Missing expected source file: {path}")

# Add a read-only counter at the real Genesis pad_read boundary. p==0 is
# controller port 1; p==1 is controller port 2. The counter is declared at
# file scope before pad_read so it is available regardless of source order.
harness_source = HARNESS.read_text(encoding="utf-8")
if "md_coop_pad_read_count[2]" not in harness_source:
    harness_source = "static unsigned int md_coop_pad_read_count[2];\\n" + harness_source
    pad_read_match = re.search(
        r"(static\\s+uint8_t\\s+pad_read\\s*\\(\\s*int\\s+p\\s*\\)\\s*\\{)",
        harness_source,
    )
    if not pad_read_match:
        raise SystemExit("Could not find the emulated Genesis pad_read(int p) function for diagnostics.")
    counter_line = "\\n    if (p >= 0 && p < 2) ++md_coop_pad_read_count[p];"
    harness_source = harness_source[:pad_read_match.end()] + counter_line + harness_source[pad_read_match.end():]
    HARNESS.write_text(harness_source, encoding="utf-8", newline="\\n")

replace_once(
    HARNESS,
    HARNESS_MARKER,
    TRACE_HELPER + "\n" + HARNESS_MARKER,
)
replace_once(
    RT_HEADER,
    HEADER_MARKER,
    "void md_coop_trace_capture(M68K *c, uint32_t descriptor, unsigned phase);\nvoid md_coop_trace_call(M68K *c, uint32_t target, unsigned phase);\n\n" + HEADER_MARKER,
)
replace_once(
    GEN,
    GEN_F19FA,
    GEN_F19FA[:-2] + " md_coop_trace_capture(c,v,1); }",
)
replace_once(
    GEN,
    GEN_F1BDE,
    GEN_F1BDE.replace(
        "RT_POLL(0x1BDE);",
        "RT_POLL(0x1BDE); md_coop_trace_capture(c,RD32(0xFFFFBC50u),2);",
        1,
    ),
)

replace_once(GEN, "L_1AF0: { RT_POLL(0x1AF0); uint32_t e=A(5); {", "L_1AF0: { RT_POLL(0x1AF0); uint32_t e=A(5); md_coop_trace_call(c,e,101); {")
replace_once(GEN, "L_1B32: { RT_POLL(0x1B32); uint32_t e=A(5); {", "L_1B32: { RT_POLL(0x1B32); uint32_t e=A(5); md_coop_trace_call(c,e,102); {")
replace_once(GEN, "L_1B56: { RT_POLL(0x1B56); uint32_t e=A(0); {", "L_1B56: { RT_POLL(0x1B56); uint32_t e=A(0); md_coop_trace_call(c,e,103); {")
replace_once(GEN, "L_1C60: { RT_POLL(0x1C60); uint32_t e=A(5); {", "L_1C60: { RT_POLL(0x1C60); uint32_t e=A(5); md_coop_trace_call(c,e,201); {")
replace_once(GEN, "L_1CA2: { RT_POLL(0x1CA2); uint32_t e=A(5); {", "L_1CA2: { RT_POLL(0x1CA2); uint32_t e=A(5); md_coop_trace_call(c,e,202); {")
replace_once(GEN, "L_1CAC: { RT_POLL(0x1CAC); uint32_t e=A(0); {", "L_1CAC: { RT_POLL(0x1CAC); uint32_t e=A(0); md_coop_trace_call(c,e,203); {")
replace_once(GEN, "L_1620: { RT_POLL(0x1620); uint32_t e=A(0); {", "L_1620: { RT_POLL(0x1620); uint32_t e=A(0); md_coop_trace_call(c,e,301); {")
replace_once(GEN, "L_162A: { RT_POLL(0x162A); uint32_t e=A(0); {", "L_162A: { RT_POLL(0x162A); uint32_t e=A(0); md_coop_trace_call(c,e,302); {")
replace_once(GEN, "L_1630: { RT_POLL(0x1630); uint32_t e=A(0); {", "L_1630: { RT_POLL(0x1630); uint32_t e=A(0); md_coop_trace_call(c,e,303); {")
replace_once(GEN, "L_163E: { RT_POLL(0x163E); uint32_t e=A(0); {", "L_163E: { RT_POLL(0x163E); uint32_t e=A(0); md_coop_trace_call(c,e,304); {")
replace_once(GEN, "L_1660: { RT_POLL(0x1660); uint32_t e=A(0); {", "L_1660: { RT_POLL(0x1660); uint32_t e=A(0); md_coop_trace_call(c,e,305); {")
replace_once(GEN, "L_166E: { RT_POLL(0x166E); uint32_t e=A(0); {", "L_166E: { RT_POLL(0x166E); uint32_t e=A(0); md_coop_trace_call(c,e,306); {")
replace_once(GEN, "L_1746: { RT_POLL(0x1746); uint32_t e=A(0); {", "L_1746: { RT_POLL(0x1746); uint32_t e=A(0); md_coop_trace_call(c,e,307); {")

print("Installed read-only player-descriptor trace hooks (no gameplay behavior changed).")
