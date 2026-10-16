#!/usr/bin/env python3
"""
Parametric CAD generator for OD-11 Minimix enclosure  (rev 2 - efter fullständig granskning)

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
LID_THICK = 3.5            # 3.5 => hanpinnens topp (6.0 - 2.5 stöd) hamnar exakt i nivå med lockets ovansida
CORNER_R = 4.0

INT_X, INT_Y, INT_Z = 156.0, 74.0, 39.5
EXT_X, EXT_Y = INT_X + 2 * WALL, INT_Y + 2 * WALL
BASE_H = FLOOR_THICK + INT_Z                  # bottenlådans höjd = lockets underkant
EXT_Z = BASE_H + LID_THICK

# Lock/botten-fog: falsen i botten, RING (ej platta!) under locket
REBATE_DEPTH = 1.6
REBATE_R = CORNER_R - WALL / 2
LIP_CLEAR = 0.25
RING_H = 1.4
RING_T = 1.2

# Distanspelare / Pi
STANDOFF_H = 37.0
STUD_L = 6.0
BOSS_H = INT_Z - STANDOFF_H                   # 2.5 mm stödhylsor under locket
PI_X, PI_Y = 21.0, 3.0
PI_BOTTOM = 10.0                              # <- BEKRÄFTA: Pi-kortets undersida över golv
PI_T = 1.6
PI_HOLES = [(PI_X + 3.5, PI_Y + 3.5), (PI_X + 61.5, PI_Y + 3.5),
            (PI_X + 3.5, PI_Y + 52.5), (PI_X + 61.5, PI_Y + 52.5)]
HAT_BOTTOM = PI_BOTTOM + PI_T + 12.0          # <- BEKRÄFTA
HAT_T = 1.6
NUT_POCKET_D, NUT_POCKET_DEPTH = 7.4, 2.2     # M2.5-mutter (5.0 nyckelvidd, 2.0 tjock)

# Cubilux TOSLINK-block + klickvagga
CR_X = 10.6
BLOCK_W, BLOCK_H, BLOCK_L = 16.4, 16.4, 24.0
CR_INNER_W = 16.6
RAIL_T = 1.4
STOP_T = 1.8
BLOCK_FRONT_Y = -WALL + 0.3                   # blockets framsida 0.3 mm innanför ytterväggen
CABLE_D, CABLE_Z = 6.0, 3.0

# USB-C (ström) - helrunda kortsidor
USBC_PLUG_W, USBC_PLUG_H = 10.7, 6.6
USBC_X = PI_X + 11.2                          # Pi 4: USB-C 11.2 mm från kortets kant
USBC_Z = PI_BOTTOM + PI_T + 1.6               # mitt på hylsan (3.2 mm hög)

# Knappar (M12)
BTN_X, BTN_Y1, BTN_Y2 = 11.0, 28.0, 54.0

# OLED (1.3")
OG_X, OG_Y = 54.0, 50.5                       # glasets mitt
GLASS_W, GLASS_H = 34.4, 18.6
WINDOW_W, WINDOW_H = 30.0, 15.4
PCB_W, PCB_H = 36.0, 34.0                     # <- BEKRÄFTA (antagande)
GLASS_OFFSET_Y = 3.7                          # glasmitt ovan PCB-mitt mot pinnkanten <- BEKRÄFTA
OLED_TOTAL_T, OLED_PCB_T = 3.4, 1.2
BEZEL_T = 1.0

# Encoder
ENC_X, ENC_Y = 132.0, 40.0                    # bakom Cubilux USB-delen (användarens beskrivning)
ENC_PCD = 14.0                                # radie (PCD 28)
ENC_ALPHA = 35.14

# Ventilation + fötter
FEET = [(9.0, 9.0), (147.0, 9.0), (9.0, 65.0), (147.0, 65.0)]


def c(ix, iy):
    return -EXT_X / 2 + WALL + ix, -EXT_Y / 2 + WALL + iy


def Z(iz):
    return FLOOR_THICK + iz


FRONT_Y, REAR_Y = -EXT_Y / 2, EXT_Y / 2
FRONT_PLANE = Plane(origin=(0, FRONT_Y, 0), x_dir=(1, 0, 0), z_dir=(0, -1, 0))   # lokal (x, Z)


# --------------------------------------------------------------------------- #
# BOTTEN
# --------------------------------------------------------------------------- #
def build_base():
    with BuildPart() as base:
        with BuildSketch():
            RectangleRounded(EXT_X, EXT_Y, CORNER_R)
        extrude(amount=BASE_H)
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
        # Ventilation högt i sladdväggen (varmluft ut). Lådan används med sladdväggen
        # bortvänd från användaren => ventilation och sladdar hamnar på samma sida.
        # Placeras till höger om USB-C-hålet så de aldrig skär portarna.
        for i in range(10):
            x, _ = c(46 + i * 6.0, 0)
            with Locations((x, FRONT_Y, Z(30))):
                Box(2.4, WALL * 3, 12, mode=Mode.SUBTRACT)

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
                RectangleRounded(CR_INNER_W, 16.6, 2.0)
        extrude(amount=WALL + 0.6, both=True, mode=Mode.SUBTRACT)
        ux, _ = c(USBC_X, 0)
        with BuildSketch(FRONT_PLANE):
            with Locations((ux, Z(USBC_Z))):
                SlotOverall(USBC_PLUG_W + 0.7, USBC_PLUG_H + 0.7)
        extrude(amount=WALL + 0.6, both=True, mode=Mode.SUBTRACT)
    return base.part


# --------------------------------------------------------------------------- #
# LOCK
# --------------------------------------------------------------------------- #
def build_lid():
    pcb_gx, pcb_gy = c(OG_X, OG_Y)
    pcb_cy = pcb_gy - GLASS_OFFSET_Y
    r_out = max(1.0, REBATE_R - LIP_CLEAR)
    with BuildPart() as lid:
        with BuildSketch():
            RectangleRounded(EXT_X, EXT_Y, CORNER_R)
        extrude(amount=LID_THICK)
        # styrring: RING (inte platta) som faller ner i falsen
        with BuildSketch(Plane.XY.offset(-RING_H)):
            RectangleRounded(INT_X + WALL - 2 * LIP_CLEAR, INT_Y + WALL - 2 * LIP_CLEAR, r_out)
            RectangleRounded(INT_X + WALL - 2 * LIP_CLEAR - 2 * RING_T,
                             INT_Y + WALL - 2 * LIP_CLEAR - 2 * RING_T, max(0.5, r_out - RING_T),
                             mode=Mode.SUBTRACT)
        extrude(amount=RING_H)

        # stödhylsor ovanpå de 4 distanserna
        for hx, hy in PI_HOLES:
            x, y = c(hx, hy)
            with Locations((x, y, -BOSS_H / 2)):
                Cylinder(3.2, BOSS_H, mode=Mode.ADD)

        # OLED: lokaliseringsram under locket
        with BuildSketch(Plane.XY.offset(-1.0)):
            with Locations((pcb_gx, pcb_cy)):
                RectangleRounded(PCB_W + 2.4, PCB_H + 2.4, 1.0)
                RectangleRounded(PCB_W + 0.4, PCB_H + 0.4, 0.6, mode=Mode.SUBTRACT)
        extrude(amount=1.0)

        # genomgående hål + mutterfickor för de 4 hanpinnarna
        for hx, hy in PI_HOLES:
            x, y = c(hx, hy)
            with Locations((x, y, 0)):
                Cylinder(1.45, 20, mode=Mode.SUBTRACT)
            with Locations((x, y, LID_THICK - NUT_POCKET_DEPTH / 2)):
                Cylinder(NUT_POCKET_D / 2, NUT_POCKET_DEPTH + 0.01, mode=Mode.SUBTRACT)

        # OLED: PCB-ficka, glasficka, fönster, reliefspår för pinnarnas lödspetsar
        with Locations((pcb_gx, pcb_cy, 0.3)):
            Box(PCB_W + 0.4, PCB_H + 0.4, 0.6, mode=Mode.SUBTRACT)
        glass_depth = LID_THICK - BEZEL_T
        with Locations((pcb_gx, pcb_gy, glass_depth / 2)):
            Box(GLASS_W + 0.6, GLASS_H + 0.6, glass_depth, mode=Mode.SUBTRACT)
        with Locations((pcb_gx, pcb_gy, 0)):
            Box(WINDOW_W, WINDOW_H, 20, mode=Mode.SUBTRACT)
        pcb_rear = pcb_cy + PCB_H / 2
        with Locations((pcb_gx, pcb_rear - 2.4, 1.3)):
            Box(12.0, 3.2, 1.6, mode=Mode.SUBTRACT)

        # knappar
        bx, by1 = c(BTN_X, BTN_Y1)
        _, by2 = c(BTN_X, BTN_Y2)
        for by in (by1, by2):
            with Locations((bx, by, 0)):
                Cylinder(6.1, 20, mode=Mode.SUBTRACT)

        # encoder
        ex, ey = c(ENC_X, ENC_Y)
        with Locations((ex, ey, 0)):
            Cylinder(10.3, 20, mode=Mode.SUBTRACT)
            for p in (0.0, 120.0, 240.0):
                for ang in (p, p + ENC_ALPHA):
                    sx = ENC_PCD * math.cos(math.radians(ang))
                    sy = ENC_PCD * math.sin(math.radians(ang))
                    with Locations((sx, sy, 0)):
                        Cylinder(1.65, 20, mode=Mode.SUBTRACT)
                    with Locations((sx, sy, LID_THICK - 0.825)):
                        Cone(bottom_radius=1.65, top_radius=3.3, height=1.65, mode=Mode.SUBTRACT)
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
    pcb_cy = pcb_gy - GLASS_OFFSET_Y
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
        x, y = c(hx, hy)
        g[f"Mutter{i+1}"] = Pos(x, y, lid_z + LID_THICK - NUT_POCKET_DEPTH + 1.0) * Cylinder(2.9, 2.0)
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
    # Encoder
    ex, ey = c(ENC_X, ENC_Y)
    g["Encoder_kropp"] = Pos(ex, ey, lid_z - 34.0 / 2) * Cylinder(19.25, 34.0)
    g["Encoder_krage"] = Pos(ex, ey, lid_z + 2.5) * Cylinder(10.0, 5.0)
    g["Encoder_axel"] = Pos(ex, ey, lid_z + 5 + 8) * Cylinder(3.0, 16.0)
    g["Ratt"] = Pos(ex, ey, lid_z + 5 + 1.0 + 8) * Cylinder(17.5, 16.0)
    # OLED-modul
    glass_top = LID_THICK - BEZEL_T - 0.1
    pcb_top = glass_top - (OLED_TOTAL_T - OLED_PCB_T)
    g["OLED_PCB"] = Pos(pcb_gx, pcb_cy, lid_z + pcb_top - OLED_PCB_T / 2) * Box(PCB_W, PCB_H, OLED_PCB_T)
    g["OLED_glas"] = Pos(pcb_gx, pcb_gy, lid_z + (pcb_top + glass_top) / 2) * Box(GLASS_W, GLASS_H, glass_top - pcb_top)
    g["OLED_lodspets"] = Pos(pcb_gx, pcb_cy + PCB_H / 2 - 2.4, lid_z + pcb_top + 0.6) * Box(10.5, 1.2, 1.2)
    g["OLED_pinhus"] = Pos(pcb_gx, pcb_cy + PCB_H / 2 - 2.4, lid_z + pcb_top - OLED_PCB_T - 4.0) * Box(10.5, 2.6, 8.0)
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
              "Mutter": (0.8, 0.8, 0.8), "Cubilux": (0.15, 0.15, 0.15), "Knapp": (0.85, 0.85, 0.9),
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
