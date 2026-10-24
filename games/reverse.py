"""
REVERSE DETECTIVE – Baklänges-quizen.

Drar nytta av OB-4-bandmotorns inbyggda reverse-funktion:
  1. Väljer en välkänd hit ur låtbiblioteket och spelar in 5 sekunder av låtens hook.
  2. Bandet vänds baklänges och spelas i loop: REVERSE ◀◀!
  3. Spelarna försöker lista ut vilken låt det är.
  4. Klicka FLIP för att vända bandet rättvänd (FORWARD ▶▶) och avslöja svaret!
"""
import json
import math
import os
import random
import threading
import time
from pathlib import Path
from . import Game

SONGS_FILE = Path(os.environ.get("HITSTER_SONGS", Path(__file__).resolve().parent.parent / "hitster_songs.json"))


def load_songs():
    try:
        data = json.loads(SONGS_FILE.read_text(encoding="utf-8"))
        return [s for s in data if s.get("confident") and s.get("uri")]
    except Exception:
        return []


class ReverseDetective(Game):
    name = "REVERSE"
    blurb = "BACKWARDS QUIZ\nOB-4 REVERSE TAPE"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.songs = load_songs()
        self.phase = "NOSONGS" if not self.songs else "CAPTURE"
        self.current_song = None
        self.capture_start = 0.0
        self.capture_dur = 5.0
        self.show_hint = False
        self._token = 0

    def on_enter(self):
        if self.songs:
            self.next_round()

    def on_exit(self):
        self._token += 1
        # Återställ bandet om det var i reverse
        t = getattr(self.ctx, "tape", None)
        if t:
            try:
                t.loop_reverse = False
                t.set_mode(t.MODE_VOL)
            except Exception:
                pass
        self.ctx.api_call("POST", "/player/pause")

    def next_round(self):
        self._token += 1
        token = self._token
        self.current_song = random.choice(self.songs)
        self.phase = "CAPTURE"
        self.show_hint = False
        self.capture_start = time.monotonic()

        t = getattr(self.ctx, "tape", None)
        if t:
            try:
                t.loop_reverse = False
                t.set_mode(t.MODE_VOL)
            except Exception:
                pass

        def run():
            ctx, song = self.ctx, self.current_song
            # Starta uppspelning via Spotify ~25% in i låten
            dur = song.get("duration_ms") or 180000
            seek_ms = int(dur * random.uniform(0.22, 0.40)) if dur > 60000 else 0
            ctx.api_call("POST", "/player/play", {"uri": song["uri"], "paused": False}, timeout=4.0)
            time.sleep(0.3)
            ctx.api_call("POST", "/player/seek", {"position": seek_ms}, timeout=2.0)
            ctx.api_call("POST", "/player/resume", timeout=1.5)

            # Spela in 5 sekunder
            t0 = time.monotonic()
            self.capture_start = t0
            while time.monotonic() - t0 < self.capture_dur and token == self._token:
                time.sleep(0.1)

            if token != self._token:
                return

            # Vänd bandet baklänges!
            t = getattr(ctx, "tape", None)
            if t:
                try:
                    # Skapa loop över de senaste 5 sekunderna och vänd baklänges
                    with t._lock:
                        t.mode = t.MODE_LOOP
                        t.loop_active = True
                        t.loop_reverse = True
                        t.loop_length_s = self.capture_dur
                        t.loop_end_pos = t.tape.write_pos
                        t.loop_start_pos = (t.tape.write_pos - int(self.capture_dur * t.sr)) % t.tape.max_frames
                        t.head_pos = t.loop_end_pos
                    # Pausa Spotify så bara baklänges-loopen hörs
                    ctx.api_call("POST", "/player/pause", timeout=1.5)
                except Exception:
                    pass

            self.phase = "GUESS"

        threading.Thread(target=run, daemon=True).start()

    def flip_to_forward(self):
        """Vänder bandet framåt så alla hör låten rättvänd!"""
        t = getattr(self.ctx, "tape", None)
        if t:
            try:
                with t._lock:
                    t.loop_reverse = False
            except Exception:
                pass
        self.phase = "REVEAL"

    # --- indata ----------------------------------------------------------- #
    def on_button(self, name):
        if name == "play_hold":
            return "menu"

        if self.phase == "NOSONGS":
            return "menu" if name == "play" else None

        if self.phase == "CAPTURE":
            if name == "play":
                # Tvinga direkt till gissning
                self.phase = "GUESS"
        elif self.phase == "GUESS":
            if name == "play":
                # Vänd bandet rättvänd och avslöja!
                self.flip_to_forward()
            elif name == "next":
                # Visa ledtråd
                self.show_hint = True
        elif self.phase == "REVEAL":
            if name == "play":
                # Nästa runda
                self.next_round()
            elif name == "next":
                # Spela igen
                self.flip_to_forward()

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
        if self.phase == "CAPTURE":
            return self._r_capture(d, t)
        elif self.phase == "GUESS":
            return self._r_guess(d, t)
        elif self.phase == "REVEAL":
            return self._r_reveal(d, t)
        else:
            self._header(d, "REVERSE")
            self._ctext(d, 50, "NO SONGS", self.ctx.F_MD)
            return False

    def _r_capture(self, d, t):
        c = self.ctx
        self._header(d, "REVERSE", "REC")
        self._ctext(d, 26, "CAPTURING...", c.F_SM)

        # Rullande framåt-spolar
        angle = t * 6.0
        if hasattr(c, "draw_tape_reel"):
            c.draw_tape_reel(d, 22, 58, 14, angle)
            c.draw_tape_reel(d, 60, 58, 14, angle * 0.9)
        else:
            d.rectangle([18, 46, 64, 70], outline=255)

        # Progress bar för inspelning
        elapsed = min(self.capture_dur, time.monotonic() - self.capture_start)
        prog = elapsed / self.capture_dur
        bar_w = c.W_MAIN - 8
        d.rectangle([4, 88, 4 + bar_w, 94], outline=255)
        d.rectangle([4, 88, 4 + int(bar_w * prog), 94], fill=255)

        self._ctext(d, 104, "LISTEN CLOSELY", c.F_XS)
        c.draw_control_sidebar(d, [
            ("", ""),
            ("", ""),
            ("top_hold", "MENU"),
            ("", ""),
            ("btm_hold", "HOME")
        ])
        return True

    def _r_guess(self, d, t):
        c = self.ctx
        self._header(d, "REVERSE", "<<")

        # Rullande baklänges-spolar (moturs rotation!)
        angle = -t * 5.0
        if hasattr(c, "draw_tape_reel"):
            c.draw_tape_reel(d, 22, 42, 13, angle)
            c.draw_tape_reel(d, 60, 42, 13, angle * 1.1)

        # Baklänges-banner
        if int(t * 2.5) % 2 == 0:
            d.rectangle([6, 64, c.W_MAIN - 8, 80], fill=255)
            self._ctext(d, 66, "REVERSE <<", c.F_SM, fill=0)
        else:
            d.rectangle([6, 64, c.W_MAIN - 8, 80], outline=255)
            self._ctext(d, 66, "REVERSE <<", c.F_SM)

        # Ledtråd
        if self.show_hint and self.current_song:
            year = self.current_song.get("year", "????")
            decade = f"{(year // 10) * 10}s" if isinstance(year, int) else "POP"
            self._ctext(d, 88, f"HINT: {decade} ({year})", c.F_XS)
        else:
            self._ctext(d, 88, "WHAT SONG IS IT?", c.F_XS)

        self._ctext(d, 108, "FLIP TO REVEAL", c.F_XS)

        c.draw_control_sidebar(d, [
            ("", ""),
            ("top_tap", "FLIP!"),
            ("top_hold", "MENU"),
            ("btm_tap", "HINT"),
            ("btm_hold", "HOME")
        ])
        return True

    def _r_reveal(self, d, t):
        c = self.ctx
        self._header(d, "SOLVED!", ">>")

        # Framåt-rullar som snurrar med musiken
        angle = t * 4.0
        if hasattr(c, "draw_tape_reel"):
            c.draw_tape_reel(d, 18, 32, 9, angle)
            c.draw_tape_reel(d, 64, 32, 9, angle)

        if self.current_song:
            self._ctext(d, 46, str(self.current_song.get("year", "")), c.F_BIG)
            c.marquee(d, (2, 74), self.current_song.get("title", ""), c.F_SM, c.W_MAIN - 4, t)
            c.marquee(d, (2, 90), self.current_song.get("artist", ""), c.F_XS, c.W_MAIN - 4, t)

        self._ctext(d, 110, "PLAY = NEXT", c.F_XS)

        c.draw_control_sidebar(d, [
            ("", ""),
            ("top_tap", "NEXT"),
            ("top_hold", "MENU"),
            ("btm_tap", "REPLAY"),
            ("btm_hold", "HOME")
        ])
        return True
