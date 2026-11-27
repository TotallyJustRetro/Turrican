#!/usr/bin/env python3
"""
Install the first native second-actor runtime for Mega Turrican.

This is deliberately a constrained prototype:
- P2 owns an independently persistent M68K context and private 68000 stack.
- Player-local RAM and the sprite scratch area are banked through the CPU bus.
- World/object pools, DMA reads, VDP state and the shared render queue remain shared.
- P2 is sampled from physical controller port 2 when connected, or can be forced on by the persistent Game Options toggle.
- A transient CPU/stack return mismatch soft-resets P2 so it can reseed from P1;
  repeated faults in a short window disable P2 rather than continuing with corrupt state.

It does not enable the launcher multiplayer UI or claim full co-op completion.
"""
from pathlib import Path
import os
import re
import sys

# ---------------------------------------------------------------------------
# PLAYER COUNT. Change this one number (or set env MT_COOP_PLAYERS) to get
# 2, 3 or 4 players. Player 1 is the original game actor; every additional
# player is a private "slot" (own CPU context, stack, player RAM bank, scratch).
# ---------------------------------------------------------------------------
COOP_PLAYERS = max(2, min(4, int(os.environ.get("MT_COOP_PLAYERS", "3"))))
# 0 = extra players get a private, never-drained DMA queue (safe default).
# 1 = extra players append to the real shared VDP DMA queue.
VDP_QUEUE_SHARED = int(os.environ.get("MT_COOP_VDP_QUEUE_SHARED", "0"))
# Skip an extra player's sprite build when fewer than this many free records
# remain in the shared 79-record object pool (one character needs up to 29).
POOL_RESERVE = int(os.environ.get("MT_COOP_POOL_RESERVE", "36"))
OBJ_OWNER = int(os.environ.get("MT_COOP_OBJ_OWNER", "1"))

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

