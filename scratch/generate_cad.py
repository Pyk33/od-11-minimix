#!/usr/bin/env python3
"""
Parametric CAD generator for OD-11 Minimix enclosure  (rev 3 - designpass + skruvlöst lock)

Koordinater:  (ix, iy, iz) = "inre" koordinater, origo i lådans inre främre vänstra hörn,
              iz = höjd över golvets ovansida.  Alla CAD-objekt byggs i centrerade
              absolutkoordinater (X/Y centrerade, Z=0 = lådans undersida).

Användarens mått:
 1. Distanspelare (golv -> topp hex): 37.0 mm      2. Hanpinne: 6.0 mm
 3. Encoder-kropp: 34.0 mm hög, 38.5 mm diam       4. Encoder-krage: 20 mm diam, 5 mm hög
 5. Encoder-hål: 6 st, 3 par, PCD ~28.0 mm         6. Ratt: 35 mm diam, 16 mm hög
 7. Knappar: M12                                   8. Knapp: 19 mm från huvudets underkant till kabelböj
 9. Cubilux TOSLINK-block 16x16x24, kabel 6 mm centrerad 3 mm från botten
10. Kablar/plintar når ~37 mm   USB-C-kontakt 10.7 x 6.6 (helrunda kortsidor)
    OLED-glas 34.4 x 18.6, total tjocklek 3.4 mm

Rev 3 - vad som är nytt:
 * Hörnradie 9 mm (layouten flyttad så Cubilux-porten ryms på den raka väggdelen)
 * Fas överkant lock, fas i fogen (skuggspalt), fas underkant botten, fas runt portarna
 * Ventilation: långa smala slitsar med helrunda ändar, i sladdväggen
 * Gravyr "OLLE's MiniMix" (nedsänkt 0.4 mm, läsbar från användarsidan)
 * Skuggspalt runt rattens bas, nedsänkt fönsterram runt skärmen
 * SKRUVLÖST lock: 7 snäpptungor i locket klickar i spår i lådans insida.
   Distansernas hanpinnar går in i BLINDA fickor på lockets undersida (inga hål på ovansidan)
 * Cubilux-blocket hålls mot framväggen av en läpp (öppningen mindre än blocket) => följer inte med ut
"""
import os
import math
from build123d import *

CAD_DIR = "/Users/ollepyk/Desktop/OD-11 Minimix/streamer-project/cad_output"

# --------------------------------------------------------------------------- #
# Parametrar (mm)
# --------------------------------------------------------------------------- #
WALL = 2.5
FLOOR_THICK = 2.4
LID_THICK = 5.0            # 5.0 => hanpinnarnas topp (3.5 mm över lockets undersida) ryms i BLINDA fickor med 1.2 mm hud
CORNER_R = 9.0

INT_X, INT_Y, INT_Z = 162.5, 74.0, 39.5
EXT_X, EXT_Y = INT_X + 2 * WALL, INT_Y + 2 * WALL
BASE_H = FLOOR_THICK + INT_Z                  # bottenlådans höjd = lockets underkant
EXT_Z = BASE_H + LID_THICK

# Lock/botten-fog: falsen i botten, RING (ej platta!) under locket
REBATE_DEPTH = 1.6
REBATE_R = CORNER_R - WALL / 2
LIP_CLEAR = 0.25
RING_H = 1.4
RING_T = 1.2

# Faser
LID_TOP_CHAMFER = 0.8      # lockets överkant
JOINT_CHAMFER = 0.6        # botten överkant + lock underkant => V-formad skuggspalt 1.2 mm
BASE_BOTTOM_CHAMFER = 1.0  # botten underkant (lådan "svävar")
PORT_CHAMFER = 0.4         # fas runt USB-C/TOSLINK-hål på utsidan

# Distanspelare / Pi
STANDOFF_H = 37.0
STUD_L = 6.0
BOSS_H = INT_Z - STANDOFF_H                   # 2.5 mm stödhylsor under locket
STUD_POCKET_R = 1.6                           # hanpinne r=1.25 + 0.35 spel
STUD_POCKET_DEPTH = STUD_L - BOSS_H + 0.3     # 3.8 mm in i locket (pinnen når 3.5)
PI_X, PI_Y = 27.5, 3.0
PI_BOTTOM = 10.0                              # <- BEKRÄFTA: Pi-kortets undersida över golv
PI_T = 1.6
PI_HOLES = [(PI_X + 3.5, PI_Y + 3.5), (PI_X + 61.5, PI_Y + 3.5),
            (PI_X + 3.5, PI_Y + 52.5), (PI_X + 61.5, PI_Y + 52.5)]
