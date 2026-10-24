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

try:
    import alsaaudio
except ImportError:
    alsaaudio = None

try:
    from gpiozero import Button, RotaryEncoder
except ImportError:
    Button, RotaryEncoder = None, None

try:
    from luma.core.interface.serial import i2c
except ImportError:
    i2c = None
try:
    from luma.oled.device import sh1106, ssd1306, sh1107
except ImportError:
    try:
        from luma.oled.device import sh1106, ssd1306
    except ImportError:
        sh1106, ssd1306 = None, None
    sh1107 = None
from PIL import Image, ImageChops, ImageDraw, ImageFont

try:
    import websocket  # websocket-client, för volymsynk med Spotify-appen
except ImportError:
    websocket = None

try:
    import games as games_pkg   # minispel (Hitster m.fl.)
except Exception as _ge:
    games_pkg = None

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
BTN_PLAY_PAUSE = 23   # övre knappen (längst från användaren)
BTN_NEXT = 22         # nedre knappen (närmast användaren)

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
W = int(os.environ.get("OLED_WIDTH", "128"))
H = int(os.environ.get("OLED_HEIGHT", "128" if os.environ.get("OLED_DRIVER", "sh1107").lower() == "sh1107" else "64"))
W_MAIN = W                                # 128 = full widescreen för alla aktiviteter och dashboards

# --------------------------------------------------------------------------- #
# Typsnitt (monospace, versaler = TE-känsla)
# --------------------------------------------------------------------------- #
FONT_CANDIDATES = [
    str(Path(__file__).with_name("fonts") / "pixel.ttf"),
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Monaco.ttf",
    "/Library/Fonts/Arial.ttf",
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
F_BIG = load_font(24)

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
    "loop_anchor_dur_ms": 0,
    "loop_anchor_live_song_ms": 0,
    "cut_flash_until": 0.0,
}
stop_event = threading.Event()


def touch():
    state["last_input"] = time.monotonic()


_games_mgr = None


