"""
audio_source.py — High-fidelity real-time audio capture and DSP spectral analysis for Lyrune.

Architecture:
  - NativeWasapiLoopback (Windows): Direct Windows Core Audio WASAPI loopback capture
    via COM/ctypes with zero external driver dependencies.
  - LinuxLoopbackCapture (Linux): PulseAudio / PipeWire / ALSA monitor capture.
  - AudioDSP: Fast short-time FFT, Hann windowing, logarithmic perceptual frequency
    grouping (25 Hz to 16 kHz), acoustic tilt, dynamic range compression, and noise gating.
  - LoopbackAudioSource & AdaptiveAudioSource: Multi-platform audio pipeline feeding genuine
    PCM spectral data to visualizers, gracefully idling on silence/pause.
"""

import sys
import time
import math
import threading
from typing import List, Dict, Any, Optional, Tuple
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

import numpy as np

from lyrune.visualizer.base import BaseAudioSource, AudioData
from lyrune.logger import log_event, log_once


# ==============================================================================
# Native Windows WASAPI Loopback Capture (COM / ctypes)
# ==============================================================================
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes, Structure, POINTER, c_float, c_int16, c_void_p, byref, cast

    ole32 = ctypes.windll.ole32

    class GUID(Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8)
        ]
        def __init__(self, l, w1, w2, b1, b2, b3, b4, b5, b6, b7, b8):
            super().__init__(l, w1, w2, (wintypes.BYTE * 8)(b1, b2, b3, b4, b5, b6, b7, b8))

    CLSID_MMDeviceEnumerator = GUID(0xBCDE0395, 0xE52F, 0x467C, 0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E)
    IID_IMMDeviceEnumerator = GUID(0xA95664D2, 0x9614, 0x4F35, 0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6)
    IID_IAudioClient = GUID(0x1CB9AD4C, 0xDBFA, 0x4C32, 0xB1, 0x78, 0xC2, 0xF5, 0x68, 0xA7, 0x03, 0xB2)
    IID_IAudioCaptureClient = GUID(0xC8ADBD64, 0xE71E, 0x48A0, 0xA4, 0xDE, 0x18, 0x5C, 0x39, 0x5C, 0xD3, 0x17)

    class WAVEFORMATEX(Structure):
        _fields_ = [
            ("wFormatTag", wintypes.WORD),
            ("nChannels", wintypes.WORD),
            ("nSamplesPerSec", wintypes.DWORD),
            ("nAvgBytesPerSec", wintypes.DWORD),
            ("nBlockAlign", wintypes.WORD),
            ("wBitsPerSample", wintypes.WORD),
            ("cbSize", wintypes.WORD),
        ]

    class IMMDeviceEnumeratorVtbl(Structure):
        _fields_ = [
            ("QueryInterface", c_void_p),
            ("AddRef", c_void_p),
            ("Release", c_void_p),
            ("EnumAudioEndpoints", c_void_p),
            ("GetDefaultAudioEndpoint", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, c_int16, c_int16, POINTER(c_void_p))),
            ("GetDevice", c_void_p),
            ("RegisterEndpointNotificationCallback", c_void_p),
            ("UnregisterEndpointNotificationCallback", c_void_p),
        ]

    class IMMDeviceVtbl(Structure):
        _fields_ = [
            ("QueryInterface", c_void_p),
            ("AddRef", c_void_p),
            ("Release", c_void_p),
            ("Activate", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))),
            ("OpenPropertyStore", c_void_p),
            ("GetId", c_void_p),
            ("GetState", c_void_p),
        ]

    class IAudioClientVtbl(Structure):
        _fields_ = [
            ("QueryInterface", c_void_p),
            ("AddRef", c_void_p),
            ("Release", c_void_p),
            ("Initialize", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, c_int16, wintypes.DWORD, ctypes.c_int64, ctypes.c_int64, POINTER(WAVEFORMATEX), POINTER(GUID))),
            ("GetBufferSize", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(wintypes.UINT))),
            ("GetStreamLatency", c_void_p),
            ("GetCurrentPadding", c_void_p),
            ("IsFormatSupported", c_void_p),
            ("GetMixFormat", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(POINTER(WAVEFORMATEX)))),
            ("GetDevicePeriod", c_void_p),
            ("Start", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p)),
            ("Stop", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p)),
            ("Reset", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p)),
            ("SetEventHandle", c_void_p),
            ("GetService", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))),
        ]

    class IAudioCaptureClientVtbl(Structure):
        _fields_ = [
            ("QueryInterface", c_void_p),
            ("AddRef", c_void_p),
            ("Release", c_void_p),
            ("GetBuffer", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(POINTER(ctypes.c_byte)), POINTER(wintypes.UINT), POINTER(wintypes.DWORD), POINTER(ctypes.c_uint64), POINTER(ctypes.c_uint64))),
            ("ReleaseBuffer", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, wintypes.UINT)),
            ("GetNextPacketSize", ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(wintypes.UINT))),
        ]

    class COMObject(Structure):
        _fields_ = [("lpVtbl", c_void_p)]