HAT_BOTTOM = PI_BOTTOM + PI_T + 12.0          # <- BEKRÄFTA
HAT_T = 1.6

# Cubilux TOSLINK-block + klickvagga
CR_X = 17.0
BLOCK_W, BLOCK_H, BLOCK_L = 16.4, 16.4, 24.0
CR_INNER_W = 16.6
RAIL_T = 1.4
STOP_T = 1.8
BLOCK_FRONT_Y = 0.1                           # blockets framsida ligger mot framväggens insida (0.1 mm spel)
TOSLINK_OPEN = 14.6                           # öppning MINDRE än blocket (16.4) => väggen håller blocket när man drar i kabeln
CABLE_D, CABLE_Z = 6.0, 3.0

# USB-C (ström) - helrunda kortsidor
USBC_PLUG_W, USBC_PLUG_H = 10.7, 6.6
USBC_X = PI_X + 11.2                          # Pi 4: USB-C 11.2 mm från kortets kant
USBC_Z = PI_BOTTOM + PI_T + 1.6               # mitt på hylsan (3.2 mm hög)

# Knappar (M12)
BTN_X, BTN_Y1, BTN_Y2 = 11.0, 28.0, 54.0

# OLED (1.5" 128x128 SH1107, tillverkarens ritning MC01506)
OG_X, OG_Y = 60.0, 35.0                       # glasets och kretskortets mitt (exakt mitt mellan Pi-distanserna)
GLASS_W, GLASS_H = 34.0, 37.3                 # glas yttermått (centrerat på PCB:t i MC01506)
GLASS_T = 1.44                                # glastjocklek
WINDOW_W, WINDOW_H = 27.2, 27.2               # kvadratiskt fönster för aktiv yta (26.86 x 26.86 mm)
WINDOW_OFFSET_Y = 2.82                        # A.A. fönster är förskjutet 2.82 mm mot överkant (pinnkanten)
PCB_W, PCB_H = 34.0, 47.0                     # kretskortets yttermått
OLED_PCB_T = 1.2                              # kretskortets tjocklek
OLED_TOTAL_T = GLASS_T + 0.3 + OLED_PCB_T     # 2.94 mm total tjocklek
BEZEL_T = 1.0                                 # godstjocklek framför glaset
OLED_TAPE_GAP = 0.3                           # plats för dubbelhäftande skumtejp
BEZEL_RECESS = 0.4                            # nedsänkt fönsterram
BEZEL_RECESS_MARGIN = 1.5                     # ram runt fönstret

# Encoder & Nedsänkt Rattbrunn (M3x6 försänkta skruvar, ratten infälld i locket)
ENC_X, ENC_Y = 138.5, 40.0                    # bakom Cubilux USB-delen
ENC_PCD = 14.0                                # radie (PCD 28 mm)
ENC_ALPHA = 35.14
KNOB_R = 17.5                                 # ratt radie (35 mm diam)
KNOB_H = 16.0                                 # ratt höjd
KNOB_WELL_R = 18.3                            # brunn radie (36.6 mm diam, 0.8 mm jämn spalt runt ratten)
KNOB_WELL_DEPTH = 2.6                         # brunnens djup från lockets ovansida (ratten nedsänkt 2.1 mm)
ENC_MOUNT_T = 2.0                             # plasttjocklek under skruvhuvud (ger 4.0 mm rent gängingrepp för M3x6)

# Gravyr (placerad under 1.5"-skärmen)
ENGRAVE_TEXT = "OLLE's MiniMix"
ENGRAVE_POS = (60.0, 12.0)                    # inre koordinater (centrerat under skärmen)
ENGRAVE_SIZE = 5.2                            # knivskarp typografi under fönstret
ENGRAVE_DEPTH = 0.4

# Ventilation + fötter
VENT_N, VENT_X0, VENT_PITCH = 11, 56.0, 6.0   # långa smala slitsar i sladdväggen
VENT_W, VENT_LEN, VENT_ZC = 2.0, 18.0, 27.0   # bredd, längd, mitthöjd (iz)
FEET = [(14.0, 14.0), (INT_X - 14.0, 14.0), (14.0, INT_Y - 14.0), (INT_X - 14.0, INT_Y - 14.0)]

# Snäpptungor (skruvlöst lock). (vägg, läge längs väggen i inre koordinater)
HOOKS = [("front", 50.0), ("front", 135.0), ("rear", 60.0), ("rear", 125.0),
         ("left", 41.0), ("right", 12.0), ("right", 64.0)]
