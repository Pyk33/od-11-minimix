#!/usr/bin/env python3
"""
tape_engine.py – Teenage Engineering OB-4 Magic Tape & Loop DSP Engine.

Funktioner inspirerade av Teenage Engineering OB-4:
  1. Kontinuerlig rullande bandbuffert (10–30 min i RAM).
  2. Vari-speed tape resampler (1:1 vinyl slipmat känsla, Super Spool acceleration & bergfast LIVE t-0).
  3. DJ Merge to LIVE: silkeslen equal-power crossfade vid återgång till realtidsmusiken.
  4. Instant looper (framåtriktad tidsförlängning & glidande tidsfönster längs låten).
  5. Sömlös uppspelningskontinuitet (musiken fortsätter alltid från aktuell punkt utan hopp).
  6. Bergfast LIVE-lås och renodlad Play/Pause vid t-0.
"""
import math
import threading
import time
from typing import Optional, Tuple
import numpy as np

# --------------------------------------------------------------------------- #
# Konstanter & Standardvärden
# --------------------------------------------------------------------------- #
SAMPLE_RATE = 48000
CHANNELS = 2
BLOCK_SIZE = 1024                    # ~21.3 ms per block vid 48 kHz
DEFAULT_TAPE_MINUTES = 15            # ~172 MB int16 stereo RAM
SAMPLES_PER_STEP = 42                # ~2.1 sekunder per helt varv (2400 steg) – 1:1 vinyl slipmat

# --------------------------------------------------------------------------- #
# Cirkulär bandbuffert
# --------------------------------------------------------------------------- #
class CircularTapeBuffer:
    """
    Håller kontinuerligt inspelat 48kHz stereoljud i en rullande ringbuffert.
    Optimerad för minimalt minne och snabb linjär interpolationsläsning.
    """
    def __init__(self, sample_rate: int = SAMPLE_RATE, max_minutes: int = DEFAULT_TAPE_MINUTES):
        self.sr = sample_rate
        self.max_frames = int(max_minutes * 60 * sample_rate)
        self.buffer = np.zeros((self.max_frames, CHANNELS), dtype=np.int16)
        self.write_pos = 0
        self.total_recorded = 0
        self._lock = threading.Lock()

    def write(self, pcm_chunk: np.ndarray):
        """
        pcm_chunk: array med form (N, 2) av int16 eller float32 i [-1.0, 1.0].
        """
        if pcm_chunk.dtype != np.int16:
            pcm_chunk = np.clip(pcm_chunk * 32767.0, -32768, 32767).astype(np.int16)

        n = len(pcm_chunk)
        if n == 0:
            return

        with self._lock:
            end = self.write_pos + n
            if end <= self.max_frames:
                self.buffer[self.write_pos:end] = pcm_chunk
            else:
                first = self.max_frames - self.write_pos
                self.buffer[self.write_pos:] = pcm_chunk[:first]
                self.buffer[:n - first] = pcm_chunk[first:]

            self.write_pos = (self.write_pos + n) % self.max_frames
            self.total_recorded = min(self.max_frames, self.total_recorded + n)

    def read_interp(self, positions: np.ndarray) -> np.ndarray:
        """
        Läser kontinuerliga flyttalspositioner med linjär interpolation.
        Returnerar float32 i [-1.0, 1.0].
        """
        pos = positions % self.max_frames
        idx0 = pos.astype(np.int64)
        idx1 = (idx0 + 1) % self.max_frames
        frac = (pos - idx0).astype(np.float32)[:, np.newaxis]

        s0 = self.buffer[idx0].astype(np.float32) / 32768.0
        s1 = self.buffer[idx1].astype(np.float32) / 32768.0
        return s0 * (1.0 - frac) + s1 * frac

    def get_rms_level(self, num_frames: int = 1024) -> float:
        """Beräknar aktuell ljudnivå (RMS) för visualisering."""
        with self._lock:
            if self.total_recorded < num_frames:
                return 0.0
            idx0 = (self.write_pos - num_frames) % self.max_frames
            if idx0 + num_frames <= self.max_frames:
                slice_ = self.buffer[idx0:idx0 + num_frames]
            else:
                slice_ = np.vstack([self.buffer[idx0:], self.buffer[:(idx0 + num_frames) % self.max_frames]])
        samples = slice_.astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(samples ** 2)))