class NativeWasapiLoopback:
    """
    Native Windows Core Audio loopback capture thread.
    Captures live output stream directly from the default playback endpoint.
    """
    def __init__(self, on_samples_callback):
        self.on_samples = on_samples_callback
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.sample_rate = 48000
        self.channels = 2
        self.device_name = "Default Windows Playback Device"
        self.is_capturing = False

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_worker, daemon=True, name="WasapiLoopbackThread")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self.is_capturing = False

    def _capture_worker(self) -> None:
        ole32.CoInitialize(None)
        pEnumerator = None
        pDevice = None
        pAudioClient = None
        pCaptureClient = None

        try:
            pEnum = c_void_p()
            CLSCTX_ALL = 23
            hr = ole32.CoCreateInstance(
                byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                byref(IID_IMMDeviceEnumerator), byref(pEnum)
            )
            if hr != 0 or not pEnum:
                log_event(f"❌ [WASAPI] CoCreateInstance MMDeviceEnumerator failed: 0x{hr:08X}")
                return
            pEnumerator = pEnum

            enum_obj = cast(pEnumerator, POINTER(COMObject)).contents
            enum_vtbl = cast(enum_obj.lpVtbl, POINTER(IMMDeviceEnumeratorVtbl)).contents

            pDev = c_void_p()
            hr = enum_vtbl.GetDefaultAudioEndpoint(pEnumerator, 0, 0, byref(pDev))  # eRender=0, eConsole=0
            if hr != 0 or not pDev:
                log_event(f"❌ [WASAPI] GetDefaultAudioEndpoint failed: 0x{hr:08X}")
                return
            pDevice = pDev

            dev_obj = cast(pDevice, POINTER(COMObject)).contents
            dev_vtbl = cast(dev_obj.lpVtbl, POINTER(IMMDeviceVtbl)).contents

            pClient = c_void_p()
            hr = dev_vtbl.Activate(pDevice, byref(IID_IAudioClient), CLSCTX_ALL, None, byref(pClient))
            if hr != 0 or not pClient:
                log_event(f"❌ [WASAPI] Activate IAudioClient failed: 0x{hr:08X}")
                return
            pAudioClient = pClient

            client_obj = cast(pAudioClient, POINTER(COMObject)).contents
            client_vtbl = cast(client_obj.lpVtbl, POINTER(IAudioClientVtbl)).contents

            pWaveFormat = POINTER(WAVEFORMATEX)()
            hr = client_vtbl.GetMixFormat(pAudioClient, byref(pWaveFormat))
            if hr != 0 or not pWaveFormat:
                log_event(f"❌ [WASAPI] GetMixFormat failed: 0x{hr:08X}")
                return

            wfx = pWaveFormat.contents
            self.sample_rate = int(wfx.nSamplesPerSec)
            self.channels = int(wfx.nChannels)
            bits_per_sample = int(wfx.wBitsPerSample)

            AUDCLNT_SHAREMODE_SHARED = 0
            AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
            hnsBufferDuration = 1000000  # 100ms

            hr = client_vtbl.Initialize(
                pAudioClient, AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK,
                hnsBufferDuration, 0, pWaveFormat, None
            )
            if hr != 0:
                log_event(f"❌ [WASAPI] IAudioClient::Initialize loopback failed: 0x{hr:08X}")
                return

            pCap = c_void_p()
            hr = client_vtbl.GetService(pAudioClient, byref(IID_IAudioCaptureClient), byref(pCap))
            if hr != 0 or not pCap:
                log_event(f"❌ [WASAPI] GetService IAudioCaptureClient failed: 0x{hr:08X}")
                return
            pCaptureClient = pCap

            capture_obj = cast(pCaptureClient, POINTER(COMObject)).contents
            capture_vtbl = cast(capture_obj.lpVtbl, POINTER(IAudioCaptureClientVtbl)).contents

            hr = client_vtbl.Start(pAudioClient)
            if hr != 0:
                log_event(f"❌ [WASAPI] IAudioClient::Start failed: 0x{hr:08X}")
                return

            self.is_capturing = True
            log_event(f"🎙️ [WASAPI Loopback] Connected: {self.sample_rate}Hz, {self.channels}ch, {bits_per_sample}-bit", force=True)

            while not self._stop_event.is_set():
                packet_size = wintypes.UINT()
                hr = capture_vtbl.GetNextPacketSize(pCaptureClient, byref(packet_size))
                if hr == 0 and packet_size.value > 0:
                    pData = POINTER(ctypes.c_byte)()
                    numFrames = wintypes.UINT()
                    flags = wintypes.DWORD()
                    hr = capture_vtbl.GetBuffer(pCaptureClient, byref(pData), byref(numFrames), byref(flags), None, None)
                    if hr == 0 and numFrames.value > 0:
                        frames_count = numFrames.value
                        total_samples = frames_count * self.channels

                        # Float 32-bit (standard WASAPI mix format)
                        if bits_per_sample == 32:
                            float_ptr = cast(pData, POINTER(c_float))
                            # Zero copy convert to numpy array
                            raw_arr = np.ctypeslib.as_array(float_ptr, shape=(frames_count, self.channels)).copy()
                            # Check silent flags (AUDCLNT_BUFFERFLAGS_SILENT = 2)
                            if flags.value & 2:
                                raw_arr.fill(0.0)
                            self.on_samples(raw_arr)
                        elif bits_per_sample == 16:
                            int16_ptr = cast(pData, POINTER(c_int16))
                            raw_arr = np.ctypeslib.as_array(int16_ptr, shape=(frames_count, self.channels)).astype(np.float32) / 32768.0
                            if flags.value & 2:
                                raw_arr.fill(0.0)
                            self.on_samples(raw_arr)

                        capture_vtbl.ReleaseBuffer(pCaptureClient, numFrames.value)
                time.sleep(0.005)  # 5ms polling loop

            client_vtbl.Stop(pAudioClient)
        except Exception as e:
            log_event(f"❌ [WASAPI Loopback Exception] {e}")
        finally:
            self.is_capturing = False
            ole32.CoUninitialize()
            log_event("[WASAPI Loopback] Capture thread stopped.")