HOOK_W = 8.0                                   # bredd 8.0 mm (var 6.0 mm, +33% fästyta)
# Profil i (v, z): v = mm inåt från väggens insida, z = mm relativt lockets undersida (nedåt negativt)
# Förstärkt rot: 2.6 mm mot locket (var 1.4 mm) med avsmalnande kil (taper) ner till 1.6 mm flexbalk
HOOK_PROFILE = [
    (0.0, 0.0),
    (2.6, 0.0),       # förstärkt rot med integrerad kil (4.6x högre böjmotstånd mot locket)
    (1.8, -3.5),      # mjuk avsmalnande profil (taper) för jämn spänningsfördelning
    (1.8, -10.0),     # solid 1.6 mm flexbalk (var 1.2 mm, 4 solida 0.4 mm perimetrar)
    (0.4, -10.0),     # fasad spets för enkel införing
    (-0.6, -9.0),     # ledande ramp vid montering
    (-0.6, -8.5),     # distinkt snäppläpp med 0.6 mm grepp i väggspåret (var 0.4 mm)
    (0.2, -7.6),      # robust snäppklack för distinkt mekaniskt klick
    (0.2, -1.0),      # 0.2 mm frigång mot väggens insida
    (0.0, -1.0)       # övergång till lockets undersida
]
# Spår i väggen (matchat för 0.6 mm läpp med 0.3 mm bottenpel)
GROOVE_PROFILE = [(0.0, -10.5), (-0.9, -9.4), (-0.9, -8.2), (0.0, -7.2)]


def c(ix, iy):
    return -EXT_X / 2 + WALL + ix, -EXT_Y / 2 + WALL + iy


def Z(iz):
    return FLOOR_THICK + iz


FRONT_Y, REAR_Y = -EXT_Y / 2, EXT_Y / 2
FRONT_PLANE = Plane(origin=(0, FRONT_Y, 0), x_dir=(1, 0, 0), z_dir=(0, -1, 0))   # lokal (x, Z)


def oled_levels():
    """(glass_top, pcb_top) i lockets lokala z (0 = undersida)."""
    glass_top = LID_THICK - BEZEL_T - OLED_TAPE_GAP
    pcb_top = glass_top - (OLED_TOTAL_T - OLED_PCB_T)
    return glass_top, pcb_top


def hook_plane(side, s):
    """Skisserplan för en tunga: lokal x = inåt från väggens insida, lokal y = Z, origo i väggens insida."""
    if side == "front":
        px, py = c(s, 0)
        n = (0, 1)
    elif side == "rear":
        px, py = c(s, INT_Y)
        n = (0, -1)
    elif side == "left":
        px, py = c(0, s)
        n = (1, 0)
    else:
        px, py = c(INT_X, s)
        n = (-1, 0)
    return Plane(origin=(px, py, 0), x_dir=(n[0], n[1], 0), z_dir=(n[1], -n[0], 0))


def _bb_inside(e, x0, x1, z0, z1, eps=0.05):
    bb = e.bounding_box()
    return (abs(bb.min.Y - FRONT_Y) < 0.01 and abs(bb.max.Y - FRONT_Y) < 0.01
            and bb.min.X >= x0 - eps and bb.max.X <= x1 + eps
            and bb.min.Z >= z0 - eps and bb.max.Z <= z1 + eps)


