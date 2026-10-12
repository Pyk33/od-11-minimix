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
import ctypes
import math
import os
from pathlib import Path
import threading
import time
from typing import Optional, Tuple
import numpy as np

# --------------------------------------------------------------------------- #
# C-baserat Cytomic Resonant State Variable Filter (SVF) för DJ Mode
# --------------------------------------------------------------------------- #
_libdsp = None
class _SVFState(ctypes.Structure):
    _fields_ = [("ic1eq", ctypes.c_float * 2), ("ic2eq", ctypes.c_float * 2)]

class _EchoState(ctypes.Structure):
    _fields_ = [
        ("buf", ctypes.c_float * (48000 * 2)),
        ("write_idx", ctypes.c_int),
        ("delay_l", ctypes.c_int),
        ("delay_r", ctypes.c_int),
        ("damp_l", ctypes.c_float),
        ("damp_r", ctypes.c_float),
    ]

for dsp_candidate in [
    Path(__file__).with_name("libdsp.so"),
    Path(__file__).with_name("libdsp.dylib"),
    Path("/home/pyken/streamer/libdsp.so"),
    Path("/tmp/libdsp.so"),
]:
    if dsp_candidate.exists():
        try:
            _libdsp = ctypes.CDLL(str(dsp_candidate))
            _libdsp.svf_filter_block.argtypes = [
                ctypes.POINTER(_SVFState),
                ctypes.POINTER(ctypes.c_float),
                ctypes.c_int,
                ctypes.c_float
            ]
            if hasattr(_libdsp, "echo_init"):
                _libdsp.echo_init.argtypes = [ctypes.POINTER(_EchoState), ctypes.c_int]
                _libdsp.echo_process_block.argtypes = [
                    ctypes.POINTER(_EchoState),
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.c_int,
                    ctypes.c_float,
                    ctypes.c_float
                ]
            break
        except Exception:
            pass

