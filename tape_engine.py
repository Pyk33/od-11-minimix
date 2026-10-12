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

    LOOP_BEAT_PRESETS = [
        (0.25, "1/4 BEAT"),
        (0.5,  "1/2 BEAT"),
        (1.0,  "1 BEAT"),
        (2.0,  "2 BEATS"),
        (4.0,  "1 BAR"),      # 1 hel takt (4 beats)
        (8.0,  "2 BARS"),     # 2 takter
        (16.0, "4 BARS"),     # 4 takter
        (32.0, "8 BARS"),     # 8 takter
    ]
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
        self.merge_fade_frames = int(1.6 * sample_rate)  # 1.6 sekunder mjuk DJ Merge
        self.merge_fade_pos = 0
        self.dj_merge_svf = _SVFState()
        self.tape_spool_svf = _SVFState()

        # Instant Looper state (Beats & Bars / Takter)
        self.loop_active = False
        self.loop_bpm = 120.0
        self.loop_beat_frames = int(0.5 * sample_rate)
        self.loop_bar_frames = int(2.0 * sample_rate)
        self.loop_preset_idx = 4  # Standard: 1 BAR (1 takt = 4 beats)
        self.loop_beats = 4.0
        self.loop_name = "1 BAR"
        self.loop_frames = int(4.0 * self.loop_beat_frames)
        self.loop_length_s = self.loop_frames / float(sample_rate)
        self.loop_start_pos = 0.0
        self.loop_end_pos = 0.0
        self.loop_reverse = False
        self.loop_edit_mode = "SIZE"    # "SIZE" (ändra längd i takter) eller "MOVE" (flytta takt för takt)
        self._loop_accum = 0

        # DJ Filter & Turntable Brake state
        self.dj_filter_val = 0.0        # -1.0 (LPF) .. 0.0 (Clean) .. +1.0 (HPF)
        self.dj_brake_active = False    # Sant när skivbromsen hålls nere
        self.dj_svf_state = _SVFState()
        self._smooth_behind_sec = 0.0

        # Auto DJ Smart Transition state (Beat-Matched DJ Transition Engine)
        self.is_dj_transition = False
        self.dj_trans_state = "IDLE"          # "WAIT_AUDIO", "ALIGN_BEAT", "CROSSFADING"
        self.dj_trans_duration_s = 7.5        # Lång, proffsig övergång över 4 takter (~7.5s)
        self.dj_trans_frames = int(7.5 * sample_rate)
        self.dj_trans_pos = 0
        self.dj_trans_progress = 0.0
        self.dj_trans_bpm = 120.0
        self.dj_trans_beat_frames = int(0.5 * sample_rate)
        self.dj_trans_bar_frames = int(2.0 * sample_rate)
        self.dj_trans_track1_head = 0.0
        self.dj_trans_t1_start = 0.0
        self.dj_trans_t1_len = int(2.0 * sample_rate)
        self.dj_trans_t1_phase = 0
        self.dj_trans_switched = False
        self.dj_trans_t2_detected_time = 0.0
        self.dj_trans_t2_head = 0.0
        self.dj_trans_wait_start = 0.0
        self.dj_trans_wait_timeout = 6.5
        self.dj_trans_svf_t1 = _SVFState()
        self.dj_trans_svf_t2 = _SVFState()
        self.dj_trans_echo_state = _EchoState()
        self._py_echo_buf = np.zeros((48000, 2), dtype=np.float32)
        self._py_echo_write_idx = 0
        self._py_echo_damp = [0.0, 0.0]

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
                self.dj_filter_val = 0.0

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
                # Gå in i LOOP: standby/armed, spela sömlöst vidare utan avbrott
                self.loop_active = False
                self.tape_stop_active = False
                self.dj_brake_active = False
                self.loop_edit_mode = "SIZE"
                self._loop_accum = 0

                # Standard: 1 BAR (4 beats)
                self.loop_preset_idx = 4
                self.loop_beats = 4.0
                self.loop_name = "1 BAR"

                anchor = int(self.head_pos if not self.is_live else live_edge)
                loop_start, bar_len, bpm = self._detect_natural_loop(anchor)
                self.loop_bpm = bpm
                self.loop_beat_frames = max(int(0.20 * self.sr), int(bar_len // 4))
                self.loop_bar_frames = 4 * self.loop_beat_frames
                self.loop_frames = self.loop_bar_frames
                self.loop_length_s = self.loop_frames / float(self.sr)

                self.loop_start_pos = loop_start
                self.loop_end_pos = (loop_start + self.loop_frames) % self.tape.max_frames
                # Behåll self.head_pos oförändrad så musiken fortsätter rulla på utan avbrott!

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

    def _detect_natural_loop(self, anchor_pos: int) -> tuple[int, int, float]:
        """
        Analyserar de senaste 3.5 sekunderna i bandbufferten före anchor_pos för att hitta
        låtens naturliga BPM och taktlängd (1 bar = 4 beats) synkad till taktslag.
        Returnerar (loop_start, bar_len_frames, bpm).
        """
        SEARCH_S = 3.5
        n_search = int(SEARCH_S * self.sr)
        pos = (anchor_pos - n_search + np.arange(n_search)) % self.tape.max_frames
        raw = self.tape.read_interp(pos)
        mono = 0.5 * (raw[:, 0] + raw[:, 1])

        hop = int(self.sr * 0.010)  # 10 ms upplösning = 480 samples vid 48 kHz
        n_frames = len(mono) // hop
        if n_frames < 100:
            fallback = int(2.0 * self.sr)
            return (anchor_pos - fallback) % self.tape.max_frames, fallback, 120.0

        mono_frames = mono[:n_frames * hop].reshape(n_frames, hop)
        energy = np.mean(mono_frames ** 2, axis=1)
        onset = np.maximum(0, np.diff(energy))

        if len(onset) > 50:
            onset_norm = onset - np.mean(onset)
            std = float(np.std(onset_norm))
            if std > 1e-6:
                onset_norm /= std

            # Sök BPM mellan 75 och 180 (lag 33..80 frames vid 10ms hop)
            min_lag = int(0.33 * 100)
            max_lag = int(0.80 * 100)
            corr = np.correlate(onset_norm, onset_norm, mode='full')
            center = len(onset_norm) - 1
            search_corr = corr[center + min_lag : center + max_lag + 1]

            if len(search_corr) > 0 and float(np.max(search_corr)) > 0.08:
                best_lag = min_lag + int(np.argmax(search_corr))
                bpm = float(np.clip(60.0 / (best_lag * 0.010), 75.0, 180.0))
                beat_frames = best_lag * hop
                bar_frames = 4 * beat_frames

                # Fashitta: hitta starkaste taktslag
                phase_scores = [float(np.sum(onset[shift::best_lag])) for shift in range(min(best_lag, len(onset)))]
                best_phase = int(np.argmax(phase_scores))

                # Hitta senaste taktslag före anchor_pos
                k_last = best_phase + int((len(onset) - 1 - best_phase) // best_lag) * best_lag
                offset_samples = int((len(onset) - 1 - k_last) * hop)

                loop_end = (anchor_pos - offset_samples) % self.tape.max_frames
                loop_start = (loop_end - bar_frames) % self.tape.max_frames
                return loop_start, bar_frames, bpm

        fallback_len = int(2.0 * self.sr)
        return (anchor_pos - fallback_len) % self.tape.max_frames, fallback_len, 120.0

    def notify_track_switched(self):
        """Anropas av streamer när nästa låt har laddats och sökts till ~18s."""
        with self._lock:
            self.dj_trans_switched = True

    def start_dj_transition(self, duration_s: Optional[float] = None, from_loop: bool = False):
        """
        Startar en takt- och energinivåsynkad DJ Smart Transition:
        1. Behåller Track 1 (antingen aktiv loop eller låtens groove) i full volym medan Spotify hämtar nästa låt.
        2. Övervakar inkommande ljudström tills Track 2 faktiskt har laddats och sökts in ~18 sekunder.
        3. Finner taktslag (beats/takt) och matchar energinivån.
        4. Lanserar en lång, mjuk crossfade (4 takter, ~7.5s) på taktslaget med LPF-basgroove och HPF-insvep.
        """
        with self._lock:
            self.is_dj_transition = True
            self.dj_trans_state = "WAIT_AUDIO"
            self.dj_trans_switched = False
            self.dj_trans_t2_detected_time = 0.0
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
            self.dj_trans_t2_head = float(live_edge)

            if from_loop or (self.mode == self.MODE_LOOP and self.loop_active):
                # Använd den aktiva loopen som Track 1
                self.dj_trans_bpm = getattr(self, "loop_bpm", 120.0)
                self.dj_trans_beat_frames = getattr(self, "loop_beat_frames", int(0.5 * self.sr))
                self.dj_trans_bar_frames = getattr(self, "loop_bar_frames", int(2.0 * self.sr))
                self.dj_trans_track1_head = self.head_pos
                self.dj_trans_t1_start = self.loop_start_pos
                self.dj_trans_t1_len = max(256, self.loop_frames)
                rel_head = (self.head_pos - self.loop_start_pos) % self.tape.max_frames
                self.dj_trans_t1_phase = int(rel_head % self.dj_trans_t1_len)
            else:
                # Analysera Track 1 för BPM och taktlängd runt uppspelningspunkten
                anchor = int(self.head_pos if not self.is_live else live_edge)
                loop_start, loop_len, bpm = self._detect_natural_loop(anchor)
                self.dj_trans_bpm = bpm
                self.dj_trans_beat_frames = int((60.0 / max(60.0, min(200.0, bpm))) * self.sr)
                self.dj_trans_bar_frames = max(self.dj_trans_beat_frames * 4, int(1.2 * self.sr))

                # Förankra Track 1: börja exakt från nuvarande uppspelningspunkt (0 ms hopp)
                self.dj_trans_track1_head = self.head_pos
                self.dj_trans_t1_start = loop_start
                self.dj_trans_t1_len = self.dj_trans_bar_frames
                self.dj_trans_t1_phase = int((anchor - loop_start) % self.dj_trans_t1_len)

            # Byt internt läge till DJ så att transition-processorn körs
            self.mode = self.MODE_DJ
            self.loop_active = False

            calc_dur = 4.0 * (self.dj_trans_bar_frames / float(self.sr))
            self.dj_trans_duration_s = float(duration_s) if duration_s is not None else max(6.5, min(9.0, calc_dur))
            self.dj_trans_frames = int(self.dj_trans_duration_s * self.sr)
            self.dj_trans_pos = 0
            self.dj_trans_progress = 0.0
            self.dj_trans_wait_start = time.monotonic()
            self.dj_trans_wait_timeout = 7.0  # Generös timeout för att vänta in Spotify-sökning och stabil audio
            self.dj_trans_svf_t1 = _SVFState()
            self.dj_trans_svf_t2 = _SVFState()
            # Överför filtertillstånd från dj_svf_state så Track 1 behåller sitt filter sömlöst utan klick
            if hasattr(self, "dj_svf_state"):
                self.dj_trans_svf_t1.ic1eq[0] = self.dj_svf_state.ic1eq[0]
                self.dj_trans_svf_t1.ic1eq[1] = self.dj_svf_state.ic1eq[1]
                self.dj_trans_svf_t1.ic2eq[0] = self.dj_svf_state.ic2eq[0]
                self.dj_trans_svf_t1.ic2eq[1] = self.dj_svf_state.ic2eq[1]
            if _libdsp is not None and hasattr(_libdsp, "echo_init"):
                _libdsp.echo_init(ctypes.byref(self.dj_trans_echo_state), self.sr)
            self._py_echo_buf.fill(0.0)
            self._py_echo_write_idx = 0
            self._py_echo_damp = [0.0, 0.0]
            self.dj_brake_active = False

    def end_dj_transition(self):
        """Avslutar övergången omedelbart och låser till nutid med användarens filter intakt."""
        with self._lock:
            self.is_dj_transition = False
            self.dj_trans_state = "IDLE"
            self.dj_trans_progress = 1.0
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
            self.head_pos = live_edge
            self.is_live = True
            self.speed = 1.0

    def _activate_loop_unlocked(self):
        """Intern metod för att aktivera loopen (anropas med self._lock hållen)."""
        if self.loop_active:
            return
        live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
        anchor = int(self.head_pos if not self.is_live else live_edge)
        loop_start, bar_len, bpm = self._detect_natural_loop(anchor)
        self.loop_bpm = bpm
        self.loop_beat_frames = max(int(0.20 * self.sr), int(bar_len // 4))
        self.loop_bar_frames = 4 * self.loop_beat_frames

        beats, label = self.LOOP_BEAT_PRESETS[self.loop_preset_idx]
        self.loop_beats = beats
        self.loop_name = label
        self.loop_frames = max(256, int(beats * self.loop_beat_frames))
        self.loop_length_s = self.loop_frames / float(self.sr)

        self.loop_start_pos = loop_start
        self.loop_end_pos = (loop_start + self.loop_frames) % self.tape.max_frames

        # Fäst head_pos faslåst inom loopen utan något hörbart hopp
        rel = (anchor - loop_start) % self.loop_frames
        self.head_pos = (self.loop_start_pos + rel) % self.tape.max_frames
        self.loop_active = True
        self.is_live = False
        self._loop_accum = 0

    def activate_loop(self):
        """Aktiverar loopen och låser musiken till den valda takten."""
        with self._lock:
            self._activate_loop_unlocked()

    def toggle_loop_edit_mode(self) -> str:
        """Växlar encoderns funktion i LOOP-läge mellan SIZE (längd) och MOVE (flytta fönster), eller aktiverar loopen om den är i standby."""
        with self._lock:
            if not self.loop_active:
                self._activate_loop_unlocked()
            else:
                self.loop_edit_mode = "MOVE" if self.loop_edit_mode == "SIZE" else "SIZE"
            return self.loop_edit_mode

    def get_merge_progress(self) -> float:
        """Exakt progress (0.0 till 1.0) för DJ Merge to LIVE visualisering på skärmen."""
        with self._lock:
            if not self.is_dj_merging or self.merge_fade_frames <= 0:
                return 0.0
            return float(np.clip(self.merge_fade_pos / float(self.merge_fade_frames), 0.0, 1.0))

    def jump_to_live(self, dj_merge: bool = True):
        """
        Hoppar till LIVE.
        - dj_merge=True:  Mjuk equal-power DJ-övergång (1.6s) med klubbasfilter.
        - dj_merge=False: Omedelbart hårt snitt (CUT) direkt till nutid utan fade.
        """
        with self._lock:
            live_edge = (self.tape.write_pos - self.live_latency_frames) % self.tape.max_frames
            behind = (live_edge - self.head_pos) % self.tape.max_frames
            behind_sec = behind / self.sr if behind < self.tape.max_frames / 2 else 0.0

            if not dj_merge or behind_sec < 0.20:
                # Omedelbart hårt snitt (CUT) till nutid utan fade
                self.head_pos = live_edge
                self.is_live = True
                self.is_dj_merging = False
                self.speed = 1.0
                self._pending_tape_steps = 0
            else:
                # Mjuk DJ Merge Crossfade!
                self.is_dj_merging = True
                self.merge_fade_pos = 0
                self.dj_merge_svf = _SVFState()

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
                if not self.loop_active:
                    self._activate_loop_unlocked()

                if self.loop_edit_mode == "SIZE":
                    # Ändra looplängd i musikaliska beats och takter (1/4 BEAT .. 8 BARS)
                    self._loop_accum += steps
                    THRESHOLD = 18  # Tydligt snäpp per klick/detent på encodern
                    if abs(self._loop_accum) >= THRESHOLD:
                        direction = 1 if self._loop_accum > 0 else -1
                        self._loop_accum = 0

                        new_idx = max(0, min(len(self.LOOP_BEAT_PRESETS) - 1, self.loop_preset_idx + direction))
                        self.loop_preset_idx = new_idx
                        beats, label = self.LOOP_BEAT_PRESETS[new_idx]
                        self.loop_beats = beats
                        self.loop_name = label
                        self.loop_frames = max(256, int(beats * self.loop_beat_frames))
                        self.loop_length_s = self.loop_frames / float(self.sr)

                        # Håll loop_start_pos förankrad och expandera/krymp loop_end_pos
                        new_end = (self.loop_start_pos + self.loop_frames) % self.tape.max_frames
                        behind_end = (live_edge - new_end) % self.tape.max_frames
                        if behind_end > self.tape.max_frames / 2: # passerade live in i framtiden
                            self.loop_end_pos = live_edge
                            self.loop_start_pos = (live_edge - self.loop_frames) % self.tape.max_frames
                        else:
                            self.loop_end_pos = new_end

                        # Säkerställ att head_pos hålls inom det nya loopintervallet
                        rel = (self.head_pos - self.loop_start_pos) % self.tape.max_frames
                        self.head_pos = (self.loop_start_pos + (rel % self.loop_frames)) % self.tape.max_frames

                elif self.loop_edit_mode == "MOVE":
                    # Skifta mellan naturliga loopsekvenser i låten (1 hel takt eller 1 beat per snäpp)
                    self._loop_accum += steps
                    THRESHOLD = 18
                    if abs(self._loop_accum) >= THRESHOLD:
                        num_steps = int(self._loop_accum // THRESHOLD) if self._loop_accum > 0 else int(-((-self._loop_accum) // THRESHOLD))
                        self._loop_accum -= num_steps * THRESHOLD

                        # Skifta med 1 hel takt (4 beats) om loopen är >= 1 takt, annars 1 beat
                        shift_unit = self.loop_bar_frames if self.loop_beats >= 4.0 else self.loop_beat_frames
                        shift = num_steps * shift_unit

                        new_start = (self.loop_start_pos + shift) % self.tape.max_frames
                        new_end = (self.loop_end_pos + shift) % self.tape.max_frames

                        behind_end = (live_edge - new_end) % self.tape.max_frames
                        if behind_end > self.tape.max_frames / 2: # kan inte flytta förbi LIVE
                            self.loop_end_pos = live_edge
                            self.loop_start_pos = (live_edge - self.loop_frames) % self.tape.max_frames
                        else:
                            self.loop_start_pos = new_start
                            self.loop_end_pos = new_end
                            self.head_pos = (self.head_pos + shift) % self.tape.max_frames

            elif self.mode == self.MODE_DJ:
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

    def get_loop_label(self) -> str:
        with self._lock:
            return getattr(self, "loop_name", "1 BAR")

    def get_loop_bpm(self) -> float:
        with self._lock:
            return getattr(self, "loop_bpm", 120.0)

    def get_loop_beats(self) -> float:
        with self._lock:
            return getattr(self, "loop_beats", 4.0)

    def get_loop_progress(self) -> float:
        """Exakt fasindikator (0.0 till 1.0) för synkad skärmanimering."""
        with self._lock:
            if self.mode != self.MODE_LOOP or not self.loop_active:
                return 0.0
            loop_len = self.loop_frames if hasattr(self, "loop_frames") and self.loop_frames > 0 else int(self.loop_length_s * self.sr)
            if loop_len <= 0:
                return 0.0
            rel = (self.head_pos - self.loop_start_pos) % self.tape.max_frames
            return float(np.clip((rel % loop_len) / float(loop_len), 0.0, 1.0))

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

                # Mjukt LPF-svep på det fördröjda bandet: rullar av toppen medan live tar över
                p_scalar = float(cur_p / max(1, fade_frames))
                f_merge = float(np.clip(-0.15 - 0.70 * p_scalar, -0.90, 0.0))
                if _libdsp is not None:
                    audio_del = np.ascontiguousarray(audio_del, dtype=np.float32)
                    ptr_del = audio_del.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                    _libdsp.svf_filter_block(ctypes.byref(self.dj_merge_svf), ptr_del, frames_needed, ctypes.c_float(f_merge))

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
                        gain = 1.4 if rate < 200 else (3.0 if rate < 600 else (8.0 if rate < 1200 else 16.0))
                        back_dist = abs(steps * int(SAMPLES_PER_STEP * gain))
                        min_scratch = int(0.35 * self.sr)
                        back_dist = max(min_scratch, back_dist)
                        self.head_pos = (live_edge - back_dist) % self.tape.max_frames
                        # Resamplingshastighet bakåt: musikalisk vinyl scratch (max -1.8x, inte -6.0x squeal)
                        self.speed = float(np.clip(-0.4 - (rate / 600.0), -1.8, -0.3))
                        pos = (self.head_pos + np.arange(frames_needed) * self.speed) % self.tape.max_frames
                        out = self.tape.read_interp(pos)
                        if _libdsp is not None:
                            out = np.ascontiguousarray(out, dtype=np.float32)
                            ptr = out.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            _libdsp.svf_filter_block(ctypes.byref(self.tape_spool_svf), ptr, frames_needed, ctypes.c_float(-0.35))
                        return out
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
                            gain = 30.0
                        elif rate > 1200:
                            gain = 18.0
                        elif rate > 600:
                            gain = 10.0
                        elif rate > 300:
                            gain = 4.5
                        elif rate > 150:
                            gain = 2.2
                        else:
                            gain = 1.4

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
                            # Resamplingshastighet (tonhöjd): behåll i ett musikaliskt intervall (max 2.0x, inte 6.0x squeal!)
                            self.speed = float(np.clip(1.0 + (rate / 600.0), 1.0, 2.0))

                    else:
                        # BAKÅT: Responsiv vinylscratch med dynamisk hastighetsacceleration
                        rate = self._velocity_est
                        if rate > 2000:
                            gain = 22.0
                        elif rate > 1200:
                            gain = 14.0
                        elif rate > 600:
                            gain = 7.0
                        elif rate > 300:
                            gain = 3.5
                        elif rate > 150:
                            gain = 1.8
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

                        # Resamplingshastighet bakåt: musikalisk vinyl-tonhöjd (mellan -0.2x och -1.8x)
                        self.speed = float(np.clip(-0.35 - (rate / 700.0), -1.8, -0.2))

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
                out = self.tape.read_interp(pos)

                # Anti-squeal bandhuvudsdämpning: dämpar skarpa diskantskrik när bandet spolas snabbt eller bakåt
                if self.speed > 1.15 or self.speed < 0.0:
                    excess = max(0.0, self.speed - 1.15) if self.speed > 0 else (abs(self.speed) * 0.45)
                    f_damp = float(np.clip(-0.15 - 0.40 * excess, -0.65, 0.0))
                    if _libdsp is not None:
                        out = np.ascontiguousarray(out, dtype=np.float32)
                        ptr = out.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                        _libdsp.svf_filter_block(ctypes.byref(self.tape_spool_svf), ptr, frames_needed, ctypes.c_float(f_damp))

                return out

            # --- MODE_LOOP: Instant looper med framåtriktad expansion ---
            elif self.mode == self.MODE_LOOP:
                if not self.loop_active:
                    # Loopen är i standby: spela sömlöst vidare utan minsta avbrott
                    if self.is_live:
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

                        return self.tape.read_interp(pos)
                    else:
                        step_frames = frames_needed * self.speed
                        pos = (self.head_pos + np.arange(frames_needed) * self.speed) % self.tape.max_frames
                        self.head_pos = (self.head_pos + step_frames) % self.tape.max_frames
                        return self.tape.read_interp(pos)

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

            # --- MODE_DJ: Beat-Matched Smart Transition Engine ---
            elif self.mode == self.MODE_DJ:
                if self.is_dj_transition:
                    # Spåra inkommande ström (Track 2) med en jämn, monoton läsnål och PLL mot live_edge
                    pos_t2 = (self.dj_trans_t2_head + np.arange(frames_needed)) % self.tape.max_frames
                    self.dj_trans_t2_head = (self.dj_trans_t2_head + frames_needed) % self.tape.max_frames

                    dist_t2 = (live_edge - self.dj_trans_t2_head) % self.tape.max_frames
                    if dist_t2 > self.tape.max_frames / 2:
                        dist_t2 -= self.tape.max_frames

                    if abs(dist_t2) > int(0.5 * self.sr):
                        self.dj_trans_t2_head = float(live_edge)
                    elif abs(dist_t2) > 100:
                        nudge_t2 = np.clip(dist_t2 * 0.005, -1.5, 1.5)
                        self.dj_trans_t2_head = (self.dj_trans_t2_head + nudge_t2) % self.tape.max_frames

                    audio_t2_raw = self.tape.read_interp(pos_t2)
                    rms_live = float(np.sqrt(np.mean(audio_t2_raw ** 2)))
                    peak_live = float(np.max(np.abs(audio_t2_raw)))
                    now = time.monotonic()

                    # FAS 1: VÄNTA PÅ ATT NÄSTA LÅT BYTS, SÖKS TILL ~18S OCH FAKTISKT HAR STABIL LJUD/ENERGI
                    if self.dj_trans_state == "WAIT_AUDIO":
                        track_ready = self.dj_trans_switched or (now - self.dj_trans_wait_start >= 1.5)
                        has_audio = track_ready and (rms_live >= 0.018 or peak_live >= 0.045)
                        timed_out = (now - self.dj_trans_wait_start >= self.dj_trans_wait_timeout)

                        if has_audio:
                            # Stabil audio-verifiering: vänta tills audio funnits i minst 0.35s så musiken verkligen kommit igång
                            if self.dj_trans_t2_detected_time == 0.0:
                                self.dj_trans_t2_detected_time = now
                            elif now - self.dj_trans_t2_detected_time >= 0.35:
                                self.dj_trans_state = "ALIGN_BEAT"
                        elif timed_out:
                            self.dj_trans_state = "ALIGN_BEAT"
                        else:
                            self.dj_trans_t2_detected_time = 0.0

                        # Medan vi väntar: Spela Track 1 i sitt musikaliska groove med klubbasfilter (-0.20 LPF)
                        rel = self.dj_trans_t1_phase
                        indices = (rel + np.arange(frames_needed)) % self.dj_trans_t1_len
                        pos_t1 = (self.dj_trans_t1_start + indices) % self.tape.max_frames
                        self.dj_trans_t1_phase = int((rel + frames_needed) % self.dj_trans_t1_len)
                        audio_t1 = self.tape.read_interp(pos_t1)

                        wrap_idx = int(self.dj_trans_t1_len - rel)
                        if 0 <= wrap_idx < frames_needed:
                            fade_len = min(256, frames_needed - wrap_idx)
                            if fade_len > 0:
                                audio_t1[wrap_idx:wrap_idx + fade_len] *= np.linspace(0.0, 1.0, fade_len)[:, np.newaxis]

                        # Filter på Track 1: Använd användarens aktiva filterposition (eller -0.20 om neutral)
                        F = self.dj_filter_val
                        f_wait = F if abs(F) > 0.05 else -0.20
                        if _libdsp is not None and abs(f_wait) >= 0.005:
                            audio_t1 = np.ascontiguousarray(audio_t1, dtype=np.float32)
                            ptr1 = audio_t1.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            _libdsp.svf_filter_block(ctypes.byref(self.dj_trans_svf_t1), ptr1, frames_needed, ctypes.c_float(f_wait))

                        self.head_pos = self.dj_trans_t2_head
                        self.dj_trans_progress = 0.0
                        return audio_t1

                    # FAS 2: SYNKRONISERA MOT NÄSTA TAKTSLAG (BEAT / TAKT)
                    if self.dj_trans_state == "ALIGN_BEAT":
                        beat_frames = max(512, self.dj_trans_beat_frames)
                        rel_in_beat = self.dj_trans_t1_phase % beat_frames
                        frames_to_beat = beat_frames - rel_in_beat

                        if frames_to_beat <= frames_needed or (now - self.dj_trans_wait_start >= self.dj_trans_wait_timeout + 1.0):
                            # NÄSTA TAKTSLAG TRÄFFAT! Starta crossfaden exakt på takten!
                            self.dj_trans_state = "CROSSFADING"
                            self.dj_trans_pos = 0
                            calc_dur = 4.0 * (self.dj_trans_bar_frames / float(self.sr))
                            self.dj_trans_duration_s = max(6.5, min(9.0, calc_dur))
                            self.dj_trans_frames = int(self.dj_trans_duration_s * self.sr)

                        rel = self.dj_trans_t1_phase
                        indices = (rel + np.arange(frames_needed)) % self.dj_trans_t1_len
                        pos_t1 = (self.dj_trans_t1_start + indices) % self.tape.max_frames
                        self.dj_trans_t1_phase = int((rel + frames_needed) % self.dj_trans_t1_len)
                        audio_t1 = self.tape.read_interp(pos_t1)

                        wrap_idx = int(self.dj_trans_t1_len - rel)
                        if 0 <= wrap_idx < frames_needed:
                            fade_len = min(256, frames_needed - wrap_idx)
                            if fade_len > 0:
                                audio_t1[wrap_idx:wrap_idx + fade_len] *= np.linspace(0.0, 1.0, fade_len)[:, np.newaxis]

                        F = self.dj_filter_val
                        f_wait = F if abs(F) > 0.05 else -0.20
                        if _libdsp is not None and abs(f_wait) >= 0.005:
                            audio_t1 = np.ascontiguousarray(audio_t1, dtype=np.float32)
                            ptr1 = audio_t1.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            _libdsp.svf_filter_block(ctypes.byref(self.dj_trans_svf_t1), ptr1, frames_needed, ctypes.c_float(f_wait))

                        self.head_pos = self.dj_trans_t2_head
                        self.dj_trans_progress = 0.0
                        return audio_t1

                    # FAS 3: DJ CROSSFADE MED ANVÄNDARENS FILTERPOSITION (-1.0 LPF .. +1.0 HPF)
                    if self.dj_trans_state == "CROSSFADING":
                        p = self.dj_trans_pos / float(max(1, self.dj_trans_frames))
                        self.dj_trans_progress = min(1.0, p)

                        # Filterkurvor anpassade efter användarens rattposition F
                        F = self.dj_filter_val
                        if F <= 0.0:
                            f1_start = min(F, -0.20) if abs(F) <= 0.05 else F
                            f1 = float(np.clip(f1_start - (0.85 + f1_start) * p, -1.0, 1.0))
                            t2_entry = 0.22
                            f2 = float(np.clip(t2_entry * (1.0 - p) + F * p, -1.0, 1.0))
                        else:
                            f1_start = F
                            f1 = float(np.clip(f1_start + (0.90 - f1_start) * p, -1.0, 1.0))
                            t2_entry = -0.22
                            f2 = float(np.clip(t2_entry * (1.0 - p) + F * p, -1.0, 1.0))

                        # 1. Track 1: Rytmkärna tonas ut med svepande filter & rymdsvans
                        rel = self.dj_trans_t1_phase
                        indices = (rel + np.arange(frames_needed)) % self.dj_trans_t1_len
                        pos_t1 = (self.dj_trans_t1_start + indices) % self.tape.max_frames
                        self.dj_trans_t1_phase = int((rel + frames_needed) % self.dj_trans_t1_len)
                        audio_t1 = self.tape.read_interp(pos_t1)

                        wrap_idx = int(self.dj_trans_t1_len - rel)
                        if 0 <= wrap_idx < frames_needed:
                            fade_len = min(256, frames_needed - wrap_idx)
                            if fade_len > 0:
                                audio_t1[wrap_idx:wrap_idx + fade_len] *= np.linspace(0.0, 1.0, fade_len)[:, np.newaxis]

                        g1 = float(np.cos(p * np.pi * 0.5))

                        if _libdsp is not None and abs(f1) >= 0.005:
                            audio_t1 = np.ascontiguousarray(audio_t1, dtype=np.float32)
                            ptr1 = audio_t1.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            _libdsp.svf_filter_block(ctypes.byref(self.dj_trans_svf_t1), ptr1, frames_needed, ctypes.c_float(f1))

                        # Stereo Space Echo Tail
                        send_t1 = float(np.clip(1.0 - 2.0 * p, 0.0, 1.0))
                        fb_t1 = float(np.clip(0.65 * (1.0 - 0.5 * p), 0.0, 0.65))
                        echo_out = np.zeros((frames_needed, 2), dtype=np.float32)

                        if _libdsp is not None and hasattr(_libdsp, "echo_process_block"):
                            audio_t1 = np.ascontiguousarray(audio_t1, dtype=np.float32)
                            ptr1 = audio_t1.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            echo_ptr = echo_out.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            _libdsp.echo_process_block(ctypes.byref(self.dj_trans_echo_state), ptr1, echo_ptr, frames_needed, ctypes.c_float(send_t1), ctypes.c_float(fb_t1))
                        else:
                            self._py_echo_process(audio_t1, echo_out, frames_needed, send_t1, fb_t1)

                        out_t1 = audio_t1 * g1 + echo_out * (0.60 * (1.0 - p))

                        # 2. Track 2: Inkommande låt via monoton dj_trans_t2_head + filter mot position F
                        audio_t2 = audio_t2_raw.copy()
                        g2 = float(np.sin(p * np.pi * 0.5))

                        if _libdsp is not None and abs(f2) >= 0.005:
                            audio_t2 = np.ascontiguousarray(audio_t2, dtype=np.float32)
                            ptr2 = audio_t2.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            _libdsp.svf_filter_block(ctypes.byref(self.dj_trans_svf_t2), ptr2, frames_needed, ctypes.c_float(f2))

                        out_t2 = audio_t2 * g2

                        # 3. Summering: konstant total akustisk energi med mjuk mättnad
                        out = np.clip(out_t1 + out_t2, -1.0, 1.0)

                        self.head_pos = self.dj_trans_t2_head
                        self.dj_trans_pos += frames_needed
                        if self.dj_trans_pos >= self.dj_trans_frames:
                            # Övergången är klar! Lås sömlöst till Track 2 med användarens filter intakt
                            self.is_dj_transition = False
                            self.dj_trans_state = "IDLE"
                            self.is_live = True
                            self.head_pos = self.dj_trans_t2_head
                            self.speed = 1.0
                            # Kopiera SVF-tillstånd för klickfri handover till normal uppspelning
                            if hasattr(self, "dj_svf_state") and hasattr(self, "dj_trans_svf_t2"):
                                self.dj_svf_state.ic1eq[0] = self.dj_trans_svf_t2.ic1eq[0]
                                self.dj_svf_state.ic1eq[1] = self.dj_trans_svf_t2.ic1eq[1]
                                self.dj_svf_state.ic2eq[0] = self.dj_trans_svf_t2.ic2eq[0]
                                self.dj_svf_state.ic2eq[1] = self.dj_trans_svf_t2.ic2eq[1]

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