# --------------------------------------------------------------------------- #
# Huvudmotor: TapeEngine (OB-4 Magic Tape & Instant Looper)
# --------------------------------------------------------------------------- #
class TapeEngine:
    MODE_VOL = "VOL"          # Standard: Encodern styr volym, sömlös uppspelning från nålen
    MODE_TAPE = "TAPE"        # OB-4 Vinyl: 1:1 slipmat scratch, Super Spool & LIVE (t-0)
    MODE_LOOP = "LOOP"        # Instant Looper: Framåt expansion & glidande tidsfönster

    LOOP_PRESETS = [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]

    def __init__(self, sample_rate: int = SAMPLE_RATE, tape_minutes: int = DEFAULT_TAPE_MINUTES):
        self.sr = sample_rate
        self.tape = CircularTapeBuffer(sample_rate, max_minutes=tape_minutes)
        self.mode = self.MODE_VOL

        # Nålposition och live-låsning
        self.head_pos = 0.0
        self.live_latency_frames = int(0.04 * sample_rate)  # 40 ms live-fördröjning
        self.initialized_head = False
        self.is_live = True

        # Vinyl Scratch Engine & Super Spool
        self._pending_tape_steps = 0
        self.speed = 1.0
        self.last_touch_time = 0.0
        self.release_timeout = 0.080    # 80 ms utan pulser = handen har släppt skivan

        # Dynamisk hastighetsmätning över pulsskurar
        self._last_rot_time = 0.0
        self._velocity_est = 0.0        # steg per sekund

        # DJ Merge to LIVE (mjuk equal-power crossfade vid återgång till nutid)
        self.is_dj_merging = False
        self.merge_fade_frames = int(0.85 * sample_rate)  # 850 ms DJ crossfade
        self.merge_fade_pos = 0

        # Instant Looper state
        self.loop_active = False
        self.loop_length_s = 2.0
        self.loop_start_pos = 0.0
        self.loop_end_pos = 0.0
        self.loop_reverse = False
        self.loop_edit_mode = "SIZE"    # "SIZE" (ändra längd framåt) eller "MOVE" (flytta loopen)
        self._loop_accum = 0

        self._lock = threading.Lock()

    # ----------------------------------------------------------------------- #
    # Läges- & Kontrollmetoder
    # ----------------------------------------------------------------------- #
    def set_mode(self, new_mode: str):
        with self._lock:
            if new_mode == self.mode:
                return
            old_mode = self.mode
            self.mode = new_mode

            if new_mode == self.MODE_VOL:
                # Återgång till VOL: fortsätt spela sömlöst från exakt där nålen befinner sig!
                self.speed = 1.0
                self._pending_tape_steps = 0

            elif new_mode == self.MODE_TAPE:
                # Gå in i TAPE: behåll nålen exakt på låten där den spelar
                self._pending_tape_steps = 0

            elif new_mode == self.MODE_LOOP:
                # Fånga slinga från nuvarande uppspelningsposition
                self.loop_active = True
                self.tape_stop_active = False
                frames = int(self.loop_length_s * self.sr)
                self.loop_start_pos = (self.head_pos - frames) % self.tape.max_frames
                self.loop_end_pos = self.head_pos
                self.loop_edit_mode = "SIZE"
                self._loop_accum = 0

    def cycle_mode(self) -> str:
        """Växlar mellan de två kreativa OB-4-lägena: TAPE <-> LOOP."""
        with self._lock:
            nxt = self.MODE_LOOP if self.mode == self.MODE_TAPE else self.MODE_TAPE
        self.set_mode(nxt)
        return nxt

    def toggle_loop_edit_mode(self) -> str:
        """Växlar encoderns funktion i LOOP-läge mellan SIZE (längd) och MOVE (flytta fönster)."""
        with self._lock:
            self.loop_edit_mode = "MOVE" if self.loop_edit_mode == "SIZE" else "SIZE"
            return self.loop_edit_mode

    def jump_to_live(self, dj_merge: bool = True):
        """Hoppar till LIVE. Om dj_merge=True sker en mjuk equal-power DJ-övergång."""
        with self._lock:
            if self.is_live and not self.is_dj_merging:
                return

            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
            behind = (live_edge - self.head_pos) % self.tape.max_frames
            behind_sec = behind / self.sr if behind < self.tape.max_frames / 2 else 0.0

            if not dj_merge or behind_sec < 0.25:
                # Omedelbart snitt om vi redan är extremt nära nutid
                self.head_pos = live_edge
                self.is_live = True
                self.is_dj_merging = False
                self.speed = 1.0
                self._pending_tape_steps = 0
            else:
                # Mjuk DJ Merge Crossfade!
                self.is_dj_merging = True
                self.merge_fade_pos = 0

    def on_encoder_rotated(self, steps: int):
        """
        Anropas med råa encoderticks (positiv = medurs/framåt, negativ = moturs/bakåt).
        """
        with self._lock:
            now = time.monotonic()
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames

            if self.mode == self.MODE_TAPE:
                dt = max(0.001, now - self._last_rot_time)
                self._last_rot_time = now
                inst_rate = abs(steps) / dt
                self._velocity_est = 0.5 * self._velocity_est + 0.5 * inst_rate

                if steps < 0:
                    # Scratcha bakåt i tiden -> lås omedelbart upp från LIVE
                    self.is_live = False
                    self.is_dj_merging = False

                self._pending_tape_steps += steps
                self.last_touch_time = now

            elif self.mode == self.MODE_LOOP:
                if self.loop_edit_mode == "SIZE":
                    # KRAV 2: Lägg till tid FRAMÅT i loopen!
                    self._loop_accum += steps
                    THRESHOLD = 40
                    if abs(self._loop_accum) >= THRESHOLD:
                        direction = 1 if self._loop_accum > 0 else -1
                        self._loop_accum = 0

                        curr_idx = min(range(len(self.LOOP_PRESETS)),
                                       key=lambda i: abs(self.LOOP_PRESETS[i] - self.loop_length_s))
                        new_idx = max(0, min(len(self.LOOP_PRESETS) - 1, curr_idx + direction))
                        self.loop_length_s = self.LOOP_PRESETS[new_idx]
                        frames = int(self.loop_length_s * self.sr)

                        # Håll loop_start_pos förankrad och expandera loop_end_pos framåt
                        new_end = (self.loop_start_pos + frames) % self.tape.max_frames
                        behind_end = (live_edge - new_end) % self.tape.max_frames
                        if behind_end > self.tape.max_frames / 2: # passerade live in i framtiden
                            self.loop_end_pos = live_edge
                            self.loop_start_pos = (live_edge - frames) % self.tape.max_frames
                        else:
                            self.loop_end_pos = new_end

                elif self.loop_edit_mode == "MOVE":
                    # KRAV 2b: Flytta hela loopfönstret längs musikhistorien!
                    shift = steps * SAMPLES_PER_STEP * 3
                    new_start = (self.loop_start_pos + shift) % self.tape.max_frames
                    new_end = (self.loop_end_pos + shift) % self.tape.max_frames

                    behind_end = (live_edge - new_end) % self.tape.max_frames
                    if behind_end > self.tape.max_frames / 2: # kan inte flytta förbi LIVE
                        frames = int(self.loop_length_s * self.sr)
                        self.loop_end_pos = live_edge
                        self.loop_start_pos = (live_edge - frames) % self.tape.max_frames
                    else:
                        self.loop_start_pos = new_start
                        self.loop_end_pos = new_end
                        self.head_pos = (self.head_pos + shift) % self.tape.max_frames

    def get_loop_progress(self) -> float:
        """Exakt fasindikator (0.0 till 1.0) för synkad skärmanimering."""
        with self._lock:
            if self.mode != self.MODE_LOOP or not self.loop_active:
                return 0.0
            loop_len = int(self.loop_length_s * self.sr)
            if loop_len <= 0:
                return 0.0
            rel = (self.head_pos - self.loop_start_pos) % self.tape.max_frames
            return float(np.clip(rel / loop_len, 0.0, 1.0))

    def get_time_behind_live_sec(self) -> float:
        """Sekunder efter realtidsströmmen (visar 0.0 vid LIVE t-0)."""
        with self._lock:
            if self.is_live:
                return 0.0
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
            behind = (live_edge - self.head_pos) % self.tape.max_frames
            if behind > self.tape.max_frames / 2 or behind < int(0.04 * self.sr):
                return 0.0
            return max(0.0, behind / self.sr)

    # ----------------------------------------------------------------------- #
    # DSP Process Block (körs kontinuerligt för varje ljudblock)
    # ----------------------------------------------------------------------- #
    def process_block(self, frames_needed: int) -> np.ndarray:
        with self._lock:
            if self.tape.total_recorded < self.live_latency_frames:
                return np.zeros((frames_needed, CHANNELS), dtype=np.float32)

            if not self.initialized_head:
                self.head_pos = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
                self.initialized_head = True
                self.is_live = True

            now = time.monotonic()
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
            max_history = max(0, min(self.tape.total_recorded - self.live_latency_frames * 2,
                                     self.tape.max_frames - self.live_latency_frames * 2))

            # --- DJ Merge to LIVE Crossfader ---
            if self.is_dj_merging:
                fade_frames = self.merge_fade_frames
                cur_p = self.merge_fade_pos

                pos_del = (self.head_pos + np.arange(frames_needed)) % self.tape.max_frames
                audio_del = self.tape.read_interp(pos_del)
                self.head_pos = (self.head_pos + frames_needed) % self.tape.max_frames

                pos_live = (live_edge - frames_needed + np.arange(frames_needed)) % self.tape.max_frames
                audio_live = self.tape.read_interp(pos_live)

                # Equal-power sinus/cosinus kurva för silkeslen DJ-övergång
                p_arr = np.linspace(cur_p, cur_p + frames_needed, frames_needed, endpoint=False) / fade_frames
                p_arr = np.clip(p_arr, 0.0, 1.0)
                fade_angle = p_arr * (np.pi / 2.0)
                gain_del = np.cos(fade_angle)[:, np.newaxis]
                gain_live = np.sin(fade_angle)[:, np.newaxis]

                mixed = audio_del * gain_del + audio_live * gain_live

                self.merge_fade_pos += frames_needed
                if self.merge_fade_pos >= fade_frames:
                    # Övergången är klar!
                    self.is_dj_merging = False
                    self.is_live = True
                    self.head_pos = live_edge
                    self.speed = 1.0

                return mixed

            # --- MODE_VOL: Normal sömlös uppspelning från aktuell nålposition ---
            if self.mode == self.MODE_VOL:
                if self.is_live:
                    self.head_pos = live_edge
                    pos = (live_edge - frames_needed + np.arange(frames_needed)) % self.tape.max_frames
                    return self.tape.read_interp(pos)

                behind_head = (live_edge - self.head_pos) % self.tape.max_frames
                if frames_needed >= behind_head or behind_head > self.tape.max_frames / 2:
                    self.head_pos = live_edge
                    self.is_live = True
                else:
                    self.head_pos = (self.head_pos + frames_needed) % self.tape.max_frames

                pos = (self.head_pos - frames_needed + np.arange(frames_needed)) % self.tape.max_frames
                return self.tape.read_interp(pos)

            # --- MODE_TAPE: Super Spool, 1:1 Vinyl Scratch & Bergfast LIVE ---
            elif self.mode == self.MODE_TAPE:
                # Om vi redan är vid LIVE, förbli bergfast vid LIVE såvida inte användaren scratchar bakåt!
                if self.is_live:
                    steps = self._pending_tape_steps
                    self._pending_tape_steps = 0
                    if steps < 0:
                        # Användaren scratchar bakåt i musikhistorien
                        self.is_live = False
                        back_dist = abs(steps * SAMPLES_PER_STEP)
                        self.head_pos = (live_edge - back_dist) % self.tape.max_frames
                        self.speed = float(np.clip(-back_dist / frames_needed, -6.0, -0.2))
                        pos = (self.head_pos + np.arange(frames_needed) * self.speed) % self.tape.max_frames
                        return self.tape.read_interp(pos)
                    else:
                        # Förbli 100% bergfast vid LIVE i realtid
                        self.head_pos = live_edge
                        self.speed = 1.0
                        pos = (live_edge - frames_needed + np.arange(frames_needed)) % self.tape.max_frames
                        return self.tape.read_interp(pos)

                hand_on_wheel = (now - self.last_touch_time <= self.release_timeout)
                steps = self._pending_tape_steps
                self._pending_tape_steps = 0

                if steps != 0:
                    current_behind = (live_edge - self.head_pos) % self.tape.max_frames
                    behind_sec = current_behind / self.sr if current_behind < self.tape.max_frames / 2 else 0.0

                    if steps > 0:
                        # SUPER SPOOL FRAMÅT MOT LIVE:
                        # Flerstegs hastighetsacceleration baserad på rotationshastighet
                        rate = self._velocity_est
                        if rate > 2000:
                            gain = 30.0
                        elif rate > 1200:
                            gain = 20.0
                        elif rate > 600:
                            gain = 10.0
                        elif rate > 300:
                            gain = 4.0
                        else:
                            gain = 1.5

                        # Avstånds-boost: om man är långt bakom (>10s eller >25s) spolas det ännu snabbare
                        if behind_sec > 25.0:
                            gain *= 2.0
                        elif behind_sec > 10.0:
                            gain *= 1.5

                        effective_step = int(SAMPLES_PER_STEP * gain)
                        delta_samples = steps * effective_step

                        # Magnet-lås mot LIVE vid nära eller passerat
                        if (delta_samples >= current_behind or
                            current_behind <= int(0.35 * self.sr) or
                            current_behind > self.tape.max_frames / 2):
                            # BERGFAST LÅSNING VID LIVE (t-0)!
                            self.head_pos = live_edge
                            self.is_live = True
                            self.speed = 1.0
                        else:
                            self.head_pos = (self.head_pos + delta_samples) % self.tape.max_frames
                            self.speed = float(np.clip(delta_samples / frames_needed, 1.0, 6.0))

                    else:
                        # BAKÅT: 1:1 autentisk vinylkänsla
                        effective_step = SAMPLES_PER_STEP
                        delta_samples = steps * effective_step
                        back_dist = abs(delta_samples)
                        remaining = max(0, max_history - current_behind)
                        if back_dist >= remaining:
                            self.head_pos = (live_edge - max_history) % self.tape.max_frames
                        else:
                            self.head_pos = (self.head_pos + delta_samples) % self.tape.max_frames
                        self.speed = float(np.clip(delta_samples / frames_needed, -6.0, 0.0))

                elif hand_on_wheel:
                    # Handen vilar på hjulet i bandhistoriken (scratch paus)
                    self.speed += (0.0 - self.speed) * 0.5
                    if abs(self.speed) < 0.05:
                        self.speed = 0.0
                        return np.zeros((frames_needed, CHANNELS), dtype=np.float32)

                else:
                    # Handen släppt -> tallriken accelererar mjukt tillbaka till 1.0x
                    if self.speed < 1.0:
                        self.speed += (1.0 - self.speed) * 0.35
                        if abs(self.speed - 1.0) < 0.04:
                            self.speed = 1.0
                    elif self.speed > 1.0:
                        self.speed += (1.0 - self.speed) * 0.45
                        if abs(self.speed - 1.0) < 0.04:
                            self.speed = 1.0

                    behind_head = (live_edge - self.head_pos) % self.tape.max_frames
                    step_frames = frames_needed * self.speed
                    if step_frames > 0 and (step_frames >= behind_head or behind_head <= int(0.35 * self.sr) or behind_head > self.tape.max_frames / 2):
                        self.head_pos = live_edge
                        self.is_live = True
                        self.speed = 1.0
                    else:
                        self.head_pos = (self.head_pos + step_frames) % self.tape.max_frames

                pos = (self.head_pos + np.arange(frames_needed) * self.speed) % self.tape.max_frames
                return self.tape.read_interp(pos)

            # --- MODE_LOOP: Instant looper med framåtriktad expansion ---
            elif self.mode == self.MODE_LOOP:
                self.is_live = False
                loop_len = int(self.loop_length_s * self.sr)
                if loop_len < 256:
                    loop_len = 256

                if self.loop_reverse:
                    rel = (self.loop_end_pos - self.head_pos) % self.tape.max_frames
                    pos = (self.loop_end_pos - (rel + np.arange(frames_needed)) % loop_len) % self.tape.max_frames
                    self.head_pos = (self.loop_end_pos - (rel + frames_needed) % loop_len) % self.tape.max_frames
                else:
                    rel = (self.head_pos - self.loop_start_pos) % self.tape.max_frames
                    pos = (self.loop_start_pos + (rel + np.arange(frames_needed)) % loop_len) % self.tape.max_frames
                    self.head_pos = (self.loop_start_pos + (rel + frames_needed) % loop_len) % self.tape.max_frames

                out = self.tape.read_interp(pos)

                # Mjuk crossfade vid loop-skarven
                wrap_idx = int(loop_len - rel)
                if 0 <= wrap_idx < frames_needed:
                    fade_len = min(256, frames_needed - wrap_idx)
                    if fade_len > 0:
                        fade_in = np.linspace(0.0, 1.0, fade_len)[:, np.newaxis]
                        out[wrap_idx:wrap_idx + fade_len] *= fade_in

                return out

            return np.zeros((frames_needed, CHANNELS), dtype=np.float32)