# --------------------------------------------------------------------------- #
# Konstanter & Standardvärden
# --------------------------------------------------------------------------- #
SAMPLE_RATE = 48000
CHANNELS = 2
BLOCK_SIZE = 1024                    # ~21.3 ms per block vid 48 kHz
DEFAULT_TAPE_MINUTES = 15            # ~172 MB int16 stereo RAM
# Bas-känslighet för bandspolning (högre värde = känsligare för stora hjul / rotor)
SAMPLES_PER_STEP = int(os.environ.get("TAPE_SAMPLES_PER_STEP", "200"))

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
    MODE_DJ = "DJ"            # DJ Mixer: Resonant Bi-polar DJ Filter & Turntable Brake

    LOOP_PRESETS = [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]

    def __init__(self, sample_rate: int = SAMPLE_RATE, tape_minutes: int = DEFAULT_TAPE_MINUTES):
        self.sr = sample_rate
        self.tape = CircularTapeBuffer(sample_rate, max_minutes=tape_minutes)
        self.mode = self.MODE_VOL

        # Nålposition och live-låsning
        self.head_pos = 0.0
        self.live_latency_frames = int(0.08 * sample_rate)  # 80 ms live-jitterbuffert (mjuk & flimmerfri)
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

        # DJ Filter & Turntable Brake state
        self.dj_filter_val = 0.0        # -1.0 (LPF) .. 0.0 (Clean) .. +1.0 (HPF)
        self.dj_brake_active = False    # Sant när skivbromsen hålls nere
        self.dj_svf_state = _SVFState()
        self._smooth_behind_sec = 0.0

        # Auto DJ Smart Transition state (Natural Beat-Loop Crossfade)
        self.is_dj_transition = False
        self.dj_trans_duration_s = 5.0
        self.dj_trans_frames = int(5.0 * sample_rate)
        self.dj_trans_pos = 0
        self.dj_trans_progress = 0.0
        self.dj_trans_bpm = 120.0
        self.dj_trans_track1_head = 0.0
        self.dj_trans_t1_start = 0.0
        self.dj_trans_t1_len = int(2.0 * sample_rate)
        self.dj_trans_svf_t1 = _SVFState()
        self.dj_trans_svf_t2 = _SVFState()

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

            if new_mode != self.MODE_DJ:
                self.is_dj_transition = False

            if new_mode == self.MODE_VOL:
                # Återgång till VOL: fortsätt spela sömlöst från exakt där nålen befinner sig!
                self.speed = 1.0
                self._pending_tape_steps = 0
                self.dj_brake_active = False
                self.loop_active = False

            elif new_mode == self.MODE_TAPE:
                # Gå in i TAPE: behåll nålen exakt på låten där den spelar
                self._pending_tape_steps = 0
                self.dj_brake_active = False
                self.loop_active = False

            elif new_mode == self.MODE_LOOP:
                # Fånga slinga från nuvarande uppspelningsposition
                self.loop_active = True
                self.tape_stop_active = False
                frames = int(self.loop_length_s * self.sr)
                self.loop_start_pos = (self.head_pos - frames) % self.tape.max_frames
                self.loop_end_pos = self.head_pos
                self.loop_edit_mode = "SIZE"
                self._loop_accum = 0
                self.dj_brake_active = False

            elif new_mode == self.MODE_DJ:
                # Gå in i DJ: nollställ broms, fortsätt spela sömlöst
                self.dj_brake_active = False
                self.speed = 1.0
                self._pending_tape_steps = 0
                self.loop_active = False

    def cycle_mode(self) -> str:
        """Växlar i cirkel mellan de tre kreativa lägena: TAPE -> LOOP -> DJ -> TAPE."""
        with self._lock:
            if self.mode == self.MODE_TAPE:
                nxt = self.MODE_LOOP
            elif self.mode == self.MODE_LOOP:
                nxt = self.MODE_DJ
            else:
                nxt = self.MODE_TAPE
        self.set_mode(nxt)
        return nxt

    def set_dj_filter(self, val: float):
        """Sätt DJ-filtrets läge (-1.0 = Max LPF, 0.0 = Clean Bypass, +1.0 = Max HPF)."""
        with self._lock:
            self.dj_filter_val = float(np.clip(val, -1.0, 1.0))

    def reset_dj_filter(self):
        """Omedelbart snitt till Clean neutral (perfekt för beat drop!)."""
        with self._lock:
            self.dj_filter_val = 0.0

    def trigger_dj_brake(self, active: Optional[bool] = None) -> bool:
        """Slå på/av skivbroms (turntable motor stop)."""
        with self._lock:
            if active is None:
                self.dj_brake_active = not self.dj_brake_active
            else:
                self.dj_brake_active = bool(active)
            return self.dj_brake_active

    def _detect_natural_loop(self, live_edge: int) -> tuple[int, int, float]:
        """
        Analyserar de senaste 3.5 sekunderna i bandbufferten för att hitta
        låtens naturliga BPM och taktlängd (1 bar = 4 beats) synkad till taktslag.
        Returnerar (loop_start, loop_len_frames, bpm).
        """
        SEARCH_S = 3.5
        n_search = int(SEARCH_S * self.sr)
        pos = (live_edge - n_search + np.arange(n_search)) % self.tape.max_frames
        raw = self.tape.read_interp(pos)
        mono = 0.5 * (raw[:, 0] + raw[:, 1])

        hop = int(self.sr * 0.010)  # 10 ms upplösning
        n_frames = len(mono) // hop
        if n_frames < 100:
            fallback = int(2.0 * self.sr)
            return (live_edge - fallback) % self.tape.max_frames, fallback, 120.0

        mono_frames = mono[:n_frames * hop].reshape(n_frames, hop)
        energy = np.mean(mono_frames ** 2, axis=1)
        onset = np.maximum(0, np.diff(energy))

        if len(onset) > 50:
            onset_norm = onset - np.mean(onset)
            std = float(np.std(onset_norm))
            if std > 1e-6:
                onset_norm /= std

            # Sök BPM mellan 85 och 165 (lag 36..71 frames)
            min_lag = int(0.36 * 100)
            max_lag = int(0.71 * 100)
            corr = np.correlate(onset_norm, onset_norm, mode='full')
            center = len(onset_norm) - 1
            search_corr = corr[center + min_lag : center + max_lag + 1]

            if len(search_corr) > 0 and float(np.max(search_corr)) > 0.08:
                best_lag = min_lag + int(np.argmax(search_corr))
                bpm = float(np.clip(60.0 / (best_lag * 0.010), 80.0, 175.0))
                beat_frames = best_lag * hop
                # 1 bar = 4 beats. Om 1 bar är kort (<1.4s vid snabb musik), använd 2 bars = 8 beats
                bar_frames = 4 * beat_frames
                if bar_frames < int(1.4 * self.sr):
                    bar_frames *= 2

                # Fashitta: hitta starkaste taktslag
                phase_scores = [float(np.sum(onset[shift::best_lag])) for shift in range(min(best_lag, len(onset)))]
                best_phase = int(np.argmax(phase_scores))
                phase_samples = best_phase * hop

                loop_len = bar_frames
                loop_start = (live_edge - loop_len) % self.tape.max_frames
                return loop_start, loop_len, bpm

        fallback_len = int(2.0 * self.sr)
        return (live_edge - fallback_len) % self.tape.max_frames, fallback_len, 120.0

    def start_dj_transition(self, duration_s: Optional[float] = None):
        """
        Startar en automatisk Natural Beat-Loop DJ-övergång:
        Detekterar låtens BPM och naturliga takt (1–2 bars), loopar groovet sömlöst,
        sveper med LPF och tonar in nästa låt från Spotify.
        """
        with self._lock:
            self.is_dj_transition = True
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames

            # Detektera det naturliga beat-loop fönstret
            loop_start, loop_len, bpm = self._detect_natural_loop(live_edge)
            self.dj_trans_t1_start = loop_start
            self.dj_trans_t1_len = loop_len
            self.dj_trans_track1_head = loop_start
            self.dj_trans_bpm = bpm

            # Anpassa transitionens längd musikaliskt till ~2.5 bars (ca 4.0–6.0s)
            bar_sec = loop_len / float(self.sr)
            if duration_s is None:
                self.dj_trans_duration_s = float(np.clip(2.5 * bar_sec, 4.0, 6.0))
            else:
                self.dj_trans_duration_s = float(duration_s)

            self.dj_trans_frames = int(self.dj_trans_duration_s * self.sr)
            self.dj_trans_pos = 0
            self.dj_trans_progress = 0.0
            self.dj_trans_svf_t1 = _SVFState()
            self.dj_trans_svf_t2 = _SVFState()
            self.dj_brake_active = False

    def end_dj_transition(self):
        """Avslutar övergången omedelbart och låser till nutid."""
        with self._lock:
            self.is_dj_transition = False
            self.dj_trans_progress = 1.0
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
            self.head_pos = live_edge
            self.is_live = True
            self.speed = 1.0
            self.dj_filter_val = 0.0

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
                    THRESHOLD = 20  # Känsligare respons för stor rotor/ratt
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

            elif self.mode == self.MODE_DJ:
                if self.is_dj_transition:
                    return
                # Ratten styr bi-polärt DJ-filter (-1.0 LPF .. 0.0 Clean .. +1.0 HPF)
                # Anpassad för stor rotor: ca 400 steg för fullt svep från neutral till max
                old_val = self.dj_filter_val
                delta = steps * 0.0025
                new_val = float(np.clip(old_val + delta, -1.0, 1.0))

                # Fånga nollpunkten mjukt om man korsar nollan när man vrider tillbaka
                if (old_val > 0.0 and new_val < 0.0) or (old_val < 0.0 and new_val > 0.0):
                    self.dj_filter_val = 0.0
                else:
                    self.dj_filter_val = new_val

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
                self._smooth_behind_sec = 0.0
                return 0.0
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
            behind = (live_edge - self.head_pos) % self.tape.max_frames
            if behind > self.tape.max_frames / 2 or behind < int(0.08 * self.sr):
                self._smooth_behind_sec = 0.0
                return 0.0
            raw_sec = max(0.0, behind / self.sr)
            # Mjuk lågpassfiltrering för att helt eliminera ALSA trådjitter på sekundgränser
            if abs(self._smooth_behind_sec - raw_sec) > 1.5 or self._smooth_behind_sec == 0.0:
                self._smooth_behind_sec = raw_sec
            else:
                self._smooth_behind_sec = 0.85 * self._smooth_behind_sec + 0.15 * raw_sec
            return self._smooth_behind_sec

    def get_loop_behind_live_sec(self) -> float:
        """Sekunder mellan LIVE och loopens startpunkt."""
        with self._lock:
            if not self.loop_active:
                return 0.0
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
            behind = (live_edge - self.loop_start_pos) % self.tape.max_frames
            if behind > self.tape.max_frames / 2:
                return 0.0
            return max(0.0, behind / self.sr)

    def _py_echo_process(self, in_stereo: np.ndarray, echo_out: np.ndarray, frames: int, send: float, feedback: float):
        """Mjuk fallback-processor för stereo-ekot om libdsp inte är tillgängligt."""
        w = self._py_echo_write_idx
        buf_len = 48000
        dl = int(0.350 * self.sr)
        dr = int(0.375 * self.sr)
        for i in range(frames):
            rl = (w - dl + buf_len) % buf_len
            rr = (w - dr + buf_len) % buf_len
            sl = float(self._py_echo_buf[rl, 0])
            sr = float(self._py_echo_buf[rr, 1])
            self._py_echo_damp[0] = 0.55 * self._py_echo_damp[0] + 0.45 * sl
            self._py_echo_damp[1] = 0.55 * self._py_echo_damp[1] + 0.45 * sr
            fl = float(np.clip(self._py_echo_damp[0] * feedback, -1.2, 1.2))
            fr = float(np.clip(self._py_echo_damp[1] * feedback, -1.2, 1.2))
            self._py_echo_buf[w, 0] = in_stereo[i, 0] * send + fl
            self._py_echo_buf[w, 1] = in_stereo[i, 1] * send + fr
            echo_out[i, 0] = sl
            echo_out[i, 1] = sr
            w = (w + 1) % buf_len
        self._py_echo_write_idx = w

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
                    pos = (self.head_pos + np.arange(frames_needed)) % self.tape.max_frames
                    self.head_pos = (self.head_pos + frames_needed) % self.tape.max_frames
                    self.speed = 1.0

                    # Mjuk faslåsning mot live_edge för att absorbera ALSA-trådjitter
                    dist = (live_edge - self.head_pos) % self.tape.max_frames
                    if dist > self.tape.max_frames / 2:
                        dist -= self.tape.max_frames
                    if abs(dist) > int(0.5 * self.sr):
                        self.head_pos = live_edge
                    elif abs(dist) > 150:
                        nudge = np.clip(dist * 0.005, -1.5, 1.5)
                        self.head_pos = (self.head_pos + nudge) % self.tape.max_frames
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
                        # Användaren scratchar bakåt i musikhistorien från LIVE
                        self.is_live = False
                        rate = self._velocity_est
                        gain = 1.5 if rate < 200 else (4.0 if rate < 600 else (12.0 if rate < 1200 else 25.0))
                        back_dist = abs(steps * int(SAMPLES_PER_STEP * gain))
                        min_scratch = int(0.50 * self.sr)
                        back_dist = max(min_scratch, back_dist)
                        self.head_pos = (live_edge - back_dist) % self.tape.max_frames
                        self.speed = float(np.clip(-back_dist / frames_needed, -6.0, -0.2))
                        pos = (self.head_pos + np.arange(frames_needed) * self.speed) % self.tape.max_frames
                        return self.tape.read_interp(pos)
                    else:
                        # Förbli 100% bergfast vid LIVE i realtid utan ljudflimmer
                        pos = (self.head_pos + np.arange(frames_needed)) % self.tape.max_frames
                        self.head_pos = (self.head_pos + frames_needed) % self.tape.max_frames
                        self.speed = 1.0

                        dist = (live_edge - self.head_pos) % self.tape.max_frames
                        if dist > self.tape.max_frames / 2:
                            dist -= self.tape.max_frames
                        if abs(dist) > int(0.5 * self.sr):
                            self.head_pos = live_edge
                        elif abs(dist) > 150:
                            nudge = np.clip(dist * 0.005, -1.5, 1.5)
                            self.head_pos = (self.head_pos + nudge) % self.tape.max_frames
                        return self.tape.read_interp(pos)

                hand_on_wheel = (now - self.last_touch_time <= self.release_timeout)
                steps = self._pending_tape_steps
                self._pending_tape_steps = 0

                if steps != 0:
                    current_behind = (live_edge - self.head_pos) % self.tape.max_frames
                    behind_sec = current_behind / self.sr if current_behind < self.tape.max_frames / 2 else 0.0

                    if steps > 0:
                        # SUPER SPOOL FRAMÅT MOT LIVE:
                        # Flerstegs hastighetsacceleration anpassad för stor rotor
                        rate = self._velocity_est
                        if rate > 2000:
                            gain = 35.0
                        elif rate > 1200:
                            gain = 22.0
                        elif rate > 600:
                            gain = 12.0
                        elif rate > 300:
                            gain = 5.0
                        elif rate > 150:
                            gain = 2.5
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
                        # BAKÅT: Responsiv vinylscratch med dynamisk hastighetsacceleration
                        rate = self._velocity_est
                        if rate > 2000:
                            gain = 25.0
                        elif rate > 1200:
                            gain = 16.0
                        elif rate > 600:
                            gain = 8.0
                        elif rate > 300:
                            gain = 4.0
                        elif rate > 150:
                            gain = 2.0
                        else:
                            gain = 1.0

                        effective_step = int(SAMPLES_PER_STEP * gain)
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

            # --- MODE_DJ: Natural Beat-Loop Smart Crossfade ---
            elif self.mode == self.MODE_DJ:
                if self.is_dj_transition:
                    p = self.dj_trans_pos / float(max(1, self.dj_trans_frames))
                    self.dj_trans_progress = min(1.0, p)

                    # 1. Track 1: Sömlös naturlig beat-loop + LPF sveper neråt + fade out
                    loop_frames = max(256, self.dj_trans_t1_len)
                    rel = (self.dj_trans_track1_head - self.dj_trans_t1_start) % loop_frames
                    pos_t1 = (self.dj_trans_t1_start + (rel + np.arange(frames_needed)) % loop_frames) % self.tape.max_frames
                    self.dj_trans_track1_head = (self.dj_trans_t1_start + (rel + frames_needed) % loop_frames) % self.tape.max_frames
                    audio_t1 = self.tape.read_interp(pos_t1)

                    # Mjuk mikro-crossfade vid loop-skarven
                    wrap_idx = int(loop_frames - rel)
                    if 0 <= wrap_idx < frames_needed:
                        fade_len = min(256, frames_needed - wrap_idx)
                        if fade_len > 0:
                            fade_in = np.linspace(0.0, 1.0, fade_len)[:, np.newaxis]
                            audio_t1[wrap_idx:wrap_idx + fade_len] *= fade_in

                    # LPF sveper neråt: tar bort diskant och sång, lämnar pulserande klubbas/groove
                    f1 = float(np.clip(-0.10 - 0.75 * p, -1.0, 1.0))
                    g1 = float(np.cos(p * np.pi * 0.5))

                    if _libdsp is not None:
                        audio_t1 = np.ascontiguousarray(audio_t1, dtype=np.float32)
                        ptr1 = audio_t1.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                        _libdsp.svf_filter_block(ctypes.byref(self.dj_trans_svf_t1), ptr1, frames_needed, ctypes.c_float(f1))

                    audio_t1 *= g1

                    # 2. Track 2: Inkommande låt från realtidsströmmen + HPF svep in till rent
                    pos_t2 = (live_edge - frames_needed + np.arange(frames_needed)) % self.tape.max_frames
                    audio_t2 = self.tape.read_interp(pos_t2)

                    f2 = float(np.clip(0.70 * (1.0 - p), -1.0, 1.0))
                    g2 = float(np.sin(p * np.pi * 0.5))

                    if _libdsp is not None and f2 >= 0.005:
                        audio_t2 = np.ascontiguousarray(audio_t2, dtype=np.float32)
                        ptr2 = audio_t2.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                        _libdsp.svf_filter_block(ctypes.byref(self.dj_trans_svf_t2), ptr2, frames_needed, ctypes.c_float(f2))

                    audio_t2 *= g2

                    # 3. Summering
                    out = audio_t1 + audio_t2

                    self.head_pos = live_edge
                    self.dj_trans_pos += frames_needed
                    if self.dj_trans_pos >= self.dj_trans_frames:
                        # Övergången är klar! Lås sömlöst till Track 2 i nutid
                        self.is_dj_transition = False
                        self.is_live = True
                        self.head_pos = live_edge
                        self.speed = 1.0
                        self.dj_filter_val = 0.0

                    return out

                if self.dj_brake_active:
                    # Turntable brake / motor stop: mjuk motoravstängning
                    self.is_live = False
                    self.speed = max(0.0, self.speed - 0.035)
                else:
                    # Normal uppspelning eller motor spin-up tillbaka till 1.0
                    if self.speed < 1.0:
                        self.speed = min(1.0, self.speed + 0.06)

                if self.is_live and self.speed >= 0.99:
                    pos = (self.head_pos + np.arange(frames_needed)) % self.tape.max_frames
                    self.head_pos = (self.head_pos + frames_needed) % self.tape.max_frames

                    dist = (live_edge - self.head_pos) % self.tape.max_frames
                    if dist > self.tape.max_frames / 2:
                        dist -= self.tape.max_frames
                    if abs(dist) > int(0.5 * self.sr):
                        self.head_pos = live_edge
                    elif abs(dist) > 150:
                        nudge = np.clip(dist * 0.005, -1.5, 1.5)
                        self.head_pos = (self.head_pos + nudge) % self.tape.max_frames

                    out = self.tape.read_interp(pos)
                else:
                    step_frames = frames_needed * self.speed
                    pos = (self.head_pos + np.arange(frames_needed) * self.speed) % self.tape.max_frames
                    self.head_pos = (self.head_pos + step_frames) % self.tape.max_frames
                    out = self.tape.read_interp(pos)

                # Applicera Cytomic resonant DJ State Variable Filter
                if _libdsp is not None and abs(self.dj_filter_val) >= 0.005:
                    out = np.ascontiguousarray(out, dtype=np.float32)
                    ptr = out.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                    _libdsp.svf_filter_block(ctypes.byref(self.dj_svf_state), ptr, frames_needed, ctypes.c_float(self.dj_filter_val))
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
