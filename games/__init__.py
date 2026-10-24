"""
Minispel-ramverk för OD-11 Minimix.

  * Game          – basklass; ett spel per fil i detta paket.
  * GameContext   – verktyg som streamer.py lånar ut (fonter, ritfunktioner, Spotify-API).
  * GameManager   – hub-skärmen + vidarebefordrar vred/knappar/rendering till aktivt spel.

Lägg till ett nytt spel: skapa games/mittspel.py med en Game-subklass och lägg den i
GAME_CLASSES nedan.
"""
import os
import threading

# Antal råa encoder-steg per "klick" i spelen (volymen använder 48 steg per procent).
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
    return [Hitster]


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
        d.line([(0, 14), (c.W_MAIN, 14)], fill=255)
        y = 20
        for i, cls in enumerate(self.classes):
            sel = i == self.selected
            if sel:
                d.rectangle([0, y - 2, c.W_MAIN - 2, y + 12], fill=255)
            d.text((4, y), cls.name, font=c.F_MD, fill=0 if sel else 255)
            y += 18
        d.text((4, y + 2), "MORE SOON", font=c.F_XS, fill=255)
        blurb = self.classes[self.selected].blurb if self.classes else ""
        for j, line in enumerate(blurb.split("\n")):
            d.text((2, 92 + j * 11), line, font=c.F_XS, fill=255)
        c.draw_control_sidebar(d, [("rot", "PICK"), ("top_tap", "PLAY"), ("", ""),
                                   ("btm_tap", "NEXT"), ("btm_hold", "HOME")])
        return False
