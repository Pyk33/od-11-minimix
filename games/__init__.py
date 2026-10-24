"""
Minispel-ramverk för OD-11 Minimix.

  * Game          – basklass; ett spel per fil i detta paket.
  * GameContext   – verktyg som streamer.py lånar ut (fonter, ritfunktioner, Spotify-API, bandmotor).
  * GameManager   – hub-skärmen + vidarebefordrar vred/knappar/rendering till aktivt spel.

Registrerade spel:
  1. Hitster          - Tidslinje & årtal (1-4 spelare)
  2. Music Quiz       - Blind-quiz på aktiv Spotify-spellista
  3. ReverseDetective - Baklänges-musikquiz (OB-4 Reverse Tape)
  4. SafeCracker      - Taktilt kassaskåpspussel för vridratten
"""
import os
import threading

STEPS_PER_TICK = int(os.environ.get("GAME_STEPS_PER_TICK", "150"))


class GameContext:
    """Samlar allt ett spel behöver från streamer.py (undviker cirkulär import)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class Game:
    name = "GAME"
    blurb = ""

    def __init__(self, ctx):
        self.ctx = ctx

    def on_enter(self):
        pass

    def on_exit(self):
        pass

    def on_rotate(self, ticks):
        """ticks > 0 = medsols."""

    def on_button(self, name):
        """name: 'play' | 'play_hold' | 'next'. Returnera 'menu' för att gå tillbaka till hubben."""

    def render(self, d, t):
        """Ritar i d (PIL ImageDraw, 1-bit). Returnera True om animerad."""
        return False


def _classes():
    from .hitster import Hitster
    from .quiz import MusicQuiz
    from .reverse import ReverseDetective
    from .safecracker import SafeCracker
    return [Hitster, MusicQuiz, ReverseDetective, SafeCracker]


class GameManager:
    def __init__(self, ctx):
        self.ctx = ctx
        self.lock = threading.RLock()
        self.classes = _classes()
        self.selected = 0
        self.active = None
        self._acc = 0

    # --- livscykel -------------------------------------------------------- #
    def enter(self):
        with self.lock:
            self.active = None
            self._acc = 0

    def exit(self):
        """Lämnar spelläget helt (t.ex. tillbaka till VOL)."""
        with self.lock:
            if self.active:
                self.active.on_exit()
            self.active = None

    # --- indata ----------------------------------------------------------- #
    def rotate(self, steps):
        with self.lock:
            self._acc += steps
            ticks = int(self._acc / STEPS_PER_TICK)
            if not ticks:
                return
            self._acc -= ticks * STEPS_PER_TICK
            if self.active:
                self.active.on_rotate(ticks)
            else:
                self.selected = max(0, min(len(self.classes) - 1, self.selected + ticks))

    def button(self, name):
        """Returnerar 'leave' när hubben vill lämna spelläget framåt (nästa flik)."""
        with self.lock:
            if self.active:
                if self.active.on_button(name) == "menu":
                    self.active.on_exit()
                    self.active = None
                return None
            if name == "play" and self.classes:
                self.active = self.classes[self.selected](self.ctx)
                self.active.on_enter()
            elif name == "next":
                return "leave"
            return None

    # --- rendering -------------------------------------------------------- #
    def render(self, d, t):
        with self.lock:
            if self.active:
                return self.active.render(d, t)
            return self._render_hub(d, t)

    def _render_hub(self, d, t):
        c = self.ctx
        d.rectangle([0, 0, 40, 12], fill=255)
        d.text((2, 1), "GAMES", font=c.F_XS, fill=0)

        # Positionsräknare t.ex. "2/4"
        pos_str = f"{self.selected + 1}/{len(self.classes)}"
        d.text((c.W_MAIN - c.text_w(d, pos_str, c.F_XS) - 2, 1), pos_str, font=c.F_XS, fill=255)
        d.line([(0, 14), (c.W_MAIN, 14)], fill=255)

        # Rullande fönster för spelen
        visible = 3
        scroll = max(0, min(len(self.classes) - visible, self.selected - 1))
        y = 18
        for i in range(scroll, min(len(self.classes), scroll + visible)):
            cls = self.classes[i]
            sel = (i == self.selected)
            if sel:
                d.rectangle([0, y - 1, c.W_MAIN - 2, y + 13], fill=255)
            d.text((4, y), cls.name, font=c.F_SM, fill=0 if sel else 255)
            y += 18

        # Avskiljare och beskrivning (blurb)
        d.line([(0, 76), (c.W_MAIN, 76)], fill=255)
        blurb = self.classes[self.selected].blurb if self.classes else ""
        for j, line in enumerate(blurb.split("\n")):
            d.text((2, 82 + j * 11), line, font=c.F_XS, fill=255)

        # Liten pil om det finns fler spel längre ner/upp
        if scroll > 0:
            d.polygon([(c.W_MAIN - 8, 18), (c.W_MAIN - 12, 23), (c.W_MAIN - 4, 23)], fill=255)
        if scroll + visible < len(self.classes):
            d.polygon([(c.W_MAIN - 8, 70), (c.W_MAIN - 12, 65), (c.W_MAIN - 4, 65)], fill=255)

        c.draw_control_sidebar(d, [("rot", "PICK"), ("top_tap", "PLAY"), ("", ""),
                                   ("btm_tap", "NEXT"), ("btm_hold", "HOME")])
        return False