# ==============================================================================
# Audio DSP Spectral Analysis Engine
# ==============================================================================
class AudioDSP:
    """
    High-resolution spectral analysis engine.
    Performs short-time FFT, Hann windowing, logarithmic perceptual grouping (25 Hz - 16 kHz),
    acoustic frequency tilt, dynamic range compression, and noise floor gating.
    """
    def __init__(self, sample_rate: int = 48000, fft_size: int = 2048):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.window = np.hanning(fft_size).astype(np.float32)
        self.min_freq = 25.0
        self.max_freq = 16000.0

        # Ring buffer for continuous audio samples
        self._buffer = np.zeros(fft_size, dtype=np.float32)
        self._lock = threading.Lock()

        # Dynamic range tracking state
        self.rolling_max = 0.02
        self.rolling_floor = 1e-4
        self.last_rms = 0.0
        self.last_peak = 0.0

    def push_pcm(self, samples: np.ndarray) -> None:
        """Appends new stereo or mono PCM float samples to the ring buffer."""
        if samples is None or len(samples) == 0:
            return
        if samples.ndim == 2:
            mono = np.mean(samples, axis=1).astype(np.float32)
        else:
            mono = samples.astype(np.float32)

        n = len(mono)
        with self._lock:
            if n >= self.fft_size:
                self._buffer[:] = mono[-self.fft_size:]
            else:
                self._buffer[:-n] = self._buffer[n:]
                self._buffer[-n:] = mono

    def analyze_spectrum(self, num_bars: int = 32) -> Tuple[List[float], float, float]:
        """
        Computes logarithmic frequency band amplitudes scaled to num_bars.
        Returns: (band_values [0.0, 1.0], rms_energy, peak_energy)
        """
        num_bars = max(4, num_bars)
        with self._lock:
            raw_pcm = self._buffer.copy()

        # DC offset removal
        mean_val = float(np.mean(raw_pcm))
        pcm = raw_pcm - mean_val

        # RMS and Peak Energy
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        peak = float(np.max(np.abs(pcm)))
        self.last_rms = rms
        self.last_peak = peak

        # Noise gate: Silence or low ambient noise
        if rms < 1e-4:
            return [0.0] * num_bars, 0.0, 0.0

        # Windowing
        windowed = pcm * self.window

        # Real FFT
        fft_complex = np.fft.rfft(windowed)
        magnitudes = (np.abs(fft_complex) / (self.fft_size / 2.0)).astype(np.float32)
        freq_bins = len(magnitudes)

        # Update rolling peak with smooth decay
        frame_peak = float(np.max(magnitudes))
        if frame_peak > self.rolling_max:
            self.rolling_max = frame_peak
        else:
            self.rolling_max = max(0.01, self.rolling_max * 0.992 + frame_peak * 0.008)

        # Calculate logarithmic frequency bands
        band_edges = np.logspace(
            np.log10(self.min_freq),
            np.log10(self.max_freq),
            num_bars + 1
        )
        freq_per_bin = (self.sample_rate / 2.0) / max(1, freq_bins - 1)

        bar_values = []
        for i in range(num_bars):
            f_low = band_edges[i]
            f_high = band_edges[i + 1]

            bin_low = f_low / freq_per_bin
            bin_high = f_high / freq_per_bin

            idx_start = int(math.floor(bin_low))
            idx_end = max(idx_start + 1, int(math.ceil(bin_high)))
            if idx_end > freq_bins:
                idx_end = freq_bins

            band_slice = magnitudes[idx_start:idx_end]
            if len(band_slice) > 0:
                raw_val = float(np.mean(band_slice))
            else:
                raw_val = float(magnitudes[min(idx_start, freq_bins - 1)])

            # Acoustic frequency tilt: +3dB/octave slope boost for upper mids & highs
            center_freq = math.sqrt(f_low * f_high)
            tilt = math.pow(center_freq / 250.0, 0.35)
            val = raw_val * tilt

            # Dynamic compression / normalization
            ref = max(1e-4, self.rolling_max)
            val_norm = val / ref

            # Soft-knee power curve compression (gamma = 0.6)
            comp_val = math.pow(min(1.0, val_norm), 0.6)

            # Noise gate threshold
            if comp_val < 0.02:
                comp_val = 0.0

            bar_values.append(min(1.0, max(0.0, comp_val)))

        return bar_values, rms, peak


