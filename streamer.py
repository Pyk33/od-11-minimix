#!/usr/bin/env python3
"""
OD-11 Minimix – taktil streamer-kontroll (Raspberry Pi 4, SH1106 OLED).

Designprinciper (OB-4-känsla):
  * Noll lagg: encoder -> ALSA sker i callback-tråden utan subprocess/shell.
  * Ingen blockerande I/O i UI- eller GPIO-trådar (status hämtas i egen tråd).
  * Monokrom, avskalad typografi; volym visas som stor overlay när man vrider.

Spotify styrs/läses via go-librespot (lokalt REST-API). AirPlay (shairport-sync)
spelar via samma ALSA-kedja; play/next för AirPlay sker best-effort via playerctl.
"""
import json
import math
import os
import signal
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import alsaaudio
from gpiozero import Button, RotaryEncoder
from luma.core.interface.serial import i2c
from luma.oled.device import sh1106, ssd1306
from PIL import Image, ImageChops, ImageDraw, ImageFont

try:
    import websocket  # websocket-client, för volymsynk med Spotify-appen
except ImportError:
    websocket = None

try:
    import tape_engine
    tape = tape_engine.TapeEngine(sample_rate=48000, tape_minutes=int(os.environ.get("TAPE_MINUTES", "15")))
    alsa_bridge = tape_engine.AlsaTapeBridge(
        tape,
        capture_device=os.environ.get("TAPE_CAPTURE_DEV", "hw:Loopback,1,0"),
        playback_device=os.environ.get("TAPE_PLAYBACK_DEV", "pcm.softvol")
    )
except Exception as _e:
    tape = None
    alsa_bridge = None

# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #
ENC_PIN_A = 17
ENC_PIN_B = 27
BTN_PLAY_PAUSE = 22
BTN_NEXT = 23

API = os.environ.get("LIBRESPOT_API", "http://127.0.0.1:3678")
MIXER_CONTROL = "Master"          # softvol-kontroll skapad av /etc/asound.conf
MIXER_DEVICE = "default"
VOL_MAX = int(os.environ.get("VOL_MAX", "85"))     # skydd för OD-11
VOL_DEFAULT = int(os.environ.get("VOL_DEFAULT", "25"))
ENC_STEPS_PER_PERCENT = float(os.environ.get("ENC_STEPS_PER_PERCENT", "48"))
# LPD3806-600: 48 steg/% => mjuk och precis volymkontroll.
# Justera efter känsla (högre tal = mjukare, lägre = känsligare).
LONG_PRESS_S = 0.5
SHUTDOWN_HOLD_S = 3.0             # håll båda knapparna så länge för att stänga av
SLEEP_AFTER_S = 300               # skärmen släcks efter inaktivitet (ej vid uppspelning)
OVERLAY_S = 1.6

STATE_FILE = Path(__file__).with_name("state.json")
W, H = 128, 64
W_MAIN = 84                          # Vänster visning (0..84). Höger fält (85..127) = 1 cm kontroller-sidebar