# --------------------------------------------------------------------------- #
# BOTTEN
# --------------------------------------------------------------------------- #
def build_base():
    with BuildPart() as base:
        with BuildSketch():
            RectangleRounded(EXT_X, EXT_Y, CORNER_R)
        extrude(amount=BASE_H)
        # faser: överkant (halva skuggspalten) och underkant (lådan "svävar")
        chamfer(base.edges().filter_by_position(Axis.Z, BASE_H - 0.01, BASE_H + 0.01), JOINT_CHAMFER)
        chamfer(base.edges().filter_by_position(Axis.Z, -0.01, 0.01), BASE_BOTTOM_CHAMFER)

        with BuildSketch(Plane.XY.offset(FLOOR_THICK)):
            RectangleRounded(INT_X, INT_Y, max(0.5, CORNER_R - WALL))
        extrude(amount=INT_Z + 5, mode=Mode.SUBTRACT)
        # falsen för locket
        with BuildSketch(Plane.XY.offset(BASE_H - REBATE_DEPTH)):
            RectangleRounded(INT_X + WALL, INT_Y + WALL, REBATE_R)
        extrude(amount=REBATE_DEPTH + 5, mode=Mode.SUBTRACT)

        # Distanshål (M2.5 underifrån) med grund försänkning
        for hx, hy in PI_HOLES:
            x, y = c(hx, hy)
            with Locations((x, y, 0)):
                Cylinder(1.35, 10, mode=Mode.SUBTRACT)
                Cylinder(2.6, 2.4, mode=Mode.SUBTRACT)        # 1.2 mm djup

        # Fötter: 4 st 12.4 mm fördjupningar för självhäftande gummifötter
        for fx, fy in FEET:
            x, y = c(fx, fy)
            with Locations((x, y, 0)):
                Cylinder(6.2, 1.6, mode=Mode.SUBTRACT)

        # Ventilation i golvet
        for i in range(6):
            x, y = c(PI_X + 22 + i * 7.0, PI_Y + 28)
            with Locations((x, y, 0)):
                Box(2.5, 28, 8, mode=Mode.SUBTRACT)
        # Ventilation högt i sladdväggen (varmluft ut): långa smala slitsar med helrunda ändar.
        # Lådan används med sladdväggen bortvänd => ventilation och sladdar på samma sida.
        for i in range(VENT_N):
            x, _ = c(VENT_X0 + i * VENT_PITCH, 0)
            with BuildSketch(FRONT_PLANE):
                with Locations((x, Z(VENT_ZC))):
                    SlotOverall(VENT_LEN, VENT_W, rotation=90)
            extrude(amount=WALL + 0.6, both=True, mode=Mode.SUBTRACT)

        # ---------------- Cubilux-vagga ("egen liten låda") ----------------
        cx_, _ = c(CR_X, 0)
        inner_half = CR_INNER_W / 2
        rail_h = 18.2
        rail_len = (BLOCK_FRONT_Y + BLOCK_L + 0.2 + STOP_T) - 0.0
        stop_in = BLOCK_FRONT_Y + BLOCK_L + 0.2
        _, y_rail_c = c(0, rail_len / 2)
        for sgn in (-1, 1):
            rx = cx_ + sgn * (inner_half + RAIL_T / 2)
            with Locations((rx, y_rail_c, FLOOR_THICK + rail_h / 2 - 0.1)):
                Box(RAIL_T, rail_len, rail_h + 0.2, mode=Mode.ADD)
        _, y_stop_c = c(0, stop_in + STOP_T / 2)
        with Locations((cx_, y_stop_c, FLOOR_THICK + rail_h / 2 - 0.1)):
            Box(CR_INNER_W + 2 * RAIL_T, STOP_T, rail_h + 0.2, mode=Mode.ADD)
        # Kabelspår i stoppväggen: öppen U-slits hela vägen upp till toppen
        # så att Cubilux kan sänkas ner rakt ovanifrån (drop-in) med kabeln
        slot_w = CABLE_D + 1.0       # 7.0 mm bred slits (god frigång för 6 mm kabel)
        slot_h = rail_h + 5.0
        with Locations((cx_, y_stop_c, FLOOR_THICK + slot_h / 2 - 0.1)):
            Box(slot_w, STOP_T * 3, slot_h, mode=Mode.SUBTRACT)
        # flexspalter => snäpptungor i sidoväggarna
        for sgn in (-1, 1):
            rx = cx_ + sgn * (inner_half + RAIL_T / 2)
            for sy in (6.2, 17.8):
                _, yy = c(0, sy)
                with Locations((rx, yy, Z(11.75))):
                    Box(RAIL_T + 0.6, 0.8, 13.5, mode=Mode.SUBTRACT)
        # snäpplist (rampad ovansida) på tungorna
        zb, zt = Z(16.8), Z(18.2)
        _, y_lip = c(0, 12.0)
        for sgn in (-1, 1):
            xf = cx_ + sgn * inner_half
            pl = Plane(origin=(xf, y_lip, 0), x_dir=(1, 0, 0), z_dir=(0, -1, 0))
            with BuildSketch(pl):
                Polygon((sgn * 0.2, zb), (sgn * 0.2, zt), (0, zt),
                        (-sgn * 0.9, zb + 0.5), (-sgn * 0.9, zb), align=None)
            extrude(amount=5.0, both=True)

        # ---------------- Portar i framväggen ----------------
        tx, _ = c(CR_X, 0)
        with BuildSketch(FRONT_PLANE):
            with Locations((tx, Z(BLOCK_H / 2))):
                RectangleRounded(TOSLINK_OPEN, TOSLINK_OPEN, 1.8)
        extrude(amount=WALL + 0.6, both=True, mode=Mode.SUBTRACT)
        ux, _ = c(USBC_X, 0)
        with BuildSketch(FRONT_PLANE):
            with Locations((ux, Z(USBC_Z))):
                SlotOverall(USBC_PLUG_W + 0.7, USBC_PLUG_H + 0.7)
        extrude(amount=WALL + 0.6, both=True, mode=Mode.SUBTRACT)

        # ---------------- Spår för lockets snäpptungor ----------------
        for side, s in HOOKS:
            pl = hook_plane(side, s)
            with BuildSketch(pl):
                Polygon(*[(v, BASE_H + z) for v, z in GROOVE_PROFILE], align=None)
            extrude(amount=HOOK_W / 2 + 0.6, both=True, mode=Mode.SUBTRACT)

        # ---------------- Fas runt portarna (utsidan) ----------------
        zt_c = Z(BLOCK_H / 2)
        uz_c = Z(USBC_Z)
        for (x0, x1, z0, z1) in (
                (tx - TOSLINK_OPEN / 2, tx + TOSLINK_OPEN / 2, zt_c - TOSLINK_OPEN / 2, zt_c + TOSLINK_OPEN / 2),
                (ux - (USBC_PLUG_W + 0.7) / 2, ux + (USBC_PLUG_W + 0.7) / 2,
                 uz_c - (USBC_PLUG_H + 0.7) / 2, uz_c + (USBC_PLUG_H + 0.7) / 2)):
            sel = [e for e in base.edges() if _bb_inside(e, x0, x1, z0, z1)]
            if sel:
                try:
                    chamfer(sel, PORT_CHAMFER)
                except Exception as exc:                       # pragma: no cover
                    print("VARNING: kunde inte fasa porthål:", exc)
    return base.part