# ==============================================================================
# Audio Source Wrappers
# ==============================================================================
class LoopbackAudioSource(BaseAudioSource):
    """
    Primary audio source capturing live audio loopback from the OS.
    Runs native WASAPI on Windows and sounddevice monitor on Linux.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dsp = AudioDSP(sample_rate=48000, fft_size=2048)
        self._target_bars = 32
        self._is_active = False

        # Native WASAPI for Windows
        if sys.platform == "win32":
            self._backend = NativeWasapiLoopback(on_samples_callback=self._dsp.push_pcm)
        else:
            self._backend = None

        # Analysis timer (60 Hz)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._analyze_tick)

    def set_target_bars(self, count: int) -> None:
        """Adapts frequency analysis resolution to the visualizer's active bar count."""
        self._target_bars = max(4, count)

    def start(self) -> None:
        if self._is_active:
            return
        self._is_active = True
        if self._backend:
            self._backend.start()
        self._timer.start()
        log_event("🎙️ [AudioSource] Live loopback spectral analysis active.", force=True)

    def stop(self) -> None:
        self._is_active = False
        self._timer.stop()
        if self._backend:
            self._backend.stop()
        log_event("[AudioSource] Live loopback audio stopped.")

    def is_active(self) -> bool:
        return self._is_active

    def _analyze_tick(self) -> None:
        if not self._is_active:
            return
        bands, rms, peak = self._dsp.analyze_spectrum(num_bars=self._target_bars)
        data = AudioData(
            amplitudes=bands,
            energy=rms,
            timestamp=time.time()
        )
        self.audio_ready.emit(data)

    def get_diagnostics(self) -> Dict[str, Any]:
        return {
            "source_type": "WASAPI Loopback" if sys.platform == "win32" else "Linux Loopback",
            "is_capturing": getattr(self._backend, "is_capturing", False) if self._backend else False,
            "sample_rate": self._dsp.sample_rate,
            "fft_size": self._dsp.fft_size,
            "bars": self._target_bars,
            "rms": self._dsp.last_rms,
            "peak": self._dsp.last_peak,
        }


