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

    def _sidebar(self, d, items):
        self.ctx.draw_control_sidebar(d, items)

    def render(self, d, t):
        return getattr(self, "_r_" + self.phase.lower())(d, t)

    def _r_nosongs(self, d, t):
        self._header(d, "HITSTER")
        self._ctext(d, 30, "NO SONGS", self.ctx.F_MD)
        for i, line in enumerate(("RUN ON PI:", "hitster_", "import.py", "<PLAYLIST>")):
            self._ctext(d, 54 + i * 12, line, self.ctx.F_XS)
        self._sidebar(d, [("", ""), ("top_tap", "BACK"), ("", ""), ("", ""), ("btm_hold", "HOME")])
        return False

    def _r_setup(self, d, t):
        c = self.ctx
        self._header(d, "HITSTER")
        self._ctext(d, 20, "PLAYERS", c.F_SM)
        self._ctext(d, 34, str(self.players), c.F_BIG)
        self._ctext(d, 72, f"GOAL {self.goal} CARDS", c.F_SM)
        self._ctext(d, 92, f"{len(self.songs)} SONGS", c.F_XS)
        self._ctext(d, 106, "PRESS PLAY", c.F_XS)
        self._sidebar(d, [("rot", "PLRS"), ("top_tap", "START"), ("top_hold", "MENU"),
                          ("btm_tap", "GOAL"), ("btm_hold", "HOME")])
        return False

    def _r_pass(self, d, t):
        c = self.ctx
        tl = self.timelines[self.cur]
        self._header(d, f"P{self.cur + 1}", f"{len(tl)}/{self.goal}")
        self._ctext(d, 22, "YOUR TURN", c.F_SM)
        self._ctext(d, 38, f"P{self.cur + 1}", c.F_XL)
        if int(t * 2) % 2 == 0:
            self._ctext(d, 92, "PLAY = GO", c.F_SM)
        self._ribbon(d, 108, tl, None)
        self._sidebar(d, [("", ""), ("top_tap", "GO"), ("top_hold", "MENU"), ("", ""), ("btm_hold", "HOME")])
        return True

    def _ribbon(self, d, y, tl, slot):
        """Tidslinjeremsa: en tick per kort + markör för vald plats."""
        c = self.ctx
        n = len(tl)
        x0, x1 = 4, c.W_MAIN - 6
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
            for i in range(9):
                h = 3 + int(9 * abs(math.sin(t * 5 + i * 1.3)))
                x = 8 + i * 8
                d.rectangle([x, 36 - h, x + 4, 36], fill=255)
            self._ctext(d, 40, "WHEN WAS IT?", c.F_XS)

        left = str(tl[self.slot - 1]["year"]) if self.slot > 0 else "----"
        right = str(tl[self.slot]["year"]) if self.slot < len(tl) else "----"
        d.text((1, 62), left, font=c.F_SM, fill=255)
        d.rectangle([28, 56, 54, 76], outline=255)
        self._ctext_in(d, 28, 54, 58, "?", c.F_MD)
        d.text((c.W_MAIN - c.text_w(d, right, c.F_SM) - 1, 62), right, font=c.F_SM, fill=255)
        d.text((2, 80), "<" if self.slot > 0 else " ", font=c.F_XS, fill=255)
        d.text((c.W_MAIN - 8, 80), ">" if self.slot < len(tl) else " ", font=c.F_XS, fill=255)

        self._ribbon(d, 90, tl, self.slot)
        d.text((2, 116), str(tl[0]["year"]), font=c.F_XS, fill=255)
        last = str(tl[-1]["year"])
        d.text((c.W_MAIN - c.text_w(d, last, c.F_XS) - 2, 116), last, font=c.F_XS, fill=255)
        self._sidebar(d, [("rot", "SLOT"), ("top_tap", "LOCK"), ("top_hold", "MENU"),
                          ("btm_tap", "AGAIN"), ("btm_hold", "HOME")])
        return True

    def _ctext_in(self, d, x0, x1, y, s, font):
        d.text((x0 + (x1 - x0 - self.ctx.text_w(d, s, font)) / 2, y), s, font=font, fill=255)

    def _r_reveal(self, d, t):
        c = self.ctx
        tl = self.timelines[self.cur]
        self._header(d, f"P{self.cur + 1}", f"{len(tl)}/{self.goal}")
        self._ctext(d, 20, str(self.song["year"]), c.F_BIG)
        banner = "RIGHT!" if self.correct else "WRONG"
        if self.correct or int(t * 3) % 2 == 0:
            d.rectangle([8, 52, c.W_MAIN - 10, 66], fill=255)
            self._ctext(d, 53, banner, c.F_SM, fill=0)
        else:
            d.rectangle([8, 52, c.W_MAIN - 10, 66], outline=255)
            self._ctext(d, 53, banner, c.F_SM)
        c.marquee(d, (2, 72), self.song["title"], c.F_SM, c.W_MAIN - 4, t)
        c.marquee(d, (2, 86), self.song["artist"], c.F_XS, c.W_MAIN - 4, t)
        self._ribbon(d, 104, tl, None)
        self._sidebar(d, [("", ""), ("top_tap", "NEXT"), ("top_hold", "MENU"), ("", ""), ("btm_hold", "HOME")])
        return True

    def _r_win(self, d, t):
        c = self.ctx
        self._header(d, "HITSTER")
        if int(t * 2) % 2 == 0:
            d.rectangle([4, 18, c.W_MAIN - 6, 64], fill=255)
            self._ctext(d, 20, f"P{self.cur + 1}", c.F_XL, fill=0)
        else:
            d.rectangle([4, 18, c.W_MAIN - 6, 64], outline=255)
            self._ctext(d, 20, f"P{self.cur + 1}", c.F_XL)
        self._ctext(d, 68, "WINS!", c.F_MD)
        for i, tl in enumerate(self.timelines):
            d.text((4, 88 + i * 10), f"P{i + 1}  {len(tl)} CARDS", font=c.F_XS, fill=255)
        self._sidebar(d, [("", ""), ("top_tap", "DONE"), ("", ""), ("", ""), ("btm_hold", "HOME")])
        return True
