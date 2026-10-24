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
    # --- rendering -------------------------------------------------------- #
    def _header(self, d, tag, right=""):
        self.ctx.draw_header(d, tag, right, self.ctx.W)

    def _ctext(self, d, y, s, font, fill=255):
        c = self.ctx
        d.text(((c.W - c.text_w(d, s, font)) / 2, y), s, font=font, fill=fill)

    def render(self, d, t):
        if self.phase == "GUESS":
            return self._r_guess(d, t)
        else:
            return self._r_reveal(d, t)

    def _r_guess(self, d, t):
        c = self.ctx
        self._header(d, "QUIZ", f"TRACK #{self.track_num}")

        # Mystery soundwave box över widescreen-bredden
        w_box = [8, 18, c.W - 8, 62]
        d.rectangle(w_box, outline=255)
        for x in range(12, c.W - 12):
            yw = 40 + int(math.sin(x * 0.22 + t * 4.0) * 11)
            d.point([(x, yw)], fill=255)

        # Frågetecken-ruta i mitten
        d.rectangle([54, 30, 74, 50], fill=255)
        self._ctext(d, 33, "?", c.F_MD, fill=0)

        # Rubrik & speltips
        self._ctext(d, 68, "GUESS TITLE & ARTIST", c.F_SM)

        # Poängrad (passar snyggt i 128px bredd)
        pts = f"P1:{self.scores[0]} P2:{self.scores[1]} P3:{self.scores[2]} P4:{self.scores[3]}"
        self._ctext(d, 86, pts, c.F_XS)

        if int(t * 2) % 2 == 0:
            self._ctext(d, 96, "PRESS REVEAL TO CHECK", c.F_XS)

        c.draw_control_bar(d, [
            ("top_tap", "REVL"),
            ("btm_tap", "SKIP"),
            ("btm_hold", "MENU"),
        ], c.W, c.H)
        return True

    def _r_reveal(self, d, t):
        c = self.ctx
        self._header(d, "QUIZ", "REVEAL")

        # Avslöjad titel och artist med mjuk widescreen marquee
        c.marquee(d, (4, 18), self.current_title, c.F_MD, c.W - 8, t)
        c.marquee(d, (4, 34), self.current_artist, c.F_SM, c.W - 8, t)

        # Avdelare
        d.line([(0, 50), (c.W - 1, 50)], fill=255)
        self._ctext(d, 54, "AWARD POINT TO:", c.F_XS)

        # Spelarval i inverterad ruta
        p_idx = self.awarding_player
        p_tag = f"PLAYER {p_idx + 1} ({self.scores[p_idx]} PTS)"
        d.rectangle([14, 66, c.W - 14, 84], fill=255)
        self._ctext(d, 69, p_tag, c.F_SM, fill=0)

        # Poängöversikt
        score_line = f"P1:{self.scores[0]} P2:{self.scores[1]} P3:{self.scores[2]} P4:{self.scores[3]}"
        self._ctext(d, 93, score_line, c.F_XS)

        c.draw_control_bar(d, [
            ("rot", "PLR"),
            ("top_tap", "NEXT"),
            ("btm_tap", "+1 PT"),
            ("btm_hold", "MENU"),
        ], c.W, c.H)
        return True
