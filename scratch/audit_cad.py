#!/usr/bin/env python3
"""Automatisk granskning av lådan: geometritester + kollisionsmatris mellan alla komponenter."""
import itertools
import math
from build123d import *
import generate_cad as CAD

base, lid, ghosts = CAD.build()
ok_all = True


def check(name, cond):
    global ok_all
    ok_all &= bool(cond)
    print(("  OK   " if cond else "  FEL  ") + name)


V = Vector
print("== Portar i framväggen (ska vara öppna fram, solida bak) ==")
tx, _ = CAD.c(CAD.CR_X, 0)
ux, _ = CAD.c(CAD.USBC_X, 0)
for nm, x, z in (("TOSLINK", tx, CAD.Z(CAD.BLOCK_H / 2)), ("USB-C", ux, CAD.Z(CAD.USBC_Z))):
    check(f"{nm}: hål öppet i framväggen", not base.is_inside(V(x, CAD.FRONT_Y + 1.2, z)))
    check(f"{nm}: bakväggen orörd", base.is_inside(V(x, CAD.REAR_Y - 1.2, z)))
check("USB-C: hålets underkant under pluggen", not base.is_inside(V(ux, CAD.FRONT_Y + 1.2, CAD.Z(CAD.USBC_Z - CAD.USBC_PLUG_H / 2 - 0.1))))
check("USB-C: golvet under hålet intakt", base.is_inside(V(ux, CAD.FRONT_Y + 1.2, CAD.Z(CAD.USBC_Z - 6.0))))
check("TOSLINK-hörn rundat (hörnpunkt är solid)", base.is_inside(V(tx + 8.25, CAD.FRONT_Y + 1.2, CAD.Z(0.1) + 0.05)))

print("== Ventilation (ska sitta på sladdväggen, användarsidan solid) ==")
vx0, _ = CAD.c(CAD.VENT_X0, 0)
vx_last, _ = CAD.c(CAD.VENT_X0 + (CAD.VENT_N - 1) * CAD.VENT_PITCH, 0)
for nm, vx in (("första", vx0), ("sista", vx_last)):
    check(f"vent {nm}: öppen i sladdväggen", not base.is_inside(V(vx, CAD.FRONT_Y + 1.2, CAD.Z(CAD.VENT_ZC))))
    check(f"vent {nm}: användarsidans vägg solid", base.is_inside(V(vx, CAD.REAR_Y - 1.2, CAD.Z(CAD.VENT_ZC))))
check("vent: solid vägg mellan två springor", base.is_inside(V((vx0 + CAD.c(CAD.VENT_X0 + CAD.VENT_PITCH, 0)[0]) / 2, CAD.FRONT_Y + 1.2, CAD.Z(CAD.VENT_ZC))))
check("vent: USB-C-hålets sida är fri från springor (x-avstånd >= 3 mm)", vx0 - 1.0 - (ux + (CAD.USBC_PLUG_W + 0.7) / 2) >= 3.0)

print("== Cubilux-vagga ==")
cx_, _ = CAD.c(CAD.CR_X, 0)
check("vagga: block-utrymme fritt", not base.is_inside(V(cx_, CAD.c(0, 10)[1], CAD.Z(8))))
check("vagga: sidovägg solid", base.is_inside(V(cx_ + 8.3 + 0.7, CAD.c(0, 3)[1], CAD.Z(8))))
check("vagga: stoppvägg solid bredvid spåret", base.is_inside(V(cx_ + 6.0, CAD.c(0, CAD.BLOCK_FRONT_Y + CAD.BLOCK_L + 1.1)[1], CAD.Z(8))))
check("vagga: kabelspår öppet i botten", not base.is_inside(V(cx_, CAD.c(0, CAD.BLOCK_FRONT_Y + CAD.BLOCK_L + 1.1)[1], CAD.Z(3.0))))
check("vagga: kabelspår öppet hela vägen till toppen (drop-in)", not base.is_inside(V(cx_, CAD.c(0, CAD.BLOCK_FRONT_Y + CAD.BLOCK_L + 1.1)[1], CAD.Z(15.0))))

