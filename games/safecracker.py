"""
SAFE CRACKER – Kassaskåpssprängaren.

Ett taktilt pusselspel för OD-11:ans vridreglage och högtalare:
  1. Kassaskåpet har ett 3-siffrigt kombinationslås (00–99).
  2. Vrid ratten långsamt och lyssna på de mekaniska klick-ljuden.
  3. När du närmar dig rätt siffra stiger klickens tonhöjd och seismiska nålen vibrerar!
  4. Klicka SET för att sätta stiftet.
  5. Knäck alla 3 stiften innan tiden går ut för att öppna valvet!
"""
import math
import os
import random
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path
from . import Game

SOUND_DIR = Path("/tmp/safe_sounds")


def init_sounds():
    """Genererar snabba mekaniska klick/thud/ljud i /tmp med ren standard-Python."""
    try:
        SOUND_DIR.mkdir(parents=True, exist_ok=True)
        rate = 44100

        def gen(path, freq, dur=0.03, decay=120.0, noise=0.0):
            if path.exists():
                return
            n = int(rate * dur)
            with wave.open(str(path), "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                buf = bytearray()
                for i in range(n):
                    t = i / rate
                    env = math.exp(-t * decay)
                    s = math.sin(2 * math.pi * freq * t)
                    if noise > 0:
                        s = s * (1.0 - noise) + random.uniform(-1, 1) * noise
                    val = int(28000 * env * s)
                    buf += struct.pack("<h", max(-32767, min(32767, val)))
                w.writeframes(buf)

        gen(SOUND_DIR / "click_cold.wav", freq=380, dur=0.02, decay=180.0)
        gen(SOUND_DIR / "click_warm.wav", freq=950, dur=0.025, decay=140.0)
        gen(SOUND_DIR / "click_hot.wav", freq=2200, dur=0.03, decay=110.0)
        gen(SOUND_DIR / "thud_ok.wav", freq=140, dur=0.12, decay=40.0)
        gen(SOUND_DIR / "buzz_err.wav", freq=110, dur=0.25, decay=20.0, noise=0.3)
        gen(SOUND_DIR / "vault_open.wav", freq=520, dur=0.45, decay=12.0)
    except Exception:
        pass


def play_sound(name):
    """Spelar upp en kort ljudfil asynkront utan att blockera UI."""
    def run():
        p = SOUND_DIR / f"{name}.wav"
        if p.exists():
            try:
                subprocess.run(["aplay", "-q", str(p)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=1.0, check=False)
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


class SafeCracker(Game):
    name = "SAFE"
    blurb = "CRACK THE VAULT\nTACTILE DIAL PUZZLE"

    def __init__(self, ctx):
        super().__init__(ctx)
        init_sounds()
        self.phase = "PLAY"   # "PLAY" | "WIN" | "GAMEOVER"
        self.current_dial = 50
        self.combo = [0, 0, 0]
        self.current_tumbler = 0  # 0, 1, 2
        self.time_left = 60.0
        self.last_tick_time = time.monotonic()
        self.tension = 0.0
        self.error_flash = 0.0

    def on_enter(self):
        self.new_game()

    def new_game(self):
        # Skapa en 3-siffrig kod med lagom spridning (0..99)
        self.combo = [
            random.randint(5, 95),
            random.randint(5, 95),
            random.randint(5, 95)
        ]
        self.current_tumbler = 0
        self.current_dial = 0
        self.time_left = 60.0
        self.phase = "PLAY"
        self.last_tick_time = time.monotonic()
        self.tension = 0.0
        self.error_flash = 0.0

    def get_distance(self):
        target = self.combo[self.current_tumbler]
        raw_diff = abs(self.current_dial - target)
        return min(raw_diff, 100 - raw_diff)

    # --- indata ----------------------------------------------------------- #
    def on_rotate(self, ticks):
        if self.phase != "PLAY":
            return

        self.current_dial = (self.current_dial + ticks) % 100
        dist = self.get_distance()

        # Beräkna spänning/tension (0.0 .. 1.0)
        self.tension = max(0.0, 1.0 - (dist / 8.0))

        # Ljudeffekt beroende på avstånd
        if dist == 0:
            play_sound("click_hot")
        elif dist <= 2:
            play_sound("click_hot")
        elif dist <= 5:
            play_sound("click_warm")
        else:
            play_sound("click_cold")

    def on_button(self, name):
        if name == "play_hold":
            return "menu"

        if self.phase == "PLAY":
            if name == "play":
                dist = self.get_distance()
                if dist == 0:
                    # Träff! Sätt stift
                    play_sound("thud_ok")
                    self.current_tumbler += 1
                    if self.current_tumbler >= 3:
                        # Vinst! Alla 3 klara
                        play_sound("vault_open")
                        self.phase = "WIN"
                else:
                    # Miss! Strafftid och fel-flash
                    play_sound("buzz_err")
                    self.time_left = max(0.0, self.time_left - 8.0)
                    self.error_flash = time.monotonic() + 0.4
                    if self.time_left <= 0:
                        self.phase = "GAMEOVER"
        elif self.phase in ("WIN", "GAMEOVER"):
            if name == "play":
                self.new_game()
            elif name == "next":
                return "menu"

        return None

    # --- rendering -------------------------------------------------------- #
    def _header(self, d, tag, right=""):
        c = self.ctx
        d.rectangle([0, 0, 8 + c.text_w(d, tag, c.F_XS), 12], fill=255)
        d.text((4, 1), tag, font=c.F_XS, fill=0)
        if right:
            d.text((c.W_MAIN - c.text_w(d, right, c.F_XS) - 2, 1), right, font=c.F_XS, fill=255)
        d.line([(0, 14), (c.W_MAIN, 14)], fill=255)

    def _ctext(self, d, y, s, font, fill=255):
        c = self.ctx
        d.text(((c.W_MAIN - c.text_w(d, s, font)) / 2, y), s, font=font, fill=fill)

    def render(self, d, t):
        now = time.monotonic()
        dt = now - self.last_tick_time
        self.last_tick_time = now

        if self.phase == "PLAY":
            self.time_left = max(0.0, self.time_left - dt)
            if self.time_left <= 0:
                self.phase = "GAMEOVER"
                play_sound("buzz_err")

        if self.phase == "WIN":
            return self._r_win(d, t)
        elif self.phase == "GAMEOVER":
            return self._r_gameover(d, t)
        else:
            return self._r_play(d, t)

    def _r_play(self, d, t):
        c = self.ctx
        now = time.monotonic()
        sec_left = int(math.ceil(self.time_left))
        self._header(d, "VAULT", f"{sec_left}s")

        # Stift-indikatorer högst upp (Tumbler 1, 2, 3)
        for i in range(3):
            tx = 10 + i * 24
            if i < self.current_tumbler:
                d.rectangle([tx, 18, tx + 16, 28], fill=255)
                d.text((tx + 3, 19), f"L{i + 1}", font=c.F_XS, fill=0)
            elif i == self.current_tumbler:
                if int(t * 4) % 2 == 0:
                    d.rectangle([tx, 18, tx + 16, 28], outline=255)
                    d.text((tx + 3, 19), f"L{i + 1}", font=c.F_XS, fill=255)
            else:
                d.rectangle([tx, 18, tx + 16, 28], outline=255)
                d.text((tx + 3, 19), "-", font=c.F_XS, fill=255)

        # Kassaskåpsskiva (Rotary Dial)
        cx, cy, r = 41, 64, 27
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=255)

        # Roterande markeringar (sträck längs kanten)
        angle_base = (self.current_dial / 100.0) * (2 * math.pi)
        for i in range(12):
            a = angle_base + i * (2 * math.pi / 12)
            x1 = cx + (r - 4) * math.cos(a)
            y1 = cy + (r - 4) * math.sin(a)
            x2 = cx + r * math.cos(a)
            y2 = cy + r * math.sin(a)
            d.line([(x1, y1), (x2, y2)], fill=255)

        # Pil / indikator i toppen
        d.polygon([(cx, cy - r - 4), (cx - 3, cy - r - 8), (cx + 3, cy - r - 8)], fill=255)

        # Stor siffervisning i mitten av skivan
        dial_str = f"{self.current_dial:02d}"
        d.ellipse([cx - 15, cy - 15, cx + 15, cy + 15], fill=0)
        self._ctext(d, cy - 9, dial_str, c.F_MD)

        # Seismisk nål / Tension meter
        d.line([(4, 102), (c.W_MAIN - 6, 102)], fill=255)
        needle_w = int((c.W_MAIN - 10) * self.tension)
        if needle_w > 0:
            d.rectangle([4, 100, 4 + needle_w, 104], fill=255)

        # Litet akustiskt fladder vid nära träff
        if self.tension > 0.6:
            flad = int(4 * math.sin(t * 30))
            d.line([(4 + needle_w, 98 + flad), (4 + needle_w, 106 - flad)], fill=255)

        # Fel-flash vid misslyckad sättning
        if now < self.error_flash:
            d.rectangle([0, 14, c.W_MAIN, c.H - 1], outline=255)

        c.draw_control_sidebar(d, [
            ("rot", "DIAL"),
            ("top_tap", "SET"),
            ("top_hold", "MENU"),
            ("", ""),
            ("btm_hold", "HOME")
        ])
        return True

    def _r_win(self, d, t):
        c = self.ctx
        self._header(d, "VAULT", "OPEN!")
        if int(t * 3) % 2 == 0:
            d.rectangle([4, 24, c.W_MAIN - 6, 68], fill=255)
            self._ctext(d, 28, "CRACKED!", c.F_MD, fill=0)
            self._ctext(d, 48, "SAFE OPEN", c.F_SM, fill=0)
        else:
            d.rectangle([4, 24, c.W_MAIN - 6, 68], outline=255)
            self._ctext(d, 28, "CRACKED!", c.F_MD)
            self._ctext(d, 48, "SAFE OPEN", c.F_SM)

        code_str = f"{self.combo[0]:02d}-{self.combo[1]:02d}-{self.combo[2]:02d}"
        self._ctext(d, 78, f"CODE: {code_str}", c.F_XS)
        self._ctext(d, 94, f"{int(self.time_left)}s LEFT", c.F_XS)
        self._ctext(d, 110, "PLAY = AGAIN", c.F_XS)

        c.draw_control_sidebar(d, [
            ("", ""),
            ("top_tap", "AGAIN"),
            ("top_hold", "MENU"),
            ("btm_tap", "EXIT"),
            ("btm_hold", "HOME")
        ])
        return True

    def _r_gameover(self, d, t):
        c = self.ctx
        self._header(d, "VAULT", "ALARM")
        d.rectangle([4, 28, c.W_MAIN - 6, 68], outline=255)
        self._ctext(d, 36, "ALARM!", c.F_MD)
        self._ctext(d, 54, "BUSTED", c.F_SM)

        code_str = f"{self.combo[0]:02d}-{self.combo[1]:02d}-{self.combo[2]:02d}"
        self._ctext(d, 82, f"WAS: {code_str}", c.F_XS)
        self._ctext(d, 108, "PLAY = RETRY", c.F_XS)

        c.draw_control_sidebar(d, [
            ("", ""),
            ("top_tap", "RETRY"),
            ("top_hold", "MENU"),
            ("btm_tap", "EXIT"),
            ("btm_hold", "HOME")
        ])
        return True
