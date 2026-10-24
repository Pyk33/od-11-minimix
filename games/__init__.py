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
        self.W = 128
        self.H = 128
        self.W_MAIN = 128
        self.__dict__.update(kw)

    def draw_header(self, d, badge, status="", W_val=None):
        w = W_val if W_val is not None else getattr(self, "W", 128)
        font = getattr(self, "F_XS", None)
        tw = self.text_w(d, badge, font) if hasattr(self, "text_w") else d.textlength(badge, font=font)
        bw = int(tw) + 8
        d.rectangle([0, 0, bw, 12], fill=255)
        d.text((4, 1), badge, font=font, fill=0)
        if status:
            sw = self.text_w(d, status, font) if hasattr(self, "text_w") else d.textlength(status, font=font)
            d.text((w - sw - 2, 1), status, font=font, fill=255)
        d.line([(0, 13), (w - 1, 13)], fill=255)

    def draw_control_bar(self, d, items, W_val=None, H_val=None):
        w = W_val if W_val is not None else getattr(self, "W", 128)
        h = H_val if H_val is not None else getattr(self, "H", 128)
        font = getattr(self, "F_XS", None)

        ABBREV = {
            "FILTER": "FLTR", "PLAYERS": "PLRS", "PLAYER": "PLR",
            "CANCEL": "BACK", "REVERSE": "REV", "REPLAY": "RPLY", "RESET": "RST"
        }
        clean = []
        for it in items:
            if not it or len(it) < 2:
                continue
            g, lbl = it[0], str(it[1]).strip().upper()
            if not lbl:
                continue
            lbl = ABBREV.get(lbl, lbl)
            clean.append((g, lbl))

        if not clean:
            return

        if len(clean) > 3:
            sel = []
            for pref in ("rot", "top_tap", "btm_tap"):
                found = next((x for x in clean if x[0] == pref), None)
                if found:
                    sel.append(found)
            if len(sel) >= 2:
                clean = sel
            else:
                clean = clean[:3]

        y_bar = h - 15
        d.line([(0, y_bar), (w - 1, y_bar)], fill=255)

        n = len(clean)
        col_w = w / n

        for i, (glyph, label) in enumerate(clean):
            x0 = int(i * col_w)
            x1 = int((i + 1) * col_w) if i < n - 1 else w - 1

            if i > 0 and n <= 3:
                d.line([(x0, y_bar + 4), (x0, h - 4)], fill=255)

            tw = self.text_w(d, label, font) if hasattr(self, "text_w") else d.textlength(label, font=font)
            glyph_w = 6 if glyph in ("rot", "top_tap", "top_hold", "btm_tap", "btm_hold", "top", "btm") else 0
            gap = 2 if glyph_w > 0 else 0
            total_w = glyph_w + gap + tw

            content_x = x0 + int((x1 - x0 - total_w) / 2)
            content_x = max(x0 + 2, content_x)
            gy = y_bar + 4
            ty = y_bar + 2

            gx = content_x
            if glyph == "rot":
                d.ellipse([gx, gy, gx + 5, gy + 5], outline=255)
                d.point([(gx + 2, gy + 2), (gx + 2, gy + 3)], fill=255)
            elif glyph in ("top_tap", "top"):
                d.polygon([(gx + 2, gy), (gx, gy + 5), (gx + 5, gy + 5)], fill=255)
            elif glyph == "top_hold":
                d.polygon([(gx + 2, gy), (gx, gy + 5), (gx + 5, gy + 5)], outline=255)
                d.point([(gx + 2, gy + 3)], fill=255)
            elif glyph in ("btm_tap", "btm"):
                d.polygon([(gx, gy), (gx + 5, gy), (gx + 2, gy + 5)], fill=255)
            elif glyph == "btm_hold":
                d.polygon([(gx, gy), (gx + 5, gy), (gx + 2, gy + 5)], outline=255)
                d.point([(gx + 2, gy + 2)], fill=255)

            text_x = gx + glyph_w + gap
            d.text((text_x, ty), label, font=font, fill=255)

    def draw_control_sidebar(self, d, items):
        self.draw_control_bar(d, items)


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
        pos_str = f"{self.selected + 1}/{len(self.classes)}"
        c.draw_header(d, "GAMES", pos_str, c.W)

        # Rullande fönster för spelen över hela widescreen-bredden (0..c.W-1)
        visible = 3
        scroll = max(0, min(len(self.classes) - visible, self.selected - 1))
        y = 18
        for i in range(scroll, min(len(self.classes), scroll + visible)):
            cls = self.classes[i]
            sel = (i == self.selected)
            if sel:
                d.rectangle([0, y - 1, c.W - 1, y + 13], fill=255)
            d.text((8, y), f"{i + 1}. {cls.name}", font=c.F_SM, fill=0 if sel else 255)
            y += 18

        # Avskiljare och beskrivning (blurb)
        d.line([(0, 74), (c.W - 1, 74)], fill=255)
        blurb = self.classes[self.selected].blurb if self.classes else ""
        for j, line in enumerate(blurb.split("\n")):
            d.text((4, 78 + j * 11), line, font=c.F_XS, fill=255)

        # Liten pil om det finns fler spel längre ner/upp
        if scroll > 0:
            d.polygon([(c.W - 8, 18), (c.W - 12, 23), (c.W - 4, 23)], fill=255)
        if scroll + visible < len(self.classes):
            d.polygon([(c.W - 8, 68), (c.W - 12, 63), (c.W - 4, 63)], fill=255)

        c.draw_control_bar(d, [("rot", "PICK"), ("top_tap", "PLAY"), ("btm_tap", "NEXT")], c.W, c.H)
        return False
