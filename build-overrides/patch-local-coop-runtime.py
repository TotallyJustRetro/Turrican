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

    callback = ((uint32_t)ram[0xBC62] << 24) |
               ((uint32_t)ram[0xBC63] << 16) |
               ((uint32_t)ram[0xBC64] << 8) |
               (uint32_t)ram[0xBC65];

    if (!md_coop_p2_ready) {
        /* Only clone the live player actor once, after the game has installed
           its native player callback. The P2 CPU is never recopied per frame. */
        if (callback != 0x0000224Cu) return;

        memset(md_coop_p2_private, 0, sizeof md_coop_p2_private);
        md_coop_p2_mark(0xBC1C, 0xBC23); /* pre/post actor callbacks */
        md_coop_p2_mark(0xBC3C, 0xBC4F); /* descriptor setup callbacks */
        md_coop_p2_mark(0xBC62, 0xBC65); /* main actor callback */
        md_coop_p2_mark(0xBC5A, 0xBC5D); /* current player resource table */
        md_coop_p2_mark(0xBC5E, 0xBC61); /* player transition callback */
        md_coop_p2_mark(0xBC68, 0xBC68); /* player contact/weapon state */
        md_coop_p2_mark(0xBC6C, 0xBC6C);
        md_coop_p2_mark(0xBC7E, 0xBC83); /* per-player input sequence pointer/state */
        md_coop_p2_mark(0xBC70, 0xBC70);
        md_coop_p2_mark(0xBC84, 0xBC8B);
        md_coop_p2_mark(0xBC90, 0xBC91);
        md_coop_p2_mark(0xBC94, 0xBC9B); /* player-specific DMA descriptors */
        md_coop_p2_mark(0xBC9C, 0xBC9F);
        md_coop_p2_mark(0xBCA4, 0xBCB4); /* animation/work descriptors */
        md_coop_p2_mark(0xBCC2, 0xBCC8); /* alternate animation state */
        md_coop_p2_mark(0xBCBC, 0xBD26);
        md_coop_p2_mark(0xBD28, 0xBD29); /* player descriptor base */
        md_coop_p2_mark(0xBF08, 0xBF29); /* player motion/camera/stats */
        md_coop_p2_mark(0xDFD8, 0xDFDA); /* private camera candidate */
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

        /* Place P2 beside P1 without changing the shared camera. */
        md_coop_p2_put_word(0xBD1E,
            (uint16_t)(md_coop_p2_word(0xBD1E) + 0x0030u));
        md_coop_p2_ready = 1;
        md_coop_p2_log("initialized", callback,
                       "one-time P1 state seed; independent CPU and F0FFFC stack");
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

/* f_8BE is an event-driven poll on BC85. Its completion flag is produced by
   the main frame/event path, which services interrupts with the primary RAM
   view. Copy the already-completed P1 latch rather than polling inside the
   isolated P2 bank where the event cannot update it. */
void md_coop_p2_sync_handshake(void) {
    if (md_coop_p2_ready && !md_coop_p2_disabled)
        md_coop_p2_ram[0xBC85] = ram[0xBC85];
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
    decls = "extern int md_coop_p2_active;\nvoid md_coop_prepare_p2(M68K *primary);\nvoid md_coop_run_local_p2(M68K *primary, uint32_t callback);\nvoid md_coop_run_local_p2_post(M68K *primary);\nvoid md_coop_p2_service_event(M68K *c);\nvoid md_coop_p2_service_irq(M68K *c);\n"
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

/* Native Mega Turrican P2 frame slice. */
extern void md_coop_prepare_p2(M68K *primary);
extern void md_coop_p2_refresh(void);
extern void md_coop_p2_sync_handshake(void);
extern void md_coop_p2_set_active(int active);
extern M68K *md_coop_p2_cpu(void);
extern const M68K *md_coop_p2_frame_seed_context(void);
extern int md_coop_p2_is_ready(void);
extern void md_coop_p2_actor_complete(M68K *cpu, uint32_t callback);
extern void md_coop_p2_abort(const char *reason, uint32_t callback);
extern void md_coop_p2_finish(void);

/* P2 keeps its own A7/USP and player RAM, while receiving the frame-entry
   non-stack registers from the original player at the same point in the loop. */
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

static int md_coop_p2_call_native(M68K *p2, uint32_t target, uint32_t sentinel) {
    uint32_t original_sp;
    int original_rt_sp;
    int ok;
    if (!p2 || !target || rt_sp < 0 || rt_sp >= 65534) return 0;
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

static int md_coop_p2_call_slot(M68K *p2, unsigned slot, uint32_t sentinel) {
    uint32_t target;
    if (!p2 || slot > 0xFFFCu) return 0;
    target = RD32(0xFFFF0000u + (uint32_t)slot);
    if (!target) return 1;
    /* The original dispatch loads the function pointer into A0 before calling. */
    p2->a[0] = target;
    return md_coop_p2_call_native(p2, target, sentinel);
}

/* Runs before P1's callback and shared render-queue flush. Only player-owned
   setup, animation and sprite-building routines are repeated here. */
void md_coop_run_local_p2(M68K *primary, uint32_t callback) {
    M68K *p2;
    const M68K *frame_seed;
    if (!primary || !md_coop_p2_is_ready()) return;
    md_coop_p2_refresh();
    if (!md_coop_p2_is_ready()) return;
    p2 = md_coop_p2_cpu();
    frame_seed = md_coop_p2_frame_seed_context();
    if (!p2 || !frame_seed) return;

    md_coop_p2_sync_call_context(p2, frame_seed);
    md_coop_p2_sync_handshake();
    md_coop_p2_set_active(1);

    /* Match f_156A's player-local preamble in its original order. */
    if (!md_coop_p2_call_native(p2, 0x00005D8Au, 0x00FEEE08u) ||
        !md_coop_p2_call_native(p2, 0x00003B38u, 0x00FEEE0Cu) ||
        !md_coop_p2_call_native(p2, 0x00001E00u, 0x00FEEE10u)) {
        md_coop_p2_abort("P2 per-frame state preamble did not restore its private stack", callback);
        md_coop_p2_finish();
        return;
    }

    /* Mirror PCs 0x15DE-0x1614, including the conditional input/state
       branch. The old P2 pass skipped it, leaving BD26 and BC82/83 stale. */
    fl_logic(p2, RD8(0xFFFFBC88u), 8);
    if (!cond(p2, 6)) {
        p2->d[0] = 2u;
        p2->a[0] = RD32(0xFFFFBC5Au);
        if (!md_coop_p2_call_native(p2, 0x000005BCu, 0x00FEEE14u)) {
            md_coop_p2_abort("P2 animation descriptor setup failed", callback);
            md_coop_p2_finish();
            return;
        }
    }
    /* f_8BE is intentionally not rerun: its BC85 wait is serviced by the
       original event path. P2 received the completed BC85 latch above. */

    /* The original checks BC70, then port-1 START in bit 7 (P2's BC90 is
       fed from controller port 2). Keep the same conditional BD26/BC70
       writes and invoke f_E0C with P2's own BC7E cursor and BC82/83 bytes. */
    fl_logic(p2, RD8(0xFFFFBC70u), 8);
    if (!cond(p2, 7)) {
        p2->z = (RD8(0xFFFFBC90u) & 0x80u) == 0u;
        if (!cond(p2, 6)) {
            WR8(0xFFFFBD26u, cond(p2, 0) ? 0xFFu : 0u);
            WR8(0xFFFFBC70u, 1u);
        }
        if (!md_coop_p2_call_native(p2, 0x00000E0Cu, 0x00FEEE1Cu)) {
            md_coop_p2_abort("P2 input/ground-state update failed", callback);
            md_coop_p2_finish();
            return;
        }
    }

    /* PC 0x160E reloads BF28 before testing whether the alternate animation
       state callback f_2150 should run. */
    fl_logic(p2, RD16(0xFFFFBF28u), 16);
    if (!cond(p2, 6) &&
        !md_coop_p2_call_native(p2, 0x00002150u, 0x00FEEE20u)) {
        md_coop_p2_abort("P2 alternate animation-state update failed", callback);
        md_coop_p2_finish();
        return;
    }

    /* f_156A installs the callback-specific A6 contexts before the first two
       descriptor calls. The targets consume these base pointers indirectly. */
    p2->a[6] = 0xFFFFDFCEu;
    if (!md_coop_p2_call_slot(p2, 0xBC3Cu, 0x00FEEE20u)) {
        md_coop_p2_abort("P2 first descriptor callback did not restore its private stack", callback);
        md_coop_p2_finish();
        return;
    }
    p2->a[6] = 0xFFFFE002u;
    if (!md_coop_p2_call_slot(p2, 0xBC44u, 0x00FEEE24u) ||
        !md_coop_p2_call_slot(p2, 0xBC4Cu, 0x00FEEE28u) ||
        !md_coop_p2_call_slot(p2, 0xBC1Cu, 0x00FEEE2Cu)) {
        md_coop_p2_abort("P2 descriptor callbacks did not restore its private stack", callback);
        md_coop_p2_finish();
        return;
    }

    /* f_3D80 owns BD28/BF08/BF0C and must run independently for P2. */
    if (!md_coop_p2_call_native(p2, 0x00003D80u, 0x00FEEE30u)) {
        md_coop_p2_abort("P2 player descriptor update failed", callback);
        md_coop_p2_finish();
        return;
    }

    if (callback != 0x0000224Cu) {
        md_coop_p2_abort("P2 callback changed from verified native entry 0x224C", callback);
        md_coop_p2_finish();
        return;
    }
    if (!md_coop_p2_call_native(p2, 0x00005DB2u, 0x00FEEE34u)) {
        md_coop_p2_abort("P2 sprite builder failed to restore its private stack", callback);
        md_coop_p2_finish();
        return;
    }
    /* PC 0x165C loads BC62 into A0 before the original indirect dispatch. */
    p2->a[0] = callback;
    if (!md_coop_p2_call_native(p2, callback, 0x00FEEE38u)) {
        md_coop_p2_abort("P2 sprite builder/player callback failed to restore its private stack", callback);
        md_coop_p2_finish();
        return;
    }

    /* Return to the primary frame with P2 state retained. f_5472 must flush
       the combined P1/P2 queue before P2's post-contact pass runs. */
    md_coop_p2_set_active(0);
}

/* Called after the shared f_5472 queue flush and before P1's f_3BD8/BC20 pass. */
void md_coop_run_local_p2_post(M68K *primary) {
    M68K *p2;
    if (!primary || !md_coop_p2_is_ready()) return;
    p2 = md_coop_p2_cpu();
    if (!p2) return;

    md_coop_p2_set_active(1);
    if (!md_coop_p2_call_native(p2, 0x00003BD8u, 0x00FEEE3Cu) ||
        !md_coop_p2_call_slot(p2, 0xBC20u, 0x00FEEE40u)) {
        md_coop_p2_abort("P2 post-contact/state callbacks failed to restore its private stack", 0x224C);
        md_coop_p2_finish();
        return;
    }
    md_coop_p2_set_active(0);
    md_coop_p2_actor_complete(p2, 0x224C);
    md_coop_p2_finish();
}
"""

gen = GEN.read_text(encoding="utf-8")
if "Native Mega Turrican P2 frame slice." not in gen:
    gen += GEN_RUNNER
    GEN.write_text(gen, encoding="utf-8", newline="\n")

# 4) Capture P2's frame-entry registers before the original player preamble.
# Run P2's actor slice before the P1 actor, then its contact pass after the
# shared render queue flush and before P1's own contact pass.
replace_once(
    GEN,
    "L_15D2: { RT_POLL(0x15D2); { uint32_t _r=0x15D6u;",
    "L_15D2: { RT_POLL(0x15D2); md_coop_prepare_p2(c); { uint32_t _r=0x15D6u;",
    "P2 frame-entry seed hook",
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

# Insert P2 post-contact processing after the shared output queue is flushed.
post_hook = (
    "L_1666: { RT_POLL(0x1666); { uint32_t _r=0x166Au;"
)
post_replacement = (
    "L_1666: { RT_POLL(0x1666); md_coop_run_local_p2_post(c); { uint32_t _r=0x166Au;"
)
replace_once(GEN, post_hook, post_replacement, "post-render P2 contact hook")

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
    "P2 owns pre/post callback slots": "md_coop_p2_mark(0xBC1C, 0xBC23)" in h and "md_coop_p2_mark(0xBC3C, 0xBC4F)" in h,
    "P2 owns input sequence state for f_E0C": "md_coop_p2_mark(0xBC7E, 0xBC83)" in h,
    "P2 owns animation descriptor RAM": "md_coop_p2_mark(0xBCA4, 0xBCB4)" in h and "md_coop_p2_mark(0xBCC2, 0xBCC8)" in h,
    "P2 owns descriptor pointers and DMA slots": "md_coop_p2_mark(0xBC5A, 0xBC5D)" in h and "md_coop_p2_mark(0xBC94, 0xBC9B)" in h,
    "P2 restores descriptor callback A6 contexts": "p2->a[6] = 0xFFFFDFCEu;" in g and "p2->a[6] = 0xFFFFE002u;" in g,
    "P2 owns motion descriptor RAM": "md_coop_p2_mark(0xBF08, 0xBF29)" in h and "md_coop_p2_mark(0xBD28, 0xBD29)" in h,
    "P2 resets private multipart scratch every frame": "0x00005D8Au" in g,
    "P2 mirrors BC70/port-2 state branch": "RD8(0xFFFFBC70u)" in g and "RD8(0xFFFFBC90u) & 0x80u" in g,
    "P2 mirrors f_5BC A0 input": "p2->a[0] = RD32(0xFFFFBC5Au);" in g,
    "P2 runs f_E0C input/ground-state update": "0x00000E0Cu" in g,
    "P2 inherits completed BC85 event handshake instead of polling": "md_coop_p2_sync_handshake();" in g and "md_coop_p2_ram[0xBC85] = ram[0xBC85];" in h and "0x000008BEu" not in g,
    "P2 reloads BF28 before conditional animation callback": "fl_logic(p2, RD16(0xFFFFBF28u), 16);" in g,
    "P2 main callback gets its A0 target": "p2->a[0] = callback;" in g,
    "P2 callback-slot dispatch loads A0": "p2->a[0] = target;" in g,
    "P2 runs player-local animation preamble": "0x00003B38u" in g and "0x00001E00u" in g and "0x00002150u" in g,
    "P2 runs native sprite builder through guarded call wrapper": "md_coop_p2_call_native(p2, 0x00005DB2u" in g,
    "P2 post-contact pass is after shared render flush": "md_coop_run_local_p2_post(c);" in g and "L_1666:" in g,
    "P2 post pass calls contact/state routines": "md_coop_p2_call_native(p2, 0x00003BD8u" in g and "md_coop_p2_call_slot(p2, 0xBC20u" in g,
    "P2 owns full indexed player work area": "md_coop_p2_mark(0xF200, 0xF9FF)" in h and "p2_player_scratch_F200_F9FF=" in h,
    "P2 input is sourced from port 2": "md_coop_p2_ram[0xBC90] = ram[0xBC92]" in h,
    "P2 actor runs immediately before P1 actor": "md_coop_run_local_p2(c,_t); rt_call_addr(c,_t);" in g,
    "P2 captures the original pre-render frame context": "static M68K md_coop_p2_frame_seed;" in h and "md_coop_p2_frame_seed_context" in g,
    "P2 keeps its renderer register results for movement": "md_coop_p2_sync_call_context(p2, frame_seed);" in g and "md_coop_p2_sync_call_context(p2, primary);" not in g,
    "P2 actor trace captures CPU and private state": "p2_state_BC62_BD26=" in h and "p2_cpu d:" in h,
    "P2 renderer uses native f_5DB2 through guarded call wrapper": "md_coop_p2_call_native(p2, 0x00005DB2u" in g,
    "P2 callback is guarded": "callback != 0x0000224Cu" in g,
    "global events suspend P2 memory view": "md_coop_p2_service_event(c)" in r and "md_coop_p2_service_irq(c)" in r,
    "DMA raw reads remain untouched": "uint16_t vdp_dma_read" in h and "rd8_raw(a)" in h and "rd8_raw(a + 1)" in h,
}
for label, passed in checks.items():
    if not passed:
        raise SystemExit("local co-op verification failed: " + label)

print("Installed P2 frame slice: frame-entry context, private animation/motion RAM, native player preamble, sprite builder/actor, and post-flush contact callbacks.")
print("P2 runtime snapshots include CPU registers and private player/scratch state; gameplay still requires in-game verification.")