print("== Lock (Skruvlöst med snäpp + slät ovansida) ==")
ll = lid.moved(Location((0, 0, -CAD.BASE_H)))
check("undersidan i mitten är ÖPPEN (ingen solid platta)", not ll.is_inside(V(0, 0, -0.7)))
check("styrringen finns vid kanten", ll.is_inside(V(CAD.INT_X / 2 + 0.6, 0, -0.7)))
gx, gy = CAD.c(CAD.OG_X, CAD.OG_Y)
pcy = gy - CAD.GLASS_OFFSET_Y
check("OLED: fönster öppet rakt igenom", not ll.is_inside(V(gx, gy, 4.0)) and not ll.is_inside(V(gx, gy, 1.0)))
check("OLED: glasficka öppen nära glasets hörn", not ll.is_inside(V(gx + 16.5, gy + 8.5, 2.0)))
check("OLED: ramen runt fönstret är solid (bezel)", ll.is_inside(V(gx + 16.0, gy, 4.1)))
check("OLED: PCB-ficka nåbar underifrån", not ll.is_inside(V(gx + 17.5, pcy - 14.0, 0.5)) and not ll.is_inside(V(gx + 17.5, pcy - 14.0, -0.5)))
for i, (hx, hy) in enumerate(CAD.PI_HOLES):
    x, y = CAD.c(hx, hy)
    check(f"distans {i+1}: blind ficka öppen underifrån + stödhylsa solid",
          (not ll.is_inside(V(x, y, 0.5))) and ll.is_inside(V(x + 2.4, y, -1.0)))
    check(f"distans {i+1}: lockets ovansida HELT SLÄT & SOLID (skruvlöst, inga hål)",
          ll.is_inside(V(x, y, CAD.LID_THICK - 0.5)))
ex, ey = CAD.c(CAD.ENC_X, CAD.ENC_Y)
check("encoder: kragehål öppet", not ll.is_inside(V(ex, ey, 1.0)))
check("encoder: rattbrunn öppen upptill", not ll.is_inside(V(ex + 16.0, ey, 3.5)))
check("encoder: brunnens bottenfläns solid mellan hål", ll.is_inside(V(ex + 16.5, ey, 1.5)))
check("encoder: M3 försänkningskon i brunnens botten öppen", not ll.is_inside(V(ex + 14.0, ey, 1.5)))
check("encoder: monteringsficka under locket öppen", not ll.is_inside(V(ex + 16.0, ey, 0.1)))

print("== Kollisionsmatris (komponenter mot låda och varandra, mm³) ==")
parts = {"BOTTEN": base, "LOCK": lid}
skip_same = ("Knapp", "Encoder", "OLED", "Cubilux", "Pi", "HAT")
allowed = {frozenset(("Ratt", "Encoder_axel")), frozenset(("Ratt", "Encoder_krage"))}
found = []
for gname, gshape in ghosts.items():
    for pname, pshape in parts.items():
        v = CAD.overlap(gshape, pshape)
        if v > 0.5 or math.isnan(v):
            found.append((gname, pname, v))
names = list(ghosts)
for a, b in itertools.combinations(names, 2):
    if frozenset((a, b)) in allowed:
        continue
    if any(a.startswith(p) and b.startswith(p) for p in skip_same):
        continue
    if {a[:5], b[:5]} == {"Mutte", "Pinne"}:
        continue
    v = CAD.overlap(ghosts[a], ghosts[b])
    if v > 0.5 or math.isnan(v):
        found.append((a, b, v))
if not found:
    print("  inga kollisioner")
for a, b, v in found:
    print(f"  KOLLISION {a:24s} x {b:24s} {v:9.1f} mm³")
print("== Kontroll av testmetoden (ska HITTA en avsiktlig kollision) ==")
probe = Pos(0, -20, CAD.BASE_H + 1.0) * Cylinder(5, 6)
check("testmetoden detekterar en cylinder genom locket", CAD.overlap(probe, lid) > 10)

print("== Minsta avstånd (mm) mellan nyckelpar ==")
def dist(a, b):
    sa = ghosts.get(a, parts.get(a)); sb = ghosts.get(b, parts.get(b))
    return sa.distance_to(sb)
for a, b, label in [
    ("OLED_PCB", "HAT_plintar", "OLED-kort  <-> HAT-plintar (övre kabelnivå 37.0)"),
    ("OLED_pinhus", "BOTTEN", "OLED-pinhus <-> bottenlådan (bakvägg/golv)"),
    ("OLED_pinhus", "HAT_PCB", "OLED-pinhus <-> HAT-kort"),
    ("Encoder_kropp", "BOTTEN", "Encoder-kropp <-> låda (golv/vägg)"),
    ("Encoder_kropp", "Cubilux_USB_ANTAGET", "Encoder <-> Cubilux USB-block (ANTAGET mått)"),
    ("Encoder_kropp", "Pi_USB_Eth", "Encoder <-> Pi USB/Ethernet"),
    ("Knapp1_mutter", "Cubilux_TOSLINK", "Knapp 1 mutter <-> Cubilux-block"),
    ("Knapp1_kropp", "Pi_PCB", "Knapp 1 <-> Pi-kort"),
    ("Cubilux_TOSLINK", "Pi_PCB", "Cubilux-block <-> Pi-kort (SD-kortsidan)"),
    ("Ratt", "LOCK", "Ratt <-> lockets ovansida"),
    ("Knapp2_kropp", "HAT_PCB", "Knapp 2 <-> HAT"),
]:
    print(f"  {dist(a, b):6.2f}  {label}")

print("\nRESULTAT:", "ALLA GEOMETRITESTER OK" if ok_all else "NÅGOT TEST FALLERADE", "|", len(found), "kollisioner")
