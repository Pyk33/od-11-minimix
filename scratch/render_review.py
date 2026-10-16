#!/usr/bin/env python3
"""Snittritningar: skär mesh-geometrin exakt längs plan (inga projektionstrick)."""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import generate_cad as CAD

OUT = "/Users/ollepyk/.gemini/antigravity-ide/brain/0caa6ce8-f626-461d-a5b3-91233207b27f"
base, lid, ghosts = CAD.build()

COL = {"Pi": "#22c55e", "HAT": "#3b82f6", "Distans": "#eab308", "Pinne": "#eab308", "Mutter": "#e5e7eb",
       "Cubilux": "#f472b6", "Knapp": "#a5f3fc", "Encoder": "#f59e0b", "Ratt": "#94a3b8", "OLED": "#38bdf8"}


def colour(name):
    for k, v in COL.items():
        if name.startswith(k):
            return v
    return "#ffffff"


def mesh(shape):
    v, t = shape.tessellate(0.08, 0.3)
    V = np.array([(p.X, p.Y, p.Z) for p in v])
    T = np.array(t, dtype=int)
    return V[T]        # (n, 3, 3)


MESH = {"Botten": mesh(base), "Lock": mesh(lid)}
for n, s in ghosts.items():
    MESH[n] = mesh(s)
STYLE = {"Botten": ("#e5e7eb", 1.3), "Lock": ("#ffffff", 1.3)}


def slice_mesh(tri, axis, d):
    s = tri[:, :, axis] - d
    segs = []
    for i, j, k in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        pass
    sg = np.sign(s)
    pts = []
    n = len(tri)
    out = []
    # kanter: (0,1),(1,2),(2,0)
    P = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        sa, sb = s[:, a], s[:, b]
        cross = (sa * sb) < 0
        t = np.where(cross, sa / (sa - sb + 1e-12), 0.0)
        pt = tri[:, a, :] + (tri[:, b, :] - tri[:, a, :]) * t[:, None]
        P.append((cross, pt))
    ax2 = [i for i in range(3) if i != axis]
    res = []
    for (c1, p1), (c2, p2) in ((P[0], P[1]), (P[1], P[2]), (P[2], P[0])):
        m = c1 & c2
        if m.any():
            res.append(np.stack([p1[m][:, ax2], p2[m][:, ax2]], axis=1))
    return np.concatenate(res) if res else np.zeros((0, 2, 2))


def panel(ax, axis, d, title, names, xlim=None, ylim=None):
    for n in names:
        segs = slice_mesh(MESH[n], axis, d)
        if len(segs) == 0:
            continue
        col, lw = STYLE.get(n, (colour(n), 1.0))
        ax.add_collection(LineCollection(segs, colors=col, linewidths=lw))
    ax.set_aspect("equal")
    ax.autoscale()
    if xlim:
        ax.set_xlim(*xlim)
    if ylim:
        ax.set_ylim(*ylim)
    ax.set_title(title, color="white", fontsize=10.5, fontweight="bold")
    ax.set_facecolor("#111111")
    ax.tick_params(colors="#777777", labelsize=7)
    for sp in ax.spines.values():
        sp.set_color("#444444")
    ax.grid(color="#2a2a2a", lw=0.4)


ALL = list(MESH)
LID_MOUNTED = ("Knapp", "Ratt", "Encoder", "OLED")
low = ["Botten"] + [n for n in ghosts if not n.startswith(LID_MOUNTED[:3] + ("OLED",))]
fz = CAD.FLOOR_THICK
bh = CAD.BASE_H

# ---------------- Bild 1: planer ----------------
fig, axs = plt.subplots(2, 2, figsize=(21, 11.5), facecolor="#111111")
panel(axs[0, 0], 2, fz + 8, "1  Plan, 8 mm över golvet: Cubilux-vagga (retention, kabelspår), standoffs, USB-C-hål", low)
panel(axs[0, 1], 2, fz + 30, "2  Plan, 30 mm över golvet: HAT-plintar, rotor, långa smala ventilationsslitsar i sladdväggen",
      ["Botten"] + [n for n in ghosts if n.startswith(("Distans", "HAT", "Encoder_kropp", "Knapp", "OLED_pinhus"))])
panel(axs[1, 0], 2, bh - 0.6, "3  Lockets undersida (0.6 mm under lockets underkant): snäpptungor, styrring, stödhylsor, OLED-ram",
      ["Lock"] + [n for n in ghosts if n.startswith(("Knapp", "OLED", "Encoder_kropp"))])
panel(axs[1, 1], 2, bh + 1.0, "4  Lock, snitt 1.0 mm in i locket: skärmens glasficka + fönster, blinda distansfickor, gravyr",
      ["Lock"] + [n for n in ghosts if n.startswith(("Knapp", "OLED", "Encoder", "Pinne"))])
plt.tight_layout()
p1 = os.path.join(OUT, "review_plans.png")
plt.savefig(p1, dpi=100, facecolor="#111111")
plt.close()

# ---------------- Bild 2: sektioner ----------------
gx, gy = CAD.c(CAD.OG_X, CAD.OG_Y)
cx_, _ = CAD.c(CAD.CR_X, 0)
ex, ey = CAD.c(CAD.ENC_X, CAD.ENC_Y)
ux, _ = CAD.c(CAD.USBC_X, 0)
fig, axs = plt.subplots(2, 2, figsize=(21, 11.5), facecolor="#111111")
panel(axs[0, 0], 1, gy, "5  Snitt genom skärmens mitt (framifrån): nedsänkt bezel, glasficka, PCB, 2.8 mm luft till plintar", ALL)
panel(axs[0, 1], 0, cx_, "6  Snitt genom Cubilux-vaggan (från sidan): block, snäpplist, stoppvägg + kabelspår, knapp ovanför",
      ["Botten", "Lock"] + [n for n in ghosts if n.startswith(("Cubilux", "Knapp", "Pi_PCB"))])
panel(axs[1, 0], 0, ex, "7  Snitt genom rotorn (från sidan): kropp, krage genom locket, ratt, golvfrigång under kroppen", ALL)
panel(axs[1, 1], 0, ux, "8  Snitt genom USB-C-hålet (från sidan): hålets höjd mot Pi:ns USB-C-hylsa och kontakten", ALL)
plt.tight_layout()
p2 = os.path.join(OUT, "review_sections.png")
plt.savefig(p2, dpi=100, facecolor="#111111")
print("Sparade:", p1, p2)
