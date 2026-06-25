import os
# Mute Hugging Face symlink warnings on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import asyncio
import sys
import threading
import queue
import re

from core.llm_engine import LLMEngine
from core.prompt_manager import PromptManager
from audio.stt_pipeline import STTPipeline
from audio.tts_pipeline import TTSPipeline
from ui.app_window import TirakotApp
from os_integration.system_tools import get_local_weather, get_top_news

async def process_prompt(prompt: str, prompt_mgr: PromptManager, llm_engine: LLMEngine, tts_pipeline: TTSPipeline, gui_queue: queue.Queue, chat_history: list, voice_mode: bool = False):
    """Processes a user prompt, executes tools if triggered, and streams the response to the GUI & TTS."""
    if not prompt.strip():
        return
        
    tts_pipeline.stop()
    gui_queue.put(("status", "thinking"))
    
    # Tool Routing (Online weather & news lookup with offline fallback)
    raw_prompt = prompt
    from os_integration.system_tools import get_current_datetime
    context_parts = [get_current_datetime()]

    if any(k in prompt.lower() for k in ["weather", "temperature", "climate"]):
        # Match cities, removing trailing filler words
        match = re.search(r'(?:in|for)\s+([a-zA-Z\s]+?)(?:\s+right\s+now|\s+today|\s+currently|\b|$)', prompt, re.IGNORECASE)
        city = match.group(1).strip() if match else ""
        weather_data = await asyncio.to_thread(get_local_weather, city)
        context_parts.append(f"Current weather: {weather_data}")
        
    elif any(k in prompt.lower() for k in ["news", "headline", "current events"]):
        news_data = await asyncio.to_thread(get_top_news)
        context_parts.append(f"Recent news headlines:\n{news_data}")

    # Build clear system context to guide the small LLM without confusion
    context_str = " | ".join(context_parts)
    prompt = f"[System Context: {context_str}]\nUser Query: {prompt}"

    # Format history and prompt — voice_mode changes the system prompt personality
    formatted_messages = prompt_mgr.format_chat_history(chat_history, prompt, voice_mode=voice_mode)
    tts_pipeline.reset()
    
    # Notify GUI that streaming is starting
    gui_queue.put(("stream_start", None))
    
    response_chunks = []
    current_sentence = ""
    speech_buffer = []
    code_block_ticks = 0      # running count of ``` markers for code-aware TTS
    
    try:
        async for chunk in llm_engine.stream_response(formatted_messages):
            # Push token to GUI Chat Bubble
            gui_queue.put(("stream_token", chunk))
            response_chunks.append(chunk)

            # Track code-block boundaries so we never speak code aloud
            code_block_ticks += chunk.count('```')
            in_code_block = code_block_ticks % 2 == 1

            if in_code_block:
                # Inside a code block — flush any pending prose, but do NOT accumulate
                if current_sentence.strip():
                    speech_buffer.append(current_sentence.strip())
                    current_sentence = ""
                if speech_buffer:
                    await tts_pipeline.speak(" ".join(speech_buffer))
                    speech_buffer.clear()
                continue

            # Skip the closing ``` line itself
            stripped = chunk.replace('```', '').replace('\n', '')
            if not stripped:
                continue

            current_sentence += chunk
            
            # Parse sentences on the fly
            if any(p in chunk for p in ['.', '!', '?', '\n']):
                parts = re.split(r'(?<=[.!?])\s+|\n+', current_sentence)
                if len(parts) > 1:
                    for p in parts[:-1]:
                        if p.strip():
                            speech_buffer.append(p.strip())
                    current_sentence = parts[-1]
                    
                    # Speak naturally if segment is long enough
                    joined_speech = " ".join(speech_buffer)
                    if len(joined_speech) >= 60 or '\n' in chunk:
                        await tts_pipeline.speak(joined_speech)
                        speech_buffer.clear()

        # Tell the GUI streaming is done so it can render code blocks properly
        gui_queue.put(("stream_end", None))

        # Speak residual prose text (never code)
        if current_sentence.strip():
            speech_buffer.append(current_sentence.strip())
        if speech_buffer:
            await tts_pipeline.speak(" ".join(speech_buffer))
            
        full_response = "".join(response_chunks)
        
        # Store history (raw user prompt and assistant response)
        chat_history.append({"role": "user", "content": raw_prompt})
        chat_history.append({"role": "assistant", "content": full_response})
        if len(chat_history) > 20:
            chat_history[:] = chat_history[-20:]
            
        # Wait briefly for speaking to start. If no speaking task was queued, return status to idle.
        await asyncio.sleep(0.3)
        if not tts_pipeline.is_speaking:
            gui_queue.put(("status", "idle"))
    except asyncio.CancelledError:
        gui_queue.put(("stream_end", None))
        gui_queue.put(("status", "idle"))
        raise

