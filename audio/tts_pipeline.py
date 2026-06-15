import os
import re
import sys
import tempfile
import asyncio
import ctypes
import yaml
import win32com.client

# Windows Multimedia Library for native MCI audio playback
try:
    winmm = ctypes.windll.winmm
except Exception:
    winmm = None

def clean_text_for_speech(text: str) -> str:
    """Removes code blocks, headers, list numbers, and formatting markup not suitable for speech."""
    # 1. Remove multi-line code blocks
    cleaned = re.sub(r'```.*?```', ' [Code block omitted] ', text, flags=re.DOTALL)
    # 2. Remove inline code backticks
    cleaned = re.sub(r'`[^`]+`', '', cleaned)
    # 3. Remove markdown headers (e.g., ### Step 1 -> Step 1)
    cleaned = re.sub(r'#+\s*', ' ', cleaned)
    # 4. Remove list markers (e.g., "1. ", "- ") using non-capturing groups to avoid look-behinds
    cleaned = re.sub(r'(?:^|\s)(?:\d+\.|\-|\*)\s+', ' ', cleaned)
    # 5. Remove markdown bold/italic asterisks or underscores
    cleaned = re.sub(r'\*+', '', cleaned)
    cleaned = re.sub(r'_+', '', cleaned)
    # 6. Replace multiple spaces/newlines with a single space
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()

class TTSPipeline:
    def __init__(self, config_path: str = "config.yaml"):
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
        except Exception:
            self.config = {}

        self.voice = self.config.get("tts_voice", "en-US-AnaNeural")
        self.volume = self.config.get("tts_volume", "+50%")
        self.fallback_enabled = self.config.get("tts_fallback", True)
        
        self.sapi_speaker = None
        self._is_playing_mci = False
        self._playback_blocked = False  # Set to True when stopped/muted during a turn
        
        # Audio playback queue and background processor
        self.queue = asyncio.Queue()
        self.worker_task = asyncio.create_task(self._process_queue())

    @property
    def is_speaking(self) -> bool:
        """Checks if there is active audio playback."""
        if self._is_playing_mci:
            return True
        if self.sapi_speaker:
            try:
                # 2 = SRSESpeaking
                return self.sapi_speaker.Status.RunningState == 2
            except Exception:
                pass
        return False

    async def _process_queue(self):
        """Monitors the queue and plays pre-generated audio files sequentially."""
        while True:
            # Get the pre-generation task from the queue
            task = await self.queue.get()
            try:
                if not self._playback_blocked:
                    # Await the pre-generation task to complete (resolves to path or text)
                    success, path_or_text = await task
                    if not self._playback_blocked:
                        if success:
                            # Play the downloaded MP3 file instantly
                            await self._play_mp3_mci(path_or_text)
                            try:
                                os.remove(path_or_text)
                            except OSError:
                                pass
                        elif self.fallback_enabled:
                            # Fallback to offline SAPI5 if online generation failed
                            await self._speak_sapi5(path_or_text)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TTS Worker Error]: {e}")
            finally:
                self.queue.task_done()

    def reset(self):
        """Resets the playback block state, allowing the pipeline to speak again."""
        self._playback_blocked = False

    def stop(self):
        """Interrupts and stops any ongoing speech playback immediately, clearing the queue and blocking future speech for this turn."""
        self._playback_blocked = True
        
        # Clear the queue of tasks, cancelling any that are currently pre-generating
        while not self.queue.empty():
            try:
                task = self.queue.get_nowait()
                if isinstance(task, asyncio.Task):
                    task.cancel()
                self.queue.task_done()
            except (asyncio.QueueEmpty, ValueError):
                break

        # Stop MCI MP3 playback
        if winmm:
            try:
                winmm.mciSendStringW('stop tirakot_speak', None, 0, 0)
                winmm.mciSendStringW('close tirakot_speak', None, 0, 0)
            except Exception:
                pass
        
        # Wait for the background play thread to confirm it has stopped and exited
        # This prevents race conditions where the main thread calls reset() immediately
        for _ in range(50):
            if not self._is_playing_mci:
                break
            import time
            time.sleep(0.01)

        # Stop SAPI5 speech
        if self.sapi_speaker:
            try:
                # Flag 2 = SVSFPurgeBeforeSpeak, stops current speech
                self.sapi_speaker.Speak("", 1 | 2)
            except Exception:
                pass

    async def speak(self, text: str):
        """
        Cleans and enqueues a background pre-generation task for speech.
        """
        if self._playback_blocked:
            return

        cleaned_text = clean_text_for_speech(text)
        # Skip if it is just empty or code block marker
        if not cleaned_text.replace("[Code block omitted]", "").strip():
            return

        # Define the pre-generation coroutine
        async def pre_generate():
            try:
                import edge_tts
                temp_dir = tempfile.gettempdir()
                # Create a unique temp file using the text hash and loop time to prevent collisions
                h = abs(hash(cleaned_text))
                t = str(asyncio.get_running_loop().time()).replace(".", "")
                mp3_path = os.path.join(temp_dir, f"tirakot_tts_{h}_{t}.mp3")

                communicate = edge_tts.Communicate(cleaned_text, self.voice, volume=self.volume)
                await communicate.save(mp3_path)

                if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                    return True, mp3_path
                return False, cleaned_text
            except Exception:
                return False, cleaned_text

        # Start the pre-generation task immediately in the background
        task = asyncio.create_task(pre_generate())
        await self.queue.put(task)

    async def _speak_sapi5(self, text: str):
        """Runs SAPI5 TTS asynchronously using COM async flags."""
        def _speak():
            try:
                import pythoncom
                pythoncom.CoInitialize()
                if not self.sapi_speaker:
                    self.sapi_speaker = win32com.client.Dispatch("SAPI.SpVoice")
                
                # Set volume to maximum for offline engine (range 0 to 100)
                self.sapi_speaker.Volume = 100
                
                # Flag 1 = SVSFlagsAsync, non-blocking speak
                self.sapi_speaker.Speak(text, 1)
                
                # SAPI5 speaks in background; we wait for it to finish in this thread
                while self.sapi_speaker.Status.RunningState == 2:
                    import time
                    time.sleep(0.05)
            except Exception as e:
                print(f"[TTS SAPI5 error]: {e}")

        await asyncio.to_thread(_speak)

    async def _play_mp3_mci(self, filepath: str):
        """Plays an MP3 file using Windows MCI in background and polls status to await completion."""
        if not winmm:
            return

        def _play():
            try:
                self._is_playing_mci = True
                # Ensure closed
                winmm.mciSendStringW('close tirakot_speak', None, 0, 0)
                # Open MP3 file
                open_cmd = f'open "{os.path.abspath(filepath)}" type mpegvideo alias tirakot_speak'
                winmm.mciSendStringW(open_cmd, None, 0, 0)
                
                # Check block state right before playing
                if self._playback_blocked:
                    return

                # Play in background (non-blocking)
                winmm.mciSendStringW('play tirakot_speak', None, 0, 0)
                
                # Poll status until finished or stopped/blocked
                buf = ctypes.create_unicode_buffer(128)
                while not self._playback_blocked:
                    winmm.mciSendStringW('status tirakot_speak mode', buf, 128, 0)
                    if buf.value == "stopped" or buf.value == "":
                        break
                    import time
                    time.sleep(0.05)
            except Exception as e:
                print(f"[TTS MCI Playback Error]: {e}")
            finally:
                # Close device
                winmm.mciSendStringW('close tirakot_speak', None, 0, 0)
                self._is_playing_mci = False

        await asyncio.to_thread(_play)
