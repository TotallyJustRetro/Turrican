#!/usr/bin/env python3
"""
Install the first native second-actor runtime for Mega Turrican.

This is deliberately a constrained prototype:
- P2 owns an independently persistent M68K context and private 68000 stack.
- Player-local RAM and the sprite scratch area are banked through the CPU bus.
- World/object pools, DMA reads, VDP state and the shared render queue remain shared.
- P2 is sampled from physical controller port 2 and only runs while it is connected.
- Any CPU/stack return mismatch disables P2 rather than continuing with corrupt state.

It does not enable the launcher multiplayer UI or claim full co-op completion.
"""
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1]).resolve()
GEN = ROOT / "recomp_gen.c"
HARNESS = ROOT / "runtime" / "harness.c"
RT_HEADER = ROOT / "runtime" / "m68k_rt.h"

def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if old not in source:
        raise SystemExit(f"local co-op patch: missing {label} anchor in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8", newline="\n")

for path in (GEN, HARNESS, RT_HEADER):
    if not path.is_file():
        raise SystemExit(f"local co-op patch: required source file missing: {path}")

# 1) Add independent P2 memory, CPU bus view and interrupt/event handoff.
HARNESS_HELPERS = r"""
/* Mega Turrican local co-op: isolated P2 actor memory view. */
#include <string.h>
extern int md_player2_connected;
extern int md_player2_live_mask;

int md_coop_p2_active = 0;
static uint8_t md_coop_p2_ram[0x10000];
static uint8_t md_coop_p2_private[0x10000];
static uint8_t md_coop_p2_stack[0x10000];
static M68K md_coop_p2_m68k;
static M68K md_coop_p2_frame_seed;
static M68K md_coop_p2_native_init_seed;
static int md_coop_p2_native_init_seed_valid = 0;
static uint8_t md_coop_p2_primary_sprite_parts[0xE8];
static unsigned md_coop_p2_primary_sprite_parts_nonzero = 0;
static int md_coop_p2_primary_sprite_parts_valid = 0;
static M68K *md_coop_primary_m68k = NULL;
static int md_coop_p2_frame_seed_valid = 0;
static int md_coop_p2_ready = 0;
static int md_coop_p2_disabled = 0;
static unsigned long md_coop_p2_frame_count = 0;

static void md_coop_p2_mark(unsigned first, unsigned last) {
    unsigned i;
    if (last >= sizeof md_coop_p2_private) last = (unsigned)sizeof md_coop_p2_private - 1;
    for (i = first; i <= last; ++i) md_coop_p2_private[i] = 1;
}

static uint16_t md_coop_p2_word(unsigned at) {
    return (uint16_t)(((uint16_t)md_coop_p2_ram[at] << 8) |
                      (uint16_t)md_coop_p2_ram[(at + 1u) & 0xFFFFu]);
}

static void md_coop_p2_put_word(unsigned at, uint16_t value) {
    md_coop_p2_ram[at] = (uint8_t)(value >> 8);
    md_coop_p2_ram[(at + 1u) & 0xFFFFu] = (uint8_t)value;
}

static uint32_t md_coop_p2_long(unsigned at) {
    return ((uint32_t)md_coop_p2_ram[at] << 24) |
           ((uint32_t)md_coop_p2_ram[(at + 1u) & 0xFFFFu] << 16) |
           ((uint32_t)md_coop_p2_ram[(at + 2u) & 0xFFFFu] << 8) |
           (uint32_t)md_coop_p2_ram[(at + 3u) & 0xFFFFu];
}

static void md_coop_p2_log(const char *event, uint32_t callback, const char *detail) {
    FILE *f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
    if (!f) return;
    fprintf(f, "event=%s frame=%lu connected=%d callback=%06X p2_x=%04X p2_y=%04X input=%02X%02X detail=%s\n",
            event, md_coop_p2_frame_count, md_player2_connected, callback,
            md_coop_p2_word(0xBD1E), md_coop_p2_word(0xBD20),
            md_coop_p2_ram[0xBC90], md_coop_p2_ram[0xBC91],
            detail ? detail : "-");
    fclose(f);
}

void md_coop_p2_set_active(int active) {
    md_coop_p2_active = active ? 1 : 0;
}

M68K *md_coop_p2_cpu(void) {
    return md_coop_p2_ready && !md_coop_p2_disabled ? &md_coop_p2_m68k : NULL;
}

const M68K *md_coop_p2_frame_seed_context(void) {
    return md_coop_p2_frame_seed_valid ? &md_coop_p2_frame_seed : NULL;
}

void md_coop_p2_capture_native_init_seed(M68K *primary) {
    if (!primary || md_coop_p2_disabled || !md_player2_connected) {
        md_coop_p2_native_init_seed_valid = 0;
        return;
    }
    /* L_15AC is immediately before native f_19FA consumes A0's resource
       template pointer and the BF1E-derived selection registers. */
    memcpy(&md_coop_p2_native_init_seed, primary,
           sizeof md_coop_p2_native_init_seed);
    md_coop_p2_native_init_seed_valid = 1;
}

const M68K *md_coop_p2_native_init_context(void) {
    return md_coop_p2_native_init_seed_valid ?
           &md_coop_p2_native_init_seed : NULL;
}

int md_coop_p2_is_ready(void) {
    return md_coop_p2_ready && !md_coop_p2_disabled &&
           md_player2_connected && md_coop_primary_m68k != NULL;
}

void md_coop_prepare_p2(M68K *primary) {
    uint32_t callback;
    unsigned i;
    if (!primary) return;
    md_coop_primary_m68k = primary;
    if (md_coop_p2_disabled || !md_player2_connected) {
        md_coop_p2_frame_seed_valid = 0;
        return;
    }

    /* Capture the caller immediately before the original f_5DB2 render pass.
       P2 starts from this same frame-entry context, runs its own renderer, then
       carries those renderer-produced registers into its movement callback. */
    memcpy(&md_coop_p2_frame_seed, primary, sizeof md_coop_p2_frame_seed);
    md_coop_p2_frame_seed_valid = 1;

    /* L_1658 is before P1's f_5DB2 consumes the native 29-part descriptor
       list. Keep a copy so P2's f_19FA setup can clear its own scratch safely
       and we can restore only this renderer input afterward. */
    memcpy(md_coop_p2_primary_sprite_parts, &ram[0xFCE8],
           sizeof md_coop_p2_primary_sprite_parts);
    md_coop_p2_primary_sprite_parts_nonzero = 0;
    for (i = 0; i < 29u; ++i) {
        unsigned o = i * 8u;
        if (md_coop_p2_primary_sprite_parts[o] ||
            md_coop_p2_primary_sprite_parts[o + 1u] ||
            md_coop_p2_primary_sprite_parts[o + 2u] ||
            md_coop_p2_primary_sprite_parts[o + 3u])
            ++md_coop_p2_primary_sprite_parts_nonzero;
    }
    md_coop_p2_primary_sprite_parts_valid = 1;

    callback = ((uint32_t)ram[0xBC62] << 24) |
               ((uint32_t)ram[0xBC63] << 16) |
               ((uint32_t)ram[0xBC64] << 8) |
               (uint32_t)ram[0xBC65];

    if (!md_coop_p2_ready) {
        /* Only clone the live player actor once, after the game has installed
           its native player callback. The P2 CPU is never recopied per frame. */
        if (callback != 0x0000224Cu) return;

        memset(md_coop_p2_private, 0, sizeof md_coop_p2_private);
        md_coop_p2_mark(0xBC14, 0xBC24); /* native state/callback pointers */
        md_coop_p2_mark(0xBC3C, 0xBC50); /* resource callback table */
        md_coop_p2_mark(0xBC5A, 0xBC65); /* resource pointer + main actor */
        md_coop_p2_mark(0xBC6C, 0xBC6C);
        md_coop_p2_mark(0xBC70, 0xBC70);
        md_coop_p2_mark(0xBC84, 0xBC8C); /* native player state flags */
        md_coop_p2_mark(0xBC90, 0xBC91); /* player-local input */
        md_coop_p2_mark(0xBC94, 0xBC98); /* descriptor callback buffers */
        md_coop_p2_mark(0xBC9C, 0xBC9F);
        md_coop_p2_mark(0xBCA4, 0xBCA7);
        md_coop_p2_mark(0xBCAC, 0xBCB4); /* native animation transfer */
        md_coop_p2_mark(0xBCB8, 0xBCBA);
        md_coop_p2_mark(0xBCBC, 0xBD26);
        md_coop_p2_mark(0xBF08, 0xBF29); /* motion, stats and lives */
        md_coop_p2_mark(0xDC9E, 0xDD1D); /* animation transfer buffer */
        md_coop_p2_mark(0xDD1E, 0xDE1D); /* first callback work buffer */
        md_coop_p2_mark(0xDE4E, 0xDECD); /* second callback work buffer */
        md_coop_p2_mark(0xDFCE, 0xE036); /* A6 callback contexts */
        md_coop_p2_mark(0xDFD4, 0xDFDA); /* player offsets/camera */
        /* f_224C indexes this 2 KiB player work area from F224 in 16-byte
           records (BCE0 is bounded by 0x7C); f_3650/f_36E0 read the same
           frame table. Bank the whole scratch page span, not only F226. */
        md_coop_p2_mark(0xF200, 0xF9FF);
        md_coop_p2_mark(0xFCE8, 0xFDCF); /* 29-entry multipart sprite scratch */

        memset(md_coop_p2_ram, 0, sizeof md_coop_p2_ram);
        for (i = 0; i < sizeof md_coop_p2_ram; ++i)
            if (md_coop_p2_private[i]) md_coop_p2_ram[i] = ram[i];

        memset(md_coop_p2_stack, 0, sizeof md_coop_p2_stack);
        memcpy(&md_coop_p2_m68k, primary, sizeof md_coop_p2_m68k);
        md_coop_p2_m68k.a[7] = 0x00F0FFFCu;
        md_coop_p2_m68k.usp = 0x00F0FFFCu;
        md_coop_p2_m68k.ret = 0;

        /* Native f_19FA will establish P2's own callback/resource state.
           Apply the lateral spawn offset only after that setup completes. */
        md_coop_p2_ready = 1;
        md_coop_p2_log("initialized", callback,
                       "one-time P1 state seed; independent CPU and F0FFFC stack");
    }
}

void md_coop_p2_apply_spawn_offset(void) {
    uint16_t p1_x = (uint16_t)(((uint16_t)ram[0xBD1E] << 8) |
                              (uint16_t)ram[0xBD1F]);
    if (!md_coop_p2_ready || md_coop_p2_disabled) return;
    md_coop_p2_put_word(0xBD1E, (uint16_t)(p1_x + 0x0030u));
}

void md_coop_p2_restore_sprite_parts(void) {
    FILE *f;
    if (!md_coop_p2_ready || md_coop_p2_disabled ||
        !md_coop_p2_primary_sprite_parts_valid) return;
    memcpy(&md_coop_p2_ram[0xFCE8], md_coop_p2_primary_sprite_parts,
           sizeof md_coop_p2_primary_sprite_parts);
    f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
    if (f) {
        fprintf(f, "event=native-resource-seed frame=%lu template=%08X parts=%u first=%08X status=restored\n",
                md_coop_p2_frame_count,
                (unsigned)md_coop_p2_native_init_seed.a[0],
                md_coop_p2_primary_sprite_parts_nonzero,
                ((uint32_t)md_coop_p2_primary_sprite_parts[0] << 24) |
                ((uint32_t)md_coop_p2_primary_sprite_parts[1] << 16) |
                ((uint32_t)md_coop_p2_primary_sprite_parts[2] << 8) |
                (uint32_t)md_coop_p2_primary_sprite_parts[3]);
        fclose(f);
    }
}

void md_coop_p2_refresh(void) {
    if (!md_coop_p2_is_ready()) return;
    /* Port 2 is latched by the normal Genesis input path into BC92/BC93.
       The native player code consumes BC90/BC91, so present those bytes in
       the private P2 view. The camera is shared and follows P1 for now. */
    md_coop_p2_ram[0xBC90] = ram[0xBC92];
    md_coop_p2_ram[0xBC91] = ram[0xBC93];
    md_coop_p2_ram[0xDFD8] = ram[0xDFD8];
    md_coop_p2_ram[0xDFD9] = ram[0xDFD9];
    md_coop_p2_ram[0xDFDA] = ram[0xDFDA];
    ++md_coop_p2_frame_count;
}

void md_coop_p2_actor_complete(M68K *cpu, uint32_t callback) {
    unsigned i;
    FILE *f;
    if (md_coop_p2_frame_count > 10u && (md_coop_p2_frame_count % 60u) != 0u)
        return;
    md_coop_p2_log("actor-frame", callback, "P2 renderer and actor callback returned");
    f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
    if (!f || !cpu) { if (f) fclose(f); return; }
    fprintf(f, "p2_cpu d:");
    for (i = 0; i < 8u; ++i) fprintf(f, " %08X", (unsigned)cpu->d[i]);
    fprintf(f, " a:");
    for (i = 0; i < 8u; ++i) fprintf(f, " %08X", (unsigned)cpu->a[i]);
    fprintf(f, " ret=%08X usp=%08X flags=%u%u%u%u%u sr=%04X\n",
            (unsigned)cpu->ret, (unsigned)cpu->usp,
            (unsigned)cpu->x, (unsigned)cpu->n, (unsigned)cpu->z,
            (unsigned)cpu->v, (unsigned)cpu->c, (unsigned)cpu->sr_sys);
    fprintf(f, "p2_state_BC62_BD26=");
    for (i = 0xBC62u; i <= 0xBD26u; ++i)
        fprintf(f, "%02X", (unsigned)md_coop_p2_ram[i]);
    fprintf(f, "\np2_player_scratch_F200_F9FF=");
    for (i = 0xF200u; i <= 0xF9FFu; ++i)
        fprintf(f, "%02X", (unsigned)md_coop_p2_ram[i]);
    fprintf(f, "\np2_camera_DFD8_DFDA=%02X%02X%02X sprite_scratch_FD24_25=%02X%02X\n",
            (unsigned)md_coop_p2_ram[0xDFD8], (unsigned)md_coop_p2_ram[0xDFD9],
            (unsigned)md_coop_p2_ram[0xDFDA],
            (unsigned)md_coop_p2_ram[0xBD24], (unsigned)md_coop_p2_ram[0xBD25]);
    fclose(f);
}

void md_coop_p2_abort(const char *reason, uint32_t callback) {
    md_coop_p2_active = 0;
    md_coop_p2_disabled = 1;
    md_coop_p2_log("disabled", callback, reason ? reason : "runtime contract failed");
}

void md_coop_p2_finish(void) {
    md_coop_p2_active = 0;
    md_coop_primary_m68k = NULL;
}

/* RT_POLL runs inside P2's generated actor code. VDP/audio events and IRQs
   must execute against the real P1/global RAM view and the primary CPU. */
void md_coop_p2_service_event(M68K *unused) {
    int was_active = md_coop_p2_active;
    M68K *primary = md_coop_primary_m68k ? md_coop_primary_m68k : unused;
    md_coop_p2_active = 0;
    if (primary) rt_event(primary);
    md_coop_p2_active = was_active;
}

void md_coop_p2_service_irq(M68K *unused) {
    int was_active = md_coop_p2_active;
    M68K *primary = md_coop_primary_m68k ? md_coop_primary_m68k : unused;
    md_coop_p2_active = 0;
    if (primary) rt_irq_service(primary);
    md_coop_p2_active = was_active;
}
"""