def get_games():
    """Skapar minispelshubben första gången (W/H är då slutgiltigt satta av main())."""
    global _games_mgr
    if _games_mgr is None and games_pkg is not None:
        ctx = games_pkg.GameContext(
            W=W, H=H, W_MAIN=W_MAIN, F_XS=F_XS, F_SM=F_SM, F_MD=F_MD, F_BIG=F_BIG, F_XL=F_XL,
            text_w=text_w, marquee=marquee, draw_control_sidebar=draw_control_bar,
            draw_control_bar=draw_control_bar, draw_header=draw_header,
            api_call=api_call, tape=tape, draw_tape_reel=draw_tape_reel,
        )
        _games_mgr = games_pkg.GameManager(ctx)
    return _games_mgr


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

    if current_mode == "GAMES":
        mgr = get_games()
        if mgr:
            mgr.rotate(steps)
            with lock:
                touch()
        return

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
def api_call(method, path, body=None, timeout=1.0):
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    else:
        data = b"" if method == "POST" else None
        headers = {}
    req = urllib.request.Request(API + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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


def do_dj_next(seek_s: float = 18.0):
    """
    DJ Smart Transition: Byter till nästa låt och hoppar direkt ~18 sekunder in
    så att crossfaden landar djupt i låtens aktiva beat/groove istället för ett tyst intro.
    """
    def run():
        with lock:
            is_spotify = state["source"] == "SPOTIFY"

        if not is_spotify:
            subprocess.run(["playerctl", "next"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=2, check=False)
            time.sleep(0.5)
            if tape:
                tape.notify_track_switched()
            return

        s0 = api_call("GET", "/status") or {}
        t0 = s0.get("track") or {}
        uri0 = t0.get("uri")

        # Hoppa till nästa låt på Spotify
        api_call("POST", "/player/next")

        # Vänta på att go-librespot byter track URI och sök direkt till ~18s
        start_t = time.monotonic()
        while time.monotonic() - start_t < 4.0:
            time.sleep(0.04)
            s1 = api_call("GET", "/status") or {}
            t1 = s1.get("track") or {}
            uri1 = t1.get("uri")
            if uri1 and uri1 != uri0:
                dur = t1.get("duration") or 180000
                seek_ms = int(seek_s * 1000) if dur > (seek_s * 2000) else int(dur * 0.15)
                api_call("POST", "/player/seek", {"position": seek_ms})
                with lock:
                    state["pos_ms"] = seek_ms
                    state["stamp"] = time.monotonic()
                    touch()
                break

        if tape:
            tape.notify_track_switched()

    threading.Thread(target=run, daemon=True).start()


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
    if m == "GAMES":
        mgr = get_games()
        if mgr:
            mgr.button("play")
        with lock:
            touch()
        return
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
    elif m == "DJ":
        if tape:
            tape.trigger_dj_brake(False)
            if getattr(tape, "is_dj_transition", False):
                tape.end_dj_transition()
            else:
                tape.start_dj_transition()
                do_dj_next(seek_s=18.0)
        touch()


def on_btn_play_long():
    with lock:
        m = state["mode"]
    if m == "GAMES":
        mgr = get_games()
        if mgr:
            mgr.button("play_hold")
        with lock:
            touch()
        return
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
            with lock:
                state["cut_flash_until"] = time.monotonic() + 0.8
        touch()
    elif m == "LOOP":
        if tape:
            tape.start_dj_transition(from_loop=getattr(tape, "loop_active", False))
            with lock:
                state["mode"] = "DJ"
            do_dj_next(seek_s=18.0)
        touch()
    elif m == "DJ":
        if tape:
            tape.trigger_dj_brake(True)
        touch()


def on_btn_play_release():
    with lock:
        m = state["mode"]
    if m == "DJ":
        if tape:
            tape.trigger_dj_brake(False)
        touch()


def on_btn_next_short():
    with lock:
        m = state["mode"]
    if m == "VOL":
        do_next()
    elif m == "DJ" and get_games() is not None:
        # Sista fliken i cirkeln (TAPE -> LOOP -> DJ) -> MINISPEL
        if tape:
            tape.set_mode(tape.MODE_VOL)     # rena ljudet medan man spelar
        get_games().enter()
        with lock:
            state["mode"] = "GAMES"
            touch()
    elif m == "GAMES":
        if get_games().button("next") == "leave":      # hubben: nästa flik = TAPE igen
            if tape:
                tape.set_mode(tape.MODE_TAPE)
            with lock:
                state["mode"] = "TAPE"
        with lock:
            touch()
    else:
        # Växla mellan de kreativa OB-4 lägena: TAPE <-> LOOP
        nxt = tape.cycle_mode() if tape else "VOL"
        with lock:
            state["mode"] = nxt
            if nxt == "LOOP":
                now = time.monotonic()
                state["loop_anchor_dur_ms"] = state["dur_ms"]
                state["loop_anchor_live_song_ms"] = state["pos_ms"] + ((now - state["stamp"]) * 1000 if state["playing"] else 0)
            touch()


def on_btn_next_long():
    with lock:
        m = state["mode"]
    if m == "GAMES" and get_games() is not None:
        get_games().exit()     # pausar ev. spel-låt och tystar spelet
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

    def __init__(self, pin, short, long_, release_long=None):
        self.btn = Button(pin, pull_up=True, bounce_time=0.03, hold_time=LONG_PRESS_S)
        self.short, self.long_, self.release_long = short, long_, release_long
        self._held = False
        self.btn.when_held = self._on_held
        self.btn.when_released = self._on_release

    def _on_held(self):
        self._held = True
        if not combo_active:
            self.long_()

    def _on_release(self):
        if self._held:
            if self.release_long and not combo_active:
                self.release_long()
        elif not combo_active:
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


def draw_header(d, badge, status="", W_val=None):
    """Ritar TE-standard header i toppen (y=0..13) med inverterad badge och status."""
    w = W_val if W_val is not None else W
    bw = int(text_w(d, badge, F_XS)) + 8
    d.rectangle([0, 0, bw, 12], fill=255)
    d.text((4, 1), badge, font=F_XS, fill=0)
    if status:
        sw = text_w(d, status, F_XS)
        d.text((w - sw - 2, 1), status, font=F_XS, fill=255)
    d.line([(0, 13), (w - 1, 13)], fill=255)


def draw_control_bar(d, items, W_val=None, H_val=None):
    """
    Ritar en kompakt och stilren Teenage Engineering-inspirerad bottenrad (y = H-15 .. H-1).
    Ger 128px widescreen bredd (0..W-1) åt alla dashboards ovanför.
    """
    w = W_val if W_val is not None else W
    h = H_val if H_val is not None else H

    # TE-ordbok för korta, stilrena förkortningar som aldrig krockar i 3-kolumnsläge
    ABBREV = {
        "FILTER": "FLTR",
        "PLAYERS": "PLRS",
        "PLAYER": "PLR",
        "CANCEL": "BACK",
        "REVERSE": "REV",
        "REPLAY": "RPLY",
        "RESET": "RST",
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

    # Om vi fick det gamla 5-raders formatet (rot, top_tap, top_hold, btm_tap, btm_hold),
    # välj ut de 3 primära knapparna (rot, top_tap, btm_tap)
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

        tw = text_w(d, label, F_XS)
        glyph_w = 6 if glyph in ("rot", "top_tap", "top_hold", "btm_tap", "btm_hold", "top", "btm") else 0
        gap = 2 if glyph_w > 0 else 0
        total_w = glyph_w + gap + tw

        # Rita diskret skiljelinje mellan kolumnerna
        if i > 0 and n <= 3:
            d.line([(x0, y_bar + 4), (x0, h - 4)], fill=255)

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
        d.text((text_x, ty), label, font=F_XS, fill=255)


def draw_control_sidebar(d, items):
    """Bakåtkompatibel alias som nu vidarebefordrar till widescreen draw_control_bar."""
    draw_control_bar(d, items, W, H)


def render_tape_view(d, s, t):
    now = time.monotonic()
    behind_sec = tape.get_time_behind_live_sec() if tape else 0.0
    speed = tape.speed if tape else 1.0
    is_merging = getattr(tape, "is_dj_merging", False) if tape else False
    is_playing = s.get("playing", True)
    is_cut_flash = now < s.get("cut_flash_until", 0.0)

    if is_cut_flash:
        status = "[CUT]"
    elif is_merging:
        merge_p = tape.get_merge_progress() if hasattr(tape, "get_merge_progress") else 0.5
        status = f"MRG {int(merge_p * 100)}%"
    elif behind_sec < 0.08:
        status = "LIVE"
    else:
        tot_s = int(round(behind_sec))
        status = f"-{tot_s//60:02d}:{tot_s%60:02d}"

    draw_header(d, "TAPE", status, W)

    if not is_playing:
        angle_l, angle_r = 0.0, 0.0
    else:
        angle_l = t * speed * 4.0
        angle_r = t * speed * 3.5

    # Stora symmetriska TE-rullar centrerade i W=128
    draw_tape_reel(d, 34, 44, 18, angle_l)
    draw_tape_reel(d, 94, 44, 18, angle_r)
    d.line([(34, 26), (94, 26)], fill=255)
    d.line([(34, 62), (94, 62)], fill=255)

    # Tonhuvud i mitten
    d.rectangle([58, 36, 70, 52], outline=255)
    d.line([(64, 38), (64, 50)], fill=255)

    if is_merging:
        merge_p = tape.get_merge_progress() if hasattr(tape, "get_merge_progress") else 0.5
        bx0, by0, bx1, by1 = 12, 68, W - 12, 74
        d.rectangle([bx0, by0, bx1, by1], outline=255)
        bar_w = int(merge_p * (bx1 - bx0 - 2))
        if bar_w > 0:
            d.rectangle([bx0 + 1, by0 + 1, bx0 + 1 + bar_w, by1 - 1], fill=255)

    if is_cut_flash:
        sp_str = "[CUT TO LIVE!]"
    elif not is_playing:
        sp_str = "PAUSED"
    elif is_merging:
        merge_p = tape.get_merge_progress() if hasattr(tape, "get_merge_progress") else 0.5
        sp_str = f"DJ MERGE {int(merge_p * 100)}%"
    elif behind_sec < 0.08:
        sp_str = "LIVE"
    elif abs(speed - 1.0) > 0.15:
        sp_str = f"SCR {speed:+.1f}x"
    else:
        sp_str = "PLAYING"

    d.text((4, 76), sp_str, font=F_MD, fill=255)
    if behind_sec >= 0.08:
        tot_s = int(round(behind_sec))
        d.text((4, 94), f"DELAY {tot_s//60:02d}:{tot_s%60:02d}", font=F_XS, fill=255)
        buf_frac = min(1.0, behind_sec / 60.0)
        d.line([(4, 105), (W - 4, 105)], fill=255)
        cx = 4 + int(buf_frac * (W - 8))
        d.rectangle([cx - 2, 102, cx + 2, 108], fill=255)
    else:
        d.text((4, 94), "BUFFER READY", font=F_XS, fill=255)
        d.text((4, 104), "TURN TO SCRUB", font=F_XS, fill=255)

    if behind_sec > 0.08:
        top_tap = "MERGE"
    elif not is_playing:
        top_tap = "PLAY"
    else:
        top_tap = "PAUS"

    tape_items = [
        ("rot", "SCRUB"),
        ("top_tap", top_tap),
        ("btm_tap", "LOOP"),
    ]
    draw_control_bar(d, tape_items, W, H)


def render_loop_view(d, s, t):
    loop_active = getattr(tape, "loop_active", False) if tape else False
    loop_sec = tape.loop_length_s if tape else 2.0
    edit_mode = getattr(tape, "loop_edit_mode", "SIZE") if tape else "SIZE"
    loop_name = tape.get_loop_label() if (tape and hasattr(tape, "get_loop_label")) else (
        getattr(tape, "loop_name", "1 BAR") if tape else "1 BAR"
    )
    loop_bpm = tape.get_loop_bpm() if (tape and hasattr(tape, "get_loop_bpm")) else (
        getattr(tape, "loop_bpm", 120.0) if tape else 120.0
    )
    loop_beats = tape.get_loop_beats() if (tape and hasattr(tape, "get_loop_beats")) else (
        getattr(tape, "loop_beats", 4.0) if tape else 4.0
    )

    if not loop_active:
        tag = "[ARMED]"
    else:
        tag = "[SIZE] MOVE" if edit_mode == "SIZE" else "SIZE [MOVE]"
    draw_header(d, "LOOP", tag, W)

    # 1. Zoomad loop-box i widescreen
    box_x0, box_y0, box_x1, box_y1 = 4, 18, W - 4, 64
    d.rectangle([box_x0, box_y0, box_x1, box_y1], outline=255)

    if not loop_active:
        prompt_txt = "TURN TO LOOP"
        pt_w = text_w(d, prompt_txt, F_XS)
        pt_x = box_x0 + (box_x1 - box_x0 - pt_w) // 2
        d.text((pt_x, box_y0 + (box_y1 - box_y0 - 8) // 2), prompt_txt, font=F_XS, fill=255)
    else:
        frac = tape.get_loop_progress() if tape else 0.0
        head_x = box_x0 + frac * (box_x1 - box_x0)
        d.line([(head_x, box_y0 + 2), (head_x, box_y1 - 2)], fill=255, width=2)

        num_subdiv = int(loop_beats) if (1 < loop_beats <= 8) else 4
        for seg in range(1, num_subdiv):
            sx = box_x0 + seg * (box_x1 - box_x0) / float(num_subdiv)
            d.line([(sx, box_y1 - 4), (sx, box_y1 - 1)], fill=255)

    # 2. Text under loopen
    info_str = f"{loop_name}  {int(round(loop_bpm))}BPM  {loop_sec:.1f}S"
    d.text((4, 70), info_str, font=F_SM, fill=255)

    # 3. Låtens tidslinje (Timeline)
    tl_x0, tl_x1 = 4, W - 4
    tl_y = 94
    d.line([(tl_x0, tl_y), (tl_x1, tl_y)], fill=255)
    d.line([(tl_x0, tl_y - 2), (tl_x0, tl_y + 2)], fill=255)
    d.line([(tl_x1, tl_y - 2), (tl_x1, tl_y + 2)], fill=255)

    dur_ms = s.get("dur_ms", 0)
    pos_ms = s.get("pos_ms", 0)

    if not loop_active:
        behind_sec = tape.get_time_behind_live_sec() if tape else 0.0
        if dur_ms > 0:
            curr_pos_ms = pos_ms + ((time.monotonic() - s["stamp"]) * 1000 if s["playing"] else 0) - (behind_sec * 1000)
            song_frac = max(0.0, min(1.0, curr_pos_ms / dur_ms))
        else:
            song_frac = max(0.0, min(1.0, 1.0 - behind_sec / 60.0))

        px = int(tl_x0 + song_frac * (tl_x1 - tl_x0))
        d.rectangle([px - 2, tl_y - 4, px + 2, tl_y + 4], fill=255)
    else:
        behind_sec = tape.get_loop_behind_live_sec() if (tape and hasattr(tape, "get_loop_behind_live_sec")) else (
            tape.get_time_behind_live_sec() if tape else 0.0
        )
        anchor_dur = s.get("loop_anchor_dur_ms", 0) or dur_ms
        anchor_live_ms = s.get("loop_anchor_live_song_ms", 0)
        if anchor_live_ms <= 0 and dur_ms > 0:
            anchor_live_ms = pos_ms + ((time.monotonic() - s["stamp"]) * 1000 if s["playing"] else 0)

        if anchor_dur > 0:
            loop_start_ms = max(0, anchor_live_ms - behind_sec * 1000)
            loop_end_ms = min(anchor_dur, loop_start_ms + loop_sec * 1000)
            start_frac = max(0.0, min(1.0, loop_start_ms / anchor_dur))
            end_frac = max(0.0, min(1.0, loop_end_ms / anchor_dur))
        else:
            window_s = 60.0
            start_frac = max(0.0, min(1.0, 1.0 - (behind_sec + loop_sec) / window_s))
            end_frac = max(0.0, min(1.0, 1.0 - behind_sec / window_s))

        lx0 = int(tl_x0 + start_frac * (tl_x1 - tl_x0))
        lx1 = int(tl_x0 + end_frac * (tl_x1 - tl_x0))
        if lx1 - lx0 < 6:
            lx1 = min(tl_x1, lx0 + 6)
        if lx1 - lx0 < 6:
            lx0 = max(tl_x0, lx1 - 6)

        d.rectangle([lx0, tl_y - 4, lx1, tl_y + 4], fill=255)
        frac = tape.get_loop_progress() if tape else 0.0
        in_x = lx0 + int(frac * (lx1 - lx0))
        d.line([(in_x, tl_y - 3), (in_x, tl_y + 3)], fill=0)

    d.text((4, 103), "[SWAP] EDIT" if loop_active else "OB-4 READY", font=F_XS, fill=255)

    loop_items = [
        ("rot", "LOOP" if not loop_active else edit_mode),
        ("top_tap", "START" if not loop_active else "SWAP"),
        ("btm_tap", "DJ"),
    ]
    draw_control_bar(d, loop_items, W, H)


def render_dj_view(d, s, t):
    filt_val = getattr(tape, "dj_filter_val", 0.0) if tape else 0.0
    is_brake = getattr(tape, "dj_brake_active", False) if tape else False
    is_trans = getattr(tape, "is_dj_transition", False) if tape else False
    trans_p = getattr(tape, "dj_trans_progress", 0.0) if tape else 0.0
    bpm = getattr(tape, "dj_trans_bpm", 120.0) if tape else 120.0

    trans_state = getattr(tape, "dj_trans_state", "CROSSFADING") if tape else "CROSSFADING"

    if is_trans:
        f_tag = ""
        if abs(filt_val) >= 0.05:
            f_tag = " LPF" if filt_val < 0 else " HPF"
        if trans_state == "WAIT_AUDIO":
            stat = f"{int(bpm)}BPM WAIT{f_tag}"
        elif trans_state == "ALIGN_BEAT":
            stat = f"{int(bpm)}BPM SYNC{f_tag}"
        else:
            stat = f"{int(bpm)}BPM {int(trans_p * 100)}%{f_tag}"
    elif is_brake:
        stat = "[BRAKE]"
    elif abs(filt_val) < 0.01:
        stat = "CLEAN"
    elif filt_val < 0:
        stat = f"LPF {int(abs(filt_val)*100)}%"
    else:
        stat = f"HPF {int(filt_val*100)}%"

    draw_header(d, "DJ", stat, W)

    bx0, by0, bx1, by1 = 4, 18, W - 4, 70
    lbl_y = 76
    tl_y = 92
    d.rectangle([bx0, by0, bx1, by1], outline=255)

    w_box = bx1 - bx0
    h_box = by1 - by0

    if is_trans:
        if trans_state in ("WAIT_AUDIO", "ALIGN_BEAT"):
            cutoff_t1 = 0.5 + 0.45 * filt_val if filt_val < 0 else (0.5 + 0.4 * filt_val)
            gain_t1 = 1.0
            cutoff_t2 = 0.70 if filt_val <= 0 else 0.30
            gain_t2 = 0.0
        else:
            if filt_val <= 0:
                c1_start = max(0.15, 0.5 + 0.45 * filt_val)
                cutoff_t1 = max(0.05, c1_start * (1.0 - trans_p))
                cutoff_t2 = 0.70 * (1.0 - trans_p) + (0.5 + 0.45 * filt_val) * trans_p
            else:
                c1_start = 0.5 + 0.4 * filt_val
                cutoff_t1 = min(0.95, c1_start + (0.95 - c1_start) * trans_p)
                cutoff_t2 = 0.30 * (1.0 - trans_p) + (0.5 + 0.4 * filt_val) * trans_p
            gain_t1 = math.cos(trans_p * math.pi * 0.5)
            gain_t2 = math.sin(trans_p * math.pi * 0.5)

        pts1, pts2 = [], []
        for px in range(bx0 + 1, bx1):
            rel_x = (px - bx0) / float(w_box)

            if rel_x < cutoff_t1:
                r1 = (0.75 + 0.06 * math.sin(rel_x * 8.0 + t * 5.0)) * gain_t1
            else:
                r1 = 0.75 * math.exp(-6.0 * (rel_x - cutoff_t1)) * gain_t1
            py1 = int(by1 - 2 - r1 * (h_box - 4))
            pts1.append((px, max(by0 + 2, min(by1 - 2, py1))))

            if gain_t2 > 0.01:
                if rel_x > cutoff_t2:
                    r2 = (0.75 + 0.05 * math.sin(rel_x * 8.0 + t * 6.0)) * gain_t2
                else:
                    r2 = 0.75 * math.exp(-6.0 * (cutoff_t2 - rel_x)) * gain_t2
                py2 = int(by1 - 2 - r2 * (h_box - 4))
                pts2.append((px, max(by0 + 2, min(by1 - 2, py2))))

        for i in range(len(pts1) - 1):
            d.line([pts1[i], pts1[i+1]], fill=255, width=1)
            if len(pts2) > i + 1 and (i // 2) % 2 == 0:
                d.line([pts2[i], pts2[i+1]], fill=255, width=1)

        if trans_state == "WAIT_AUDIO":
            d.text((4, lbl_y), "CORE", font=F_XS, fill=255)
            d.text((bx1 - text_w(d, "WAIT", F_XS), lbl_y), "WAIT", font=F_XS, fill=255)
            d.line([(bx0, tl_y), (bx1, tl_y)], fill=255)
            pulse_pos = int((math.sin(t * 8.0) * 0.5 + 0.5) * (bx1 - bx0 - 6))
            d.rectangle([bx0 + pulse_pos, tl_y - 2, bx0 + pulse_pos + 6, tl_y + 2], fill=255)
        elif trans_state == "ALIGN_BEAT":
            d.text((4, lbl_y), "CORE", font=F_XS, fill=255)
            d.text((bx1 - text_w(d, "SYNC", F_XS), lbl_y), "SYNC", font=F_XS, fill=255)
            d.line([(bx0, tl_y), (bx1, tl_y)], fill=255)
            d.rectangle([bx0, tl_y - 2, bx1, tl_y + 2], fill=255)
        else:
            d.text((4, lbl_y), "OUT", font=F_XS, fill=255)
            d.text((bx1 - text_w(d, "IN", F_XS), lbl_y), "IN", font=F_XS, fill=255)
            d.line([(bx0, tl_y), (bx1, tl_y)], fill=255)
            bar_w = int(trans_p * (bx1 - bx0))
            if bar_w > 0:
                d.rectangle([bx0, tl_y - 1, bx0 + bar_w, tl_y + 1], fill=255)
    else:
        pts = []
        for px in range(bx0 + 1, bx1):
            rel_x = (px - bx0) / float(w_box)
            if abs(filt_val) < 0.01:
                resp = 0.7 + 0.08 * math.sin(rel_x * 9.0 + t * 4.0)
            elif filt_val < 0:
                cutoff_rel = 1.0 - abs(filt_val) * 0.85
                if rel_x < cutoff_rel:
                    resp = 0.75 + 0.05 * math.sin(rel_x * 8.0 + t * 5.0)
                else:
                    resp = 0.75 * math.exp(-6.0 * (rel_x - cutoff_rel))
            else:
                cutoff_rel = filt_val * 0.85
                if rel_x > cutoff_rel:
                    resp = 0.75 + 0.05 * math.sin(rel_x * 8.0 + t * 5.0)
                else:
                    resp = 0.75 * math.exp(-6.0 * (cutoff_rel - rel_x))

            py = int(by1 - 2 - resp * (h_box - 4))
            pts.append((px, max(by0 + 2, min(by1 - 2, py))))

        for i in range(len(pts) - 1):
            d.line([pts[i], pts[i+1]], fill=255, width=1)
            if i % 3 == 0:
                top_y = pts[i][1]
                for sy in range(top_y + 3, by1 - 1, 3):
                    d.point([(pts[i][0], sy)], fill=255)

        d.text((4, lbl_y), "LPF", font=F_XS, fill=255)
        d.text((bx1 - text_w(d, "HPF", F_XS), lbl_y), "HPF", font=F_XS, fill=255)

        d.line([(bx0, tl_y), (bx1, tl_y)], fill=255)
        center_x = (bx0 + bx1) // 2
        d.line([(center_x, tl_y - 3), (center_x, tl_y + 3)], fill=255)

        curr_x = int(center_x + filt_val * (bx1 - center_x))
        curr_x = max(bx0, min(bx1, curr_x))
        d.rectangle([curr_x - 2, tl_y - 3, curr_x + 2, tl_y + 3], fill=255)

    d.text((4, 103), "BRAKE ACTIVE" if is_brake else "FILTER READY", font=F_XS, fill=255)

    dj_items = [
        ("rot", "FILTER"),
        ("top_tap", "XFADE"),
        ("btm_tap", "TAPE"),
    ]
    draw_control_bar(d, dj_items, W, H)


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

    # --- Minispel -----------------------------------------------------------
    if s["mode"] == "GAMES" and get_games() is not None:
        get_games().render(d, t)
        return img, True

    # --- OB-4 & DJ Speciallägen (TAPE, LOOP & DJ) ----------------------------
    if s["mode"] == "TAPE":
        render_tape_view(d, s, t)
        return img, True
    elif s["mode"] == "LOOP":
        render_loop_view(d, s, t)
        return img, True
    elif s["mode"] == "DJ":
        render_dj_view(d, s, t)
        return img, True

    if now < s["overlay_until"]:
        # --- Volym-overlay widescreen ---------------------------------------
        draw_header(d, "VOLUME", "LEVEL", W)
        label = "MUTE" if s["muted"] else f"{s['volume']:d}"
        font = F_MD if s["muted"] else F_XL
        w = text_w(d, label, font)
        d.text(((W - w) / 2, 28 if not s["muted"] else 40), label, font=font, fill=255)
        seg_bar(d, 8, 78, W - 16, 12, 0 if s["muted"] else s["volume"] / max(1, VOL_MAX), 16)
        lbl_str = "MUTED" if s["muted"] else f"{s['volume']}/{VOL_MAX}"
        d.text(((W - text_w(d, lbl_str, F_XS)) / 2, 96), lbl_str, font=F_XS, fill=255)
        draw_control_bar(d, [("rot", "VOL"), ("top_tap", "MUTE"), ("btm_tap", "CLOSE")], W, H)
        return img, False
    else:
        # --- Standard VOL Dashboard Widescreen (128x128) -------------------
        src = s["source"] or "OD-11"
        behind_sec = tape.get_time_behind_live_sec() if tape else 0.0
        if behind_sec > 1.5:
            tot_s = int(round(behind_sec))
            stat = f"-{tot_s//60:02d}:{tot_s%60:02d}"
        else:
            stat = "PLAY" if s["playing"] and s["source"] else ("PAUS" if s["source"] else "RDY")
        draw_header(d, src, stat, W)

        # --- Titel/artist (full widescreen) ---
        if s["source"]:
            animating |= marquee(d, (2, 17), s["title"].upper() or "-", F_MD, W - 4, t)
            animating |= marquee(d, (2, 31), s["artist"].upper() or "-", F_SM, W - 4, t)
        else:
            d.text((2, 17), "OLLE'S", font=F_MD, fill=255)
            d.text((2, 31), "MINIMIX", font=F_SM, fill=255)

        # --- Audio Spectrum Visualizer (16 bars i 124px) ---
        bx0, by0, bx1, by1 = 2, 46, W - 2, 74
        if s["playing"] and s["source"]:
            animating = True
            num_bars = 16
            bw = (bx1 - bx0) / num_bars
            for b in range(num_bars):
                h_val = int(abs(math.sin(t * 4.0 + b * 0.5)) * (by1 - by0 - 4)) + 3
                xb = bx0 + b * bw
                d.rectangle([xb + 1, by1 - h_val, xb + bw - 2, by1], fill=255)
        else:
            d.line([(bx0, (by0 + by1) // 2), (bx1, (by0 + by1) // 2)], fill=255)

        # --- Progress ---
        if s["dur_ms"] > 0:
            pos = s["pos_ms"] + ((now - s["stamp"]) * 1000 if s["playing"] else 0)
            frac = max(0.0, min(1.0, pos / s["dur_ms"]))
            mm = int(pos // 60000)
            ss = int((pos // 1000) % 60)
            dur_mm = int(s["dur_ms"] // 60000)
            dur_ss = int((s["dur_ms"] // 1000) % 60)
            d.text((2, 80), f"{mm}:{ss:02d}", font=F_XS, fill=255)
            dur_str = f"{dur_mm}:{dur_ss:02d}"
            d.text((W - 2 - text_w(d, dur_str, F_XS), 80), dur_str, font=F_XS, fill=255)
            d.line([(2, 91), (W - 2, 91)], fill=255)
            prog_x = 2 + int(frac * (W - 4))
            d.rectangle([prog_x - 1, 88, prog_x + 1, 94], fill=255)
            animating |= s["playing"]
        else:
            d.line([(2, 91), (W - 2, 91)], fill=255)

        # --- Volym-mätare ---
        vtxt = "MUTE" if s["muted"] else f"VOL {s['volume']}"
        d.text((2, 99), vtxt, font=F_XS, fill=255)
        seg_bar(d, 44, 101, W - 46, 6, 0 if s["muted"] else s["volume"] / max(1, VOL_MAX), segs=12)

        # --- Bottenrad ---
        is_playing = s.get("playing", True)
        vol_items = [
            ("rot", "VOL"),
            ("top_tap", "PAUS" if is_playing else "PLAY"),
            ("btm_tap", "NEXT"),
        ]
        draw_control_bar(d, vol_items, W, H)
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
        # 20 FPS ger silkeslen animering och lämnar 90%+ CPU/GIL ledigt för ALSA-ljudet
        stop_event.wait(1 / 20 if animating else 0.1)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def shutdown(*_):
    stop_event.set()


def main():
    global encoder, W, H, W_MAIN
    driver_name = os.environ.get("OLED_DRIVER", "sh1107").lower()
    if driver_name == "sh1106":
        driver = sh1106
        default_h = 64
    elif driver_name == "ssd1306":
        driver = ssd1306
        default_h = 64
    else:
        driver = "sh1107"
        default_h = 128

    W = int(os.environ.get("OLED_WIDTH", "128"))
    H = int(os.environ.get("OLED_HEIGHT", str(default_h)))
    W_MAIN = W
    # Lådan används med sladdväggen bortvänd => skärmbilden vänds 180° i mjukvara.
    oled_rotate = int(os.environ.get("OLED_ROTATE", "2"))
    try:
        if driver_name == "sh1107":
            try:
                from sh1107_driver import SH1107Device
                device = SH1107Device(width=W, height=H, rotate=oled_rotate)
                device.contrast(200)
            except Exception as e:
                print(f"SH1107Device init fel ({e}), provar luma", flush=True)
                if sh1107 is not None:
                    device = sh1107(i2c(port=1, address=0x3C), width=W, height=H, rotate=oled_rotate)
                    device.contrast(200)
                else:
                    raise
        elif driver is not None:
            device = driver(i2c(port=1, address=0x3C), width=W, height=H, rotate=oled_rotate)
            device.contrast(200)
        else:
            raise RuntimeError("Ingen OLED-drivrutin tillgänglig")
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
        LongShortButton(BTN_PLAY_PAUSE, on_btn_play_short, on_btn_play_long, on_btn_play_release),
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