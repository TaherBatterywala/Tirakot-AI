import os
import queue
import tempfile
import asyncio
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wavfile
import yaml

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
        Records audio from microphone until the stop_event is set.
        Saves to a temporary WAV file and returns the file path.
        """
        self.audio_queue.queue.clear()
        
        # Start recording stream
        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype='int16',
            callback=self._audio_callback
        )
        
        with stream:
            print("\n[Listening... Speak now. Press ENTER again to stop.]")
            while not stop_event.is_set():
                await asyncio.sleep(0.1)
        
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
            segments, info = self.model.transcribe(audio_file_path, beam_size=5)
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