# --------------------------------------------------------------------------- #
# Typsnitt (monospace, versaler = TE-känsla)
# --------------------------------------------------------------------------- #
FONT_CANDIDATES = [
    str(Path(__file__).with_name("fonts") / "pixel.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_XS = load_font(9)
F_SM = load_font(10)
F_MD = load_font(13)
F_XL = load_font(40)

# --------------------------------------------------------------------------- #
# Delat tillstånd
# --------------------------------------------------------------------------- #
lock = threading.Lock()
state = {
    "source": "",       # "SPOTIFY" | "AIRPLAY" | ""
    "playing": False,
    "title": "",
    "artist": "",
    "pos_ms": 0,
    "dur_ms": 0,
    "stamp": time.monotonic(),   # när pos_ms hämtades
    "volume": VOL_DEFAULT,
    "muted": False,
    "overlay_until": 0.0,
    "last_input": time.monotonic(),
    "shutting_down": False,
    "mode": "VOL",      # "VOL" | "TAPE" | "LOOP"
}
stop_event = threading.Event()


def touch():
    state["last_input"] = time.monotonic()


# --------------------------------------------------------------------------- #
# Volym (in-process ALSA, ingen fork)
# --------------------------------------------------------------------------- #
mixer = None
_last_apply = 0.0
_save_timer = None


def open_mixer():
    global mixer
    try:
        mixer = alsaaudio.Mixer(MIXER_CONTROL, device=MIXER_DEVICE)
    except alsaaudio.ALSAAudioError:
        mixer = None  # softvol-kontrollen skapas först vid första uppspelning


def load_volume():
    try:
        return max(0, min(VOL_MAX, int(json.loads(STATE_FILE.read_text())["volume"])))
    except Exception:
        return min(VOL_DEFAULT, VOL_MAX)


def save_volume_debounced():
    global _save_timer
    if _save_timer:
        _save_timer.cancel()
    _save_timer = threading.Timer(1.0, _write_state)
    _save_timer.daemon = True
    _save_timer.start()


def _write_state():
    try:
        STATE_FILE.write_text(json.dumps({"volume": state["volume"]}))
    except OSError:
        pass


def apply_volume():
    global mixer, _last_apply
    _last_apply = time.monotonic()
    if mixer is None:
        open_mixer()
    if mixer is None:
        return
    v = 0 if state["muted"] else state["volume"]
    try:
        mixer.setvolume(v)
    except alsaaudio.ALSAAudioError:
        mixer = None


_enc_remainder = 0.0
_last_rot = time.monotonic()


def on_rotated():
    """Körs i gpiozeros tråd – håll den snabb."""
    global _enc_remainder, _last_rot
    now = time.monotonic()
    steps = -encoder.steps
    encoder.steps = 0
    if steps == 0:
        return

    with lock:
        current_mode = state["mode"]

    if current_mode != "VOL" and tape is not None:
        # OB-4 lägen: styr bandspolning, looplängd eller drönarklangfärg
        tape.on_encoder_rotated(steps)
        touch()
        return

    # Mjuk acceleration för volym
    dt = now - _last_rot
    _last_rot = now
    gain = 1.0 if dt > 0.04 else (1.3 if dt > 0.02 else 1.6)
    _enc_remainder += steps * gain / ENC_STEPS_PER_PERCENT
    whole = int(_enc_remainder)
    if whole == 0:
        return
    _enc_remainder -= whole
    with lock:
        if state["muted"] and whole > 0:
            state["muted"] = False
        state["volume"] = max(0, min(VOL_MAX, state["volume"] + whole))
        state["overlay_until"] = now + OVERLAY_S
        touch()
    apply_volume()
    save_volume_debounced()
    request_spotify_volume_push()


# --------------------------------------------------------------------------- #
# Volymsynk med Spotify-appen (go-librespot external_volume: true)
#   app 0..max  <->  Pi 0..VOL_MAX
# --------------------------------------------------------------------------- #
push_event = threading.Event()
_last_local_change = 0.0


def request_spotify_volume_push():
    global _last_local_change
    _last_local_change = time.monotonic()
    push_event.set()


def spotify_push_loop():
    """Skickar encoderns volym till appen (samlar snabba vridningar)."""
    while not stop_event.is_set():
        if not push_event.wait(1.0):
            continue
        push_event.clear()
        stop_event.wait(0.12)
        with lock:
            vol = state["volume"]
        body = json.dumps({"volume": round(vol / max(1, VOL_MAX) * 100)}).encode()
        req = urllib.request.Request(API + "/player/volume", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=0.8).read()
        except Exception:
            pass


def mixer_watch_loop():
    """Följer ändringar av ALSA-reglaget utifrån (AirPlay via shairport-sync)."""
    while not stop_event.is_set():
        stop_event.wait(0.4)
        m = mixer
        if m is None:
            continue
        now = time.monotonic()
        if now - _last_apply < 0.6 or now - _last_local_change < 0.6:
            continue
        try:
            try:
                m.handleevents()
            except Exception:
                pass
            v = int(m.getvolume()[0])
        except Exception:
            continue
        with lock:
            if state["muted"] or v == state["volume"]:
                continue
            state["volume"] = min(v, VOL_MAX)
            state["overlay_until"] = now + OVERLAY_S
            touch()
        if v > VOL_MAX:
            apply_volume()
        save_volume_debounced()
        request_spotify_volume_push()


def spotify_events_loop():
    """Läser volymhändelser från appen och sätter Pi:ns volym."""
    if websocket is None:
        return
    ws_url = API.replace("http://", "ws://").replace("https://", "wss://") + "/events"
    while not stop_event.is_set():
        try:
            ws = websocket.create_connection(ws_url, timeout=5)
            while not stop_event.is_set():
                try:
                    msg = json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if msg.get("type") != "volume":
                    continue
                data = msg.get("data") or {}
                mx = max(1, int(data.get("max", 100)))
                now = time.monotonic()
                if now - _last_local_change < 0.5:      # eko av vår egen ändring
                    continue
                new = max(0, min(VOL_MAX, round(int(data.get("value", 0)) / mx * VOL_MAX)))
                with lock:
                    if new == state["volume"]:
                        continue
                    state["volume"] = new
                    state["muted"] = False
                    state["overlay_until"] = now + OVERLAY_S
                    touch()
                apply_volume()
                save_volume_debounced()
        except Exception:
            stop_event.wait(2.0)


# --------------------------------------------------------------------------- #
# Uppspelningsstyrning
# --------------------------------------------------------------------------- #
def api_call(method, path):
    req = urllib.request.Request(API + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=0.8) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except Exception:
        return None


def player_cmd(spotify_path, playerctl_cmd):
    def run():
        with lock:
            is_spotify = state["source"] == "SPOTIFY"
        if is_spotify and api_call("POST", spotify_path) is not None:
            return
        subprocess.run(["playerctl", playerctl_cmd], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=2, check=False)
    threading.Thread(target=run, daemon=True).start()


def do_playpause():
    with lock:           # optimistisk uppdatering = omedelbar visuell respons
        state["playing"] = not state["playing"]
        touch()
    player_cmd("/player/playpause", "play-pause")


def do_next():
    with lock:
        state["pos_ms"], state["stamp"] = 0, time.monotonic()
        touch()
    player_cmd("/player/next", "next")


def do_prev():
    with lock:
        touch()
    player_cmd("/player/prev", "previous")


def do_mute():
    with lock:
        state["muted"] = not state["muted"]
        state["overlay_until"] = time.monotonic() + OVERLAY_S
        touch()
    apply_volume()


# --- Mode-medvetna knapptryck (OB-4 funktioner) -----------------------------
def on_btn_play_short():
    with lock:
        m = state["mode"]
    if m == "VOL":
        do_playpause()
    elif m == "TAPE":
        if tape:
            behind_sec = tape.get_time_behind_live_sec()
            if behind_sec > 0.08:
                tape.jump_to_live(dj_merge=True)
            else:
                # Vid LIVE: vanlig Play/Pause!
                do_playpause()
        touch()
    elif m == "LOOP":
        if tape:
            tape.toggle_loop_edit_mode()
        touch()


def on_btn_play_long():
    with lock:
        m = state["mode"]
    if m == "VOL":
        behind_sec = tape.get_time_behind_live_sec() if tape else 0.0
        if behind_sec > 1.0:
            if tape:
                tape.jump_to_live(dj_merge=True)
            touch()
        else:
            do_mute()
    elif m == "TAPE":
        if tape:
            tape.jump_to_live(dj_merge=False) # Långtryck = direkt klipp till LIVE utan fade
        touch()
    elif m == "LOOP":
        if tape:
            tape.loop_reverse = not tape.loop_reverse
        touch()


def on_btn_next_short():
    with lock:
        m = state["mode"]
    if m == "VOL":
        do_next()
    else:
        # Växla mellan de kreativa OB-4 lägena: TAPE <-> LOOP
        nxt = tape.cycle_mode() if tape else "VOL"
        with lock:
            state["mode"] = nxt
            touch()


def on_btn_next_long():
    with lock:
        m = state["mode"]
    if m == "VOL":
        # Gå in i OB-4 TAPE mode!
        if tape:
            tape.set_mode(tape.MODE_TAPE)
        with lock:
            state["mode"] = "TAPE"
            touch()
    else:
        # Återgå till standard VOL (fortsätter sömlöst från aktuell punkt)
        if tape:
            tape.set_mode(tape.MODE_VOL)
        with lock:
            state["mode"] = "VOL"
            touch()


combo_active = False   # sant medan båda knapparna hålls ned (enskilda åtgärder ignoreras)


class LongShortButton:
    """Kort tryck vid släpp, långt tryck triggas medan knappen hålls."""

    def __init__(self, pin, short, long_):
        self.btn = Button(pin, pull_up=True, bounce_time=0.03, hold_time=LONG_PRESS_S)
        self.short, self.long_ = short, long_
        self._held = False
        self.btn.when_held = self._on_held
        self.btn.when_released = self._on_release

    def _on_held(self):
        self._held = True
        if not combo_active:
            self.long_()

    def _on_release(self):
        if not self._held and not combo_active:
            self.short()
        self._held = False


def do_poweroff():
    with lock:
        state["shutting_down"] = True
        touch()
    time.sleep(1.5)   # låt skärmen visa meddelandet
    subprocess.run(["sudo", "-n", "shutdown", "-h", "now"], check=False)


def combo_watcher(buttons):
    """Håll båda knapparna SHUTDOWN_HOLD_S sekunder => stäng av Pi:n."""
    global combo_active
    since = None
    while not stop_event.is_set():
        try:
            pressed = [b.btn.is_pressed for b in buttons]
        except Exception:
            break
        if all(pressed):
            combo_active = True
            if since is None:
                since = time.monotonic()
            elif time.monotonic() - since >= SHUTDOWN_HOLD_S:
                do_poweroff()
                return
        else:
            since = None
            if not any(pressed):
                combo_active = False
        stop_event.wait(0.02)


# --------------------------------------------------------------------------- #
# Status-poller (egen tråd – blockerar aldrig UI)
# --------------------------------------------------------------------------- #
def playerctl_status():
    try:
        out = subprocess.run(
            ["playerctl", "metadata", "--format", "{{status}}|{{title}}|{{artist}}"],
            capture_output=True, text=True, timeout=1.5).stdout.strip()
        if not out:
            return None
        status, title, artist = (out.split("|") + ["", ""])[:3]
        return status, title, artist
    except Exception:
        return None


def poll_loop():
    while not stop_event.is_set():
        st = api_call("GET", "/status")
        now = time.monotonic()
        with lock:
            if st and not st.get("stopped", True):
                tr = st.get("track") or {}
                state.update(
                    source="SPOTIFY",
                    playing=not st.get("paused", False),
                    title=tr.get("name", ""),
                    artist=", ".join(tr.get("artist_names") or []),
                    pos_ms=tr.get("position", 0),
                    dur_ms=tr.get("duration", 0),
                    stamp=now,
                )
                nxt = 0.5
            else:
                nxt = 1.0
                state["source"] = ""
        if nxt == 1.0:
            pc = playerctl_status()
            with lock:
                if pc and pc[0] in ("Playing", "Paused"):
                    state.update(source="AIRPLAY", playing=pc[0] == "Playing",
                                 title=pc[1], artist=pc[2], pos_ms=0, dur_ms=0, stamp=now)
                else:
                    state.update(playing=False, title="", artist="", pos_ms=0, dur_ms=0)
        stop_event.wait(nxt)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def text_w(draw, s, font):
    return draw.textlength(s, font=font)


def marquee(draw, xy, s, font, width, t, fill=255):
    """Ritar text; scrollar horisontellt (paus i start/slut) om den är för lång."""
    x, y = xy
    tw = text_w(draw, s, font)
    if tw <= width:
        draw.text((x, y), s, font=font, fill=fill)
        return False
    over = tw - width
    cycle = over / 22.0 + 3.0           # 22 px/s + 1.5 s paus per ände
    ph = t % cycle
    off = 0 if ph < 1.5 else min(over, (ph - 1.5) * 22.0)
    layer = Image.new("1", (width, 16), 0)
    ImageDraw.Draw(layer).text((-off, 0), s, font=font, fill=1)
    draw.bitmap((x, y), layer, fill=fill)
    return True


def seg_bar(draw, x, y, w, h, frac, segs=24):
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


def draw_control_sidebar(d, items):
    """
    Ritar en 1 cm (~43 px) bred TE-inspirerad kommandokolumn på höger sida (x=84..127).
    Visar exakt vad de 5 kontrollerna gör i aktivt läge:
      1. Rotor (ratt)
      2. Övre knapp kort (Tap)
      3. Övre knapp långt (Hold)
      4. Nedre knapp kort (Tap)
      5. Nedre knapp långt (Hold)
    """
    d.line([(W_MAIN, 0), (W_MAIN, 63)], fill=255)
    row_y = [1, 13, 26, 39, 51]
    for i, (glyph, label) in enumerate(items):
        y = row_y[i]
        gx = W_MAIN + 3
        gy = y + 1

        if glyph == "rot":
            d.ellipse([gx, gy, gx + 6, gy + 6], outline=255)
            d.point([(gx + 3, gy + 3), (gx + 3, gy + 1), (gx + 1, gy + 3)], fill=255)
        elif glyph == "top_tap":
            # Solid fylld upp-pil (Övre knapp kort tryck)
            d.polygon([(gx + 3, gy + 1), (gx, gy + 7), (gx + 6, gy + 7)], fill=255)
        elif glyph == "top_hold":
            # Vinkel-pil / förgrening ↳ (Övre knapp långt tryck / håll)
            d.line([(gx + 2, gy), (gx + 2, gy + 5)], fill=255)
            d.line([(gx + 2, gy + 5), (gx + 6, gy + 5)], fill=255)
            d.line([(gx + 5, gy + 3), (gx + 7, gy + 5)], fill=255)
            d.line([(gx + 5, gy + 7), (gx + 7, gy + 5)], fill=255)
        elif glyph == "btm_tap":
            # Solid fylld ner-pil (Nedre knapp kort tryck)
            d.polygon([(gx, gy + 1), (gx + 6, gy + 1), (gx + 3, gy + 7)], fill=255)
        elif glyph == "btm_hold":
            # Vinkel-pil / förgrening ↳ (Nedre knapp långt tryck / håll)
            d.line([(gx + 2, gy), (gx + 2, gy + 5)], fill=255)
            d.line([(gx + 2, gy + 5), (gx + 6, gy + 5)], fill=255)
            d.line([(gx + 5, gy + 3), (gx + 7, gy + 5)], fill=255)
            d.line([(gx + 5, gy + 7), (gx + 7, gy + 5)], fill=255)

        d.text((gx + 9, y), label, font=F_XS, fill=255)


def render_tape_view(d, s, t):
    behind_sec = tape.get_time_behind_live_sec() if tape else 0.0
    speed = tape.speed if tape else 1.0
    is_merging = getattr(tape, "is_dj_merging", False) if tape else False
    is_playing = s.get("playing", True)

    d.rectangle([0, 0, 30, 9], fill=255)
    d.text((2, 0), "TAPE", font=F_XS, fill=0)

    if is_merging:
        status = "MERGE"
    elif behind_sec < 0.08:
        status = "LIVE"
    else:
        status = f"-{int(behind_sec//60):02d}:{int(behind_sec%60):02d}"
    d.text((W_MAIN - text_w(d, status, F_XS) - 2, 0), status, font=F_XS, fill=255)
    d.line([(0, 10), (W_MAIN, 10)], fill=255)

    if not is_playing:
        angle_l, angle_r = 0.0, 0.0
    else:
        angle_l = t * speed * 4.0
        angle_r = t * speed * 3.5

    # Rullbandshjul placerade symmetriskt i 0..W_MAIN
    draw_tape_reel(d, 22, 29, 10, angle_l)
    draw_tape_reel(d, 62, 29, 10, angle_r)

    d.line([(22, 19), (62, 19)], fill=255)
    d.line([(22, 39), (62, 39)], fill=255)

    d.rectangle([38, 23, 46, 35], outline=255)
    d.line([(42, 25), (42, 33)], fill=255)

    if not is_playing:
        sp_str = "PAUSED"
    elif is_merging:
        sp_str = "MERGING..."
    elif behind_sec < 0.08:
        sp_str = "LIVE"
    elif abs(speed - 1.0) > 0.15:
        sp_str = f"SCR {speed:+.1f}x"
    else:
        sp_str = "PLAYING"
    d.text((2, 53), sp_str, font=F_XS, fill=255)

    # 1 cm sidebar kontroller
    if behind_sec > 0.08 and not is_merging:
        top_tap = "LIVE"
    elif not is_playing:
        top_tap = "PLAY"
    else:
        top_tap = "PAUS"

    tape_items = [
        ("rot", "SCRUB"),
        ("top_tap", top_tap),
        ("top_hold", "CUT"),
        ("btm_tap", "LOOP"),
        ("btm_hold", "VOL"),
    ]
    draw_control_sidebar(d, tape_items)


def render_loop_view(d, s, t):
    loop_sec = tape.loop_length_s if tape else 2.0
    edit_mode = getattr(tape, "loop_edit_mode", "SIZE") if tape else "SIZE"

    # Header: LOOP badge till vänster, aktivt läge (SIZE eller MOVE) till höger
    d.rectangle([0, 0, 26, 9], fill=255)
    d.text((2, 0), "LOOP", font=F_XS, fill=0)

    d.text((W_MAIN - text_w(d, edit_mode, F_XS) - 2, 0), edit_mode, font=F_XS, fill=255)
    d.line([(0, 10), (W_MAIN, 10)], fill=255)

    # Loop-fönster med faslåst playhead i perfekt synk med ljudet
    box_x0, box_y0, box_x1, box_y1 = 4, 15, 80, 34
    d.rectangle([box_x0, box_y0, box_x1, box_y1], outline=255)

    frac = tape.get_loop_progress() if tape else 0.0
    head_x = box_x0 + frac * (box_x1 - box_x0)
    d.line([(head_x, box_y0 + 2), (head_x, box_y1 - 2)], fill=255, width=2)

    for seg in range(1, 4):
        sx = box_x0 + seg * (box_x1 - box_x0) / 4.0
        d.line([(sx, box_y1 - 3), (sx, box_y1 - 1)], fill=255)

    # Under loopen:
    # 1. Hur mycket vi loopar (loop-längd)
    sec_str = f"{loop_sec:.3f}s" if loop_sec < 0.5 else (f"{loop_sec:.2f}s" if loop_sec < 1.0 else f"{loop_sec:.1f}s")
    if tape and getattr(tape, "loop_reverse", False):
        sec_str += " REV"
    d.text((4, 38), f"LEN: {sec_str}", font=F_XS, fill=255)

    # 2. Var i låten vi loopar (spårposition eller tid bakom live)
    behind_sec = tape.get_loop_behind_live_sec() if (tape and hasattr(tape, "get_loop_behind_live_sec")) else (
        tape.get_time_behind_live_sec() if tape else 0.0
    )
    now = time.monotonic()
    if s["dur_ms"] > 0:
        live_song_ms = s["pos_ms"] + ((now - s["stamp"]) * 1000 if s["playing"] else 0)
        loop_song_ms = max(0, live_song_ms - behind_sec * 1000)
        mm = int(loop_song_ms // 60000)
        ss = int((loop_song_ms // 1000) % 60)
        pos_str = f"{mm:02d}:{ss:02d}"
    else:
        mm = int(behind_sec // 60)
        ss = int(behind_sec % 60)
        pos_str = f"-{mm:02d}:{ss:02d}"
    d.text((4, 50), f"AT:  {pos_str}", font=F_XS, fill=255)

    loop_items = [
        ("rot", edit_mode),
        ("top_tap", "SWAP"),
        ("top_hold", "REV"),
        ("btm_tap", "TAPE"),
        ("btm_hold", "VOL"),
    ]
    draw_control_sidebar(d, loop_items)


def render(t):
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    with lock:
        s = dict(state)
    now = time.monotonic()
    animating = False

    if s["shutting_down"]:
        for i, line in enumerate(("SHUTTING", "DOWN...")):
            w = text_w(d, line, F_MD)
            d.text(((W - w) / 2, 14 + i * 18), line, font=F_MD, fill=255)
        return img, False

    # --- OB-4 Speciallägen (TAPE & LOOP) -------------------------------------
    if s["mode"] == "TAPE":
        render_tape_view(d, s, t)
        return img, True
    elif s["mode"] == "LOOP":
        render_loop_view(d, s, t)
        return img, True

    if now < s["overlay_until"]:
        # --- Volym-overlay i vänstra visningsfältet 0..W_MAIN -----------------
        label = "MUTE" if s["muted"] else f"{s['volume']:d}"
        font = F_MD if s["muted"] else F_XL
        w = text_w(d, label, font)
        d.text(((W_MAIN - w) / 2, 2 if not s["muted"] else 14), label, font=font, fill=255)
        d.text((2, 54), "VOL", font=F_XS, fill=255)
        seg_bar(d, 22, 54, W_MAIN - 24, 8, 0 if s["muted"] else s["volume"] / max(1, VOL_MAX), 14)
    else:
        # --- Topprad --------------------------------------------------------
        src = s["source"] or "OD-11"
        d.text((2, 0), src, font=F_XS, fill=255)
        behind_sec = tape.get_time_behind_live_sec() if tape else 0.0
        if behind_sec > 1.5:
            stat = f"-{int(behind_sec//60):02d}:{int(behind_sec%60):02d}"
        else:
            stat = "PLAY" if s["playing"] and s["source"] else ("PAUS" if s["source"] else "RDY")
        d.text((W_MAIN - 2 - text_w(d, stat, F_XS), 0), stat, font=F_XS, fill=255)
        d.line([(0, 11), (W_MAIN, 11)], fill=255)

        # --- Titel/artist ---------------------------------------------------
        if s["source"]:
            animating |= marquee(d, (2, 16), s["title"].upper() or "-", F_SM, W_MAIN - 4, t)
            animating |= marquee(d, (2, 31), s["artist"].upper() or "-", F_XS, W_MAIN - 4, t)
        else:
            d.text((2, 18), "OLLE'S", font=F_SM, fill=255)
            d.text((2, 32), "MINIMIX", font=F_XS, fill=255)

        # --- Progress (1 px linje i 0..W_MAIN) ------------------------------
        if s["dur_ms"] > 0:
            pos = s["pos_ms"] + ((now - s["stamp"]) * 1000 if s["playing"] else 0)
            frac = max(0.0, min(1.0, pos / s["dur_ms"]))
            d.line([(2, 46), (W_MAIN - 3, 46)], fill=255)
            x = 2 + frac * (W_MAIN - 5)
            d.rectangle([x - 1, 43, x + 1, 49], fill=255)
            animating |= s["playing"]
            mm = int(pos // 60000)
            ss = int(pos // 1000 % 60)
            d.text((2, 53), f"{mm}:{ss:02d}", font=F_XS, fill=255)
        else:
            d.line([(2, 46), (W_MAIN - 3, 46)], fill=255)
            vtxt = "MUTE" if s["muted"] else f"VOL {s['volume']}"
            d.text((2, 53), vtxt, font=F_XS, fill=255)

    # --- Dedikerad 1cm sidebar på höger sida (x=84..127) för alla VOL-kontroller ---
    is_playing = s.get("playing", True)
    behind_sec = tape.get_time_behind_live_sec() if tape else 0.0
    top_hold_lbl = "LIVE" if behind_sec > 1.0 else "MUTE"
    vol_items = [
        ("rot", "VOL"),
        ("top_tap", "PAUS" if is_playing else "PLAY"),
        ("top_hold", top_hold_lbl),
        ("btm_tap", "NEXT"),
        ("btm_hold", "TAPE"),
    ]
    draw_control_sidebar(d, vol_items)
    return img, animating


def ui_loop(device):
    last = None
    asleep = False
    t0 = time.monotonic()
    while not stop_event.is_set():
        now = time.monotonic()
        with lock:
            idle = now - state["last_input"]
            playing = state["playing"]
        if idle > SLEEP_AFTER_S and not playing:
            if not asleep:
                device.hide()
                asleep = True
            stop_event.wait(0.2)
            continue
        if asleep:
            device.show()
            asleep = False
            last = None

        img, animating = render(now - t0)
        if last is None or ImageChops.difference(img, last).getbbox():
            device.display(img)
            last = img
        stop_event.wait(1 / 30 if animating else 0.1)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def shutdown(*_):
    stop_event.set()


def main():
    global encoder
    driver = ssd1306 if os.environ.get("OLED_DRIVER", "sh1106").lower() == "ssd1306" else sh1106
    try:
        device = driver(i2c(port=1, address=0x3C))
        device.contrast(200)
    except Exception as exc:
        print(f"OLED saknas ({exc}) - k\u00f6r utan sk\u00e4rm", flush=True)

        class NullDevice:
            def display(self, *_): pass
            def show(self): pass
            def hide(self): pass
            def clear(self): pass
            def contrast(self, *_): pass

        device = NullDevice()

    state["volume"] = load_volume()
    open_mixer()
    apply_volume()

    encoder = RotaryEncoder(ENC_PIN_A, ENC_PIN_B, max_steps=0, wrap=False)
    encoder.when_rotated = lambda: on_rotated()
    buttons = [
        LongShortButton(BTN_PLAY_PAUSE, on_btn_play_short, on_btn_play_long),
        LongShortButton(BTN_NEXT, on_btn_next_short, on_btn_next_long),
    ]

    if alsa_bridge is not None:
        alsa_bridge.start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=combo_watcher, args=(buttons,), daemon=True).start()
    threading.Thread(target=spotify_events_loop, daemon=True).start()
    threading.Thread(target=spotify_push_loop, daemon=True).start()
    threading.Thread(target=mixer_watch_loop, daemon=True).start()

    # softvol-kontrollen dyker upp först efter första uppspelningen – försök igen
    threading.Thread(target=lambda: [apply_volume() or stop_event.wait(5) for _ in range(12)],
                     daemon=True).start()

    try:
        ui_loop(device)
    finally:
        if alsa_bridge is not None:
            alsa_bridge.stop()
        _write_state()
        device.clear()
        encoder.close()
        for b in buttons:
            b.btn.close()


if __name__ == "__main__":
    main()