# --------------------------------------------------------------------------- #
# ALSA Audio Bridge (Capture & Playback trådar)
# --------------------------------------------------------------------------- #
class AlsaTapeBridge:
    """
    Kopplar samman Linux ALSA Loopback med TapeEngine och Cubilux USB-DAC:en.
    """
    def __init__(self, engine: TapeEngine, capture_device: str = "hw:Loopback,1,0",
                 playback_device: str = "default"):
        self.engine = engine
        self.capture_device = capture_device
        self.playback_device = playback_device
        self.running = False
        self._threads = []

    def start(self) -> bool:
        """Startar ljudströmmen om ALSA Loopback finns tillgänglig."""
        try:
            import alsaaudio
        except ImportError:
            print("alsaaudio saknas - ljudbrygga kan inte starta.", flush=True)
            return False

        try:
            # Testa att öppna capture-enheten
            test_inp = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NORMAL,
                                     channels=CHANNELS, rate=SAMPLE_RATE,
                                     format=alsaaudio.PCM_FORMAT_S16_LE,
                                     periodsize=BLOCK_SIZE, device=self.capture_device)
            test_inp.close()
        except Exception as exc:
            print(f"ALSA Loopback ({self.capture_device}) ej tillgänglig: {exc}", flush=True)
            return False

        self.running = True
        t_cap = threading.Thread(target=self._capture_worker, daemon=True)
        t_play = threading.Thread(target=self._playback_worker, daemon=True)
        t_cap.start()
        t_play.start()
        self._threads = [t_cap, t_play]
        print("ALSA Tape Bridge aktiv!", flush=True)
        return True

    def stop(self):
        self.running = False

    def _capture_worker(self):
        import alsaaudio
        try:
            inp = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NORMAL,
                                channels=CHANNELS, rate=SAMPLE_RATE,
                                format=alsaaudio.PCM_FORMAT_S16_LE,
                                periodsize=BLOCK_SIZE, device=self.capture_device)
        except Exception as exc:
            print(f"Fel vid start av ALSA capture: {exc}", flush=True)
            return

        while self.running:
            length, data = inp.read()
            if length > 0 and data:
                chunk = np.frombuffer(data, dtype=np.int16).reshape(-1, CHANNELS)
                self.engine.tape.write(chunk)
            elif length == -32: # EPIPE / xrun
                pass

        inp.close()

    def _playback_worker(self):
        import alsaaudio
        try:
            out = alsaaudio.PCM(alsaaudio.PCM_PLAYBACK, alsaaudio.PCM_NORMAL,
                                channels=CHANNELS, rate=SAMPLE_RATE,
                                format=alsaaudio.PCM_FORMAT_S16_LE,
                                periodsize=BLOCK_SIZE, device=self.playback_device)
        except Exception as exc:
            print(f"Fel vid start av ALSA playback: {exc}", flush=True)
            return

        while self.running:
            block = self.engine.process_block(BLOCK_SIZE)
            int16_bytes = np.clip(block * 32767.0, -32768, 32767).astype(np.int16).tobytes()
            out.write(int16_bytes)

        out.close()