# --------------------------------------------------------------------------- #
# LOCK
# --------------------------------------------------------------------------- #
def build_lid():
    pcb_gx, pcb_gy = c(OG_X, OG_Y)
    pcb_cy = pcb_gy                                           # glaset är exakt centrerat på kretskortet i MC01506
    win_gx, win_gy = pcb_gx, pcb_gy + WINDOW_OFFSET_Y         # fönstret förskjutet mot överkant (2.82 mm)
    r_out = max(1.0, REBATE_R - LIP_CLEAR)
    glass_top, pcb_top = oled_levels()
    with BuildPart() as lid:
        with BuildSketch():
            RectangleRounded(EXT_X, EXT_Y, CORNER_R)
        extrude(amount=LID_THICK)
        # faser: överkant + underkant (andra halvan av skuggspalten)
        chamfer(lid.edges().filter_by_position(Axis.Z, LID_THICK - 0.01, LID_THICK + 0.01), LID_TOP_CHAMFER)
        chamfer(lid.edges().filter_by_position(Axis.Z, -0.01, 0.01), JOINT_CHAMFER)

        # styrring: RING (inte platta) som faller ner i falsen
        with BuildSketch(Plane.XY.offset(-RING_H)):
            RectangleRounded(INT_X + WALL - 2 * LIP_CLEAR, INT_Y + WALL - 2 * LIP_CLEAR, r_out)
            RectangleRounded(INT_X + WALL - 2 * LIP_CLEAR - 2 * RING_T,
                             INT_Y + WALL - 2 * LIP_CLEAR - 2 * RING_T, max(0.5, r_out - RING_T),
                             mode=Mode.SUBTRACT)
        extrude(amount=RING_H)

        # snäpptungor (skruvlöst lock)
        for side, s in HOOKS:
            pl = hook_plane(side, s)
            with BuildSketch(pl):
                Polygon(*HOOK_PROFILE, align=None)
            extrude(amount=HOOK_W / 2, both=True)

        # stödhylsor ovanpå de 4 distanserna
        for hx, hy in PI_HOLES:
            x, y = c(hx, hy)
            with Locations((x, y, -BOSS_H / 2)):
                Cylinder(3.2, BOSS_H, mode=Mode.ADD)

        # OLED: lokaliseringsram under locket (för 1.5" PCB)
        with BuildSketch(Plane.XY.offset(-1.0)):
            with Locations((pcb_gx, pcb_cy)):
                RectangleRounded(PCB_W + 2.4, PCB_H + 2.4, 1.0)
                RectangleRounded(PCB_W + 0.8, PCB_H + 0.8, 0.6, mode=Mode.SUBTRACT)
        extrude(amount=1.0)

        # BLINDA fickor för de 4 hanpinnarna (inga hål genom locket)
        for hx, hy in PI_HOLES:
            x, y = c(hx, hy)
            with Locations((x, y, (STUD_POCKET_DEPTH - BOSS_H) / 2)):
                Cylinder(STUD_POCKET_R, STUD_POCKET_DEPTH + BOSS_H, mode=Mode.SUBTRACT)

        # OLED: PCB-ficka (rymlig med 0.8 mm spel)
        pcb_pocket_d = pcb_top + 0.1
        with Locations((pcb_gx, pcb_cy, pcb_pocket_d / 2)):
            Box(PCB_W + 0.8, PCB_H + 0.8, pcb_pocket_d, mode=Mode.SUBTRACT)

        # OLED: Glasficka (generös med +0.8 mm bredd och +1.2 mm höjd)
        glass_depth = LID_THICK - BEZEL_T
        with Locations((pcb_gx, pcb_gy, glass_depth / 2)):
            Box(GLASS_W + 0.8, GLASS_H + 1.2, glass_depth, mode=Mode.SUBTRACT)

        # OLED: Titthål för 128x128 kvadratiska fönstret
        with Locations((win_gx, win_gy, 0)):
            Box(WINDOW_W, WINDOW_H, 20, mode=Mode.SUBTRACT)

        # OLED: FLEXKABEL-AVLASTNING i nederkant (10.31 mm cutout på PCB)
        # Urfräsning så flatkabeln hänger helt fritt i luften utan något mekaniskt tryck
        flex_y = pcb_cy - PCB_H / 2 + 3.5
        with Locations((pcb_gx, flex_y, glass_depth / 2)):
            Box(15.0, 9.0, glass_depth + 0.2, mode=Mode.SUBTRACT)

        # OLED: LÖDSPETS- OCH PINN-AVLASTNING i överkant
        pin_y = pcb_cy + PCB_H / 2 - 2.0
        with Locations((pcb_gx, pin_y, glass_depth / 2)):
            Box(15.0, 6.0, glass_depth + 0.2, mode=Mode.SUBTRACT)

        # nedsänkt fönsterram (bezel sänkt 0.4 mm runt kvadratiska fönstret)
        with BuildSketch(Plane.XY.offset(LID_THICK - BEZEL_RECESS)):
            with Locations((win_gx, win_gy)):
                RectangleRounded(WINDOW_W + 2 * BEZEL_RECESS_MARGIN, WINDOW_H + 2 * BEZEL_RECESS_MARGIN, 2.0)
        extrude(amount=BEZEL_RECESS + 0.1, mode=Mode.SUBTRACT)

        # knappar
        bx, by1 = c(BTN_X, BTN_Y1)
        _, by2 = c(BTN_X, BTN_Y2)
        for by in (by1, by2):
            with Locations((bx, by, 0)):
                Cylinder(6.1, 20, mode=Mode.SUBTRACT)

        # encoder & nedsänkt rattbrunn (M3x6 försänkta skruvar)
        ex, ey = c(ENC_X, ENC_Y)
        well_bottom_z = LID_THICK - KNOB_WELL_DEPTH            # 2.4 mm i locket
        enc_face_z = well_bottom_z - ENC_MOUNT_T              # 0.4 mm i locket (2.0 mm fästfläns)
        # 1. Nedsänkt brunn för ratten från lockets ovansida
        with Locations((ex, ey, LID_THICK - KNOB_WELL_DEPTH / 2)):
            Cylinder(KNOB_WELL_R, KNOB_WELL_DEPTH + 0.01, mode=Mode.SUBTRACT)
        # 2. Ficka under locket upp till fästytan
        with Locations((ex, ey, enc_face_z / 2)):
            Cylinder(19.8, enc_face_z + 0.01, mode=Mode.SUBTRACT)
        # 3. Centrumhål för encoderns 20 mm krage
        with Locations((ex, ey, 0)):
            Cylinder(10.3, 20, mode=Mode.SUBTRACT)
        # 4. 6 st M3-hål med 90° försänkning från brunnens botten (optimerade för M3x6)
        cone_h = 1.65                                         # DIN 7991 M3 försänkt huvud
        cone_zc = well_bottom_z - cone_h / 2                  # 1.575 mm i locket
        for p in (0.0, 120.0, 240.0):
            for ang in (p, p + ENC_ALPHA):
                sx = ex + ENC_PCD * math.cos(math.radians(ang))
                sy = ey + ENC_PCD * math.sin(math.radians(ang))
                with Locations((sx, sy, 0)):
                    Cylinder(1.65, 20, mode=Mode.SUBTRACT)
                with Locations((sx, sy, cone_zc)):
                    Cone(bottom_radius=1.65, top_radius=3.3, height=cone_h, mode=Mode.SUBTRACT)

        # gravyr (nedsänkt, samma färg). Vänd 180° => läsbar från användarsidan (bakre kanten)
        tx_, ty_ = c(*ENGRAVE_POS)
        with BuildSketch(Plane.XY.offset(LID_THICK - ENGRAVE_DEPTH)):
            with Locations((tx_, ty_)):
                Text(ENGRAVE_TEXT, font_size=ENGRAVE_SIZE, font_style=FontStyle.BOLD, rotation=180)
        extrude(amount=ENGRAVE_DEPTH + 0.1, mode=Mode.SUBTRACT)
    return lid.part