# 1) Add independent per-player memory slots, CPU bus views and event handoff.
HARNESS_HELPERS = r"""
/* Mega Turrican local co-op: isolated P2 actor memory view. */
#include <string.h>
extern int md_local_coop_enabled;
extern int md_player_live_masks[4];
extern int md_player_connected[4];

#ifndef MT_COOP_PLAYERS
#define MT_COOP_PLAYERS 2
#endif
#ifndef MT_COOP_VDP_QUEUE_SHARED
#define MT_COOP_VDP_QUEUE_SHARED 0
#endif
#ifndef MT_COOP_POOL_RESERVE
#define MT_COOP_POOL_RESERVE 36
#endif
#ifndef MT_COOP_OBJ_OWNER
#define MT_COOP_OBJ_OWNER 1
#endif
#define MT_COOP_SLOTS (MT_COOP_PLAYERS - 1)
#ifndef MT_COOP_DIAG
#define MT_COOP_DIAG 1
#endif

/* One slot per additional player. The legacy md_coop_p2_* names below are
   macros that always resolve to the CURRENT slot, so every routine written for
   "P2" runs unchanged for P2, P3, P4... The runner selects the slot first. */
typedef struct {
    uint8_t ram[0x10000];
    uint8_t priv[0x10000];
    uint8_t stack[0x10000];
    uint8_t shared_w[0x10000];          /* audit: shared bytes this slot wrote */
    uint8_t shared_w_reported[0x10000];
    M68K m68k, frame_seed, collision_seed, spatial_seed, motion_seed;
    int collision_seed_valid, spatial_seed_valid, motion_seed_valid;
    uint8_t primary_collision_desc[0x1E0];
    unsigned primary_collision_count;
    int primary_collision_desc_valid;
    unsigned collision_shadow_count;
    uint32_t collision_result_log_frames;
    int frame_seed_valid, ready, disabled;
    unsigned long frame_count, abort_frame;
    unsigned abort_count;
    unsigned pool_skips;
} md_coop_slot_t;

int md_coop_p2_active = 0;
/* Pad bytes (BC90/BC91 layout) for players 3+; slot 0 (P2) reads port 2. */
static md_coop_slot_t md_coop_slots[MT_COOP_SLOTS];
static unsigned md_coop_cur = 0;
#define MD_CUR (md_coop_slots[md_coop_cur])
#define md_coop_p2_ram MD_CUR.ram
#define md_coop_p2_private MD_CUR.priv
#define md_coop_p2_stack MD_CUR.stack
#define md_coop_p2_m68k MD_CUR.m68k
#define md_coop_p2_frame_seed MD_CUR.frame_seed
#define md_coop_p2_collision_seed MD_CUR.collision_seed
#define md_coop_p2_collision_seed_valid MD_CUR.collision_seed_valid
#define md_coop_p2_spatial_seed MD_CUR.spatial_seed
#define md_coop_p2_spatial_seed_valid MD_CUR.spatial_seed_valid
#define md_coop_p2_motion_seed MD_CUR.motion_seed
#define md_coop_p2_motion_seed_valid MD_CUR.motion_seed_valid
#define md_coop_p2_primary_collision_desc MD_CUR.primary_collision_desc
#define md_coop_p2_primary_collision_count MD_CUR.primary_collision_count
#define md_coop_p2_primary_collision_desc_valid MD_CUR.primary_collision_desc_valid
#define md_coop_p2_collision_shadow_count MD_CUR.collision_shadow_count
#define md_coop_p2_collision_result_log_frames MD_CUR.collision_result_log_frames
#define md_coop_p2_frame_seed_valid MD_CUR.frame_seed_valid
#define md_coop_p2_ready MD_CUR.ready
#define md_coop_p2_disabled MD_CUR.disabled
#define md_coop_p2_frame_count MD_CUR.frame_count
#define md_coop_p2_abort_frame MD_CUR.abort_frame
#define md_coop_p2_abort_count MD_CUR.abort_count
static M68K *md_coop_primary_m68k = NULL;
/* Each extra player starts 0x10 px further right than the previous one. */
#define MD_COOP_SPAWN_DX (0x0010u * (md_coop_cur + 1u))

unsigned md_coop_p2_slot_count(void) { return MT_COOP_SLOTS; }

/* Object ownership: pool records remain in the shared world list, but an
   object created while an extra player is active remembers that player.
   Its per-frame handler then runs with that player's private RAM/CPU view. */
static uint8_t md_obj_owner[0x10000];
static int md_obj_ctx = 0;
unsigned long md_obj_dispatch_count = 0;

void md_obj_note_alloc(M68K *c) {
#if MT_COOP_OBJ_OWNER
    uint32_t rec;
    if (!c) return;
    rec = c->a[0] & 0xFFFFu;
    if (rec == 0xBF3Cu) return; /* shared fallback record is never owned */
    md_obj_owner[rec] = md_coop_p2_active ? (uint8_t)(md_coop_cur + 1u) : 0u;
#else
    (void)c;
#endif
}

void md_obj_enter(M68K *c) {
#if MT_COOP_OBJ_OWNER
    unsigned o;
    if (!c) return;
    o = md_obj_owner[c->a[5] & 0xFFFFu];
    md_obj_ctx = 0;
    if (o != 0u && o <= MT_COOP_SLOTS && !md_coop_p2_active &&
        md_coop_slots[o - 1u].ready && !md_coop_slots[o - 1u].disabled) {
        md_coop_cur = o - 1u;
        md_coop_p2_active = 1;
        md_obj_ctx = 1;
        ++md_obj_dispatch_count;
    }
#else
    (void)c;
#endif
}

void md_obj_leave(void) {
    if (md_obj_ctx) {
        md_coop_p2_active = 0;
        md_coop_cur = 0u;
        md_obj_ctx = 0;
    }
}

void md_coop_p2_select(unsigned slot) { md_coop_cur = slot < MT_COOP_SLOTS ? slot : 0u; }

/* Shared-write audit. While an extra player's code runs, every byte it writes
   OUTSIDE its private bank is recorded. Anything unexpected in
   MegaTurrican-coop-shared-writes.txt is a shared-state leak, which is exactly
   what produces glitches like a corrupted HUD or scroll. */
void md_coop_p2_note_shared_write(unsigned a, unsigned len) {
    unsigned i;
    for (i = 0; i < len; ++i) MD_CUR.shared_w[(a + i) & 0xFFFFu] = 1;
}

void md_coop_p2_flush_audit(void) {
    unsigned i, start;
    FILE *f = NULL;
    for (i = 0; i < 0x10000u; ) {
        if (MD_CUR.shared_w[i] && !MD_CUR.shared_w_reported[i]) {
            start = i;
            while (i < 0x10000u && MD_CUR.shared_w[i] && !MD_CUR.shared_w_reported[i]) {
                MD_CUR.shared_w_reported[i] = 1; ++i;
            }
            if (!f) f = fopen("MegaTurrican-coop-shared-writes.txt", "a");
            if (!f) return;
            fprintf(f, "slot=%u frame=%lu new_shared_write FF%04X-FF%04X\n",
                    md_coop_cur + 2u, md_coop_p2_frame_count, start, i - 1u);
        } else ++i;
    }
    if (f) fclose(f);
}

/* Physical pad 2 enables P2 automatically; the persistent Game Options
   override can also force the actor on when no second controller is attached. */
/* Convert the SDL logical mask to the exact native 16-bit Genesis
   active-low player word consumed at BC90/BC91. The hardware layout is:
   UP/DOWN/LEFT/RIGHT -> bits 8..11, B/C/A/START -> bits 12/13/14/15.
   The existing P2 trace verifies B=EFFF, B+START=6FFF, B+RIGHT=E7FF. */
static uint16_t md_coop_encode_genesis_input(unsigned mask) {
    static const uint16_t bits[8] = {
        0x0100u, 0x0200u, 0x0400u, 0x0800u,
        0x4000u, 0x1000u, 0x2000u, 0x8000u
    };
    uint16_t value = 0xFFFFu;
    unsigned i;
    for (i = 0; i < 8u; ++i)
        if (mask & (1u << i)) value = (uint16_t)(value & (uint16_t)~bits[i]);
    return value;
}

static int md_coop_p2_requested(void) {
    const unsigned player = md_coop_cur + 1u; /* slot 0 is P2, slot 1 is P3, ... */
    if (player >= 4u) return 0;
    if (md_player_connected[player]) return 1;
    /* Preserve the existing Game Options override for P2 only. P3/P4 require
       their own detected controller, so enabling P2 never creates idle extra actors. */
    return player == 1u && md_local_coop_enabled;
}

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

static void md_coop_p2_put_long(unsigned at, uint32_t value) {
    md_coop_p2_ram[at] = (uint8_t)(value >> 24);
    md_coop_p2_ram[(at + 1u) & 0xFFFFu] = (uint8_t)(value >> 16);
    md_coop_p2_ram[(at + 2u) & 0xFFFFu] = (uint8_t)(value >> 8);
    md_coop_p2_ram[(at + 3u) & 0xFFFFu] = (uint8_t)value;
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
    fprintf(f, "slot=%u event=%s frame=%lu connected=%d forced=%d callback=%06X p2_x=%04X p2_y=%04X input=%02X%02X detail=%s\n",
            md_coop_cur + 2u, event, md_coop_p2_frame_count,
            md_player_connected[md_coop_cur + 1u],
            (md_coop_cur == 0u) ? md_local_coop_enabled : 0, callback,
            md_coop_p2_word(0xBD1E), md_coop_p2_word(0xBD20),
            md_coop_p2_ram[0xBC90], md_coop_p2_ram[0xBC91],
            detail ? detail : "-");
    fclose(f);
}

/* Frame-by-frame probe around the native player ground/collision calculation.
   Only writes while the private P2 bus is active, and only for the first
   420 P2 ticks of each run so the diagnostic file stays bounded. */
void md_coop_p2_trace_ground(const char *stage, M68K *cpu) {
    FILE *f;
    unsigned i;
    if (!md_coop_p2_active || !md_coop_p2_ready ||
        md_coop_p2_frame_count > 420u) return;
    f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
    if (!f) return;
    fprintf(f,
        "event=p2-ground stage=%s frame=%lu xy=%04X,%04X "
        "in=%02X%02X BCEA=%04X BC8A=%02X BC8B=%02X "
        "BCF0=%02X BCF1=%02X BCF2=%02X BCFC=%02X BCFE=%02X "
        "BCD8=%02X BCD9=%02X BD02=%02X BD04=%02X "
        "BD12=%02X%02X BD14=%02X BD1D=%02X BD22=%02X "
        "BCC0=%04X BCC2=%04X BCC8=%04X BCE0=%04X BCE2=%04X BCE4=%02X BCE5=%02X",
        stage ? stage : "-", md_coop_p2_frame_count,
        md_coop_p2_word(0xBD1E), md_coop_p2_word(0xBD20),
        md_coop_p2_ram[0xBC90], md_coop_p2_ram[0xBC91],
        md_coop_p2_word(0xBCEA),
        md_coop_p2_ram[0xBC8A], md_coop_p2_ram[0xBC8B],
        md_coop_p2_ram[0xBCF0], md_coop_p2_ram[0xBCF1],
        md_coop_p2_ram[0xBCF2], md_coop_p2_ram[0xBCFC],
        md_coop_p2_ram[0xBCFE], md_coop_p2_ram[0xBCD8],
        md_coop_p2_ram[0xBCD9], md_coop_p2_ram[0xBD02],
        md_coop_p2_ram[0xBD04], md_coop_p2_ram[0xBD12],
        md_coop_p2_ram[0xBD13], md_coop_p2_ram[0xBD14],
        md_coop_p2_ram[0xBD1D], md_coop_p2_ram[0xBD22],
        md_coop_p2_word(0xBCC0), md_coop_p2_word(0xBCC2),
        md_coop_p2_word(0xBCC8), md_coop_p2_word(0xBCE0),
        md_coop_p2_word(0xBCE2), md_coop_p2_ram[0xBCE4],
        md_coop_p2_ram[0xBCE5]);
    if (cpu) {
        fprintf(f, " D=%08X,%08X,%08X,%08X,%08X,%08X,%08X,%08X"
                   " A=%08X,%08X,%08X,%08X,%08X,%08X,%08X",
                (unsigned)cpu->d[0], (unsigned)cpu->d[1],
                (unsigned)cpu->d[2], (unsigned)cpu->d[3],
                (unsigned)cpu->d[4], (unsigned)cpu->d[5],
                (unsigned)cpu->d[6], (unsigned)cpu->d[7],
                (unsigned)cpu->a[0], (unsigned)cpu->a[1],
                (unsigned)cpu->a[2], (unsigned)cpu->a[3],
                (unsigned)cpu->a[4], (unsigned)cpu->a[5],
                (unsigned)cpu->a[6]);
    }
    fprintf(f, " F268=%08X,%08X,%08X,%08X F2A8=%08X,%08X,%08X,%08X\n",
            (unsigned)md_coop_p2_long(0xF268),
            (unsigned)md_coop_p2_long(0xF26C),
            (unsigned)md_coop_p2_long(0xF270),
            (unsigned)md_coop_p2_long(0xF274),
            (unsigned)md_coop_p2_long(0xF2A8),
            (unsigned)md_coop_p2_long(0xF2AC),
            (unsigned)md_coop_p2_long(0xF2B0),
            (unsigned)md_coop_p2_long(0xF2B4));
    fclose(f);
}

/* f_3650 is the native player map/tile collision pass. Capture both sides
   of that routine and the F226 lookup scratch that the f_3284 probe missed. */
void md_coop_p2_trace_floor(const char *stage, M68K *cpu) {
    FILE *f;
    unsigned i;
    if (!md_coop_p2_active || !md_coop_p2_ready ||
        md_coop_p2_frame_count > 360u) return;
    f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
    if (!f) return;
    fprintf(f,
        "event=p2-floor stage=%s frame=%lu xy=%04X,%04X "
        "BCD9=%02X BCE5=%02X BCE6=%08X BCE0=%04X BCE2=%04X BCE4=%02X "
        "BCDA=%08X BCDC=%04X BC54=%08X BC58=%04X BC86=%02X BD16=%02X "
        "BCD8=%02X BCC8=%04X",
        stage ? stage : "-", md_coop_p2_frame_count,
        md_coop_p2_word(0xBD1E), md_coop_p2_word(0xBD20),
        md_coop_p2_ram[0xBCD9], md_coop_p2_ram[0xBCE5],
        (unsigned)md_coop_p2_long(0xBCE6),
        md_coop_p2_word(0xBCE0), md_coop_p2_word(0xBCE2),
        md_coop_p2_ram[0xBCE4], (unsigned)md_coop_p2_long(0xBCDA),
        md_coop_p2_word(0xBCDC),
        (unsigned)(((uint32_t)ram[0xBC54] << 24) | ((uint32_t)ram[0xBC55] << 16) |
                   ((uint32_t)ram[0xBC56] << 8) | (uint32_t)ram[0xBC57]),
        (uint16_t)(((uint16_t)ram[0xBC58] << 8) | (uint16_t)ram[0xBC59]),
        md_coop_p2_ram[0xBC86],
        md_coop_p2_ram[0xBD16], md_coop_p2_ram[0xBCD8],
        md_coop_p2_word(0xBCC8));
    if (cpu) {
        fprintf(f, " D=%08X,%08X,%08X,%08X,%08X,%08X,%08X,%08X"
                   " A=%08X,%08X,%08X,%08X,%08X,%08X,%08X",
                (unsigned)cpu->d[0], (unsigned)cpu->d[1],
                (unsigned)cpu->d[2], (unsigned)cpu->d[3],
                (unsigned)cpu->d[4], (unsigned)cpu->d[5],
                (unsigned)cpu->d[6], (unsigned)cpu->d[7],
                (unsigned)cpu->a[0], (unsigned)cpu->a[1],
                (unsigned)cpu->a[2], (unsigned)cpu->a[3],
                (unsigned)cpu->a[4], (unsigned)cpu->a[5],
                (unsigned)cpu->a[6]);
    }
    fprintf(f, " F226=");
    for (i = 0; i < 64u; ++i)
        fprintf(f, "%02X", (unsigned)md_coop_p2_ram[0xF226u + i]);
    fprintf(f, " F268=");
    for (i = 0; i < 16u; ++i)
        fprintf(f, "%02X", (unsigned)md_coop_p2_ram[0xF268u + i]);
    fprintf(f, " F2A8=");
    for (i = 0; i < 16u; ++i)
        fprintf(f, "%02X", (unsigned)md_coop_p2_ram[0xF2A8u + i]);
    fprintf(f, "\n");
    fclose(f);
}

/* Capture the actual BD20 writes and the velocity/state fields feeding them.
   Limit the trace to the reproducible fall window around P2 frames 220-280. */
void md_coop_p2_trace_motion(const char *stage, M68K *cpu) {
    FILE *f;
    if (!md_coop_p2_active || !md_coop_p2_ready ||
        md_coop_p2_frame_count > 420u) return;
    f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
    if (!f) return;
    fprintf(f,
        "event=p2-motion stage=%s frame=%lu xy=%04X,%04X "
        "BCEC=%04X BCEE=%04X BCD8=%02X BCD9=%02X "
        "BCE0=%04X BCE2=%04X BCE5=%02X BCE6=%08X "
        "BCDA=%08X BCDC=%04X BCF3=%02X BCF5=%02X BCF6=%02X BCF7=%02X BCF8=%02X "
        "BCFC=%02X BCFE=%02X BC90=%02X%02X "
        "BD02=%02X BD04=%02X BD1D=%02X BD22=%02X "
        "BCC8=%04X BCEA=%04X",
        stage ? stage : "-", md_coop_p2_frame_count,
        md_coop_p2_word(0xBD1E), md_coop_p2_word(0xBD20),
        md_coop_p2_word(0xBCEC), md_coop_p2_word(0xBCEE),
        md_coop_p2_ram[0xBCD8], md_coop_p2_ram[0xBCD9],
        md_coop_p2_word(0xBCE0), md_coop_p2_word(0xBCE2),
        md_coop_p2_ram[0xBCE5], (unsigned)md_coop_p2_long(0xBCE6),
        (unsigned)md_coop_p2_long(0xBCDA), md_coop_p2_word(0xBCDC),
        md_coop_p2_ram[0xBCF3], md_coop_p2_ram[0xBCF5],
        md_coop_p2_ram[0xBCF6], md_coop_p2_ram[0xBCF7],
        md_coop_p2_ram[0xBCF8], md_coop_p2_ram[0xBCFC],
        md_coop_p2_ram[0xBCFE], md_coop_p2_ram[0xBC90],
        md_coop_p2_ram[0xBC91], md_coop_p2_ram[0xBD02],
        md_coop_p2_ram[0xBD04], md_coop_p2_ram[0xBD1D],
        md_coop_p2_ram[0xBD22], md_coop_p2_word(0xBCC8),
        md_coop_p2_word(0xBCEA));
    if (cpu) {
        fprintf(f,
            " CC=%u%u%u%u D=%08X,%08X,%08X,%08X,%08X,%08X,%08X,%08X"
            " A=%08X,%08X,%08X,%08X,%08X,%08X,%08X",
            (unsigned)cpu->n, (unsigned)cpu->z, (unsigned)cpu->v,
            (unsigned)cpu->c,
            (unsigned)cpu->d[0], (unsigned)cpu->d[1],
            (unsigned)cpu->d[2], (unsigned)cpu->d[3],
            (unsigned)cpu->d[4], (unsigned)cpu->d[5],
            (unsigned)cpu->d[6], (unsigned)cpu->d[7],
            (unsigned)cpu->a[0], (unsigned)cpu->a[1],
            (unsigned)cpu->a[2], (unsigned)cpu->a[3],
            (unsigned)cpu->a[4], (unsigned)cpu->a[5],
            (unsigned)cpu->a[6]);
    }
    fprintf(f, "\n");
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

static void md_coop_p2_capture_collision_seed_slot(M68K *primary) {
    if (!primary || md_coop_p2_disabled || !md_coop_p2_requested()) {
        md_coop_p2_collision_seed_valid = 0;
        return;
    }
    /* Capture the exact register/condition-code inputs immediately before
       P1's native per-frame f_3B38 collision-state reset. */
    memcpy(&md_coop_p2_collision_seed, primary,
           sizeof md_coop_p2_collision_seed);
    md_coop_p2_collision_seed_valid = 1;
}

const M68K *md_coop_p2_collision_seed_context(void) {
    return md_coop_p2_collision_seed_valid ? &md_coop_p2_collision_seed : NULL;
}

static void md_coop_p2_capture_spatial_seed_slot(M68K *primary) {
    if (!primary || md_coop_p2_disabled || !md_coop_p2_requested()) {
        md_coop_p2_spatial_seed_valid = 0;
        return;
    }
    /* f_56CE builds the per-frame F268/F2A8 spatial candidate buffers.
       Capture the exact register context immediately before P1's pass. */
    memcpy(&md_coop_p2_spatial_seed, primary,
           sizeof md_coop_p2_spatial_seed);
    md_coop_p2_spatial_seed_valid = 1;
}

const M68K *md_coop_p2_spatial_seed_context(void) {
    return md_coop_p2_spatial_seed_valid ? &md_coop_p2_spatial_seed : NULL;
}

static void md_coop_p2_capture_motion_seed_slot(M68K *primary) {
    if (!primary || md_coop_p2_disabled || !md_coop_p2_requested()) {
        md_coop_p2_motion_seed_valid = 0;
        return;
    }
    /* Capture at f_156A's BF28 gate so P2 can replay its conditional
       f_2150 state-preparation call with the exact native call-site context. */
    memcpy(&md_coop_p2_motion_seed, primary, sizeof md_coop_p2_motion_seed);
    md_coop_p2_motion_seed_valid = 1;
}

const M68K *md_coop_p2_motion_seed_context(void) {
    return md_coop_p2_motion_seed_valid ? &md_coop_p2_motion_seed : NULL;
}

static void md_coop_p2_capture_collision_descriptors_slot(M68K *primary) {
    unsigned count;
    FILE *f;
    if (!primary || md_coop_p2_disabled || !md_coop_p2_requested()) {
        md_coop_p2_primary_collision_desc_valid = 0;
        return;
    }
    count = ((unsigned)ram[0xBF0C] << 8) | (unsigned)ram[0xBF0D];
    md_coop_p2_primary_collision_count = count;
    md_coop_p2_primary_collision_desc_valid = 0;
    if (count > (sizeof md_coop_p2_primary_collision_desc / 12u)) {
        f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
        if (f) {
            fprintf(f, "event=collision-desc-capture frame=%lu count=%u status=overflow\n",
                    md_coop_p2_frame_count, count);
            fclose(f);
        }
        return;
    }
    if (count)
        memcpy(md_coop_p2_primary_collision_desc, &ram[0xBD28], count * 12u);
    md_coop_p2_primary_collision_desc_valid = 1;
    f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
    if (f) {
        fprintf(f, "event=collision-desc-capture frame=%lu count=%u status=captured\n",
                md_coop_p2_frame_count, count);
        fclose(f);
    }
}

/* f_3D6A registers 12-byte collision descriptors in BD28..BF07: four
   16-bit bounds followed by a 32-bit pointer at +8. f_3D80 writes its
   +11 contact result and +16 candidate pointer into the referenced 24-byte
   collision-result context. P2 gets private copies of these contexts so its
   collision pass cannot overwrite P1's results. The F268 candidate list is
   separately rebuilt from the shared world-object list into private scratch.
   The table holds 40 entries. */
int md_coop_p2_import_collision_descriptors(void) {
    uint32_t old_ptrs[40];
    uint16_t new_offsets[40];
    unsigned old_count = 0;
    unsigned count = md_coop_p2_primary_collision_count;
    unsigned i, j;
    FILE *f;
    if (!md_coop_p2_ready || md_coop_p2_disabled ||
        !md_coop_p2_primary_collision_desc_valid || count > 40u)
        return 0;

    memset(&md_coop_p2_ram[0xBD28], 0, 0x1E0u);
    if (count)
        memcpy(&md_coop_p2_ram[0xBD28],
               md_coop_p2_primary_collision_desc, count * 12u);

    memset(&md_coop_p2_ram[0xEA00], 0, 0x500u);
    md_coop_p2_collision_shadow_count = 0;
    for (i = 0; i < count; ++i) {
        unsigned record = 0xBD28u + i * 12u;
        uint32_t ptr = md_coop_p2_long(record + 8u);
        unsigned source;
        unsigned dest;
        if ((ptr & 0x00FF0000u) != 0x00FF0000u ||
            (ptr & 0x0000FFFFu) > 0xFFE8u) {
            f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
            if (f) {
                fprintf(f, "event=collision-desc-import frame=%lu index=%u ptr=%08X status=invalid-pointer\n",
                        md_coop_p2_frame_count, i, (unsigned)ptr);
                fclose(f);
            }
            return 0;
        }
        source = (unsigned)(ptr & 0xFFFFu);
        for (j = 0; j < old_count; ++j)
            if (old_ptrs[j] == ptr) break;
        if (j < old_count) {
            dest = new_offsets[j];
        } else {
            if (old_count >= 40u) return 0;
            dest = 0xEA00u + old_count * 0x20u;
            if (source > 0xFFE8u || dest > 0xEEE8u) return 0;
            memcpy(&md_coop_p2_ram[dest], &ram[source], 24u);
            /* Do not carry P1's previous per-object collision result into P2. */
            md_coop_p2_ram[dest + 11u] = 0;
            md_coop_p2_put_long(dest + 16u, 0);
            old_ptrs[old_count] = ptr;
            new_offsets[old_count] = (uint16_t)dest;
            ++old_count;
        }
        md_coop_p2_put_long(record + 8u, 0xFFFF0000u | (uint32_t)dest);
    }

    md_coop_p2_put_long(0xBF08u, 0xFFFFBD28u);
    md_coop_p2_put_word(0xBF0Cu, (uint16_t)count);
    md_coop_p2_collision_shadow_count = old_count;
    f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
    if (f) {
        fprintf(f, "event=collision-desc-import frame=%lu count=%u shadows=%u status=ready\n",
                md_coop_p2_frame_count, count, old_count);
        fclose(f);
    }
    return 1;
}

/* Trace the P2 collision-result contexts after native f_3D80. The +11
   byte and +16 long are the fields f_3D80 writes. The source bytes show
   P1's already-computed result; the shadow bytes show P2's independent pass. */
void md_coop_p2_trace_collision_results(void) {
    FILE *f;
    unsigned i, p1_nonzero = 0, p2_nonzero = 0, logged = 0;
    unsigned count = md_coop_p2_primary_collision_count;
    if (!md_coop_p2_active || !md_coop_p2_primary_collision_desc_valid ||
        count > 40u || md_coop_p2_frame_count > 240u) return;
    f = fopen("MegaTurrican-coop-collision-result-trace.txt", "a");
    if (!f) return;
    for (i = 0; i < count; ++i) {
        const uint8_t *src_desc = &md_coop_p2_primary_collision_desc[i * 12u];
        unsigned record = 0xBD28u + i * 12u;
        uint32_t src_ptr = ((uint32_t)src_desc[8] << 24) |
                           ((uint32_t)src_desc[9] << 16) |
                           ((uint32_t)src_desc[10] << 8) | (uint32_t)src_desc[11];
        uint32_t dst_ptr = md_coop_p2_long(record + 8u);
        unsigned src = (unsigned)(src_ptr & 0xFFFFu);
        unsigned dst = (unsigned)(dst_ptr & 0xFFFFu);
        uint8_t p1_flag, p2_flag;
        uint32_t p1_candidate, p2_candidate;
        unsigned j;
        if ((src_ptr & 0x00FF0000u) != 0x00FF0000u ||
            (dst_ptr & 0x00FF0000u) != 0x00FF0000u ||
            src > 0xFFE8u || dst > 0xFFE8u) continue;
        for (j = 0; j < i; ++j) {
            const uint8_t *prior = &md_coop_p2_primary_collision_desc[j * 12u];
            uint32_t prior_ptr = ((uint32_t)prior[8] << 24) |
                                 ((uint32_t)prior[9] << 16) |
                                 ((uint32_t)prior[10] << 8) | (uint32_t)prior[11];
            if (prior_ptr == src_ptr) break;
        }
        if (j < i) continue;
        p1_flag = ram[src + 11u];
        p2_flag = md_coop_p2_ram[dst + 11u];
        p1_candidate = ((uint32_t)ram[src + 16u] << 24) |
                       ((uint32_t)ram[src + 17u] << 16) |
                       ((uint32_t)ram[src + 18u] << 8) |
                       (uint32_t)ram[src + 19u];
        p2_candidate = md_coop_p2_long(dst + 16u);
        if (p1_flag) ++p1_nonzero;
        if (p2_flag) ++p2_nonzero;
        if (p2_flag || p2_candidate) {
            fprintf(f,
                "event=p2-collision-context frame=%lu index=%u "
                "source=%08X shadow=%08X p1_flag=%02X p2_flag=%02X "
                "p1_candidate=%08X p2_candidate=%08X\n",
                md_coop_p2_frame_count, i, (unsigned)src_ptr,
                (unsigned)dst_ptr, (unsigned)p1_flag, (unsigned)p2_flag,
                (unsigned)p1_candidate, (unsigned)p2_candidate);
            ++logged;
        }
    }
    if (md_coop_p2_collision_result_log_frames != md_coop_p2_frame_count) {
        fprintf(f,
            "event=p2-collision-summary frame=%lu descriptors=%u "
            "p1_nonzero=%u p2_nonzero=%u changed_records=%u\n",
            md_coop_p2_frame_count, count, p1_nonzero, p2_nonzero, logged);
        md_coop_p2_collision_result_log_frames = (uint32_t)md_coop_p2_frame_count;
    }
    fclose(f);
}

/* f_224C's native hit response receives A2 from f_57A6, which follows
   candidate pointers from the shared world-object list. Log the target fields
   on both sides of the writes so runtime evidence can distinguish a real
   shared-world mutation from an isolated P2 shadow. */
void md_coop_p2_trace_hit_target(const char *stage, M68K *cpu) {
    FILE *f;
    uint32_t base, at9, at11;
    unsigned off9, off11;
    int is_ram9, is_ram11, private9, private11;
    uint8_t value9, value11;
    if (!md_coop_p2_active || !cpu || md_coop_p2_frame_count > 300u)
        return;
    base = cpu->a[2];
    at9 = base + 9u;
    at11 = base + 11u;
    is_ram9 = ((at9 & 0x00FF0000u) == 0x00FF0000u);
    is_ram11 = ((at11 & 0x00FF0000u) == 0x00FF0000u);
    if (!is_ram9 || !is_ram11) return;
    off9 = (unsigned)(at9 & 0xFFFFu);
    off11 = (unsigned)(at11 & 0xFFFFu);
    private9 = md_coop_p2_private[off9] != 0;
    private11 = md_coop_p2_private[off11] != 0;
    value9 = private9 ? md_coop_p2_ram[off9] : ram[off9];
    value11 = private11 ? md_coop_p2_ram[off11] : ram[off11];
    f = fopen("MegaTurrican-coop-shared-hit-trace.txt", "a");
    if (!f) return;
    fprintf(f,
        "event=p2-hit-target stage=%s frame=%lu A2=%08X "
        "target9=%08X value9=%02X private9=%u "
        "target11=%08X value11=%02X private11=%u D0=%08X\n",
        stage ? stage : "-", md_coop_p2_frame_count, (unsigned)base,
        (unsigned)at9, (unsigned)value9, (unsigned)private9,
        (unsigned)at11, (unsigned)value11, (unsigned)private11,
        (unsigned)cpu->d[0]);
    fclose(f);
}

void md_coop_p2_trace_sprite_build(const char *stage, M68K *cpu) {
    FILE *f;
    unsigned i, p2_nonzero = 0, p1_nonzero = 0;
    uint32_t p2_hash = 2166136261u, p1_hash = 2166136261u;
    uint32_t queue_ptr;
    uint16_t queue_count;
    if (md_coop_p2_frame_count > 12u &&
        md_coop_p2_frame_count != 60u &&
        md_coop_p2_frame_count != 120u &&
        md_coop_p2_frame_count != 240u &&
        md_coop_p2_frame_count != 360u) return;
    f = fopen("MegaTurrican-local-coop-runtime.txt", "a");
    if (!f) return;
    for (i = 0; i < 29u; ++i) {
        unsigned at = 0xFCE8u + i * 4u;
        uint32_t p2v = md_coop_p2_long(at);
        uint32_t p1v = ((uint32_t)ram[at] << 24) |
                       ((uint32_t)ram[at + 1u] << 16) |
                       ((uint32_t)ram[at + 2u] << 8) |
                       (uint32_t)ram[at + 3u];
        if (p2v) ++p2_nonzero;
        if (p1v) ++p1_nonzero;
        p2_hash = (p2_hash ^ p2v) * 16777619u;
        p1_hash = (p1_hash ^ p1v) * 16777619u;
    }
    queue_ptr = ((uint32_t)ram[0xBC54] << 24) |
                ((uint32_t)ram[0xBC55] << 16) |
                ((uint32_t)ram[0xBC56] << 8) | (uint32_t)ram[0xBC57];
    queue_count = (uint16_t)(((uint16_t)ram[0xBC58] << 8) | ram[0xBC59]);
    fprintf(f,
        "event=p2-sprite-build stage=%s frame=%lu connected=%d forced=%d "
        "p2_parts=%u p2_hash=%08X p1_parts=%u p1_hash=%08X "
        "queue_ptr=%08X queue_count=%04X "
        "p2_BD24=%02X p2_BD25=%02X p2_BD02=%02X p2_BD22=%02X p2_BC86=%02X "
        "p2_camera=%04X,%04X p1_camera=%04X,%04X",
        stage ? stage : "-", md_coop_p2_frame_count,
        md_player_connected[md_coop_cur + 1u],
        (md_coop_cur == 0u) ? md_local_coop_enabled : 0,
        p2_nonzero, (unsigned)p2_hash, p1_nonzero, (unsigned)p1_hash,
        (unsigned)queue_ptr, (unsigned)queue_count,
        (unsigned)md_coop_p2_ram[0xBD24], (unsigned)md_coop_p2_ram[0xBD25],
        (unsigned)md_coop_p2_ram[0xBD02], (unsigned)md_coop_p2_ram[0xBD22],
        (unsigned)md_coop_p2_ram[0xBC86],
        (unsigned)md_coop_p2_word(0xDFD8), (unsigned)md_coop_p2_word(0xDFDA),
        (unsigned)(((uint16_t)ram[0xDFD8] << 8) | ram[0xDFD9]),
        (unsigned)(((uint16_t)ram[0xDFDA] << 8) | ram[0xDFDB]));
    if (cpu) fprintf(f, " A0=%08X A1=%08X A2=%08X D0=%08X D7=%08X SR=%04X",
                     (unsigned)cpu->a[0], (unsigned)cpu->a[1],
                     (unsigned)cpu->a[2], (unsigned)cpu->d[0],
                     (unsigned)cpu->d[7], (unsigned)cpu->sr_sys);
    fprintf(f, " p2_entries=");
    for (i = 0; i < 29u; ++i) {
        uint32_t v = md_coop_p2_long(0xFCE8u + i * 4u);
        if (v) fprintf(f, "%s%u:%08X", i ? "," : "", i, (unsigned)v);
    }
    fprintf(f, "\n");
    fclose(f);
}

int md_coop_p2_is_ready(void) {
    return md_coop_p2_ready && !md_coop_p2_disabled &&
           md_coop_p2_requested() && md_coop_primary_m68k != NULL;
}

static void md_coop_prepare_p2_slot(M68K *primary) {
    uint32_t callback;
    unsigned i;
    if (!primary) return;
    md_coop_primary_m68k = primary;
    if (md_coop_p2_disabled || !md_coop_p2_requested()) {
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
        md_coop_p2_mark(0xBC18, 0xBC27); /* per-player init, post-actor and state callbacks */
        md_coop_p2_mark(0xBC3C, 0xBC43); /* descriptor-selected animation/update callback pair */
        md_coop_p2_mark(0xBC44, 0xBC4B); /* descriptor-selected animation/update callback pair */
        md_coop_p2_mark(0xBC4C, 0xBC53); /* descriptor-selected callback and descriptor pointer */
        md_coop_p2_mark(0xBC5A, 0xBC61); /* dynamic state callback and callback context */
        md_coop_p2_mark(0xBF0E, 0xBF17); /* per-player camera/position snapshot used by lifecycle */
        md_coop_p2_mark(0xBF18, 0xBF1D); /* descriptor-derived per-player identity/context */
        md_coop_p2_mark(0xBC62, 0xBC65); /* main actor callback */ 
        md_coop_p2_mark(0xBC6C, 0xBC6C);
        md_coop_p2_mark(0xBC70, 0xBC70);
        md_coop_p2_mark(0xBC84, 0xBC8B); /* includes f_3B38 collision flags */
        md_coop_p2_mark(0xBC8C, 0xBC8C); /* player initialization state installed by f_19FA */
        md_coop_p2_mark(0xBC90, 0xBC91);
        md_coop_p2_mark(0xBC9C, 0xBC9F);
#if !MT_COOP_VDP_QUEUE_SHARED
        /* $FFBCA4 = DMA queue write index, $FFBCA6 = busy flag, queue entries
           live at $FFD2DA + index*16 (see MAKER-ACTOR-RESEARCH). They are WORLD
           state drained by f_554 in VBlank, which only ever resets the REAL
           index. Giving a player a private index with a never-reset counter made
           its f_71C enqueues march through RAM and overwrite the HUD, tilemap
           and scroll data. In the default isolate mode the player gets a private
           index AND a private queue buffer that is reset every frame, so its
           transfers are safely discarded. */
        md_coop_p2_mark(0xBCA4, 0xBCA7);
        md_coop_p2_mark(0xD2DA, 0xD8D9); /* 96 private queue entries */
#endif
        md_coop_p2_mark(0xBCBC, 0xBD26);
        md_coop_p2_mark(0xBD28, 0xBF07); /* 40 x 12-byte per-player collision descriptors */
        md_coop_p2_mark(0xEA00, 0xEEFF); /* up to 40 shadow copies of mutable collision targets */
        md_coop_p2_mark(0xBF08, 0xBF0D); /* per-player collision descriptor cursor */
        md_coop_p2_mark(0xFE58, 0xFE58); /* P2-private copy of f_3B38's global flag byte */
        md_coop_p2_mark(0xBF1E, 0xBF29); /* per-player stats/lives */
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

        /* Place this player beside P1 (offset grows per slot) without changing the shared camera. The
           native f_1BDE respawn path rebuilds BD1E from BF0E (viewport origin)
           and BF12 (the saved player X/Y). Keep P2's saved X aligned with the
           live spawn offset or its next native respawn would collapse onto P1. */
        md_coop_p2_put_word(0xBD1E,
            (uint16_t)(md_coop_p2_word(0xBD1E) + MD_COOP_SPAWN_DX));
        md_coop_p2_put_word(0xBF12,
            (uint16_t)(md_coop_p2_word(0xBF12) + MD_COOP_SPAWN_DX));

        /* BCF5 is tested and decremented by f_3222 as a movement-lock countdown.
           BCF6..BCF8 are adjacent movement/state branch bytes. Do not inherit
           P1's live action/lock state when creating P2's independent actor. */
        md_coop_p2_ram[0xBCF5] = 0;
        md_coop_p2_ram[0xBCF6] = 0;
        md_coop_p2_ram[0xBCF7] = 0;
        md_coop_p2_ram[0xBCF8] = 0;

        /* f_224C reads BCEC/BCED as the vertical movement delta added to BD20.
           Start P2 at rest rather than inheriting P1's current jump/fall delta. */
        md_coop_p2_put_word(0xBCEC, 0);
        /* BCEE is consulted as a movement-state latch in f_224C; clear the
           inherited P1 latch rather than treating it as P2's own input state. */
        md_coop_p2_put_word(0xBCEE, 0);

        md_coop_p2_ready = 1;
        md_coop_p2_log("initialized", callback,
                       "one-time P1 state seed; P2 spawn offset +0x10; independent CPU and F0FFFC stack");
    }
}

void md_coop_p2_refresh(void) {
    unsigned player = md_coop_cur + 1u; /* Genesis player number: P2=1, P3=2, P4=3 */
    if (!md_coop_p2_is_ready() || player >= 4u) return;
    /* P2 keeps the verified native port-2 bytes. P3/P4 receive their own
       controller mask converted to the same active-low 16-bit Genesis input
       pair at the player-local BC90/BC91 addresses. */
    if (player == 1u) {
        md_coop_p2_ram[0xBC90] = ram[0xBC92];
        md_coop_p2_ram[0xBC91] = ram[0xBC93];
    } else {
        const uint16_t active_low = md_coop_encode_genesis_input(
            (unsigned)md_player_live_masks[player]);
        md_coop_p2_ram[0xBC90] = (uint8_t)(active_low >> 8);
        md_coop_p2_ram[0xBC91] = (uint8_t)active_low;
    }
#if !MT_COOP_VDP_QUEUE_SHARED
    /* Private DMA queue: restart empty every frame so it can never run away. */
    md_coop_p2_ram[0xBCA4] = 0; md_coop_p2_ram[0xBCA5] = 0;
    md_coop_p2_ram[0xBCA6] = 0; md_coop_p2_ram[0xBCA7] = 0;
#endif
    md_coop_p2_ram[0xDFD8] = ram[0xDFD8];
    md_coop_p2_ram[0xDFD9] = ram[0xDFD9];
    md_coop_p2_ram[0xDFDA] = ram[0xDFDA];
    ++md_coop_p2_frame_count;
}


/* Per-frame change log for each independent local player. This captures the
   pose/state bytes around BCC0, movement/collision state, inputs and positions
   so tests can distinguish shared animation state from independent state. */
static const unsigned md_diag_ranges[3][2] = {
    {0xBC84u, 0xBC8Cu}, {0xBCBCu, 0xBD26u}, {0xBF08u, 0xBF29u}
};
static uint8_t md_diag_prev[MT_COOP_SLOTS + 1u][0x10000];

static int md_diag_changes(char *out, int n, int cap, const char *tag,
                           const uint8_t *cur, uint8_t *prev) {
    unsigned r, a;
    int start = n, first = 1;
    for (r = 0; r < 3u; ++r) {
        for (a = md_diag_ranges[r][0]; a <= md_diag_ranges[r][1]; ++a) {
            if (cur[a] != prev[a]) {
                if (first) {
                    n += snprintf(out + n, (size_t)(cap - n), " %s", tag);
                    first = 0;
                }
                if (n < cap - 24)
                    n += snprintf(out + n, (size_t)(cap - n),
                                  " %04X:%02X>%02X", a, prev[a], cur[a]);
                prev[a] = cur[a];
            }
        }
    }
    return n > start ? n : start;
}

static void md_coop_diag_frame(void) {
#if MT_COOP_DIAG
    static FILE *df = NULL;
    static unsigned long bytes = 0;
    static unsigned last_sig[MT_COOP_SLOTS];
    char buf[4096], slot_tag[8];
    int n, base;
    unsigned long frame = md_coop_p2_frame_count;
    unsigned sig;
    int input_changed;
    if (bytes > 12000000ul) return;
    if (!df) {
        df = fopen("MegaTurrican-coop-diag.txt", "w");
        if (!df) { bytes = 12000001ul; return; }
        fprintf(df,
            "# F=slot frame S=player; camera=DFD4/DFD6; inputs=BC90/BC91; "
            "positions=BD1E/BD20. Changes are ADDR:old>new. "
            "Pose/animation bytes include BCC0 and surrounding state.\n");
    }
    snprintf(slot_tag, sizeof slot_tag, "P%u", md_coop_cur + 2u);
    n = snprintf(buf, sizeof buf,
        "F=%lu S=%u own=%lu cam=%02X%02X,%02X%02X rawP2=%02X%02X "
        "P1in=%02X%02X %sin=%02X%02X "
        "P1xy=%02X%02X,%02X%02X %sxy=%02X%02X,%02X%02X",
        frame, md_coop_cur + 2u, md_obj_dispatch_count,
        ram[0xDFD4], ram[0xDFD5], ram[0xDFD6], ram[0xDFD7],
        ram[0xBC92], ram[0xBC93],
        ram[0xBC90], ram[0xBC91],
        slot_tag, md_coop_p2_ram[0xBC90], md_coop_p2_ram[0xBC91],
        ram[0xBD1E], ram[0xBD1F], ram[0xBD20], ram[0xBD21],
        slot_tag, md_coop_p2_ram[0xBD1E], md_coop_p2_ram[0xBD1F],
        md_coop_p2_ram[0xBD20], md_coop_p2_ram[0xBD21]);
    base = n;
    if (md_coop_cur == 0u)
        n = md_diag_changes(buf, n, (int)sizeof buf, "P1",
                            ram, md_diag_prev[0]);
    n = md_diag_changes(buf, n, (int)sizeof buf, slot_tag,
                        md_coop_p2_ram, md_diag_prev[md_coop_cur + 1u]);
    sig = ((unsigned)ram[0xBC90] << 24) |
          ((unsigned)ram[0xBC91] << 16) |
          ((unsigned)md_coop_p2_ram[0xBC90] << 8) |
          md_coop_p2_ram[0xBC91];
    input_changed = (sig != last_sig[md_coop_cur]);
    last_sig[md_coop_cur] = sig;
    if (n == base && !input_changed && (frame % 30u) != 0u) return;
    bytes += (unsigned long)fprintf(df, "%s\n", buf);
    if ((frame % 30u) == 0u) fflush(df);
#endif
}

void md_coop_p2_actor_complete(M68K *cpu, uint32_t callback) {
    unsigned i;
    FILE *f;
    md_coop_diag_frame();
    /* Reset the abort fault counter after 300 consecutive successful frames
       so sporadic stack noise events do not accumulate toward permanent disable. */
    if (md_coop_p2_abort_count > 0u &&
        md_coop_p2_frame_count > md_coop_p2_abort_frame + 300u)
        md_coop_p2_abort_count = 0u;
    if (md_coop_p2_frame_count > 10u && (md_coop_p2_frame_count % 60u) != 0u)
        return;
    md_coop_p2_flush_audit();
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
    fprintf(f,
        "p2_callback_slots BC18=%08X BC1C=%08X BC20=%08X BC24=%08X "
        "BC3C=%08X BC40=%08X BC44=%08X BC48=%08X BC4C=%08X "
        "BC50=%08X BC5A=%08X BC5E=%08X BF0E=%08X BF12=%08X BF16=%02X BF17=%02X "
        "BC8C=%02X BF18=%08X BF1C=%04X\n",
        (unsigned)md_coop_p2_long(0xBC18), (unsigned)md_coop_p2_long(0xBC1C),
        (unsigned)md_coop_p2_long(0xBC20), (unsigned)md_coop_p2_long(0xBC24),
        (unsigned)md_coop_p2_long(0xBC3C), (unsigned)md_coop_p2_long(0xBC40),
        (unsigned)md_coop_p2_long(0xBC44), (unsigned)md_coop_p2_long(0xBC48),
        (unsigned)md_coop_p2_long(0xBC4C), (unsigned)md_coop_p2_long(0xBC50),
        (unsigned)md_coop_p2_long(0xBC5A), (unsigned)md_coop_p2_long(0xBC5E),
        (unsigned)md_coop_p2_long(0xBF0E), (unsigned)md_coop_p2_long(0xBF12),
        (unsigned)md_coop_p2_ram[0xBF16], (unsigned)md_coop_p2_ram[0xBF17],
        (unsigned)md_coop_p2_ram[0xBC8C],
        (unsigned)md_coop_p2_long(0xBF18),
        (unsigned)md_coop_p2_word(0xBF1C));
    fprintf(f, "p2_state_BC62_BD26=");
    for (i = 0xBC62u; i <= 0xBD26u; ++i)
        fprintf(f, "%02X", (unsigned)md_coop_p2_ram[i]);
    fprintf(f, "\np2_player_scratch_F200_F9FF=");
    for (i = 0xF200u; i <= 0xF9FFu; ++i)
        fprintf(f, "%02X", (unsigned)md_coop_p2_ram[i]);
    fprintf(f, "\np2_vdp_queue_idx_BCA4=%04X shared_idx=%04X pool_skips=%u",
            (unsigned)md_coop_p2_word(0xBCA4),
            (unsigned)(((unsigned)ram[0xBCA4] << 8) | ram[0xBCA5]), MD_CUR.pool_skips);
    fprintf(f, "\np2_camera_DFD8_DFDA=%02X%02X%02X sprite_scratch_FD24_25=%02X%02X\n",
            (unsigned)md_coop_p2_ram[0xDFD8], (unsigned)md_coop_p2_ram[0xDFD9],
            (unsigned)md_coop_p2_ram[0xDFDA],
            (unsigned)md_coop_p2_ram[0xBD24], (unsigned)md_coop_p2_ram[0xBD25]);
    fclose(f);
}

void md_coop_p2_abort(const char *reason, uint32_t callback) {
    md_coop_p2_active = 0;
    /* Start a fresh fault window if the previous fault was more than 180 P2
       frames ago. This makes the documented rapid-fault threshold explicit. */
    if (md_coop_p2_abort_count > 0u &&
        md_coop_p2_frame_count > md_coop_p2_abort_frame + 180u)
        md_coop_p2_abort_count = 0u;
    md_coop_p2_abort_count++;
    md_coop_p2_abort_frame = md_coop_p2_frame_count;
    /* Permanently disable only after more than 3 faults within the 180-frame
       window, which indicates a structural incompatibility.
       A single or infrequent fault gets a soft reset: P2 re-seeds from P1 on the
       next prepare cycle so a recoverable condition (stack noise during an event)
       does not kill co-op for the entire session. */
    if (md_coop_p2_abort_count > 3u) {
        md_coop_p2_disabled = 1;
        md_coop_p2_log("permanently-disabled", callback, reason ? reason : "repeated runtime contract failures");
    } else {
        md_coop_p2_ready = 0;
        md_coop_p2_frame_seed_valid = 0;
        md_coop_p2_collision_seed_valid = 0;
        md_coop_p2_spatial_seed_valid = 0;
        md_coop_p2_motion_seed_valid = 0;
        md_coop_p2_primary_collision_desc_valid = 0;
        md_coop_p2_log("soft-abort", callback, reason ? reason : "runtime contract failed");
    }
}

void md_coop_p2_finish(void) {
    md_coop_p2_active = 0; /* primary pointer stays valid for the next slot */
}

void md_coop_p2_end_frame(void) {
    md_coop_p2_active = 0;
    md_coop_primary_m68k = NULL;
    md_coop_cur = 0;
}

/* Public hook entry points used by the generated code: fan out to every slot. */
#define MD_COOP_FANOUT(NAME) \
    void NAME(M68K *primary) { \
        unsigned s_; \
        for (s_ = 0; s_ < MT_COOP_SLOTS; ++s_) { md_coop_cur = s_; NAME##_slot(primary); } \
        md_coop_cur = 0; \
    }
MD_COOP_FANOUT(md_coop_prepare_p2)
MD_COOP_FANOUT(md_coop_p2_capture_collision_seed)
MD_COOP_FANOUT(md_coop_p2_capture_spatial_seed)
MD_COOP_FANOUT(md_coop_p2_capture_motion_seed)
MD_COOP_FANOUT(md_coop_p2_capture_collision_descriptors)

/* RT_POLL runs inside P2's generated actor code. VDP/audio events and IRQs
   must execute against the real P1/global RAM view and the primary CPU. */
void md_coop_p2_note_pool_skip(void) { ++MD_CUR.pool_skips; }

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

HARNESS_HELPERS = (HARNESS_HELPERS
    .replace("#define MT_COOP_PLAYERS 2", f"#define MT_COOP_PLAYERS {COOP_PLAYERS}", 1)
    .replace("#define MT_COOP_VDP_QUEUE_SHARED 0", f"#define MT_COOP_VDP_QUEUE_SHARED {VDP_QUEUE_SHARED}", 1)
    .replace("#define MT_COOP_POOL_RESERVE 36", f"#define MT_COOP_POOL_RESERVE {POOL_RESERVE}", 1))
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
    "  if(md_coop_p2_active && a >= 0xE00000u && md_coop_p2_private[a & 0xFFFFu]){ md_coop_p2_ram[a & 0xFFFFu]=v; return; }\n"
    "  if(md_coop_p2_active && a >= 0xE00000u) md_coop_p2_note_shared_write(a,1u);\n",
    "bus_wr8",
)
insert_after_ram_mask(
    HARNESS,
    r"void\s+bus_wr16\s*\(\s*uint32_t\s+a\s*,\s*uint16_t\s+v\s*\)",
    "  if(md_coop_p2_active && a >= 0xF00000u && a < 0xF10000u){ unsigned o=a&0xFFFFu; md_coop_p2_stack[o]=(uint8_t)(v>>8); md_coop_p2_stack[(o+1u)&0xFFFFu]=(uint8_t)v; return; }\n"
    "  if(md_coop_p2_active && a >= 0xE00000u){ unsigned o=a&0xFFFFu, n=(o+1u)&0xFFFFu; if(md_coop_p2_private[o]) md_coop_p2_ram[o]=(uint8_t)(v>>8); else { ram[o]=(uint8_t)(v>>8); md_coop_p2_note_shared_write(o,1u); } if(md_coop_p2_private[n]) md_coop_p2_ram[n]=(uint8_t)v; else { ram[n]=(uint8_t)v; md_coop_p2_note_shared_write(n,1u); } return; }\n",
    "bus_wr16",
)

# 2) Let generated RT_POLL service the global VDP/IRQ side using the primary CPU.
header = RT_HEADER.read_text(encoding="utf-8")
if "void md_coop_p2_service_event(M68K *c);" not in header:
    marker = "#define RT_POLL(pc)"
    if marker not in header:
        raise SystemExit("local co-op patch: RT_POLL macro anchor missing")
    decls = "extern int md_coop_p2_active;\nvoid md_coop_prepare_p2(M68K *primary);\nvoid md_coop_p2_capture_collision_seed(M68K *primary);\nvoid md_coop_p2_capture_spatial_seed(M68K *primary);\nvoid md_coop_p2_capture_motion_seed(M68K *primary);\nvoid md_coop_p2_capture_collision_descriptors(M68K *primary);\nvoid md_coop_run_local_p2(M68K *primary, uint32_t callback);\nvoid md_coop_p2_service_event(M68K *c);\nvoid md_obj_note_alloc(M68K *c);\nvoid md_obj_enter(M68K *c);\nvoid md_obj_leave(void);\nvoid md_coop_p2_service_irq(M68K *c);\nvoid md_coop_p2_trace_ground(const char *stage, M68K *cpu);\nvoid md_coop_p2_trace_floor(const char *stage, M68K *cpu);\nvoid md_coop_p2_trace_motion(const char *stage, M68K *cpu);\nvoid md_coop_p2_trace_collision_results(void);\nvoid md_coop_p2_trace_hit_target(const char *stage, M68K *cpu);\n"
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
#ifndef MT_COOP_POOL_RESERVE
#define MT_COOP_POOL_RESERVE __POOL_RESERVE__
#endif
extern void md_coop_prepare_p2(M68K *primary);
extern void md_coop_p2_refresh(void);
extern void md_coop_p2_set_active(int active);
extern M68K *md_coop_p2_cpu(void);
extern const M68K *md_coop_p2_frame_seed_context(void);
extern const M68K *md_coop_p2_collision_seed_context(void);
extern const M68K *md_coop_p2_spatial_seed_context(void);
extern const M68K *md_coop_p2_motion_seed_context(void);
extern int md_coop_p2_import_collision_descriptors(void);
extern int md_coop_p2_is_ready(void);
extern void md_coop_p2_actor_complete(M68K *cpu, uint32_t callback);
extern void md_coop_p2_trace_sprite_build(const char *stage, M68K *cpu);
extern void md_coop_p2_abort(const char *reason, uint32_t callback);
extern void md_coop_p2_finish(void);
extern void md_coop_p2_end_frame(void);
extern unsigned md_coop_p2_slot_count(void);
extern void md_coop_p2_select(unsigned slot);
extern void md_coop_p2_note_pool_skip(void);

/* Free records left in the shared 79-record object pool (free list at $FFBC2C,
   next pointer at +0). f_5300 hands out the shared fallback record at $FFBF3C
   when this runs dry, which makes every sprite part share one record. */
static unsigned md_coop_pool_free_records(void) {
    uint32_t n = RD32(0xFFFFBC2Cu);
    unsigned c = 0;
    while ((n & 0x00FF0000u) == 0x00FF0000u && c <= 80u) { ++c; n = RD32(n); }
    return c;
}

/* Player state persists in P2 RAM, but the game's callback also receives live
   per-frame D/A register inputs from its caller. Refresh those inputs for each
   native call while preserving P2's independent A7 and USP. */
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

static void md_coop_run_local_slot(M68K *primary, uint32_t callback) {
    M68K *p2;
    const M68K *frame_seed;
    const M68K *collision_seed;
    const M68K *spatial_seed;
    const M68K *motion_seed;
    if (!primary || !md_coop_p2_is_ready()) return;
    md_coop_p2_refresh();
    if (!md_coop_p2_is_ready()) return;
    p2 = md_coop_p2_cpu();
    frame_seed = md_coop_p2_frame_seed_context();
    collision_seed = md_coop_p2_collision_seed_context();
    spatial_seed = md_coop_p2_spatial_seed_context();
    motion_seed = md_coop_p2_motion_seed_context();
    if (!p2 || !frame_seed || !collision_seed || !spatial_seed || !motion_seed) return;

    /* Keep the last known-visible Build #644 actor phase order.
       P2 is seeded at the native render seam; Build #645 first replayed
       f_2130 inside the isolated P2 context, after which P2 stopped appearing.
       The later f_5D8A replay was also never present in the visible build.
       Leave both initializers out of the P2 runner until their private-side
       effects can be validated independently from the render path. */

    /* Re-run only the native player-local collision-state reset for P2.
       It writes P2-banked RAM (BC8A/B, BCE4/BCF0-2, BD14-1D, BF08/0C),
       and performs no VDP or shared-object-pool operation. */
    md_coop_p2_sync_call_context(p2, collision_seed);
    md_coop_p2_set_active(1);
    if (!md_coop_p2_call_actor(p2, 0x00003B38u)) {
        md_coop_p2_abort("P2 per-frame collision-state reset f_3B38 did not restore its CPU stack/return frame", 0x3B38u);
        md_coop_p2_finish();
        return;
    }
    md_coop_p2_set_active(0);

    /* Rebuild P2's spatial collision candidates with the game's native
       f_56CE pass. It reads the shared BC28 object list, but its F268/F2A8
       outputs are entirely inside P2's private F200-F9FF scratch bank. */
    md_coop_p2_sync_call_context(p2, spatial_seed);
    md_coop_p2_set_active(1);
    if (!md_coop_p2_call_actor(p2, 0x000056CEu)) {
        md_coop_p2_abort("P2 spatial collision builder f_56CE did not restore its CPU stack/return frame", 0x56CEu);
        md_coop_p2_finish();
        return;
    }
    md_coop_p2_set_active(0);

    /* P1's object callbacks registered its native collision candidates in
       BD28 before the P1 f_3D80 pass. Import a snapshot of that table with
       every mutable target shadowed into P2 RAM, then run f_3D80 against
       P2's freshly rebuilt F268 spatial list and P2 position registers. */
    if (!md_coop_p2_import_collision_descriptors()) {
        md_coop_p2_abort("P2 collision descriptor table could not be safely isolated", 0x3D80u);
        md_coop_p2_finish();
        return;
    }
    md_coop_p2_set_active(1);
    if (!md_coop_p2_call_actor(p2, 0x00003D80u)) {
        md_coop_p2_abort("P2 collision descriptor resolver f_3D80 did not restore its CPU stack/return frame", 0x3D80u);
        md_coop_p2_finish();
        return;
    }
    md_coop_p2_trace_collision_results();
    md_coop_p2_set_active(0);

    /* Return to the exact pre-render registers for P2's sprite and movement
       passes; f_3B38/f_56CE/f_3D80 state changes remain in P2's private RAM. */
    md_coop_p2_sync_call_context(p2, frame_seed);
    /* active is 0 here, so this reads the real shared pool. */
    if (md_coop_pool_free_records() >= (unsigned)MT_COOP_POOL_RESERVE) {
        md_coop_p2_set_active(1);
        md_coop_p2_trace_sprite_build("before-f5db2", p2);
        if (!md_coop_p2_call_renderer(p2)) {
            md_coop_p2_abort("P2 sprite builder did not restore its CPU stack/return frame", 0);
            md_coop_p2_finish();
            return;
        }
        md_coop_p2_trace_sprite_build("after-f5db2", p2);
    } else {
        /* Pool nearly full: omit this player's sprite this frame (brief flicker)
           instead of draining the pool and corrupting list/fallback state. */
        md_coop_p2_note_pool_skip();
        md_coop_p2_set_active(1);
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

    /* The original frame loop runs f_3BD8 immediately after the player's
       movement callback. It finalizes per-player contact/collision flags
       consumed by the next frame's f_3B38/f_3284 path. P2 must run the same
       native post-actor phase against its private RAM view or its contact
       state is only initialized, then cleared without being rebuilt. */
    if (!md_coop_p2_call_actor(p2, 0x00003BD8u)) {
        md_coop_p2_abort("P2 post-actor contact finalizer f_3BD8 did not restore its CPU stack/return frame", 0x3BD8u);
        md_coop_p2_finish();
        return;
    }

    md_coop_p2_set_active(0);
    md_coop_p2_actor_complete(p2, callback);
    md_coop_p2_finish();
}

/* Run every extra player in order (P2, P3, ...), then restore the primary view. */
void md_coop_run_local_p2(M68K *primary, uint32_t callback) {
    unsigned s, n = md_coop_p2_slot_count();
    for (s = 0; s < n; ++s) {
        md_coop_p2_select(s);
        md_coop_run_local_slot(primary, callback);
    }
    md_coop_p2_end_frame();
}
"""