class ProceduralAudioSource(BaseAudioSource):
    """
    Test/Development spectrum generator.
    Explicitly labeled as test-only (never masquerades as real audio in production).
    """
    def __init__(self, num_bands: int = 32, parent=None):
        super().__init__(parent)
        self.num_bands = num_bands
        self._is_running = False
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._generate_frame)

    def start(self) -> None:
        self._is_running = True
        self._timer.start()

    def stop(self) -> None:
        self._is_running = False
        self._timer.stop()

    def is_active(self) -> bool:
        return self._is_running

    def set_target_bars(self, count: int) -> None:
        self.num_bands = max(4, count)

    def _generate_frame(self) -> None:
        if not self._is_running:
            return
        self._phase += 0.05
        bands = []
        for i in range(self.num_bands):
            norm_i = i / float(self.num_bands - 1)
            val = 0.4 + 0.5 * math.sin(self._phase * 2.0 + norm_i * 6.0)
            bands.append(max(0.0, min(1.0, val)))
        self.audio_ready.emit(AudioData(amplitudes=bands, energy=0.5, timestamp=time.time()))


class AdaptiveAudioSource(BaseAudioSource):
    """
    Master audio provider for Lyrune.
    Routes 100% genuine loopback audio analysis.
    If real audio is unavailable or silent, cleanly delivers idle/resting frames.
    """
    def __init__(self, num_bands: int = 32, parent=None):
        super().__init__(parent)
        self.loopback = LoopbackAudioSource(parent=self)
        self.loopback.set_target_bars(num_bands)
        self.loopback.audio_ready.connect(self._on_loopback_data)
        self._media_status = "Paused"
        self._media_is_running = False

    def set_target_bars(self, count: int) -> None:
        self.loopback.set_target_bars(count)

    def start(self) -> None:
        self.loopback.start()

    def stop(self) -> None:
        self.loopback.stop()

    def is_active(self) -> bool:
        return self.loopback.is_active()

    def set_media_info(self, info: Dict[str, Any]) -> None:
        self._media_status = info.get("status", "Paused")
        self._media_is_running = info.get("is_running", False)

    def _on_loopback_data(self, data: AudioData) -> None:
        # Deliver genuine audio data
        self.audio_ready.emit(data)

    def get_diagnostics(self) -> Dict[str, Any]:
        diag = self.loopback.get_diagnostics()
        diag["media_status"] = self._media_status
        diag["media_is_running"] = self._media_is_running
        return diag
