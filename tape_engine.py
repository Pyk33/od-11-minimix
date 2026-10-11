#!/usr/bin/env python3
"""
tape_engine.py – Teenage Engineering OB-4 Magic Tape & Loop DSP Engine.

Funktioner inspirerade av Teenage Engineering OB-4:
  1. Kontinuerlig rullande bandbuffert (10–30 min i RAM).
  2. Vari-speed tape resampler (spola bakåt i realtid med autenisk pitch/scrub och tröghet).
  3. Instant looper (upprepar slingor från 1/8 sekund upp till 16 sekunder med klickfria crossfades).
  4. Ambient drone synthesizer (OB-4 Disk Mode: granulerar musiken till en oändlig harmonisk drönare).
  5. Tape Stop (simulerar skivspelare/bandavstängning med realistisk retardation).
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
# Huvudmotor: TapeEngine
# --------------------------------------------------------------------------- #
class TapeEngine:
    MODE_VOL = "VOL"          # Standard: Encodern styr volym
    MODE_TAPE = "TAPE"        # OB-4 Band: Scrubbing / Spolning
    MODE_LOOP = "LOOP"        # Instant Looper: Upprepning / Stutter
    MODE_AMBIENT = "AMBIENT"  # Disk Mode: Eterisk drönarsyntes

    LOOP_PRESETS = [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]

    def __init__(self, sample_rate: int = SAMPLE_RATE, tape_minutes: int = DEFAULT_TAPE_MINUTES):
        self.sr = sample_rate
        self.tape = CircularTapeBuffer(sample_rate, max_minutes=tape_minutes)
        self.mode = self.MODE_VOL

        # Playhead & Vari-speed
        self.head_pos = 0.0
        self.live_latency_frames = int(0.04 * sample_rate)  # 40 ms live-fördröjning
        self.speed = 1.0
        self.target_speed = 1.0
        self.inertia = 0.22                                # mekanisk tröghet i bandet
        self.tape_stop_active = False

        # Scrubbing state
        self._last_scrub_time = time.monotonic()
        self.is_scrubbing = False

        # Instant Looper state
        self.loop_active = False
        self.loop_length_s = 2.0
        self.loop_start_pos = 0.0
        self.loop_end_pos = 0.0
        self.loop_reverse = False
        self._loop_accum = 0

        # Ambient Drone (Disk Mode)
        self.ambient_anchor_pos = 0.0
        self.ambient_offset = 0.0
        self.ambient_grain_size = int(0.45 * sample_rate)   # 450 ms korn
        self.ambient_phase = np.array([0.0, 0.25, 0.5, 0.75], dtype=np.float32)
        self._ambient_accum = 0

        # Ljudtrådar och hårdvara
        self._running = False
        self._capture_thread_obj: Optional[threading.Thread] = None
        self._playback_thread_obj: Optional[threading.Thread] = None
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
                self.speed = 1.0
                self.target_speed = 1.0
                self.tape_stop_active = False
            elif new_mode == self.MODE_TAPE:
                if old_mode == self.MODE_VOL:
                    self.head_pos = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
                self.target_speed = 1.0
                self.speed = 1.0
                self.is_scrubbing = False
                self.tape_stop_active = False
            elif new_mode == self.MODE_LOOP:
                # Fånga omedelbart slinga från nuvarande uppspelningsposition
                frames = int(self.loop_length_s * self.sr)
                self.loop_end_pos = self.head_pos
                self.loop_start_pos = (self.loop_end_pos - frames) % self.tape.max_frames
                self.loop_active = True
                self.tape_stop_active = False
                self._loop_accum = 0
            elif new_mode == self.MODE_AMBIENT:
                # Förankra ambient drönarfönster vid nuvarande ljud
                self.ambient_anchor_pos = self.head_pos
                self.ambient_offset = 0.0
                self.tape_stop_active = False
                self._ambient_accum = 0

    def cycle_mode(self) -> str:
        """Växlar cykliskt mellan lägena: VOL -> TAPE -> LOOP -> AMBIENT -> VOL."""
        modes = [self.MODE_VOL, self.MODE_TAPE, self.MODE_LOOP, self.MODE_AMBIENT]
        curr_idx = modes.index(self.mode) if self.mode in modes else 0
        nxt = modes[(curr_idx + 1) % len(modes)]
        self.set_mode(nxt)
        return nxt

    def jump_to_live(self):
        """Hoppar omedelbart fram till livesändningen."""
        with self._lock:
            self.mode = self.MODE_VOL
            self.tape_stop_active = False
            self.speed = 1.0
            self.target_speed = 1.0
            self.head_pos = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames

    def toggle_tape_stop(self):
        """Växlar autentisk motorstopp/retardation."""
        with self._lock:
            self.tape_stop_active = not self.tape_stop_active

    def on_encoder_rotated(self, steps: int):
        """
        Anropas med råa encoderticks (positiv = medurs, negativ = moturs).
        """
        with self._lock:
            now = time.monotonic()
            if self.mode == self.MODE_TAPE:
                dt = max(0.005, now - self._last_scrub_time)
                self._last_scrub_time = now

                # 2400 steg/varv -> 60 samples per steg = 3 sekunder per varv
                samples_per_step = 60
                scrub_velocity_samples_sec = (steps * samples_per_step) / dt
                raw_speed = scrub_velocity_samples_sec / self.sr

                # Fysisk hastighetsbegränsning: -4.0x (snabb rewind) till +3.0x
                self.target_speed = max(-4.0, min(3.0, raw_speed))
                self.is_scrubbing = True
                self.tape_stop_active = False

            elif self.mode == self.MODE_LOOP:
                # Kalibrerad känslighet: 48 steg (ett distinkt taktilt hack) per förval
                self._loop_accum += steps
                THRESHOLD = 48
                if abs(self._loop_accum) >= THRESHOLD:
                    direction = 1 if self._loop_accum > 0 else -1
                    self._loop_accum = 0

                    curr_idx = min(range(len(self.LOOP_PRESETS)),
                                   key=lambda i: abs(self.LOOP_PRESETS[i] - self.loop_length_s))
                    new_idx = max(0, min(len(self.LOOP_PRESETS) - 1, curr_idx + direction))
                    self.loop_length_s = self.LOOP_PRESETS[new_idx]
                    frames = int(self.loop_length_s * self.sr)
                    self.loop_start_pos = (self.loop_end_pos - frames) % self.tape.max_frames

            elif self.mode == self.MODE_AMBIENT:
                # Mjuk förskjutning av drönarklangfärg
                self._ambient_accum += steps
                THRESHOLD = 24
                if abs(self._ambient_accum) >= THRESHOLD:
                    direction = 1 if self._ambient_accum > 0 else -1
                    self._ambient_accum = 0
                    self.ambient_offset += direction * 0.05 * self.sr

    def get_loop_progress(self) -> float:
        """Exakt fasindikator (0.0 till 1.0) för synkad skärmanimering."""
        with self._lock:
            if self.mode != self.MODE_LOOP:
                return 0.0
            loop_len = int(self.loop_length_s * self.sr)
            if loop_len <= 0:
                return 0.0
            rel = (self.head_pos - self.loop_start_pos) % self.tape.max_frames
            return float(np.clip(rel / loop_len, 0.0, 1.0))

    def get_time_behind_live_sec(self) -> float:
        """Sekunder efter realtidsströmmen."""
        with self._lock:
            if self.mode == self.MODE_VOL:
                return 0.0
            behind = (self.tape.write_pos - self.head_pos) % self.tape.max_frames
            return max(0.0, behind / self.sr)

    # ----------------------------------------------------------------------- #
    # DSP Process Block (körs kontinuerligt för varje ljudblock)
    # ----------------------------------------------------------------------- #
    def process_block(self, frames_needed: int) -> np.ndarray:
        with self._lock:
            if self.tape.total_recorded < self.live_latency_frames:
                return np.zeros((frames_needed, CHANNELS), dtype=np.float32)

            now = time.monotonic()

            if self.mode == self.MODE_VOL:
                # Direkt passthrough från live-bandhuvudet
                live_target = (self.tape.write_pos - self.live_latency_frames - frames_needed) % self.tape.max_frames
                self.head_pos = live_target
                pos = (self.head_pos + np.arange(frames_needed)) % self.tape.max_frames
                self.head_pos = (self.head_pos + frames_needed) % self.tape.max_frames
                return self.tape.read_interp(pos)

            elif self.mode == self.MODE_TAPE:
                # Om användaren slutade vrida för > 100 ms: glid mjukt tillbaka till 1.0x uppspelning
                if self.is_scrubbing and (now - self._last_scrub_time > 0.10):
                    if not self.tape_stop_active:
                        self.target_speed = 1.0
                    self.is_scrubbing = False

                if self.tape_stop_active:
                    self.target_speed = 0.0

                # Mjuk retardation och tröghetsfilter
                self.speed += (self.target_speed - self.speed) * self.inertia
                if abs(self.speed) < 0.02 and self.tape_stop_active:
                    return np.zeros((frames_needed, CHANNELS), dtype=np.float32)

                pos = self.head_pos + np.arange(frames_needed) * self.speed
                self.head_pos = (self.head_pos + frames_needed * self.speed) % self.tape.max_frames

                # Har vi hunnit ifatt realtidsströmmen?
                behind = (self.tape.write_pos - self.head_pos) % self.tape.max_frames
                if behind < self.live_latency_frames and self.speed >= 0:
                    self.head_pos = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
                    self.speed = 1.0
                    self.target_speed = 1.0

                return self.tape.read_interp(pos)

            elif self.mode == self.MODE_LOOP:
                # Instant Loop med klickfri wrap och faslåst uppspelning
                loop_len = int(self.loop_length_s * self.sr)
                if loop_len < 256:
                    loop_len = 256

                rel = (self.head_pos - self.loop_start_pos) % self.tape.max_frames
                pos = (self.loop_start_pos + (rel + np.arange(frames_needed)) % loop_len) % self.tape.max_frames
                self.head_pos = (self.loop_start_pos + (rel + frames_needed) % loop_len) % self.tape.max_frames
                out = self.tape.read_interp(pos)

                # Mjuk equal-power crossfade vid loop-skarven
                wrap_idx = int(loop_len - rel)
                if 0 <= wrap_idx < frames_needed:
                    fade_len = min(256, frames_needed - wrap_idx)
                    if fade_len > 0:
                        fade_in = np.linspace(0.0, 1.0, fade_len)[:, np.newaxis]
                        out[wrap_idx:wrap_idx + fade_len] *= fade_in

                return out

            elif self.mode == self.MODE_AMBIENT:
                # 4-stämmig Hann-fönstrad granulsyntes (OB-4 Disk Ambient)
                grain_len = self.ambient_grain_size
                out = np.zeros((frames_needed, CHANNELS), dtype=np.float32)
                center = (self.ambient_anchor_pos + self.ambient_offset) % self.tape.max_frames

                for v in range(4):
                    phase = (self.ambient_phase[v] + np.arange(frames_needed) / grain_len) % 1.0
                    self.ambient_phase[v] = (self.ambient_phase[v] + frames_needed / grain_len) % 1.0

                    grain_pos = (center + (phase - 0.5) * grain_len) % self.tape.max_frames
                    voice_samples = self.tape.read_interp(grain_pos)

                    weights = 0.5 * (1.0 - np.cos(2.0 * np.pi * phase))[:, np.newaxis]
                    out += voice_samples * weights * 0.38

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