# ---- Attribute allocated world objects to the active local player. ----
def install_owner_hooks() -> None:
    if not OBJ_OWNER:
        print("Object ownership hooks disabled by MT_COOP_OBJ_OWNER=0.")
        return
    g = GEN.read_text(encoding="utf-8")
    if "md_obj_enter(c);" in g and "md_obj_note_alloc(c);" in g:
        print("Object-ownership hooks already present.")
        return
    hooks = []
    for label, pc in (("L_5380", "0x5380"), ("L_53D4", "0x53D4")):
        rx = re.compile(
            r"(" + label + r":\s*\{\s*RT_POLL\(" + pc + r"\);\s*)"
            r"(\{\s*c->ret=RD32\(A\(7\)\);\s*A\(7\)\+=4;\s*return;\s*\}\s*\})"
        )
        g, n = rx.subn(r"\1md_obj_note_alloc(c); \2", g, count=1)
        hooks.append((label, n))
    rx = re.compile(
        r"(L_5448:\s*\{[^\n]*?rt_shadow\[rt_sp\+\+\]=_r;\s*)rt_call_addr\(c,_t\);"
    )
    g, n = rx.subn(
        r"\1md_obj_enter(c); rt_call_addr(c,_t); md_obj_leave();",
        g,
        count=1,
    )
    hooks.append(("L_5448", n))
    if all(n == 1 for _, n in hooks):
        GEN.write_text(g, encoding="utf-8", newline="\n")
        print("Installed object-ownership hooks (f_5300, f_5382, f_5432 dispatch).")
    else:
        missing = ", ".join(label for label, n in hooks if n != 1)
        print("WARNING: object-ownership hooks NOT installed (anchors not found: "
              + missing + "). P2 rope/shot objects may still act on P1.")

