#!/usr/bin/env python3
import struct
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import os

ARTIFACT_DIR = "/Users/ollepyk/.gemini/antigravity-ide/brain/0caa6ce8-f626-461d-a5b3-91233207b27f"
CAD_DIR = "/Users/ollepyk/Desktop/OD-11 Minimix/streamer-project/cad_output"

def load_stl_binary(filepath):
    with open(filepath, "rb") as f:
        f.read(80)
        num_triangles = struct.unpack("<I", f.read(4))[0]
        data = f.read(num_triangles * 50)
    
    record_dtype = np.dtype([
        ("normal", "<f4", (3,)),
        ("v0", "<f4", (3,)),
        ("v1", "<f4", (3,)),
        ("v2", "<f4", (3,)),
        ("attr", "<u2")
    ])
    mesh_data = np.frombuffer(data, dtype=record_dtype)
    return np.stack([mesh_data["v0"], mesh_data["v1"], mesh_data["v2"]], axis=1)

base_verts = load_stl_binary(os.path.join(CAD_DIR, "od11_minimix_base.stl"))
lid_verts = load_stl_binary(os.path.join(CAD_DIR, "od11_minimix_lid.stl"))

fig = plt.figure(figsize=(16, 7), facecolor="#111111")

# 1. 3D Exploded View
ax1 = fig.add_subplot(1, 2, 1, projection='3d', facecolor="#111111")
ax1.set_title("OD-11 Minimix – 3D Exploded View (161 x 79 x 43 mm)", color="#FFFFFF", fontsize=13, pad=12, fontweight="bold")

