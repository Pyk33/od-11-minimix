#!/usr/bin/env python3
"""
Generates visual previews of OD-11 Minimix UI views in both 128x64 and 128x128
to test and verify the layout before updating streamer.py.
"""
import math
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def get_font(size):
    candidates = [
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Monaco.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()

F_XS = get_font(9)
F_SM = get_font(10)
F_MD = get_font(13)
F_XL = get_font(38)

def text_w(draw, s, font):
    return draw.textlength(s, font=font)

def seg_bar(draw, x, y, w, h, frac, segs=16):
    gap = 1
    sw = (w - gap * (segs - 1)) / segs
    on = int(round(frac * segs))
    for i in range(segs):
        x0 = x + i * (sw + gap)
        box = [x0, y, x0 + sw - 0.01, y + h]
        if i < on:
            draw.rectangle(box, fill=255)
        else:
            draw.line([(x0, y + h), (x0 + sw - 0.01, y + h)], fill=255)

def draw_tape_reel(d, cx, cy, radius, angle):
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=255)
    d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=255)
    for i in range(3):
        a = angle + i * (2 * math.pi / 3)
        x2 = cx + (radius - 1) * math.cos(a)
        y2 = cy + (radius - 1) * math.sin(a)
        d.line([(cx, cy), (x2, y2)], fill=255)

def draw_control_sidebar(d, items, w=128, h=128, w_main=82):
    d.line([(w_main, 0), (w_main, h - 1)], fill=255)
    if h >= 100:
        row_y = [8, 33, 58, 83, 108]
    else:
        row_y = [1, 13, 26, 39, 51]
    
    font = F_SM if h >= 100 else F_XS

    for i, (glyph, label) in enumerate(items):
        if i >= len(row_y):
            break
        y = row_y[i]
        gx = w_main + 3
        gy = y + 1

        if glyph == "rot":
            d.ellipse([gx, gy, gx + 6, gy + 6], outline=255)
            d.point([(gx + 3, gy + 3), (gx + 3, gy + 1), (gx + 1, gy + 3)], fill=255)
        elif glyph == "top_tap":
            d.polygon([(gx + 3, gy + 1), (gx, gy + 7), (gx + 6, gy + 7)], fill=255)
        elif glyph == "top_hold":
            d.line([(gx + 2, gy), (gx + 2, gy + 5)], fill=255)
            d.line([(gx + 2, gy + 5), (gx + 6, gy + 5)], fill=255)
            d.line([(gx + 5, gy + 3), (gx + 7, gy + 5)], fill=255)
            d.line([(gx + 5, gy + 7), (gx + 7, gy + 5)], fill=255)
        elif glyph == "btm_tap":
            d.polygon([(gx, gy + 1), (gx + 6, gy + 1), (gx + 3, gy + 7)], fill=255)
        elif glyph == "btm_hold":
            d.line([(gx + 2, gy), (gx + 2, gy + 5)], fill=255)
            d.line([(gx + 2, gy + 5), (gx + 6, gy + 5)], fill=255)
            d.line([(gx + 5, gy + 3), (gx + 7, gy + 5)], fill=255)
            d.line([(gx + 5, gy + 7), (gx + 7, gy + 5)], fill=255)

        d.text((gx + 10, y), label, font=font, fill=255)