install_owner_hooks()

gen = GEN.read_text(encoding="utf-8")
GEN_RUNNER = GEN_RUNNER.replace("__POOL_RESERVE__", str(POOL_RESERVE))
if "First native Mega Turrican P2 actor runner." not in gen:
    gen += GEN_RUNNER
    GEN.write_text(gen, encoding="utf-8", newline="\n")

# 4) Capture the native per-frame collision reset inputs, seed P2 at the
# pre-render seam, then run P2 beside the original player actor.
replace_once(
    GEN,
    "L_15D6: { RT_POLL(0x15D6); { uint32_t _r=0x15DAu;",
    "L_15D6: { RT_POLL(0x15D6); md_coop_p2_capture_collision_seed(c); { uint32_t _r=0x15DAu;",
    "P2 collision reset register/condition-code capture",
)
replace_once(
    GEN,
    "L_160E: { RT_POLL(0x160E); uint32_t e=0xFFFFBF28u; uint32_t v=RD16(e); uint32_t r=v; fl_logic(c,r,16); }",
    "L_160E: { RT_POLL(0x160E); md_coop_p2_capture_motion_seed(c); uint32_t e=0xFFFFBF28u; uint32_t v=RD16(e); uint32_t r=v; fl_logic(c,r,16); }",
    "P2 motion-state seed at the native BF28 gate",
)
replace_once(
    GEN,
    "L_1650: { RT_POLL(0x1650); { uint32_t _r=0x1654u;",
    "L_1650: { RT_POLL(0x1650); md_coop_p2_capture_spatial_seed(c); { uint32_t _r=0x1654u;",
    "P2 f_56CE spatial-builder register capture",
)
replace_once(
    GEN,
    "L_1654: { RT_POLL(0x1654); { uint32_t _r=0x1658u;",
    "L_1654: { RT_POLL(0x1654); md_coop_p2_capture_collision_descriptors(c); { uint32_t _r=0x1658u;",
    "P2 collision descriptor snapshot before P1 f_3D80",
)
replace_once(
    GEN,
    "L_1658: { RT_POLL(0x1658); { uint32_t _r=0x165Cu;",
    "L_1658: { RT_POLL(0x1658); md_coop_prepare_p2(c); { uint32_t _r=0x165Cu;",
    "P2 one-time seed hook at player render seam",
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

replace_once(
    GEN,
    "L_3284: { RT_POLL(0x3284); D(1)=(uint32_t)(int32_t)(int8_t)0; fl_logic(c,D(1),32);",
    "L_3284: { RT_POLL(0x3284); md_coop_p2_trace_ground(\"f3284-enter\",c); D(1)=(uint32_t)(int32_t)(int8_t)0; fl_logic(c,D(1),32);",
    "P2 ground-check entry trace",
)
replace_once(
    GEN,
    "L_3366: { RT_POLL(0x3366); { c->ret=RD32(A(7)); A(7)+=4; return; } }",
    "L_3366: { RT_POLL(0x3366); md_coop_p2_trace_ground(\"f3284-exit\",c); { c->ret=RD32(A(7)); A(7)+=4; return; } }",
    "P2 ground-check exit trace",
)

replace_once(
    GEN,
    "L_3286: { RT_POLL(0x3286); uint32_t s=0xFFFFBCEAu; uint32_t v=RD16(s); DSET(0,16,v); fl_logic(c,v,16); }",
    "L_3286: { RT_POLL(0x3286); md_coop_p2_trace_ground(\"f3284-bcea-loaded\",c); uint32_t s=0xFFFFBCEAu; uint32_t v=RD16(s); DSET(0,16,v); fl_logic(c,v,16); }",
    "P2 f3284 BCEA load probe",
)
replace_once(
    GEN,
    "L_3290: { RT_POLL(0x3290); if(cond(c,6)) goto L_329C; }",
    "L_3290: { RT_POLL(0x3290); md_coop_p2_trace_ground(\"f3284-input-bit2-branch\",c); if(cond(c,6)) goto L_329C; }",
    "P2 f3284 input bit 2 branch probe",
)
replace_once(
    GEN,
    "L_32A2: { RT_POLL(0x32A2); if(cond(c,6)) goto L_32AE; }",
    "L_32A2: { RT_POLL(0x32A2); md_coop_p2_trace_ground(\"f3284-input-bit3-branch\",c); if(cond(c,6)) goto L_32AE; }",
    "P2 f3284 input bit 3 branch probe",
)
replace_once(
    GEN,
    "L_32B6: { RT_POLL(0x32B6); if(cond(c,6)) goto L_335A; }",
    "L_32B6: { RT_POLL(0x32B6); md_coop_p2_trace_ground(\"f3284-bcfe-branch\",c); if(cond(c,6)) goto L_335A; }",
    "P2 f3284 BCFE branch probe",
)
replace_once(
    GEN,
    "L_32CA: { RT_POLL(0x32CA); if(cond(c,6)) goto L_3326; }",
    "L_32CA: { RT_POLL(0x32CA); md_coop_p2_trace_ground(\"f3284-first-bound-result\",c); if(cond(c,6)) goto L_3326; }",
    "P2 f3284 first bounds result probe",
)
replace_once(
    GEN,
    "L_32E8: { RT_POLL(0x32E8); if(cond(c,6)) goto L_3326; }",
    "L_32E8: { RT_POLL(0x32E8); md_coop_p2_trace_ground(\"f3284-second-bound-result\",c); if(cond(c,6)) goto L_3326; }",
    "P2 f3284 second bounds result probe",
)
replace_once(
    GEN,
    "L_32FC: { RT_POLL(0x32FC); if(cond(c,7)) goto L_335A; }",
    "L_32FC: { RT_POLL(0x32FC); md_coop_p2_trace_ground(\"f3284-bcd8-branch\",c); if(cond(c,7)) goto L_335A; }",
    "P2 f3284 BCD8 branch probe",
)
replace_once(
    GEN,
    "L_334C: { RT_POLL(0x334C); uint32_t e=0xFFFFBCD8u; WR8(e,(cond(c,1)?0xFF:0)); }",
    "L_334C: { RT_POLL(0x334C); md_coop_p2_trace_ground(\"f3284-bcd8-write\",c); uint32_t e=0xFFFFBCD8u; WR8(e,(cond(c,1)?0xFF:0)); }",
    "P2 f3284 BCD8 result write probe",
)
replace_once(
    GEN,
    "L_3350: { RT_POLL(0x3350); uint32_t e=0xFFFFBCE5u; WR8(e,(cond(c,1)?0xFF:0)); }",
    "L_3350: { RT_POLL(0x3350); md_coop_p2_trace_ground(\"f3284-bce5-write\",c); uint32_t e=0xFFFFBCE5u; WR8(e,(cond(c,1)?0xFF:0)); }",
    "P2 f3284 BCE5 result write probe",
)
replace_once(
    GEN,
    "L_3362: { RT_POLL(0x3362); uint32_t e=0xFFFFBD22u; WR8(e,(cond(c,11)?0xFF:0)); }",
    "L_3362: { RT_POLL(0x3362); md_coop_p2_trace_ground(\"f3284-bd22-write\",c); uint32_t e=0xFFFFBD22u; WR8(e,(cond(c,11)?0xFF:0)); }",
    "P2 f3284 BD22 result write probe",
)



replace_once(
    GEN,
    "L_3222: { RT_POLL(0x3222); uint32_t e=0xFFFFBCF5u; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "L_3222: { RT_POLL(0x3222); md_coop_p2_trace_motion(\"f3222-enter\",c); uint32_t e=0xFFFFBCF5u; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "P2 f3222 entry trace",
)
replace_once(
    GEN,
    "L_3226: { RT_POLL(0x3226); if(cond(c,7)) { f_3284(c); return; } }",
    "L_3226: { RT_POLL(0x3226); md_coop_p2_trace_motion(\"f3222-bcf5-zero-branch\",c); if(cond(c,7)) { md_coop_p2_trace_motion(\"f3222-empty-pre-f3284\",c); f_3284(c); md_coop_p2_trace_motion(\"f3222-empty-return\",c); return; } }",
    "P2 f3222 empty-count branch trace",
)
replace_once(
    GEN,
    "L_3232: { RT_POLL(0x3232); uint32_t e=0xFFFFBCF5u; uint32_t v=RD8(e); uint32_t r=op_sub(c,1,v,8); WR8(e,r); }",
    "L_3232: { RT_POLL(0x3232); md_coop_p2_trace_motion(\"f3222-bcf5-decrement\",c); uint32_t e=0xFFFFBCF5u; uint32_t v=RD8(e); uint32_t r=op_sub(c,1,v,8); WR8(e,r); }",
    "P2 f3222 BCF5 decrement trace",
)
replace_once(
    GEN,
    "L_3240: { RT_POLL(0x3240); uint32_t e=0xFFFFBCF6u; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "L_3240: { RT_POLL(0x3240); md_coop_p2_trace_motion(\"f3222-bcf6-load\",c); uint32_t e=0xFFFFBCF6u; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "P2 f3222 BCF6 load trace",
)
replace_once(
    GEN,
    "L_3244: { RT_POLL(0x3244); if(cond(c,7)) goto L_3256; }",
    "L_3244: { RT_POLL(0x3244); md_coop_p2_trace_motion(\"f3222-bcf6-branch\",c); if(cond(c,7)) goto L_3256; }",
    "P2 f3222 BCF6 branch trace",
)
replace_once(
    GEN,
    "L_324C: { RT_POLL(0x324C); { uint32_t _r=0x3250u; A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r; f_3514(c); rt_sp--; if(c->ret!=_r && !rt_fix_ret(c,_r)) return; } }",
    "L_324C: { RT_POLL(0x324C); md_coop_p2_trace_motion(\"f3222-f3514-first-before\",c); { uint32_t _r=0x3250u; A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r; f_3514(c); rt_sp--; if(c->ret!=_r && !rt_fix_ret(c,_r)) return; } md_coop_p2_trace_motion(\"f3222-f3514-first-after\",c); }",
    "P2 f3222 first f3514 call trace",
)
replace_once(
    GEN,
    "L_3262: { RT_POLL(0x3262); { uint32_t _r=0x3266u; A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r; f_3514(c); rt_sp--; if(c->ret!=_r && !rt_fix_ret(c,_r)) return; } }",
    "L_3262: { RT_POLL(0x3262); md_coop_p2_trace_motion(\"f3222-f3514-second-before\",c); { uint32_t _r=0x3266u; A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r; f_3514(c); rt_sp--; if(c->ret!=_r && !rt_fix_ret(c,_r)) return; } md_coop_p2_trace_motion(\"f3222-f3514-second-after\",c); }",
    "P2 f3222 second f3514 call trace",
)
replace_once(
    GEN,
    "L_327C: { RT_POLL(0x327C); { c->ret=RD32(A(7)); A(7)+=4; return; } }",
    "L_327C: { RT_POLL(0x327C); md_coop_p2_trace_motion(\"f3222-normal-return\",c); { c->ret=RD32(A(7)); A(7)+=4; return; } }",
    "P2 f3222 normal return trace",
)
replace_once(
    GEN,
    "L_3282: { RT_POLL(0x3282); { c->ret=RD32(A(7)); A(7)+=4; return; } }",
    "L_3282: { RT_POLL(0x3282); md_coop_p2_trace_motion(\"f3222-fallback-return\",c); { c->ret=RD32(A(7)); A(7)+=4; return; } }",
    "P2 f3222 fallback return trace",
)

replace_once(
    GEN,
    "L_3650: { RT_POLL(0x3650); uint32_t s=0xFFFFBCE6u; uint32_t v=RD32(s); A(7)-=4; uint32_t d=A(7); WR32(d,v); fl_logic(c,v,32);",
    "L_3650: { RT_POLL(0x3650); md_coop_p2_trace_floor(\"f3650-enter\",c); uint32_t s=0xFFFFBCE6u; uint32_t v=RD32(s); A(7)-=4; uint32_t d=A(7); WR32(d,v); fl_logic(c,v,32);",
    "P2 map collision entry trace",
)
replace_once(
    GEN,
    "L_36DE: { RT_POLL(0x36DE); { c->ret=RD32(A(7)); A(7)+=4; return; } }",
    "L_36DE: { RT_POLL(0x36DE); md_coop_p2_trace_floor(\"f3650-exit\",c); { c->ret=RD32(A(7)); A(7)+=4; return; } }",
    "P2 map collision exit trace",
)

replace_once(
    GEN,
    "L_2502: { RT_POLL(0x2502); if(cond(c,11)) goto L_2508; }",
    "L_2502: { RT_POLL(0x2502); md_coop_p2_trace_floor(\"f2502-branch\",c); if(cond(c,11)) goto L_2508; }",
    "P2 map collision branch decision trace",
)
replace_once(
    GEN,
    "L_2504: { RT_POLL(0x2504); { uint32_t _r=0x2508u; A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r; f_3650(c); rt_sp--; if(c->ret!=_r && !rt_fix_ret(c,_r)) return; } }",
    "L_2504: { RT_POLL(0x2504); md_coop_p2_trace_floor(\"f2504-call\",c); { uint32_t _r=0x2508u; A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r; f_3650(c); rt_sp--; if(c->ret!=_r && !rt_fix_ret(c,_r)) return; } }",
    "P2 map collision call-site trace",
)
replace_once(
    GEN,
    "L_2508: { RT_POLL(0x2508); uint32_t e=0xFFFFBCF3u; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "L_2508: { RT_POLL(0x2508); md_coop_p2_trace_floor(\"f2508-after\",c); uint32_t e=0xFFFFBCF3u; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "P2 map collision branch continuation trace",
)

replace_once(
    GEN,
    "L_24F2: { RT_POLL(0x24F2); if(cond(c,7)) goto L_2508; }",
    "L_24F2: { RT_POLL(0x24F2); md_coop_p2_trace_motion(\"f24f2-optional-branch\",c); if(cond(c,7)) goto L_2508; }",
    "P2 optional collision branch trace",
)
replace_once(
    GEN,
    "L_2452: { RT_POLL(0x2452); if(cond(c,7)) goto L_2498; }",
    "L_2452: { RT_POLL(0x2452); md_coop_p2_trace_motion(\"f2452-vertical-branch\",c); if(cond(c,7)) goto L_2498; }",
    "P2 vertical velocity branch trace",
)
replace_once(
    GEN,
    "L_247C: { RT_POLL(0x247C); uint32_t s=0xFFFFBCECu; uint32_t v=RD16(s); DSET(0,16,v); fl_logic(c,v,16); }",
    "L_247C: { RT_POLL(0x247C); md_coop_p2_trace_motion(\"f247c-velocity-load\",c); uint32_t s=0xFFFFBCECu; uint32_t v=RD16(s); DSET(0,16,v); fl_logic(c,v,16); }",
    "P2 vertical velocity load trace",
)
replace_once(
    GEN,
    "L_2480: { RT_POLL(0x2480); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_add(c,D(0),v,16); WR16(e,r); }",
    "L_2480: { RT_POLL(0x2480); md_coop_p2_trace_motion(\"f2480-y-add-before\",c); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_add(c,D(0),v,16); WR16(e,r); }",
    "P2 primary vertical addition trace",
)
replace_once(
    GEN,
    "L_2484: { RT_POLL(0x2484); goto L_2498; }",
    "L_2484: { RT_POLL(0x2484); md_coop_p2_trace_motion(\"f2484-y-add-after\",c); goto L_2498; }",
    "P2 primary vertical addition result trace",
)
replace_once(
    GEN,
    "L_227A: { RT_POLL(0x227A); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_sub(c,D(1),v,16); WR16(e,r); }",
    "L_227A: { RT_POLL(0x227A); md_coop_p2_trace_motion(\"f227a-y-sub-before\",c); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_sub(c,D(1),v,16); WR16(e,r); }",
    "P2 alternate vertical subtraction trace",
)
replace_once(
    GEN,
    "L_227E: { RT_POLL(0x227E); uint32_t e=0xFFFFBCFCu; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "L_227E: { RT_POLL(0x227E); md_coop_p2_trace_motion(\"f227e-y-sub-after\",c); uint32_t e=0xFFFFBCFCu; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "P2 alternate vertical subtraction result trace",
)
replace_once(
    GEN,
    "L_25F8: { RT_POLL(0x25F8); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_sub(c,2,v,16); WR16(e,r); }",
    "L_25F8: { RT_POLL(0x25F8); md_coop_p2_trace_motion(\"f25f8-y-minus-two-before\",c); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_sub(c,2,v,16); WR16(e,r); }",
    "P2 second vertical adjustment trace",
)
replace_once(
    GEN,
    "L_25FC: { RT_POLL(0x25FC); uint32_t e=0xFFFFBCC4u; uint32_t v=RD16(e); uint32_t r=v; op_cmp(c,0xFFFCu,v,16); }",
    "L_25FC: { RT_POLL(0x25FC); md_coop_p2_trace_motion(\"f25fc-y-minus-two-after\",c); uint32_t e=0xFFFFBCC4u; uint32_t v=RD16(e); uint32_t r=v; op_cmp(c,0xFFFCu,v,16); }",
    "P2 second vertical adjustment result trace",
)
replace_once(
    GEN,
    "L_2818: { RT_POLL(0x2818); uint32_t v=(D(1)&0xFFFFu); uint32_t d=0xFFFFBD20u; WR16(d,v); fl_logic(c,v,16); }",
    "L_2818: { RT_POLL(0x2818); md_coop_p2_trace_motion(\"f2818-y-store-before\",c); uint32_t v=(D(1)&0xFFFFu); uint32_t d=0xFFFFBD20u; WR16(d,v); fl_logic(c,v,16); }",
    "P2 direct vertical store trace",
)
replace_once(
    GEN,
    "L_281C: { RT_POLL(0x281C); uint32_t e=0xFFFFBCC2u; WR8(e,(cond(c,0)?0xFF:0)); }",
    "L_281C: { RT_POLL(0x281C); md_coop_p2_trace_motion(\"f281c-y-store-after\",c); uint32_t e=0xFFFFBCC2u; WR8(e,(cond(c,0)?0xFF:0)); }",
    "P2 direct vertical store result trace",
)
replace_once(
    GEN,
    "L_287C: { RT_POLL(0x287C); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_add(c,D(0),v,16); WR16(e,r); }",
    "L_287C: { RT_POLL(0x287C); md_coop_p2_trace_motion(\"f287c-y-add-before\",c); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_add(c,D(0),v,16); WR16(e,r); }",
    "P2 later vertical addition trace",
)
replace_once(
    GEN,
    "L_2880: { RT_POLL(0x2880); uint32_t e=0xFFFFBC90u; uint32_t m=1u<<(4u&7); uint32_t v=RD8(e); c->z=!(v&m); }",
    "L_2880: { RT_POLL(0x2880); md_coop_p2_trace_motion(\"f2880-y-add-after\",c); uint32_t e=0xFFFFBC90u; uint32_t m=1u<<(4u&7); uint32_t v=RD8(e); c->z=!(v&m); }",
    "P2 later vertical addition result trace",
)
replace_once(
    GEN,
    "L_2984: { RT_POLL(0x2984); uint32_t v=0xFFE0u; uint32_t d=0xFFFFBD20u; WR16(d,v); fl_logic(c,v,16); }",
    "L_2984: { RT_POLL(0x2984); md_coop_p2_trace_motion(\"f2984-y-clamp-before\",c); uint32_t v=0xFFE0u; uint32_t d=0xFFFFBD20u; WR16(d,v); fl_logic(c,v,16); }",
    "P2 vertical clamp trace",
)
replace_once(
    GEN,
    "L_298A: { RT_POLL(0x298A); uint32_t s=0xFFFFBCC4u; uint32_t v=RD32(s); DSET(1,32,v); fl_logic(c,v,32); }",
    "L_298A: { RT_POLL(0x298A); md_coop_p2_trace_motion(\"f298a-y-clamp-after\",c); uint32_t s=0xFFFFBCC4u; uint32_t v=RD32(s); DSET(1,32,v); fl_logic(c,v,32); }",
    "P2 vertical clamp result trace",
)
replace_once(
    GEN,
    "L_29AC: { RT_POLL(0x29AC); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_sub(c,D(1),v,16); WR16(e,r); }",
    "L_29AC: { RT_POLL(0x29AC); md_coop_p2_trace_motion(\"f29ac-y-sub-before\",c); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_sub(c,D(1),v,16); WR16(e,r); }",
    "P2 late vertical subtraction trace",
)
replace_once(
    GEN,
    "L_29B0: { RT_POLL(0x29B0); uint32_t e=0xFFFFBCD8u; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "L_29B0: { RT_POLL(0x29B0); md_coop_p2_trace_motion(\"f29b0-y-sub-after\",c); uint32_t e=0xFFFFBCD8u; uint32_t v=RD8(e); uint32_t r=v; fl_logic(c,r,8); }",
    "P2 late vertical subtraction result trace",
)
replace_once(
    GEN,
    "L_2AE6: { RT_POLL(0x2AE6); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_add(c,D(7),v,16); WR16(e,r); }",
    "L_2AE6: { RT_POLL(0x2AE6); md_coop_p2_trace_motion(\"f2ae6-y-add-before\",c); uint32_t e=0xFFFFBD20u; uint32_t v=RD16(e); uint32_t r=op_add(c,D(7),v,16); WR16(e,r); }",
    "P2 final vertical addition trace",
)
replace_once(
    GEN,
    "L_2AEA: { RT_POLL(0x2AEA); { uint32_t _r=0x2AEEu; A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r; f_3222(c); rt_sp--; if(c->ret!=_r && !rt_fix_ret(c,_r)) return; } }",
    "L_2AEA: { RT_POLL(0x2AEA); md_coop_p2_trace_motion(\"f2aea-y-add-after\",c); { uint32_t _r=0x2AEEu; A(7)-=4; WR32(A(7),_r); rt_shadow[rt_sp++]=_r; f_3222(c); rt_sp--; if(c->ret!=_r && !rt_fix_ret(c,_r)) return; } }",
    "P2 final vertical addition result trace",
)

replace_once(
    GEN,
    "L_25AA: { RT_POLL(0x25AA); uint32_t v=(D(0)&0xFFu); uint32_t d=A(2)+(int32_t)11; WR8(d,v); fl_logic(c,v,8); }",
    "L_25AA: { RT_POLL(0x25AA); uint32_t v=(D(0)&0xFFu); uint32_t d=A(2)+(int32_t)11; md_coop_p2_trace_hit_target(\"before-object-hit-write\",c); WR8(d,v); md_coop_p2_trace_hit_target(\"after-object-hit-write\",c); fl_logic(c,v,8); }",
    "P2 native shared-object hit pre-write trace",
)
# 5) Static contract checks. These do not prove gameplay; they ensure the
# patch is installed once, P2 gets a private stack/bus bank, and the old unsafe
# all-RAM shadow script remains untouched.
h = HARNESS.read_text(encoding="utf-8")
g = GEN.read_text(encoding="utf-8")
r = RT_HEADER.read_text(encoding="utf-8")
checks = {
    "P2 owns persistent M68K context": "M68K m68k, frame_seed" in h and "#define md_coop_p2_m68k MD_CUR.m68k" in h,
    "P2 uses a separate synthetic stack": "0x00F0FFFCu" in h and "md_coop_p2_stack" in h,
    "P2 private RAM uses explicit allowlist": "md_coop_p2_mark(0xBCBC, 0xBD26)" in h,
    "P2 owns its original descriptor callback slots": all(x in h for x in (
        "md_coop_p2_mark(0xBC18, 0xBC27)", "md_coop_p2_mark(0xBC3C, 0xBC43)",
        "md_coop_p2_mark(0xBC44, 0xBC4B)", "md_coop_p2_mark(0xBC4C, 0xBC53)",
        "md_coop_p2_mark(0xBC5A, 0xBC61)")),
    "P2 owns its original respawn/camera position snapshot": "md_coop_p2_mark(0xBF0E, 0xBF17)" in h,
    "P2 owns f_19FA player init state BC8C": "md_coop_p2_mark(0xBC8C, 0xBC8C)" in h,
    "P2 init state is included in runtime trace": "BC8C=%02X BF18=%08X BF1C=%04X" in h,
    "P2 owns f_19FA descriptor state BF18..BF1D": "md_coop_p2_mark(0xBF18, 0xBF1D)" in h,
    "P2 live spawn offset matches its native respawn X snapshot": "md_coop_p2_put_word(0xBF12" in h and "md_coop_p2_word(0xBF12) + MD_COOP_SPAWN_DX" in h,
    "P2 descriptor and lifecycle state are included in runtime trace": "p2_callback_slots BC18=%08X" in h and "BF0E=%08X BF12=%08X" in h,
    "P2 owns full indexed player work area": "md_coop_p2_mark(0xF200, 0xF9FF)" in h and "p2_player_scratch_F200_F9FF=" in h,
    "P2 input retains the verified native port-2 pair": "md_coop_p2_ram[0xBC90] = ram[0xBC92]" in h and "md_coop_p2_ram[0xBC91] = ram[0xBC93]" in h,
    "P3/P4 receive independent Genesis active-low input pairs": "md_player_live_masks[player]" in h and "md_coop_encode_genesis_input" in h and "active_low >> 8" in h,
    "Genesis button input encodes the traced B and Start bit positions": "0x1000u" in h and "0x8000u" in h and "0x0800u" in h,
    "per-slot activation uses each player's own physical controller": "md_player_connected[player]" in h and "return player == 1u && md_local_coop_enabled;" in h,
    "P2 Game Options override remains backward-compatible": "return player == 1u && md_local_coop_enabled;" in h,
    "P2 seed capture and readiness honor forced mode": h.count("!md_coop_p2_requested()") >= 5 and "md_coop_p2_requested() && md_coop_primary_m68k != NULL" in h,
    "P2 trace records whether multiplayer was forced": "connected=%d forced=%d callback=%06X" in h,
    "P2 actor runs immediately before P1 actor": "md_coop_run_local_p2(c,_t); rt_call_addr(c,_t);" in g,
    "P2 captures the original pre-render frame context": "#define md_coop_p2_frame_seed MD_CUR.frame_seed" in h and "md_coop_p2_frame_seed_context" in g,
    "P2 captures the native collision-reset register context": "md_coop_p2_capture_collision_seed(c)" in g and "md_coop_p2_collision_seed_context" in g,
    "P2 captures the native f_56CE spatial-builder context": "md_coop_p2_capture_spatial_seed(c)" in g and "md_coop_p2_spatial_seed_context" in g,
    "P2 rebuilds f_56CE collision candidates every frame": "md_coop_p2_call_actor(p2, 0x000056CEu)" in g,
    "P2 captures native BD28 collision candidates before P1 consumes them": "md_coop_p2_capture_collision_descriptors(c)" in g and "md_coop_p2_primary_collision_desc" in h and "count * 12u" in h,
    "P2 owns 40 native 12-byte collision descriptors": "md_coop_p2_mark(0xBD28, 0xBF07)" in h and "count * 12u" in h and "count > 40u" in h and "record = 0xBD28u + i * 12u" in h,
    "P2 redirects descriptors to private collision-result contexts through offset +8": "md_coop_p2_long(record + 8u)" in h and "md_coop_p2_put_long(record + 8u, 0xFFFF0000u" in h,
    "P2 shadows up to 40 collision-result contexts in private scratch": "uint32_t old_ptrs[40]" in h and "old_count >= 40u" in h and "md_coop_p2_mark(0xEA00, 0xEEFF)" in h and "md_coop_p2_ram[dest + 11u] = 0;" in h and "md_coop_p2_put_long(dest + 16u, 0);" in h and "(ptr & 0x00FF0000u) != 0x00FF0000u" in h,
    "P2 runs native f_3D80 with isolated collision-result contexts": "md_coop_p2_call_actor(p2, 0x00003D80u)" in g and "md_coop_p2_import_collision_descriptors()" in g,
    "P2 and P1 collision results are traced independently": "md_coop_p2_trace_collision_results(void)" in h and "p1_flag=%02X p2_flag=%02X" in h and "md_coop_p2_trace_collision_results();" in g,
    "P2 native object hit target writes are traced on both sides": "md_coop_p2_trace_hit_target(const char *stage, M68K *cpu)" in h and "before-object-hit-write" in g and "after-object-hit-write" in g,
    "P2 isolates the f_56CE scratch outputs": "md_coop_p2_mark(0xF200, 0xF9FF)" in h,
    "P2 collision flags and descriptor cursor have isolated storage": "md_coop_p2_mark(0xBC84, 0xBC8B)" in h and "md_coop_p2_mark(0xBD28, 0xBF07)" in h and "md_coop_p2_mark(0xBF08, 0xBF0D)" in h and "md_coop_p2_mark(0xFE58, 0xFE58)" in h,
    "P2 replays only native f_3B38 collision-state reset": "md_coop_p2_call_actor(p2, 0x00003B38u)" in g,
    "P2 preserves the Build #644 visible actor phase order without replaying f_2130 or f_5D8A": "md_coop_p2_call_actor(p2, 0x00002130u)" not in g and "md_coop_p2_call_actor(p2, 0x00005D8Au)" not in g and "md_coop_p2_call_actor(p2, 0x00003B38u)" in g,
    "P2 waits for the original native motion-state seed before running": "motion_seed = md_coop_p2_motion_seed_context();" in g and "|| !motion_seed" in g,
    "P2 runs native post-actor contact finalizer f_3BD8": "md_coop_p2_call_actor(p2, 0x00003BD8u)" in g,
    "P2 f3284 internal collision decision points are traced": "md_coop_p2_trace_ground(\"f3284-bcea-loaded\",c)" in g and "md_coop_p2_trace_ground(\"f3284-input-bit2-branch\",c)" in g and "md_coop_p2_trace_ground(\"f3284-input-bit3-branch\",c)" in g and "md_coop_p2_trace_ground(\"f3284-bcfe-branch\",c)" in g and "md_coop_p2_trace_ground(\"f3284-first-bound-result\",c)" in g and "md_coop_p2_trace_ground(\"f3284-second-bound-result\",c)" in g and "md_coop_p2_trace_ground(\"f3284-bcd8-branch\",c)" in g and "md_coop_p2_trace_ground(\"f3284-bcd8-write\",c)" in g and "md_coop_p2_trace_ground(\"f3284-bce5-write\",c)" in g and "md_coop_p2_trace_ground(\"f3284-bd22-write\",c)" in g,
    "P2 f3222 post-movement collision path is traced": "md_coop_p2_trace_motion(\"f3222-enter\",c)" in g and "md_coop_p2_trace_motion(\"f3222-bcf5-zero-branch\",c)" in g and "md_coop_p2_trace_motion(\"f3222-bcf6-load\",c)" in g and "md_coop_p2_trace_motion(\"f3222-f3514-first-before\",c)" in g and "md_coop_p2_trace_motion(\"f3222-f3514-second-after\",c)" in g and "md_coop_p2_trace_motion(\"f3222-normal-return\",c)" in g and "BCF5=%02X BCF6=%02X" in h,
    "P2 ground-check entry and exit are traced": "md_coop_p2_trace_ground(\"f3284-enter\",c)" in g and "md_coop_p2_trace_ground(\"f3284-exit\",c)" in g and "event=p2-ground" in h,
    "P2 map collision f_3650 entry and exit are traced": "md_coop_p2_trace_floor(\"f3650-enter\",c)" in g and "md_coop_p2_trace_floor(\"f3650-exit\",c)" in g and "event=p2-floor" in h and "F226=" in h,
    "P2 map collision branch and call-site are traced": "md_coop_p2_trace_floor(\"f2502-branch\",c)" in g and "md_coop_p2_trace_floor(\"f2504-call\",c)" in g and "md_coop_p2_trace_floor(\"f2508-after\",c)" in g,
    "P2 records each native BD20 vertical movement branch": "md_coop_p2_trace_motion(\"f24f2-optional-branch\",c)" in g and "md_coop_p2_trace_motion(\"f2452-vertical-branch\",c)" in g and "md_coop_p2_trace_motion(\"f2480-y-add-before\",c)" in g and "md_coop_p2_trace_motion(\"f2484-y-add-after\",c)" in g and "md_coop_p2_trace_motion(\"f227a-y-sub-before\",c)" in g and "md_coop_p2_trace_motion(\"f2818-y-store-before\",c)" in g and "md_coop_p2_trace_motion(\"f287c-y-add-before\",c)" in g and "md_coop_p2_trace_motion(\"f2984-y-clamp-before\",c)" in g and "md_coop_p2_trace_motion(\"f29ac-y-sub-before\",c)" in g and "md_coop_p2_trace_motion(\"f2ae6-y-add-before\",c)" in g and "event=p2-motion" in h,
    "P2 keeps its renderer register results for movement": "md_coop_p2_sync_call_context(p2, frame_seed);" in g and "md_coop_p2_sync_call_context(p2, primary);" not in g,
    "P2 actor trace captures CPU and private state": "p2_state_BC62_BD26=" in h and "p2_cpu d:" in h,
    "P2 renderer uses native f_5DB2": "f_5DB2(p2);" in g,
    "P2 sprite diagnostics bracket f_5DB2 and inspect 29 private parts plus shared queue": "md_coop_p2_trace_sprite_build(\"before-f5db2\", p2)" in g and "md_coop_p2_trace_sprite_build(\"after-f5db2\", p2)" in g and "event=p2-sprite-build" in h and "for (i = 0; i < 29u; ++i)" in h and "queue_count=%04X" in h,
    "P2 callback is guarded": "callback != 0x0000224Cu" in g,
    "global events suspend P2 memory view": "md_coop_p2_service_event(c)" in r and "md_coop_p2_service_irq(c)" in r,
    "DMA raw reads remain untouched": "uint16_t vdp_dma_read" in h and "rd8_raw(a)" in h and "rd8_raw(a + 1)" in h,
    "P2 movement-lock bytes are zeroed at spawn": all(x in h for x in (
        "md_coop_p2_ram[0xBCF5] = 0;", "md_coop_p2_ram[0xBCF6] = 0;",
        "md_coop_p2_ram[0xBCF7] = 0;", "md_coop_p2_ram[0xBCF8] = 0;")),
    "P2 velocity accumulators are zeroed at spawn": "md_coop_p2_put_word(0xBCEC, 0)" in h and "md_coop_p2_put_word(0xBCEE, 0)" in h,
    "DMA queue is isolated or deliberately shared, never half-banked": ("md_coop_p2_mark(0xD2DA, 0xD8D9)" in h) and ("md_coop_p2_mark(0xBCA4, 0xBCA7)" in h) and "md_coop_p2_ram[0xBCA4] = 0" in h,
    "extra players are slots, not singletons": "md_coop_slot_t md_coop_slots[MT_COOP_SLOTS]" in h and "md_coop_run_local_slot(primary, callback)" in g,
    "slot count is bounded to two through four total players": "max(2, min(4, int(os.environ.get(\"MT_COOP_PLAYERS\", \"3\"))))" in Path(__file__).read_text(encoding="utf-8"),
    "four controller slots are visible to runtime": "extern int md_player_live_masks[4];" in h and "extern int md_player_connected[4];" in h,
    "object pool guard before extra-player sprite build": "md_coop_pool_free_records() >= (unsigned)MT_COOP_POOL_RESERVE" in g,
    "shared-write audit installed on the bus": h.count("md_coop_p2_note_shared_write") >= 3,
    "P2 uses soft abort with retry instead of permanent disable on first fault": "soft-abort" in h and "md_coop_p2_abort_count" in h and "md_coop_p2_ready = 0" in h,
    "per-frame diagnostic log captures player state and pose bytes": "MegaTurrican-coop-diag.txt" in h and "md_diag_ranges" in h and "0xBCBCu, 0xBD26u" in h and "md_coop_diag_frame();" in h,
    "object ownership metadata and dispatch helpers are installed": "md_obj_owner[0x10000]" in h and "md_obj_note_alloc(M68K *c)" in h and "md_obj_enter(M68K *c)" in h and "md_obj_leave(void)" in h,
    "object dispatch count is included in diagnostics": "own=%lu" in h and "md_obj_dispatch_count" in h,
    "motion trace covers the later fall window": "md_coop_p2_frame_count > 420u" in h,
}
# Enforce the ownership boundary: these ranges belong to the one shared
# world/renderer/game-flow instance and must never enter P2's private bank.
private_ranges = [
    (int(start, 16), int(end, 16))
    for start, end in re.findall(
        r"md_coop_p2_mark\(0x([0-9A-Fa-f]+),\s*0x([0-9A-Fa-f]+)\)", h
    )
]
shared_ranges = {
    "shared world-object list BC28..BC3B": (0xBC28, 0xBC3B),
    "shared sprite queue BC54..BC59": (0xBC54, 0xBC59),
    "shared viewport origin DFD4..DFD7": (0xDFD4, 0xDFD7),
    "shared gameplay flags BC68..BC69": (0xBC68, 0xBC69),
    "global continue counter BF3A": (0xBF3A, 0xBF3A),
    "shared object-pool cursor BF3C": (0xBF3C, 0xBF3C),
    "shared viewport world bounds DFDC": (0xDFDC, 0xDFDC),
    "shared viewport world bounds DFE4": (0xDFE4, 0xDFE4),
}
for label, (first, last) in shared_ranges.items():
    checks[label + " remain world-owned"] = not any(
        first <= private_last and private_first <= last
        for private_first, private_last in private_ranges
    )

for label, passed in checks.items():
    if not passed:
        raise SystemExit("local co-op verification failed: " + label)

print("Installed guarded native P2 actor prototype: isolated f_3B38/f_56CE preparation, 40-entry 12-byte BD28 table, private collision-result contexts, and native f_3D80 resolver.")
print("Ownership contracts keep world objects, sprite queue, game-flow flags, object-pool cursor, viewport origin/bounds, and continue flow shared; gameplay still requires in-game verification.")