# --------------------------------------------------------------------------- #
# KOMPONENTER (skuggmodeller för kollisionskontroll) - i monterade koordinater
# --------------------------------------------------------------------------- #
def ibox(x0, x1, y0, y1, z0, z1):
    ax, ay = c(x0, y0)
    bx, by = c(x1, y1)
    return Pos((ax + bx) / 2, (ay + by) / 2, Z((z0 + z1) / 2)) * Box(x1 - x0, y1 - y0, z1 - z0)


def icyl(x, y, z0, z1, r, rot=(0, 0, 0)):
    ax, ay = c(x, y)
    return Pos(ax, ay, Z((z0 + z1) / 2)) * Cylinder(r, z1 - z0, rotation=rot)


def build_ghosts():
    g = {}
    pcb_gx, pcb_gy = c(OG_X, OG_Y)
    pcb_cy = pcb_gy                                           # centrerat på kretskortet
    lid_z = BASE_H
    g["Pi_PCB"] = ibox(PI_X, PI_X + 85, PI_Y, PI_Y + 56, PI_BOTTOM, PI_BOTTOM + PI_T)
    g["Pi_USB_Eth"] = ibox(PI_X + 68, PI_X + 85.8, PI_Y, PI_Y + 56, PI_BOTTOM + PI_T, PI_BOTTOM + PI_T + 15.6)
    g["HAT_PCB"] = ibox(PI_X, PI_X + 65, PI_Y, PI_Y + 56, HAT_BOTTOM, HAT_BOTTOM + HAT_T)
    g["HAT_plintar"] = ibox(PI_X + 7.5, PI_X + 57, PI_Y + 6, PI_Y + 50, HAT_BOTTOM + HAT_T, STANDOFF_H)
    for i, (hx, hy) in enumerate(PI_HOLES):
        g[f"Distans{i+1}_nedre"] = icyl(hx, hy, 0, PI_BOTTOM, 2.5)
        g[f"Distans{i+1}_mitt"] = icyl(hx, hy, PI_BOTTOM + PI_T, HAT_BOTTOM, 2.5)
        g[f"Distans{i+1}_ovre"] = icyl(hx, hy, HAT_BOTTOM + HAT_T, STANDOFF_H, 2.5)
        g[f"Pinne{i+1}"] = icyl(hx, hy, STANDOFF_H, STANDOFF_H + STUD_L, 1.25)
    # Cubilux TOSLINK-block + kabel
    blk = ibox(CR_X - BLOCK_W / 2, CR_X + BLOCK_W / 2, BLOCK_FRONT_Y, BLOCK_FRONT_Y + BLOCK_L, 0, BLOCK_H)
    g["Cubilux_TOSLINK"] = fillet(blk.edges().filter_by(Axis.Y), 2.0)      # blocket är rundat 2 mm
    cxx, cyy = c(CR_X, BLOCK_FRONT_Y + BLOCK_L + 8)
    g["Cubilux_kabel"] = Pos(cxx, cyy, Z(CABLE_Z)) * Cylinder(CABLE_D / 2, 16, rotation=(90, 0, 0))
    # Cubilux USB-block (ANTAGANDE: ~28 mm utanför Pi:ns högerkant, 16 bred, 14 hög)
    g["Cubilux_USB_ANTAGET"] = ibox(PI_X + 85.8, PI_X + 85.8 + 22, PI_Y + 1, PI_Y + 17,
                                     PI_BOTTOM + PI_T + 0.4, PI_BOTTOM + PI_T + 14.4)
    # Knappar: huvud ovan lock, kropp 19 mm ner, mutter under locket
    for i, by in enumerate((BTN_Y1, BTN_Y2)):
        g[f"Knapp{i+1}_kropp"] = Pos(*c(BTN_X, by), lid_z + LID_THICK - 19.0 / 2 + 1.5) * Cylinder(5.9, 19.0 + 3.0)
        g[f"Knapp{i+1}_mutter"] = Pos(*c(BTN_X, by), lid_z - 1.5) * Cylinder(8.1, 3.0)
        g[f"Knapp{i+1}_huvud"] = Pos(*c(BTN_X, by), lid_z + LID_THICK + 1.0) * Cylinder(7.25, 2.0)
    # Encoder & Ratt (nedsänkt i locket, M3x6 skruvar i brunnens botten)
    ex, ey = c(ENC_X, ENC_Y)
    enc_face = lid_z + (LID_THICK - KNOB_WELL_DEPTH - ENC_MOUNT_T)   # monteringsyta = lid_z + 0.4
    g["Encoder_kropp"] = Pos(ex, ey, enc_face - 34.0 / 2) * Cylinder(19.25, 34.0)
    g["Encoder_krage"] = Pos(ex, ey, enc_face + 2.5) * Cylinder(10.0, 5.0)
    g["Encoder_axel"] = Pos(ex, ey, enc_face + 5.0 + 8.0) * Cylinder(3.0, 16.0)
    # Ratten sänks ner 2.1 mm under lockets ovansida (0.5 mm frigång till brunnens botten)
    knob_bottom = lid_z + (LID_THICK - KNOB_WELL_DEPTH) + 0.5        # lid_z + 2.9
    g["Ratt"] = Pos(ex, ey, knob_bottom + KNOB_H / 2) * Cylinder(KNOB_R, KNOB_H)
    # OLED-modul (1.5" SH1107 128x128)
    glass_top, pcb_top = oled_levels()
    g["OLED_PCB"] = Pos(pcb_gx, pcb_cy, lid_z + pcb_top - OLED_PCB_T / 2) * Box(PCB_W, PCB_H, OLED_PCB_T)
    g["OLED_glas"] = Pos(pcb_gx, pcb_gy, lid_z + (pcb_top + glass_top) / 2) * Box(GLASS_W, GLASS_H, glass_top - pcb_top)
    g["OLED_lodspets"] = Pos(pcb_gx, pcb_cy + PCB_H / 2 - 1.5, lid_z + pcb_top + 0.6) * Box(12.0, 2.0, 1.2)
    g["OLED_pinhus"] = Pos(pcb_gx, pcb_cy + PCB_H / 2 - 1.5, lid_z + pcb_top - OLED_PCB_T - 4.0) * Box(12.0, 2.6, 8.0)
    return g


