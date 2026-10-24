"""
HITSTER – gissa årtalet och bygg din tidslinje.

Spelgång (2–4 spelare turas om vid samma vred):
  1. En okänd låt spelas (via go-librespot). Vrid för att välja var den hör hemma på din
     tidslinje, tryck PLAY för att låsa.
  2. Årtalet avslöjas. Rätt placering => kortet läggs in i tidslinjen, annars kastas det.
  3. Första spelaren med MÅL antal kort vinner.

Låtdata kommer från hitster_songs.json (byggs av hitster_import.py). Endast låtar med
"confident": true används, så årtalen är pålitliga.
"""
import bisect
import json
import math
import os
import random
import threading
import time
from pathlib import Path

from . import Game

SONGS_FILE = Path(os.environ.get("HITSTER_SONGS", Path(__file__).resolve().parent.parent / "hitster_songs.json"))
GOALS = (5, 7, 10)


def load_songs(path=SONGS_FILE):
    try:
        songs = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []
    return [s for s in songs if s.get("confident") and s.get("year") and s.get("uri")]


class Hitster(Game):
    name = "HITSTER"
    blurb = "GUESS THE\nYEAR (2-4P)"

    # --- initiering ------------------------------------------------------- #
    def __init__(self, ctx, songs=None):
        super().__init__(ctx)
        self.songs = load_songs() if songs is None else songs
        self.phase = "SETUP" if self.songs else "NOSONGS"
        self.players = 2
        self.goal = GOALS[-1]
        self.timelines = []        # per spelare: lista av song-dicts sorterad på år
        self.cur = 0
        self.deck = []
        self.song = None
        self.slot = 0
        self.correct = False
        self.error = ""
        self.clip_start_ms = 0
        self._token = 0

    def on_exit(self):
        self._token += 1
        self.ctx.api_call("POST", "/player/pause")

    # --- spellogik (ren, testbar) ----------------------------------------- #
    def draw_card(self):
        if not self.deck:
            self.deck = list(self.songs)
            random.shuffle(self.deck)
        return self.deck.pop()

    def start_game(self):
        self.deck = []
        self.timelines = [[self.draw_card()] for _ in range(self.players)]
        self.cur = 0
        self.phase = "PASS"

    @staticmethod
    def slot_is_correct(timeline, slot, year):
        left_ok = slot == 0 or timeline[slot - 1]["year"] <= year
        right_ok = slot >= len(timeline) or year <= timeline[slot]["year"]
        return left_ok and right_ok

    def lock_in(self):
        tl = self.timelines[self.cur]
        self.correct = self.slot_is_correct(tl, self.slot, self.song["year"])
        if self.correct:
            pos = bisect.bisect_right([s["year"] for s in tl], self.song["year"])
            tl.insert(pos, self.song)
        self.phase = "REVEAL"

    def after_reveal(self):
        if len(self.timelines[self.cur]) >= self.goal:
            self.phase = "WIN"
        else:
            self.cur = (self.cur + 1) % self.players
            self.phase = "PASS"

    def next_song(self):
        self.song = self.draw_card()
        self.slot = len(self.timelines[self.cur]) // 2
        self.phase = "PLACE"
        self.error = ""
        self.clip_start_ms = 0
        self._play_clip(first=True)

    # --- uppspelning ------------------------------------------------------ #
    def _play_clip(self, first):
        self._token += 1
        token, song, ctx = self._token, self.song, self.ctx

        def run():
            if first:
                if ctx.api_call("POST", "/player/play", {"uri": song["uri"], "paused": False},
                                timeout=6.0) is None:
                    self.error = "NO SPOTIFY"
                    return
                t0 = time.monotonic()
                dur = song.get("duration_ms") or 0
                while time.monotonic() - t0 < 8.0 and token == self._token:
                    st = ctx.api_call("GET", "/status", timeout=2.0) or {}
                    tr = st.get("track") or {}
                    if tr.get("uri") == song["uri"]:
                        dur = tr.get("duration") or dur
                        break
                    time.sleep(0.1)
                else:
                    if token == self._token:
                        self.error = "PLAY FAILED"
                    return
                # Hoppa in i låten (undvik tyst intro), samma ställe vid REPLAY
                self.clip_start_ms = int(dur * random.uniform(0.20, 0.45)) if dur > 60000 else 0
            if token == self._token:
                ctx.api_call("POST", "/player/seek", {"position": self.clip_start_ms}, timeout=3.0)
                ctx.api_call("POST", "/player/resume", timeout=2.0)

        threading.Thread(target=run, daemon=True).start()

    # --- indata ----------------------------------------------------------- #
    def on_rotate(self, ticks):
        if self.phase == "SETUP":
            self.players = max(1, min(4, self.players + ticks))
        elif self.phase == "PLACE":
            n = len(self.timelines[self.cur])
            self.slot = max(0, min(n, self.slot + ticks))

    def on_button(self, name):
        if name == "play_hold":
            return "menu"
        ph = self.phase
        if ph == "NOSONGS":
            return "menu" if name == "play" else None
        if ph == "SETUP":
            if name == "play":
                self.start_game()
            elif name == "next":
                self.goal = GOALS[(GOALS.index(self.goal) + 1) % len(GOALS)]
        elif ph == "PASS":
            if name == "play":
                self.next_song()
        elif ph == "PLACE":
            if name == "play":
                self.lock_in()
            elif name == "next":
                self._play_clip(first=False)
        elif ph == "REVEAL":
            if name == "play":
                self.after_reveal()
        elif ph == "WIN":
            if name == "play":
                return "menu"
        return None

    # --- rendering -------------------------------------------------------- #
    # --- rendering -------------------------------------------------------- #
    def _header(self, d, tag, right=""):
        self.ctx.draw_header(d, tag, right, self.ctx.W)

    def _ctext(self, d, y, s, font, fill=255):
        c = self.ctx
        d.text(((c.W - c.text_w(d, s, font)) / 2, y), s, font=font, fill=fill)

    def _sidebar(self, d, items):
        self.ctx.draw_control_bar(d, items, self.ctx.W, self.ctx.H)

    def render(self, d, t):
        return getattr(self, "_r_" + self.phase.lower())(d, t)

    def _r_nosongs(self, d, t):
        self._header(d, "HITSTER")
        self._ctext(d, 30, "NO SONGS", self.ctx.F_MD)
        for i, line in enumerate(("RUN ON PI:", "hitster_import.py", "<PLAYLIST>")):
            self._ctext(d, 54 + i * 12, line, self.ctx.F_XS)
        self._sidebar(d, [("top_tap", "BACK"), ("btm_tap", "HOME")])
        return False

    def _r_setup(self, d, t):
        c = self.ctx
        self._header(d, "HITSTER", "SETUP")
        self._ctext(d, 18, "PLAYERS", c.F_SM)
        self._ctext(d, 32, str(self.players), c.F_BIG)
        self._ctext(d, 62, f"GOAL: {self.goal} CARDS", c.F_SM)
        self._ctext(d, 80, f"{len(self.songs)} SONGS LOADED", c.F_XS)
        self._ctext(d, 94, "PRESS PLAY TO START", c.F_XS)
        self._sidebar(d, [("rot", "PLRS"), ("top_tap", "START"), ("btm_tap", "GOAL")])
        return False

    def _r_pass(self, d, t):
        c = self.ctx
        tl = self.timelines[self.cur]
        self._header(d, f"P{self.cur + 1}", f"{len(tl)}/{self.goal}")
        self._ctext(d, 22, "YOUR TURN", c.F_SM)
        self._ctext(d, 38, f"PLAYER {self.cur + 1}", c.F_MD)
        if int(t * 2) % 2 == 0:
            self._ctext(d, 70, "PRESS GO TO PLAY", c.F_SM)
        self._ribbon(d, 94, tl, None)
        self._sidebar(d, [("top_tap", "GO"), ("btm_tap", "MENU")])
        return True

    def _ribbon(self, d, y, tl, slot):
        """Tidslinjeremsa över hela widescreen-bredden: en tick per kort + markör för vald plats."""
        c = self.ctx
        n = len(tl)
        x0, x1 = 6, c.W - 6
        sp = (x1 - x0) / max(1, n)
        d.line([(x0, y + 6), (x1, y + 6)], fill=255)
        for i in range(n):
            x = x0 + (i + 0.5) * sp
            d.rectangle([x - 1, y + 1, x + 1, y + 11], fill=255)
        if slot is not None:
            x = x0 + slot * sp
            d.polygon([(x, y + 13), (x - 4, y + 19), (x + 4, y + 19)], fill=255)

    def _r_place(self, d, t):
        c = self.ctx
        tl = self.timelines[self.cur]
        self._header(d, f"P{self.cur + 1}", f"{len(tl)}/{self.goal}")
        if self.error:
            self._ctext(d, 24, self.error, c.F_MD)
            self._ctext(d, 44, "NEXT = RETRY", c.F_XS)
        else:
            # Animerad equalizer så man ser att musik spelas
            num_eq = 14
            for i in range(num_eq):
                h = 3 + int(9 * abs(math.sin(t * 5 + i * 0.8)))
                x = 8 + i * 8
                d.rectangle([x, 34 - h, x + 5, 34], fill=255)
            self._ctext(d, 38, "WHERE DOES IT FIT?", c.F_XS)

        left = str(tl[self.slot - 1]["year"]) if self.slot > 0 else "----"
        right = str(tl[self.slot]["year"]) if self.slot < len(tl) else "----"

        # Vänster år-kort
        d.rectangle([6, 50, 42, 70], outline=255)
        self._ctext_in(d, 6, 42, 55, left, c.F_SM)

        # Aktiv plats (?) med blinkande ram
        blink = (int(t * 4) % 2 == 0)
        d.rectangle([48, 48, 80, 72], fill=255 if blink else 0, outline=255)
        self._ctext_in(d, 48, 80, 52, "?", c.F_MD, fill=0 if blink else 255)

        # Höger år-kort
        d.rectangle([86, 50, 122, 70], outline=255)
        self._ctext_in(d, 86, 122, 55, right, c.F_SM)

        self._ribbon(d, 78, tl, self.slot)
        d.text((6, 98), f"SLOT {self.slot + 1}/{len(tl) + 1}", font=c.F_XS, fill=255)
        d.text((c.W - 6 - c.text_w(d, f"{tl[0]['year']}-{tl[-1]['year']}", c.F_XS), 98),
               f"{tl[0]['year']}-{tl[-1]['year']}", font=c.F_XS, fill=255)

        self._sidebar(d, [("rot", "SLOT"), ("top_tap", "LOCK"), ("btm_tap", "AGAIN")])
        return True

    def _ctext_in(self, d, x0, x1, y, s, font, fill=255):
        d.text((x0 + (x1 - x0 - self.ctx.text_w(d, s, font)) / 2, y), s, font=font, fill=fill)

    def _r_reveal(self, d, t):
        c = self.ctx
        tl = self.timelines[self.cur]
        self._header(d, f"P{self.cur + 1}", f"{len(tl)}/{self.goal}")
        self._ctext(d, 18, str(self.song["year"]), c.F_BIG)
        banner = "CORRECT! +1 PT" if self.correct else f"WRONG! ({self.song['year']})"
        if self.correct or int(t * 3) % 2 == 0:
            d.rectangle([8, 46, c.W - 8, 62], fill=255)
            self._ctext(d, 49, banner, c.F_SM, fill=0)
        else:
            d.rectangle([8, 46, c.W - 8, 62], outline=255)
            self._ctext(d, 49, banner, c.F_SM)
        c.marquee(d, (4, 68), self.song["title"], c.F_SM, c.W - 8, t)
        c.marquee(d, (4, 84), self.song["artist"], c.F_XS, c.W - 8, t)
        self._ribbon(d, 96, tl, None)
        self._sidebar(d, [("top_tap", "NEXT"), ("btm_tap", "MENU")])
        return True

    def _r_win(self, d, t):
        c = self.ctx
        self._header(d, "HITSTER", "WINNER!")
        if int(t * 2) % 2 == 0:
            d.rectangle([8, 18, c.W - 8, 54], fill=255)
            self._ctext(d, 22, f"P{self.cur + 1} WINS!", c.F_MD, fill=0)
        else:
            d.rectangle([8, 18, c.W - 8, 54], outline=255)
            self._ctext(d, 22, f"P{self.cur + 1} WINS!", c.F_MD)
        self._ctext(d, 60, f"REACHED {self.goal} CARDS!", c.F_SM)
        for i, tl in enumerate(self.timelines):
            d.text((8, 78 + i * 10), f"PLAYER {i + 1}: {len(tl)} CARDS", font=c.F_XS, fill=255)
        self._sidebar(d, [("top_tap", "AGAIN"), ("btm_tap", "MENU")])
        return True