def render_main(d, s, w=128, h=128, w_main=82, t=0.0):
    if h >= 100:
        # 128x128 layout
        src = s.get("source") or "OD-11"
        d.text((2, 2), src, font=F_SM, fill=255)
        stat = "PLAY" if s.get("playing") else "PAUS"
        d.text((w_main - 2 - text_w(d, stat, F_SM), 2), stat, font=F_SM, fill=255)
        d.line([(0, 16), (w_main, 16)], fill=255)

        # Title & Artist
        title = (s.get("title") or "THE LESS I KNOW THE BETTER").upper()
        artist = (s.get("artist") or "TAME IMPALA").upper()
        d.text((2, 22), title[:13], font=F_MD, fill=255)
        d.text((2, 38), artist[:16], font=F_SM, fill=255)

        # Mini TE-style Spectrum Analyzer (dancing bars)
        bx0, by0, bx1, by1 = 2, 54, w_main - 4, 76
        num_bars = 10
        bw = (bx1 - bx0) / num_bars
        for b in range(num_bars):
            h_val = int(abs(math.sin(t * 4.0 + b * 0.7)) * (by1 - by0 - 4)) + 3
            x_b = bx0 + b * bw
            d.rectangle([x_b + 1, by1 - h_val, x_b + bw - 2, by1], fill=255)

        # Progress
        dur_ms = s.get("dur_ms", 216000)
        pos_ms = s.get("pos_ms", 84000)
        frac = pos_ms / dur_ms
        mm = int(pos_ms // 60000)
        ss = int((pos_ms // 1000) % 60)
        dur_mm = int(dur_ms // 60000)
        dur_ss = int((dur_ms // 1000) % 60)
        d.text((2, 82), f"{mm}:{ss:02d}", font=F_XS, fill=255)
        d.text((w_main - 2 - text_w(d, f"{dur_mm}:{dur_ss:02d}", F_XS), 82), f"{dur_mm}:{dur_ss:02d}", font=F_XS, fill=255)
        seg_bar(d, 2, 94, w_main - 4, 5, frac, segs=16)

        # Volume Footer
        d.line([(0, 106), (w_main, 106)], fill=255)
        vol = s.get("volume", 35)
        d.text((2, 112), f"VOL {vol}", font=F_XS, fill=255)
        seg_bar(d, 40, 114, w_main - 42, 6, vol / 85.0, segs=8)
    else:
        # 128x64 legacy layout
        src = s.get("source") or "OD-11"
        d.text((2, 0), src, font=F_XS, fill=255)
        stat = "PLAY" if s.get("playing") else "PAUS"
        d.text((w_main - 2 - text_w(d, stat, F_XS), 0), stat, font=F_XS, fill=255)
        d.line([(0, 11), (w_main, 11)], fill=255)
        d.text((2, 16), s.get("title", "TITLE")[:12].upper(), font=F_SM, fill=255)
        d.text((2, 31), s.get("artist", "ARTIST")[:15].upper(), font=F_XS, fill=255)
        d.line([(2, 46), (w_main - 3, 46)], fill=255)
        d.text((2, 53), f"VOL {s.get('volume', 35)}", font=F_XS, fill=255)

    vol_items = [("rot", "VOL"), ("top_tap", "PAUS"), ("top_hold", "MUTE"), ("btm_tap", "NEXT"), ("btm_hold", "TAPE")]
    draw_control_sidebar(d, vol_items, w=w, h=h, w_main=w_main)

def render_vol_overlay(d, s, w=128, h=128, w_main=82, t=0.0):
    if h >= 100:
        d.rectangle([2, 4, 34, 15], fill=255)
        d.text((4, 4), "VOLUME", font=F_XS, fill=0)
        label = f"{s.get('volume', 42)}"
        w_lbl = text_w(d, label, F_XL)
        d.text(((w_main - w_lbl) / 2, 28), label, font=F_XL, fill=255)
        seg_bar(d, 6, 82, w_main - 12, 12, s.get("volume", 42) / 85.0, segs=12)
        d.text(((w_main - text_w(d, "LEVEL 42/85", F_XS)) / 2, 104), "LEVEL 42/85", font=F_XS, fill=255)
    else:
        label = f"{s.get('volume', 42)}"
        w_lbl = text_w(d, label, F_XL)
        d.text(((w_main - w_lbl) / 2, 2), label, font=F_XL, fill=255)
        d.text((2, 54), "VOL", font=F_XS, fill=255)
        seg_bar(d, 22, 54, w_main - 24, 8, s.get("volume", 42) / 85.0, 14)

    vol_items = [("rot", "VOL"), ("top_tap", "PAUS"), ("top_hold", "MUTE"), ("btm_tap", "NEXT"), ("btm_hold", "TAPE")]
    draw_control_sidebar(d, vol_items, w=w, h=h, w_main=w_main)

def render_tape(d, s, w=128, h=128, w_main=82, t=0.0):
    if h >= 100:
        d.rectangle([0, 0, 32, 12], fill=255)
        d.text((2, 1), "TAPE", font=F_XS, fill=0)
        status = "-00:45"
        d.text((w_main - text_w(d, status, F_XS) - 2, 1), status, font=F_XS, fill=255)
        d.line([(0, 14), (w_main, 14)], fill=255)

        # Large detailed reels
        draw_tape_reel(d, 20, 48, 15, t * 3.5)
        draw_tape_reel(d, 62, 48, 15, t * 3.0)
        d.line([(20, 33), (62, 33)], fill=255)
        d.line([(20, 63), (62, 63)], fill=255)
        d.rectangle([36, 40, 46, 56], outline=255)
        d.line([(41, 42), (41, 54)], fill=255)

        # Tape readout
        d.text(((w_main - text_w(d, "BUFFER -00:45", F_SM)) / 2, 74), "BUFFER -00:45", font=F_SM, fill=255)
        d.line([(4, 92), (w_main - 4, 92)], fill=255)
        d.rectangle([20, 89, 26, 95], fill=255)
        d.text((2, 100), "SCRUB 1.0x", font=F_MD, fill=255)
        d.text((2, 116), "LIVE READY", font=F_XS, fill=255)
    else:
        d.rectangle([0, 0, 30, 9], fill=255)
        d.text((2, 0), "TAPE", font=F_XS, fill=0)
        d.text((w_main - text_w(d, "-00:45", F_XS) - 2, 0), "-00:45", font=F_XS, fill=255)
        d.line([(0, 10), (w_main, 10)], fill=255)
        draw_tape_reel(d, 22, 29, 10, t * 3.5)
        draw_tape_reel(d, 62, 29, 10, t * 3.0)
        d.line([(22, 19), (62, 19)], fill=255)
        d.line([(22, 39), (62, 39)], fill=255)
        d.text((2, 53), "PLAYING", font=F_XS, fill=255)

    tape_items = [("rot", "SCRUB"), ("top_tap", "MERGE"), ("top_hold", "CUT"), ("btm_tap", "LOOP"), ("btm_hold", "VOL")]
    draw_control_sidebar(d, tape_items, w=w, h=h, w_main=w_main)

def main():
    dummy_state = {
        "source": "SPOTIFY",
        "playing": True,
        "title": "The Less I Know The Better",
        "artist": "Tame Impala",
        "volume": 42,
        "pos_ms": 78000,
        "dur_ms": 216000,
    }

    views = [
        ("main", render_main),
        ("vol", render_vol_overlay),
        ("tape", render_tape),
    ]

    # Render 128x128
    for name, func in views:
        img = Image.new("1", (128, 128), 0)
        d = ImageDraw.Draw(img)
        func(d, dummy_state, w=128, h=128, w_main=82, t=1.2)
        out_path = Path(__file__).resolve().parent / f"preview_128x128_{name}.png"
        img.save(out_path)
        print(f"Saved: {out_path}")

    # Render 128x64 comparison
    for name, func in views:
        img = Image.new("1", (128, 64), 0)
        d = ImageDraw.Draw(img)
        func(d, dummy_state, w=128, h=64, w_main=84, t=1.2)
        out_path = Path(__file__).resolve().parent / f"preview_128x64_{name}.png"
        img.save(out_path)
        print(f"Saved: {out_path}")

if __name__ == "__main__":
    main()
