import os
import queue
import tempfile
import asyncio
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wavfile
import yaml
import threading
import time as _time

class STTPipeline:
    def __init__(self, config_path: str = "config.yaml"):
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
        except Exception:
            self.config = {}

        self.model_name = self.config.get("stt_model", "tiny.en")
        self.device = self.config.get("stt_device", "cuda")
        self.compute_type = self.config.get("stt_compute_type", "float16")
        
        # Verify CUDA availability for PyTorch/faster-whisper
        import torch
        if self.device == "cuda" and not torch.cuda.is_available():
            print("[STT Warning]: CUDA is not available. Falling back to CPU.")
            self.device = "cpu"
            self.compute_type = "int8"

        self.model = None
        self.audio_queue = queue.Queue()
        self.sample_rate = 16000
        self.is_loaded = False
        self._wake_thread = None
        self._wake_active = False
        self._wake_suspended = False

    def load_model(self):
        """Loads the Whisper model. Can be run in a thread to prevent blocking."""
        if self.model is None:
            print(f"Loading STT Model: {self.model_name} on {self.device} ({self.compute_type})...")
            # Lazy import faster_whisper to avoid startup delay
            from faster_whisper import WhisperModel
            self.model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type
            )
            self.is_loaded = True
            print("STT Model loaded successfully.")

    def _audio_callback(self, indata, frames, time, status):
        """Callback for sounddevice input stream."""
        if status:
            print(status, flush=True)
        self.audio_queue.put(indata.copy())

    async def record_until_stopped(self, stop_event: asyncio.Event) -> str:
        """
        Records audio from microphone until the stop_event is set or auto-silence is triggered.
        Saves to a temporary WAV file and returns the file path.
        
        Includes a 1.5s grace period before silence detection starts, and a minimum
        recording duration of 1.0s to prevent premature cutoff.
        """
        self.audio_queue.queue.clear()
        
        recorded_chunks = []
        def callback(indata, frames, time, status):
            recorded_chunks.append(indata.copy())
            self.audio_queue.put(indata.copy())
            
        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype='int16',
            callback=callback
        )
        
        silence_threshold = 100.0   # RMS threshold for speech detection
        silence_limit = 2.0         # Seconds of silence after speech before auto-stopping
        grace_period = 1.5          # Seconds to wait before starting silence detection
        min_duration = 1.0          # Minimum recording duration in seconds
        poll_interval = 0.05        # Polling interval in seconds
        chunks_needed = int(silence_limit / poll_interval)
        
        speech_detected = False
        silence_count = 0
        elapsed = 0.0
        
        with stream:
            print("\n[Listening... Speak now.]")
            while not stop_event.is_set():
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                
                if recorded_chunks:
                    latest = recorded_chunks[-1]
                    rms = np.sqrt(np.mean(latest.astype(np.float32)**2))
                    
                    if rms > silence_threshold:
                        speech_detected = True
                        silence_count = 0
                    else:
                        # Only start counting silence after grace period AND speech was detected AND minimum duration passed
                        if speech_detected and elapsed > grace_period and elapsed > min_duration:
                            silence_count += 1
                            if silence_count >= chunks_needed:
                                print("[Auto-silence detected, stopping...]")
                                stop_event.set()
        
        # Collect all chunks
        audio_data = []
        while not self.audio_queue.empty():
            audio_data.append(self.audio_queue.get())
        
        if not audio_data:
            return ""

        # Concatenate and save to temporary file
        audio_np = np.concatenate(audio_data, axis=0)
        
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, "tirakot_stt_temp.wav")
        wavfile.write(temp_file_path, self.sample_rate, audio_np)
        return temp_file_path

    async def record_with_timeout(self, timeout_seconds: float = 8.0) -> str:
        """
        Records audio with an absolute timeout for follow-up listening.
        If no speech is detected within timeout_seconds, returns empty string.
        If speech is detected, records until silence (same as record_until_stopped).
        Returns the path to the recorded WAV file, or empty string if no speech.
        """
        self.audio_queue.queue.clear()
        
        recorded_chunks = []
        def callback(indata, frames, time, status):
            recorded_chunks.append(indata.copy())
            self.audio_queue.put(indata.copy())
            
        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype='int16',
            callback=callback
        )
        
        silence_threshold = 100.0
        silence_limit = 2.0
        poll_interval = 0.05
        chunks_needed = int(silence_limit / poll_interval)
        
        speech_detected = False
        silence_count = 0
        elapsed = 0.0
        
        with stream:
            print(f"\n[Follow-up Listening... {timeout_seconds}s timeout]")
            while elapsed < timeout_seconds:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                
                if recorded_chunks:
                    latest = recorded_chunks[-1]
                    rms = np.sqrt(np.mean(latest.astype(np.float32)**2))
                    
                    if rms > silence_threshold:
                        speech_detected = True
                        silence_count = 0
                    else:
                        if speech_detected:
                            silence_count += 1
                            if silence_count >= chunks_needed:
                                print("[Follow-up: Auto-silence detected, stopping...]")
                                break
            
            if not speech_detected:
                print("[Follow-up: No speech detected, timing out...]")
                return ""
        
        # Collect all chunks
        audio_data = []
        while not self.audio_queue.empty():
            audio_data.append(self.audio_queue.get())
        
        if not audio_data:
            return ""

        audio_np = np.concatenate(audio_data, axis=0)
        
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, "tirakot_stt_followup.wav")
        wavfile.write(temp_file_path, self.sample_rate, audio_np)
        return temp_file_path

    async def transcribe(self, audio_file_path: str) -> str:
        """
        Transcribes the given audio file using faster-whisper.
        Runs in an executor to avoid blocking the async event loop.
        """
        if not audio_file_path or not os.path.exists(audio_file_path):
            return ""

        if self.model is None:
            await asyncio.to_thread(self.load_model)

        def _run_transcription():
            segments, info = self.model.transcribe(audio_file_path, beam_size=5, language="en")
            text = "".join([segment.text for segment in segments])
            return text.strip()

        try:
            transcript = await asyncio.to_thread(_run_transcription)
            # Cleanup temp file
            try:
                os.remove(audio_file_path)
            except OSError:
                pass
            return transcript
        except Exception as e:
            print(f"[STT Error]: Transcription failed: {e}")
            return ""

    def start_wake_word_detector(self, on_wake_cb):
        """Starts background acoustic wake word thread (Hey Tirakot / Tirakot)."""
        if self._wake_active:
            return
        self._wake_active = True
        self._wake_thread = threading.Thread(target=self._wake_loop, args=(on_wake_cb,), daemon=True)
        self._wake_thread.start()

    def pause_wake_word(self):
        """Pauses the wake word detector to prevent PortAudio conflicts."""
        self._wake_suspended = True

    def resume_wake_word(self):
        """Resumes the wake word detector."""
        self._wake_suspended = False

    def _wake_loop(self, on_wake_cb):
        audio_q = queue.Queue()

        def callback(indata, frames, time_info, status):
            audio_q.put(indata.copy())

        # Buffer size of 2.0s for capturing complete phrases (e.g. 'hello assistant')
        buffer_seconds = 2.0
        buffer = np.zeros(int(self.sample_rate * buffer_seconds), dtype='float32')
        stream = None
        background_rms = 0.015
        
        # VAD state tracking
        vad_speech_frames = 0       # Count of consecutive speech frames
        vad_speech_threshold = 3    # Need 3 consecutive speech frames (~150ms) to trigger transcription
        
        while self._wake_active:
            if self._wake_suspended:
                if stream is not None:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
                    stream = None
                _time.sleep(0.2)
                continue
                
            if stream is None:
                try:
                    stream = sd.InputStream(
                        samplerate=self.sample_rate,
                        channels=1,
                        dtype='float32',
                        callback=callback
                    )
                    stream.start()
                except Exception as e:
                    print(f"[Wake Stream Start Err]: {e}")
                    _time.sleep(1.0)
                    continue
                
            try:
                chunk = audio_q.get(timeout=0.5)
            except queue.Empty:
                continue
            
            buffer = np.roll(buffer, -len(chunk))
            buffer[-len(chunk):] = chunk.flatten()
            
            # RMS over the last 0.5s of audio for more responsive detection
            rms_window = int(self.sample_rate * 0.5)
            rms = np.sqrt(np.mean(buffer[-rms_window:]**2))
            
            # Smoothly calibrate to constant background noise (static/fans)
            background_rms = 0.98 * background_rms + 0.02 * rms
            
            # Balanced trigger threshold from background noise
            trigger_threshold = max(0.012, background_rms * 1.8)
            
            if rms > trigger_threshold:
                vad_speech_frames += 1
            else:
                vad_speech_frames = 0
            
            # VAD gate: only transcribe after sustained speech (not just a noise spike)
            if vad_speech_frames >= vad_speech_threshold:
                print(f"[Wake Monitor] RMS: {rms:.4f} (Noise Floor: {background_rms:.4f}, Threshold: {trigger_threshold:.4f}) - VAD speech detected. Transcribing...", flush=True)
                vad_speech_frames = 0  # Reset VAD counter
                
                if self.model is None:
                    self.load_model()
                try:
                    # Use beam_size=5 (matching chat) for highly accurate transcription
                    segments, _ = self.model.transcribe(buffer, beam_size=5, language="en")
                    text = " ".join([seg.text for seg in segments]).lower().strip()
                    if text:
                        print(f"[Wake Monitor] Heard: '{text}'", flush=True)
                        if any(w in text for w in ["assistant", "tirakot", "teracot", "tyrakot", "tira", "cot", "kot"]):
                            print("[Wake Monitor] TRIGGER WAKE WORD!", flush=True)
                            on_wake_cb()
                            buffer.fill(0.0)
                            background_rms = rms  # Reset floor baseline
                            while not audio_q.empty():
                                try:
                                    audio_q.get_nowait()
                                except queue.Empty:
                                    break
                            # Cooldown for re-activation
                            _time.sleep(1.0)
                except Exception as e:
                    print(f"[Wake Monitor Err]: {e}", flush=True)
            else:
                # Periodic status indicator (every few seconds) to show it's alive and listening quietly
                if _time.time() % 15 < 0.5:
                    print(f"[Wake Monitor] Idle... (Noise Floor: {background_rms:.4f})", flush=True)
                    
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