async def async_worker(cmd_queue: queue.Queue, gui_queue: queue.Queue):
    """Asynchronous worker running in the background thread."""
    # Preload modules
    prompt_mgr = PromptManager()
    llm_engine = LLMEngine()
    
    stt_pipeline = STTPipeline()
    # Lazy load STT in background
    stt_load_task = asyncio.create_task(asyncio.to_thread(stt_pipeline.load_model))
    
    tts_pipeline = TTSPipeline(gui_queue=gui_queue)
    
    chat_history = []
    is_recording = False
    voice_enabled = True      # Tracks whether voice/TTS is active (Jarvis mode)
    stop_event = None
    recording_task = None
    active_prompt_task = None
    # Command loop
    while True:
        try:
            # Non-blocking fetch of synchronous Queue from thread pool
            cmd_type, data = await asyncio.to_thread(cmd_queue.get)
            
            if cmd_type == "exit":
                if active_prompt_task and not active_prompt_task.done():
                    active_prompt_task.cancel()
                tts_pipeline.stop()
                break
                
            elif cmd_type == "send_text":
                if active_prompt_task and not active_prompt_task.done():
                    active_prompt_task.cancel()
                    await asyncio.sleep(0.01)
                active_prompt_task = asyncio.create_task(process_prompt(data, prompt_mgr, llm_engine, tts_pipeline, gui_queue, chat_history, voice_mode=voice_enabled))

            elif cmd_type == "stop_speech":
                if active_prompt_task and not active_prompt_task.done():
                    active_prompt_task.cancel()
                tts_pipeline.stop()

            elif cmd_type == "toggle_voice":
                # data = True means voice ON (Jarvis mode), False = text chatbot mode
                voice_enabled = data
                tts_pipeline.set_muted(not data)
                
            elif cmd_type == "toggle_mic":
                if not is_recording:
                    # Start voice recording
                    if not stt_pipeline.is_loaded:
                        gui_queue.put(("status", "thinking"))
                        await stt_load_task
                        gui_queue.put(("status", "idle"))
                    
                    if active_prompt_task and not active_prompt_task.done():
                        active_prompt_task.cancel()
                    tts_pipeline.stop()
                    is_recording = True
                    stop_event = asyncio.Event()
                    
                    # Play start chime and activate recording state
                    gui_queue.put(("chime", "start"))
                    gui_queue.put(("mic_active", None))
                    gui_queue.put(("status", "listening"))
                    
                    recording_task = asyncio.create_task(stt_pipeline.record_until_stopped(stop_event))
                else:
                    # Stop voice recording
                    if stop_event:
                        is_recording = False
                        gui_queue.put(("chime", "stop"))
                        gui_queue.put(("mic_inactive", None))
                        gui_queue.put(("status", "thinking"))
                        
                        stop_event.set()
                        wav_path = await recording_task
                        
                        if wav_path:
                            # Transcribe audio to text
                            prompt = await stt_pipeline.transcribe(wav_path)
                            if prompt.strip():
                                gui_queue.put(("user_voice_transcribed", prompt))
                            gui_queue.put(("status", "idle"))
                        else:
                            gui_queue.put(("status", "idle"))
                            
            cmd_queue.task_done()
        except Exception as e:
            print(f"[Backend Worker Error]: {e}")

def start_async_loop(cmd_queue: queue.Queue, gui_queue: queue.Queue):
    """Initializes and runs the asyncio loop on the background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_worker(cmd_queue, gui_queue))
    loop.close()

if __name__ == "__main__":
    # Create thread-safe communication queues
    cmd_queue = queue.Queue()
    gui_queue = queue.Queue()
    
    # Launch backend loop in separate background thread
    bg_thread = threading.Thread(target=start_async_loop, args=(cmd_queue, gui_queue), daemon=True)
    bg_thread.start()
    
    # Run CustomTkinter GUI on the main thread
    app = TirakotApp(cmd_queue, gui_queue)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        cmd_queue.put(("exit", None))
        sys.exit(0)
