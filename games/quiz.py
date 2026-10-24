"""
Klassiskt Blind-Musikquiz på den aktiva Spotify-spellistan.

Spelgång:
  1. Hoppar till nästa låt i spellistan/kön och spelar upp den i högtalaren.
  2. Skärmen döljer artist och låttitel och visar bara speltid och equalizer.
  3. Spelarna runt bordet gissar låt/artist.
  4. Klicka REVEAL för att avslöja svaret!
  5. Vrid ratten för att dela ut poäng till den som gissade rätt (P1–P4).
  6. Klicka NEXT för nästa låt!
"""
import math
import time
import threading
from . import Game


class MusicQuiz(Game):
    name = "MUSIC QUIZ"
    blurb = "ACTIVE PLAYLIST\nBLIND GUESSING"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.phase = "GUESS"   # "GUESS" | "REVEAL"
        self.track_num = 1
        self.current_title = ""
        self.current_artist = ""
        self.duration_ms = 0
        self.scores = [0, 0, 0, 0]
        self.awarding_player = 0
        self._token = 0

    def on_enter(self):
        self.track_num = 1
        self.next_track()

    def on_exit(self):
        self._token += 1

    def next_track(self):
        self._token += 1
        token = self._token
        self.phase = "GUESS"
        self.current_title = "LOADING..."
        self.current_artist = ""

        def run():
            ctx = self.ctx
            # Hoppa till nästa låt på Spotify
            ctx.api_call("POST", "/player/next", timeout=2.0)
            time.sleep(0.4)
            ctx.api_call("POST", "/player/resume", timeout=2.0)

            # Polla för nya låtens metadata
            t0 = time.monotonic()
            while time.monotonic() - t0 < 6.0 and token == self._token:
                st = ctx.api_call("GET", "/status", timeout=1.5) or {}
                tr = st.get("track") or {}
                title = tr.get("name", "")
                if title and title != self.current_title:
                    self.current_title = title
                    self.current_artist = ", ".join(tr.get("artist_names") or [])
                    self.duration_ms = tr.get("duration") or 0
                    break
                time.sleep(0.15)

        threading.Thread(target=run, daemon=True).start()

    # --- indata ----------------------------------------------------------- #
    def on_rotate(self, ticks):
        if self.phase == "REVEAL":
            self.awarding_player = (self.awarding_player + ticks) % 4

    def on_button(self, name):
        if name == "play_hold":
            return "menu"

        if self.phase == "GUESS":
            if name == "play":
                self.phase = "REVEAL"
            elif name == "next":
                self.track_num += 1
                self.next_track()
        elif self.phase == "REVEAL":
            if name == "play":
                # Nästa låt
                self.track_num += 1
                self.next_track()
            elif name == "next":
                # Dela ut poäng till markerad spelare
                self.scores[self.awarding_player] += 1

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
        if self.phase == "GUESS":
            return self._r_guess(d, t)
        else:
            return self._r_reveal(d, t)

    def _r_guess(self, d, t):
        c = self.ctx
        self._header(d, "QUIZ", f"#{self.track_num}")

        # Animerad equalizer i mitten
        for i in range(11):
            h = 4 + int(14 * abs(math.sin(t * 6 + i * 0.85)))
            x = 6 + i * 7
            d.rectangle([x, 50 - h, x + 4, 50], fill=255)

        # Frågetecken-ruta
        d.rectangle([14, 58, c.W_MAIN - 16, 82], outline=255)
        self._ctext(d, 62, "? ? ?", c.F_MD)

        # Poängrad
        pts = f"P1:{self.scores[0]} P2:{self.scores[1]} P3:{self.scores[2]} P4:{self.scores[3]}"
        if c.text_w(d, pts, c.F_XS) > c.W_MAIN - 4:
            pts = f"SCORE {self.scores[0]}-{self.scores[1]}-{self.scores[2]}-{self.scores[3]}"
        self._ctext(d, 94, pts, c.F_XS)

        # Speltips
        if int(t * 2) % 2 == 0:
            self._ctext(d, 110, "PLAY = REVEAL", c.F_XS)

        c.draw_control_sidebar(d, [
            ("", ""),
            ("top_tap", "REVEAL"),
            ("top_hold", "MENU"),
            ("btm_tap", "SKIP"),
            ("btm_hold", "HOME")
        ])
        return True

    def _r_reveal(self, d, t):
        c = self.ctx
        self._header(d, "QUIZ", f"#{self.track_num}")

        # Avslöjad titel och artist med mjuk scroll (marquee)
        c.marquee(d, (2, 22), self.current_title, c.F_MD, c.W_MAIN - 4, t)
        c.marquee(d, (2, 40), self.current_artist, c.F_SM, c.W_MAIN - 4, t)

        # Utdelning av poäng
        p_idx = self.awarding_player
        d.line([(0, 60), (c.W_MAIN, 60)], fill=255)
        self._ctext(d, 66, f"GIVE POINT TO:", c.F_XS)

        # Spelarval
        p_tag = f"P{p_idx + 1} ({self.scores[p_idx]} PTS)"
        d.rectangle([10, 80, c.W_MAIN - 12, 98], fill=255)
        self._ctext(d, 82, p_tag, c.F_SM, fill=0)

        # Poängöversikt
        score_line = f"P1:{self.scores[0]} P2:{self.scores[1]} P3:{self.scores[2]} P4:{self.scores[3]}"
        if c.text_w(d, score_line, c.F_XS) > c.W_MAIN - 4:
            score_line = f"SCORE {self.scores[0]}-{self.scores[1]}-{self.scores[2]}-{self.scores[3]}"
        self._ctext(d, 106, score_line, c.F_XS)

        c.draw_control_sidebar(d, [
            ("rot", "PLR"),
            ("top_tap", "NEXT"),
            ("top_hold", "MENU"),
            ("btm_tap", "+1 PT"),
            ("btm_hold", "HOME")
        ])
        return True