if "Mega Turrican local co-op: isolated P2 actor memory view." not in HARNESS.read_text(encoding="utf-8"):
    replace_once(
        HARNESS,
        "uint8_t bus_rd8(uint32_t a){",
        HARNESS_HELPERS + "\nuint8_t bus_rd8(uint32_t a){",
        "P2 memory-view helper insertion",
    )

# Route only explicit P2-private RAM and the synthetic P2 stack through the bank.
# rd8_raw() and vdp_dma_read() are intentionally untouched: DMA still sees
# the real shared RAM image.
def insert_after_ram_mask(path: Path, signature: str, injected: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if injected.strip() in source:
        return
    pattern = re.compile(
        r"(" + signature + r"\s*\{\s*a\s*&=\s*0xFFFFFF\s*;\s*)",
        re.MULTILINE,
    )
    source, count = pattern.subn(lambda match: match.group(1) + injected, source, count=1)
    if count != 1:
        raise SystemExit(f"local co-op patch: could not find {label} signature/24-bit mask in {path}")
    path.write_text(source, encoding="utf-8", newline="\n")

insert_after_ram_mask(
    HARNESS,
    r"uint8_t\s+bus_rd8\s*\(\s*uint32_t\s+a\s*\)",
    "  if(md_coop_p2_active && a >= 0xF00000u && a < 0xF10000u) return md_coop_p2_stack[a & 0xFFFFu];\n"
    "  if(md_coop_p2_active && a >= 0xE00000u && md_coop_p2_private[a & 0xFFFFu]) return md_coop_p2_ram[a & 0xFFFFu];\n",
    "bus_rd8",
)
insert_after_ram_mask(
    HARNESS,
    r"uint16_t\s+bus_rd16\s*\(\s*uint32_t\s+a\s*\)",
    "  if(md_coop_p2_active && a >= 0xF00000u && a < 0xF10000u){ unsigned o=a&0xFFFFu; return (uint16_t)(((uint16_t)md_coop_p2_stack[o]<<8)|md_coop_p2_stack[(o+1u)&0xFFFFu]); }\n"
    "  if(md_coop_p2_active && a >= 0xE00000u){ unsigned o=a&0xFFFFu, n=(o+1u)&0xFFFFu; uint8_t h=md_coop_p2_private[o]?md_coop_p2_ram[o]:ram[o]; uint8_t l=md_coop_p2_private[n]?md_coop_p2_ram[n]:ram[n]; return (uint16_t)(((uint16_t)h<<8)|l); }\n",
    "bus_rd16",
)
insert_after_ram_mask(
    HARNESS,
    r"void\s+bus_wr8\s*\(\s*uint32_t\s+a\s*,\s*uint8_t\s+v\s*\)",
    "  if(md_coop_p2_active && a >= 0xF00000u && a < 0xF10000u){ md_coop_p2_stack[a & 0xFFFFu]=v; return; }\n"
    "  if(md_coop_p2_active && a >= 0xE00000u && md_coop_p2_private[a & 0xFFFFu]){ md_coop_p2_ram[a & 0xFFFFu]=v; return; }\n",
    "bus_wr8",
)
insert_after_ram_mask(
    HARNESS,
    r"void\s+bus_wr16\s*\(\s*uint32_t\s+a\s*,\s*uint16_t\s+v\s*\)",
    "  if(md_coop_p2_active && a >= 0xF00000u && a < 0xF10000u){ unsigned o=a&0xFFFFu; md_coop_p2_stack[o]=(uint8_t)(v>>8); md_coop_p2_stack[(o+1u)&0xFFFFu]=(uint8_t)v; return; }\n"
    "  if(md_coop_p2_active && a >= 0xE00000u){ unsigned o=a&0xFFFFu, n=(o+1u)&0xFFFFu; if(md_coop_p2_private[o]) md_coop_p2_ram[o]=(uint8_t)(v>>8); else ram[o]=(uint8_t)(v>>8); if(md_coop_p2_private[n]) md_coop_p2_ram[n]=(uint8_t)v; else ram[n]=(uint8_t)v; return; }\n",
    "bus_wr16",
)

# 2) Let generated RT_POLL service the global VDP/IRQ side using the primary CPU.
header = RT_HEADER.read_text(encoding="utf-8")
if "void md_coop_p2_service_event(M68K *c);" not in header:
    marker = "#define RT_POLL(pc)"
    if marker not in header:
        raise SystemExit("local co-op patch: RT_POLL macro anchor missing")
    decls = "extern int md_coop_p2_active;\nvoid md_coop_prepare_p2(M68K *primary);\nvoid md_coop_p2_capture_native_init_seed(M68K *primary);\nvoid md_coop_run_local_p2(M68K *primary, uint32_t callback);\nvoid md_coop_p2_service_event(M68K *c);\nvoid md_coop_p2_service_irq(M68K *c);\n"
    header = header.replace(marker, decls + marker, 1)

poll = re.compile(
    r"if\s*\(\s*--rt_budget\s*<\s*0\s*\)\s*rt_event\(c\)\s*;\s*"
    r"if\s*\(\s*rt_irq_pending\s*\)\s*rt_irq_service\(c\)\s*;"
)
if "md_coop_p2_service_event(c)" not in header:
    header, count = poll.subn(
        "if(--rt_budget<0){ if(md_coop_p2_active) md_coop_p2_service_event(c); else rt_event(c); } "
        "if(rt_irq_pending){ if(md_coop_p2_active) md_coop_p2_service_irq(c); else rt_irq_service(c); }",
        header,
        count=1,
    )
    if count != 1:
        raise SystemExit("local co-op patch: could not safely wrap RT_POLL event/IRQ dispatch")
RT_HEADER.write_text(header, encoding="utf-8", newline="\n")

# 3) Add native actor execution in the generated translation unit, where the
# static f_5DB2() renderer is visible. Every call gets a private stack frame and
# must return to the exact sentinel/stack pointer before P1 resumes.
GEN_RUNNER = r"""

/* First native Mega Turrican P2 actor runner. */
extern void md_coop_prepare_p2(M68K *primary);
extern void md_coop_p2_refresh(void);
extern void md_coop_p2_set_active(int active);
extern M68K *md_coop_p2_cpu(void);
extern const M68K *md_coop_p2_frame_seed_context(void);
extern const M68K *md_coop_p2_native_init_context(void);
extern void md_coop_p2_apply_spawn_offset(void);
extern void md_coop_p2_restore_sprite_parts(void);
extern int md_coop_p2_is_ready(void);
extern void md_coop_p2_actor_complete(M68K *cpu, uint32_t callback);
extern void md_coop_p2_abort(const char *reason, uint32_t callback);
extern void md_coop_p2_finish(void);

/* Player state persists in P2 RAM, but the game's callback also receives live
   per-frame D/A register inputs from its caller. Refresh those inputs for each
   native call while preserving P2's independent A7 and USP. */
static int md_coop_p2_native_setup_done = 0;

static void md_coop_p2_sync_call_context(M68K *p2, const M68K *primary) {
    unsigned i;
    if (!p2 || !primary) return;
    for (i = 0; i < 8u; ++i) p2->d[i] = primary->d[i];
    for (i = 0; i < 7u; ++i) p2->a[i] = primary->a[i];
    p2->x = primary->x;
    p2->n = primary->n;
    p2->z = primary->z;
    p2->v = primary->v;
    p2->c = primary->c;
    p2->sr_sys = primary->sr_sys;
}

static int md_coop_p2_call_renderer(M68K *p2) {
    const uint32_t sentinel = 0x00FEEE00u;
    uint32_t original_sp;
    int original_rt_sp;
    int ok;
    if (!p2 || rt_sp < 0 || rt_sp >= 65534) return 0;
    original_sp = p2->a[7];
    if (original_sp < 0x00F00008u || original_sp > 0x00F0FFFCu) return 0;
    original_rt_sp = rt_sp;
    p2->a[7] -= 4;
    WR32(p2->a[7], sentinel);
    rt_shadow[rt_sp++] = sentinel;
    f_5DB2(p2);
    ok = (p2->ret == sentinel && p2->a[7] == original_sp &&
          rt_sp == original_rt_sp + 1);
    rt_sp = original_rt_sp;
    return ok;
}

static int md_coop_p2_call_native_19fa(M68K *p2) {
    const uint32_t sentinel = 0x00FEEE08u;
    uint32_t original_sp;
    int original_rt_sp;
    int ok;
    if (!p2 || rt_sp < 0 || rt_sp >= 65534) return 0;
    original_sp = p2->a[7];
    if (original_sp < 0x00F00008u || original_sp > 0x00F0FFFCu) return 0;
    original_rt_sp = rt_sp;
    p2->a[7] -= 4;
    WR32(p2->a[7], sentinel);
    rt_shadow[rt_sp++] = sentinel;
    f_19FA(p2);
    ok = (p2->ret == sentinel && p2->a[7] == original_sp &&
          rt_sp == original_rt_sp + 1);
    rt_sp = original_rt_sp;
    return ok;
}

static int md_coop_p2_call_actor(M68K *p2, uint32_t target) {
    const uint32_t sentinel = 0x00FEEE04u;
    uint32_t original_sp;
    int original_rt_sp;
    int ok;
    if (!p2 || rt_sp < 0 || rt_sp >= 65534) return 0;
    original_sp = p2->a[7];
    if (original_sp < 0x00F00008u || original_sp > 0x00F0FFFCu) return 0;
    original_rt_sp = rt_sp;
    p2->a[7] -= 4;
    WR32(p2->a[7], sentinel);
    rt_shadow[rt_sp++] = sentinel;
    rt_call_addr(p2, target);
    ok = (p2->ret == sentinel && p2->a[7] == original_sp &&
          rt_sp == original_rt_sp + 1);
    rt_sp = original_rt_sp;
    return ok;
}

void md_coop_run_local_p2(M68K *primary, uint32_t callback) {
    M68K *p2;
    const M68K *frame_seed;
    if (!primary || !md_coop_p2_is_ready()) return;
    md_coop_p2_refresh();
    if (!md_coop_p2_is_ready()) return;
    p2 = md_coop_p2_cpu();
    frame_seed = md_coop_p2_frame_seed_context();
    if (!p2 || !frame_seed) return;

    if (!md_coop_p2_native_setup_done) {
        const M68K *init_seed = md_coop_p2_native_init_context();
        if (init_seed) {
            md_coop_p2_sync_call_context(p2, init_seed);
            md_coop_p2_set_active(1);
            if (!md_coop_p2_call_native_19fa(p2)) {
                md_coop_p2_abort("P2 native f_19FA setup did not restore its CPU stack/return frame", 0x19FAu);
                md_coop_p2_finish();
                return;
            }
            md_coop_p2_set_active(0);
            md_coop_p2_apply_spawn_offset();
            md_coop_p2_restore_sprite_parts();
        }
        md_coop_p2_native_setup_done = 1;
    }

    /* f_19FA consumes the native resource template once for P2. Resume the
       exact pre-render register context captured at L_1658 for the body pass. */
    md_coop_p2_sync_call_context(p2, frame_seed);
    md_coop_p2_set_active(1);
    if (!md_coop_p2_call_renderer(p2)) {
        md_coop_p2_abort("P2 sprite builder did not restore its CPU stack/return frame", 0);
        md_coop_p2_finish();
        return;
    }

    /* Initial implementation follows the game's verified native player actor.
       A different callback is treated as an unsupported state, not guessed. */
    if (callback != 0x0000224Cu) {
        md_coop_p2_abort("P2 callback changed from verified native entry 0x224C", callback);
        md_coop_p2_finish();
        return;
    }
    if (!md_coop_p2_call_actor(p2, callback)) {
        md_coop_p2_abort("P2 actor did not restore its CPU stack/return frame", callback);
        md_coop_p2_finish();
        return;
    }
    md_coop_p2_set_active(0);
    md_coop_p2_actor_complete(p2, callback);
    md_coop_p2_finish();
}
"""

gen = GEN.read_text(encoding="utf-8")
if "First native Mega Turrican P2 actor runner." not in gen:
    gen += GEN_RUNNER
    GEN.write_text(gen, encoding="utf-8", newline="\n")

# 4) Seed P2 before the sprite-builder seam, then run P2's render/update pass
# at the callback call site, before P1 enters the same native actor routine.
replace_once(
    GEN,
    "L_1658: { RT_POLL(0x1658); { uint32_t _r=0x165Cu;",
    "L_1658: { RT_POLL(0x1658); md_coop_prepare_p2(c); { uint32_t _r=0x165Cu;",
    "P2 one-time seed hook at player render seam",
)

replace_once(
    GEN,
    "L_15AC: { RT_POLL(0x15AC); { uint32_t _r=0x15B0u;",
    "L_15AC: { RT_POLL(0x15AC); md_coop_p2_capture_native_init_seed(c); { uint32_t _r=0x15B0u;",
    "P2 native resource-template capture before f_19FA",
)

line = re.compile(
    r"(L_1660:\s*\{[^\n]*?rt_shadow\[rt_sp\+\+\]=_r;\s*)"
    r"rt_call_addr\(c,_t\);"
)
gen = GEN.read_text(encoding="utf-8")
if "md_coop_run_local_p2(c,_t);" not in gen:
    gen, count = line.subn(r"\1md_coop_run_local_p2(c,_t); rt_call_addr(c,_t);", gen, count=1)
    if count != 1:
        raise SystemExit("local co-op patch: verified pre-callback L_1660 seam not found")
    GEN.write_text(gen, encoding="utf-8", newline="\n")

# 5) Static contract checks. These do not prove gameplay; they ensure the
# patch is installed once, P2 gets a private stack/bus bank, and the old unsafe
# all-RAM shadow script remains untouched.
h = HARNESS.read_text(encoding="utf-8")
g = GEN.read_text(encoding="utf-8")
r = RT_HEADER.read_text(encoding="utf-8")
checks = {
    "P2 owns persistent M68K context": "static M68K md_coop_p2_m68k;" in h,
    "P2 uses a separate synthetic stack": "0x00F0FFFCu" in h and "md_coop_p2_stack" in h,
    "P2 private RAM uses explicit allowlist": "md_coop_p2_mark(0xBCBC, 0xBD26)" in h,
    "P2 owns full indexed player work area": "md_coop_p2_mark(0xF200, 0xF9FF)" in h and "p2_player_scratch_F200_F9FF=" in h,
    "P2 input is sourced from port 2": "md_coop_p2_ram[0xBC90] = ram[0xBC92]" in h,
    "P2 actor runs immediately before P1 actor": "md_coop_run_local_p2(c,_t); rt_call_addr(c,_t);" in g,
    "P2 captures the original pre-render frame context": "static M68K md_coop_p2_frame_seed;" in h and "md_coop_p2_frame_seed_context" in g,
    "P2 captures pre-f_19FA register/template context": "md_coop_p2_capture_native_init_seed(c)" in g and "md_coop_p2_native_init_seed_valid" in h,
    "P2 capture hook has a prototype before f_156A": "void md_coop_p2_capture_native_init_seed(M68K *primary);" in r,
    "P2 builds native callback/resource state through f_19FA": "f_19FA(p2);" in g and "md_coop_p2_call_native_19fa(p2)" in g,
    "P2 keeps f_19FA callback buffers private": "md_coop_p2_mark(0xBC3C, 0xBC50)" in h and "md_coop_p2_mark(0xDD1E, 0xDE1D)" in h and "md_coop_p2_mark(0xDE4E, 0xDECD)" in h and "md_coop_p2_mark(0xDFCE, 0xE036)" in h,
    "P2 restores only the native sprite-part input after f_19FA": "md_coop_p2_restore_sprite_parts();" in g and "memcpy(&md_coop_p2_ram[0xFCE8], md_coop_p2_primary_sprite_parts" in h,
    "P2 applies its side-by-side offset after native setup": "md_coop_p2_apply_spawn_offset();" in g,
    "P2 keeps its renderer register results for movement": "md_coop_p2_sync_call_context(p2, frame_seed);" in g and "md_coop_p2_sync_call_context(p2, primary);" not in g,
    "P2 actor trace captures CPU and private state": "p2_state_BC62_BD26=" in h and "p2_cpu d:" in h,
    "P2 renderer uses native f_5DB2": "f_5DB2(p2);" in g,
    "P2 callback is guarded": "callback != 0x0000224Cu" in g,
    "global events suspend P2 memory view": "md_coop_p2_service_event(c)" in r and "md_coop_p2_service_irq(c)" in r,
    "DMA raw reads remain untouched": "uint16_t vdp_dma_read" in h and "rd8_raw(a)" in h and "rd8_raw(a + 1)" in h,
}
for label, passed in checks.items():
    if not passed:
        raise SystemExit("local co-op verification failed: " + label)

print("Installed guarded native P2 actor prototype: independent CPU/stack, native f_19FA resource setup, private callback buffers, port-2 input and native sprite builder.")
print("P2 preserves P1's pre-render sprite-part inputs across its one-time native setup; gameplay still requires in-game verification.")