step_b = max(1, len(base_verts) // 8000)
sub_base = base_verts[::step_b]
coll_base = Poly3DCollection(sub_base, facecolors="#1e1e1e", edgecolors="#3a3a3a", linewidths=0.35, alpha=0.96)
ax1.add_collection3d(coll_base)

step_l = max(1, len(lid_verts) // 6000)
sub_lid = lid_verts[::step_l].copy()
sub_lid[:, :, 2] += 40.0 + 26.0
coll_lid = Poly3DCollection(sub_lid, facecolors="#181818", edgecolors="#4f4f4f", linewidths=0.35, alpha=0.96)
ax1.add_collection3d(coll_lid)

ax1.set_xlim(-85, 85)
ax1.set_ylim(-45, 45)
ax1.set_zlim(0, 95)
ax1.view_init(elev=26, azim=-52)
ax1.axis('off')

# 2. Toppvy & Komponentplacering (Top View Map)
ax2 = fig.add_subplot(1, 2, 2, facecolor="#181818")
ax2.set_title("Toppanel & Komponentlayout (Matchar ditt foto!)", color="#FFFFFF", fontsize=13, pad=12, fontweight="bold")

EXT_X, EXT_Y = 161.0, 79.0
WALL = 2.5
x0 = -EXT_X / 2.0
y0 = -EXT_Y / 2.0

# Rita yttre skal
rect = plt.Rectangle((x0, y0), EXT_X, EXT_Y, facecolor="#222222", edgecolor="#666666", lw=2, zorder=1)
ax2.add_patch(rect)

# Rita Raspberry Pi 4 + HAT placering
pi_x = x0 + WALL + 21.0
pi_y = y0 + WALL + 3.0
pi_rect = plt.Rectangle((pi_x, pi_y), 85, 56, facecolor="#172b1d", edgecolor="#22c55e", lw=1.2, ls="--", zorder=2, alpha=0.6)
ax2.add_patch(pi_rect)
ax2.text(pi_x + 42.5, pi_y + 12, "Raspberry Pi 4 + GeeekPi HAT (Under)", color="#4ade80", fontsize=8, ha="center", zorder=3)

# 4 st mässingsdistanser
pi_holes = [
    (pi_x + 3.5, pi_y + 3.5),
    (pi_x + 3.5 + 58.0, pi_y + 3.5),
    (pi_x + 3.5, pi_y + 3.5 + 49.0),
    (pi_x + 3.5 + 58.0, pi_y + 3.5 + 49.0),
]
for hx, hy in pi_holes:
    ax2.add_patch(plt.Circle((hx, hy), 2.2, facecolor="#eab308", edgecolor="#ca8a04", lw=1.0, zorder=4))
ax2.text(pi_holes[0][0] + 29, pi_holes[2][1] - 3, "4x Distanstappar i hörnen", color="#eab308", fontsize=7, ha="center", zorder=4)

# Vänster zon: 2 st 12mm knappar på rad bakåt
btn_x = x0 + WALL + 11.0
btn_front_y = y0 + WALL + 28.0
btn_back_y  = y0 + WALL + 54.0
ax2.add_patch(plt.Circle((btn_x, btn_front_y), 6.1, facecolor="#e2e8f0", edgecolor="#ffffff", lw=1.5, zorder=5))
ax2.add_patch(plt.Circle((btn_x, btn_back_y),  6.1, facecolor="#e2e8f0", edgecolor="#ffffff", lw=1.5, zorder=5))
ax2.text(btn_x, btn_front_y, "PLAY\nPAUSE", color="#000", fontsize=6.5, ha="center", va="center", fontweight="bold", zorder=6)
ax2.text(btn_x, btn_back_y,  "NEXT\nMODE",  color="#000", fontsize=6.5, ha="center", va="center", fontweight="bold", zorder=6)

# Center zon: 1.3" OLED Display (ovanför HAT mellan bakre distanserna)
oled_cx = pi_x + 33.0
oled_cy = pi_y + 47.0
oled_rect = plt.Rectangle((oled_cx - 15.0, oled_cy - 7.75), 30, 15.5, facecolor="#050505", edgecolor="#00d2ff", lw=1.5, zorder=5)
ax2.add_patch(oled_rect)
ax2.text(oled_cx, oled_cy, "1.3\" OLED DISPLAY", color="#38bdf8", fontsize=7.5, ha="center", va="center", fontweight="bold", zorder=6)

# Höger zon: LPD3806 Encoder & Stor Aluminiumratt
enc_cx = pi_x + 85.0 + 26.0
enc_cy = pi_y + 32.0
ax2.add_patch(plt.Circle((enc_cx, enc_cy), 19.25, facecolor="#1a1a1a", edgecolor="#f59e0b", lw=1.2, ls=":", zorder=3))
ax2.add_patch(plt.Circle((enc_cx, enc_cy), 17.5, facecolor="#383838", edgecolor="#f3f4f6", lw=2.2, zorder=5, alpha=0.9))
ax2.add_patch(plt.Circle((enc_cx, enc_cy), 3.0, facecolor="#ffffff", edgecolor="#000000", lw=1.0, zorder=6))
ax2.add_patch(plt.Circle((enc_cx, enc_cy + 13.5), 1.2, facecolor="#ffffff", edgecolor="#000", lw=0.5, zorder=6)) # prick på ratten
ax2.text(enc_cx, enc_cy - 9, "DIN SILVERRATT", color="#ffffff", fontsize=7.5, ha="center", fontweight="bold", zorder=7)
ax2.text(enc_cx, enc_cy + 8, "LPD3806 (38.5mm)", color="#f59e0b", fontsize=7, ha="center", zorder=7)

# Portar i framväggen (USB-C & TOSLINK bredvid varandra)
usbc_cx = pi_x + 10.6
toslink_cx = x0 + WALL + 11.0
ax2.plot([usbc_cx - 6, usbc_cx + 6], [y0, y0], color="#ef4444", lw=4.5, zorder=7)
ax2.text(usbc_cx, y0 - 8.5, "USB-C (Power)", color="#ef4444", fontsize=7.5, ha="center", fontweight="bold")

ax2.plot([toslink_cx - 8.2, toslink_cx + 8.2], [y0, y0], color="#a855f7", lw=4.5, zorder=7)
ax2.text(toslink_cx, y0 - 4.5, "TOSLINK (16.4mm)", color="#a855f7", fontsize=7.5, ha="center", fontweight="bold")

# Bakre sladdutrymme indikering
ax2.text(0, y0 + EXT_Y - 5, "▲ Bakre sladdutrymme (+15 mm) för kabeldragning", color="#94a3b8", fontsize=7.5, ha="center")

ax2.set_xlim(-95, 95)
ax2.set_ylim(-52, 52)
ax2.set_aspect('equal')
ax2.axis('off')

plt.tight_layout()
preview_path = os.path.join(ARTIFACT_DIR, "cad_preview_photo_matched.png")
plt.savefig(preview_path, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
print(f"Preview sparad till {preview_path}!")