def overlap(a, b):
    try:
        r = a & b
        if r is None:
            return 0.0
        if hasattr(r, "volume"):
            return float(r.volume)
        return sum(s.volume for s in r)
    except Exception:
        return float("nan")


def build():
    base = build_base()
    lid = build_lid().moved(Location((0, 0, BASE_H)))
    return base, lid, build_ghosts()


if __name__ == "__main__":
    os.makedirs(CAD_DIR, exist_ok=True)
    base, lid, ghosts = build()
    print(f"Yttermått: {EXT_X:.1f} x {EXT_Y:.1f} x {EXT_Z:.1f} mm")
    lid_local = lid.moved(Location((0, 0, -BASE_H)))
    export_step(base, os.path.join(CAD_DIR, "od11_minimix_base.step"))
    export_stl(base, os.path.join(CAD_DIR, "od11_minimix_base.stl"), tolerance=0.01, angular_tolerance=0.1)
    export_step(lid_local, os.path.join(CAD_DIR, "od11_minimix_lid.step"))
    export_stl(lid_local, os.path.join(CAD_DIR, "od11_minimix_lid.stl"), tolerance=0.01, angular_tolerance=0.1)
    export_step(Compound([base, lid]), os.path.join(CAD_DIR, "od11_minimix_assembly.step"))

    colors = {"Pi": (0.1, 0.5, 0.2), "HAT": (0.1, 0.2, 0.7), "Distans": (0.85, 0.65, 0.2), "Pinne": (0.85, 0.65, 0.2),
              "Cubilux": (0.15, 0.15, 0.15), "Knapp": (0.85, 0.85, 0.9),
              "Encoder": (0.25, 0.25, 0.28), "Ratt": (0.7, 0.7, 0.72), "OLED": (0.1, 0.1, 0.35)}
    parts = [base, lid]
    base.label, lid.label = "Botten", "Lock"
    base.color, lid.color = Color(0.12, 0.12, 0.12), Color(0.16, 0.16, 0.16)
    for name, shp in ghosts.items():
        shp.label = name
        for k, col in colors.items():
            if name.startswith(k):
                shp.color = Color(*col)
        parts.append(shp)
    export_step(Compound(children=parts, label="OD-11 Minimix"),
                os.path.join(CAD_DIR, "od11_minimix_assembly_with_components.step"))
    print("Filer exporterade.")
