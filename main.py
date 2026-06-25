import os
# Mute Hugging Face symlink warnings on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import asyncio
import sys
import threading
import queue
import re
import json

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
    
    raw_prompt = prompt
    from os_integration.system_tools import get_current_datetime
    context_parts = [get_current_datetime()]

    if any(k in prompt.lower() for k in ["weather", "temperature", "climate"]):
        match = re.search(r'(?:in|for)\s+([a-zA-Z\s]+?)(?:\s+right\s+now|\s+today|\s+currently|\b|$)', prompt, re.IGNORECASE)
        city = match.group(1).strip() if match else ""
        from os_integration.system_tools import get_local_weather
        weather_data = await asyncio.to_thread(get_local_weather, city)
        context_parts.append(f"Current weather: {weather_data}")
        
    elif any(k in prompt.lower() for k in ["news", "headline", "current events"]):
        from os_integration.system_tools import get_top_news
        news_data = await asyncio.to_thread(get_top_news)
        context_parts.append(f"Recent news headlines:\n{news_data}")

    context_str = " | ".join(context_parts)
    prompt = f"[System Context: {context_str}]\nUser Query: {prompt}"

    formatted_messages = prompt_mgr.format_chat_history(chat_history, prompt, voice_mode=voice_mode)
    tts_pipeline.reset()
    
    is_json_action = False
    response_chunks = []
    
    try:
        stream_gen = llm_engine.stream_response(formatted_messages)
        
        # Buffer first non-empty chunk(s) to accurately detect JSON block
        first_non_empty = ""
        buffered_chunks = []
        async for chunk in stream_gen:
            buffered_chunks.append(chunk)
            first_non_empty += chunk
            if first_non_empty.strip():
                break
                
        stripped_prefix = first_non_empty.strip()
        if stripped_prefix.startswith("{") or stripped_prefix.startswith("```json") or stripped_prefix.startswith("```"):
            is_json_action = True
            
        if is_json_action:
            response_chunks.extend(buffered_chunks)
            async for chunk in stream_gen:
                response_chunks.append(chunk)
                
            full_response = "".join(response_chunks)
            
            # Robust JSON extraction helper for multiple JSON blocks
            def extract_all_json(text: str) -> list[dict]:
                results = []
                indices = [i for i, char in enumerate(text) if char == '{']
                for start in indices:
                    brace_count = 0
                    end = -1
                    for j in range(start, len(text)):
                        if text[j] == '{':
                            brace_count += 1
                        elif text[j] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end = j
                                break
                    if end != -1:
                        try:
                            obj = json.loads(text[start:end+1])
                            if isinstance(obj, dict):
                                results.append(obj)
                        except Exception:
                            pass
                return results

            action_list = extract_all_json(full_response)
            known_tools = ["web_search", "execute_system_command", "advanced_open", "create_vscode_file", "send_whatsapp", "locate_and_open_file", "append_local_note", "calculator_compute"]
            
            try:
                if action_list:
                    import os_integration.system_tools as tools
                    tool_results = []
                    has_conversational_tool = False
                    
                    for action_data in action_list:
                        tool_name = action_data.get("tool")
                        parameter = action_data.get("parameter")
                        
                        if tool_name not in known_tools:
                            continue
                            
                        # Speak/display custom speech confirmation
                        speech = action_data.get("speech", "")
                        if not speech:
                            # Auto-generated confirmations
                            if tool_name == "execute_system_command":
                                speech = f"Got it. Opening {parameter}."
                            elif tool_name == "advanced_open":
                                speech = f"Sure, opening {parameter} for you."
                            elif tool_name == "create_vscode_file":
                                speech = f"I'm creating {parameter.get('filename', 'the file')} and opening it in VS Code."
                            elif tool_name == "send_whatsapp":
                                speech = f"Got it. Staging a WhatsApp message."
                            elif tool_name == "locate_and_open_file":
                                speech = f"Searching for {parameter.get('filename')} to open it."
                            elif tool_name == "append_local_note":
                                speech = "I'm adding that note to your records."
                            elif tool_name == "web_search":
                                speech = f"Searching the web for {parameter}."
                            elif tool_name == "calculator_compute":
                                speech = f"Let me calculate that for you."
                        
                        gui_queue.put(("stream_start", None))
                        gui_queue.put(("stream_token", speech))
                        gui_queue.put(("stream_end", None))
                        await tts_pipeline.speak(speech)
                        
                        gui_queue.put(("tool_status", f"Running: {tool_name}..."))
                        
                        tool_result = ""
                        
                        if tool_name == "web_search":
                            has_conversational_tool = True
                            tool_result = await asyncio.to_thread(tools.web_search, parameter)
                        elif tool_name == "calculator_compute":
                            # Fallback if parameter doesn't look like a math expression
                            import re as _re
                            if not parameter or not _re.match(r'^[\d\s\+\-\*/\.\(\)%x×÷\^]+$', str(parameter)):
                                tool_result = await asyncio.to_thread(tools.execute_system_command, "calc")
                            else:
                                has_conversational_tool = True
                                tool_result = await asyncio.to_thread(tools.calculator_compute, parameter)
                        elif tool_name == "execute_system_command":
                            tool_result = await asyncio.to_thread(tools.execute_system_command, parameter)
                        elif tool_name == "advanced_open":
                            tool_result = await asyncio.to_thread(tools.advanced_open, parameter)
                        elif tool_name == "create_vscode_file":
                            fn = parameter.get("filename", "file.py")
                            code = parameter.get("code", "")
                            tool_result = await asyncio.to_thread(tools.create_vscode_file, fn, code)
                        elif tool_name == "send_whatsapp":
                            contact = parameter.get("contact_name", "")
                            txt = parameter.get("text", "")
                            tool_result = await asyncio.to_thread(tools.send_whatsapp, contact, txt)
                        elif tool_name == "locate_and_open_file":
                            fn = parameter.get("filename", "")
                            dp = parameter.get("directory_path", "")
                            tool_result = await asyncio.to_thread(tools.locate_and_open_file, fn, dp)
                        elif tool_name == "append_local_note":
                            tool_result = await asyncio.to_thread(tools.append_local_note, parameter)
                            
                        tool_results.append((tool_name, tool_result))
                        
                    chat_history.append({"role": "user", "content": raw_prompt})
                    chat_history.append({"role": "assistant", "content": full_response})
                    
                    if not has_conversational_tool:
                        gui_queue.put(("status", "idle"))
                        return
                    else:
                        # For single calculator_compute, speak the result directly
                        if len(tool_results) == 1 and tool_results[0][0] == "calculator_compute":
                            result_speech = f"The result is {tool_results[0][1]}."
                            gui_queue.put(("stream_start", None))
                            gui_queue.put(("stream_token", result_speech))
                            gui_queue.put(("stream_end", None))
                            chat_history.append({"role": "assistant", "content": result_speech})
                            await tts_pipeline.speak(result_speech)
                            gui_queue.put(("status", "idle"))
                            return
                        
                        if voice_mode:
                            secondary_prompt = f"System: Tool result from web_search is:\n{tool_result}\nSummarize this output for the user in 1 or 2 sentences."
                        else:
                            secondary_prompt = f"System: Tool result from web_search is:\n{tool_result}\nProvide a comprehensive, detailed, and well-structured summary of these search results, highlighting key facts and listing the source links/URLs."
                        chat_history.append({"role": "user", "content": secondary_prompt})
                        
                        secondary_messages = prompt_mgr.format_chat_history(chat_history[:-1], secondary_prompt, voice_mode=voice_mode)
                        
                        gui_queue.put(("stream_start", None))
                        secondary_chunks = []
                        async for chunk in llm_engine.stream_response(secondary_messages):
                            gui_queue.put(("stream_token", chunk))
                            secondary_chunks.append(chunk)
                        gui_queue.put(("stream_end", None))
                        
                        full_secondary = "".join(secondary_chunks)
                        chat_history.append({"role": "assistant", "content": full_secondary})
                        await tts_pipeline.speak(full_secondary)
                        gui_queue.put(("status", "idle"))
                        return
                else:
                    is_json_action = False
            except Exception as e:
                is_json_action = False
                
            if not is_json_action:
                # Conversational fallback: stream the buffered response text normally
                gui_queue.put(("stream_start", None))
                gui_queue.put(("stream_token", full_response))
                gui_queue.put(("stream_end", None))
                await tts_pipeline.speak(full_response)
                
                chat_history.append({"role": "user", "content": raw_prompt})
                chat_history.append({"role": "assistant", "content": full_response})
                if len(chat_history) > 20:
                    chat_history[:] = chat_history[-20:]
                gui_queue.put(("status", "idle"))
                return
            
        gui_queue.put(("stream_start", None))
        gui_queue.put(("stream_token", first_non_empty))
        response_chunks.extend(buffered_chunks)
        
        current_sentence = first_non_empty
        speech_buffer = []
        code_block_ticks = first_non_empty.count('```')
        
        async for chunk in stream_gen:
            gui_queue.put(("stream_token", chunk))
            response_chunks.append(chunk)

            code_block_ticks += chunk.count('```')
            in_code_block = code_block_ticks % 2 == 1

            if in_code_block:
                if current_sentence.strip():
                    speech_buffer.append(current_sentence.strip())
                    current_sentence = ""
                if speech_buffer:
                    await tts_pipeline.speak(" ".join(speech_buffer))
                    speech_buffer.clear()
                continue

            stripped = chunk.replace('```', '').replace('\n', '')
            if not stripped:
                continue

            current_sentence += chunk
            if any(p in chunk for p in ['.', '!', '?', '\n']):
                parts = re.split(r'(?<=[.!?])\s+|\n+', current_sentence)
                if len(parts) > 1:
                    for p in parts[:-1]:
                        if p.strip():
                            speech_buffer.append(p.strip())
                    current_sentence = parts[-1]
                    
                    joined_speech = " ".join(speech_buffer)
                    if len(joined_speech) >= 60 or '\n' in chunk:
                        await tts_pipeline.speak(joined_speech)
                        speech_buffer.clear()

        gui_queue.put(("stream_end", None))

        if current_sentence.strip():
            speech_buffer.append(current_sentence.strip())
        if speech_buffer:
            await tts_pipeline.speak(" ".join(speech_buffer))
            
        full_response = "".join(response_chunks)
        chat_history.append({"role": "user", "content": raw_prompt})
        chat_history.append({"role": "assistant", "content": full_response})
        if len(chat_history) > 20:
            chat_history[:] = chat_history[-20:]
            
        await asyncio.sleep(0.3)
        if tts_pipeline.queue.empty() and not tts_pipeline.is_speaking:
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
    
    async def start_wake_word_after_load():
        await stt_load_task
        stt_pipeline.start_wake_word_detector(lambda: cmd_queue.put(("wake_by_voice", None)))
        
    asyncio.create_task(start_wake_word_after_load())
    
    tts_pipeline = TTSPipeline(gui_queue=gui_queue)
    
    chat_history = []
    is_recording = False
    voice_enabled = True      # Tracks whether voice/TTS is active (Jarvis mode)
    stop_event = None
    recording_task = None
    active_prompt_task = None
    voice_triggered = False   # Tracks if current interaction was started by voice
    
    async def start_recording(is_followup=False):
        nonlocal is_recording, stop_event, recording_task, voice_triggered
        if is_recording:
            return
        
        if not stt_pipeline.is_loaded:
            gui_queue.put(("status", "thinking"))
            await stt_load_task
            gui_queue.put(("status", "idle"))
            
        if active_prompt_task and not active_prompt_task.done():
            active_prompt_task.cancel()
        if not is_followup:
            tts_pipeline.stop()
        
        stt_pipeline.pause_wake_word()
        is_recording = True
        voice_triggered = True
        stop_event = asyncio.Event()
        
        gui_queue.put(("mic_active", None))
        gui_queue.put(("status", "listening"))
        if is_followup:
            gui_queue.put(("overlay_followup", None))
            
        async def record_task_wrapper(event, followup):
            try:
                if followup:
                    path = await stt_pipeline.record_with_timeout(timeout_seconds=8.0)
                else:
                    gui_queue.put(("chime", "start"))
                    path = await stt_pipeline.record_until_stopped(event)
                cmd_queue.put(("recording_finished", (path, followup)))
            except Exception as ex:
                print(f"[Recording Task Error]: {ex}")
                cmd_queue.put(("recording_finished", ("", followup)))
                
        recording_task = asyncio.create_task(record_task_wrapper(stop_event, is_followup))

    def stop_current_recording(discard=False):
        nonlocal is_recording, stop_event
        if is_recording:
            is_recording = False
            if stop_event:
                stop_event.set()
            gui_queue.put(("mic_inactive", None))

    # Command loop
    while True:
        try:
            cmd_type, data = await asyncio.to_thread(cmd_queue.get)
            
            if cmd_type == "exit":
                if active_prompt_task and not active_prompt_task.done():
                    active_prompt_task.cancel()
                tts_pipeline.stop()
                stop_current_recording(discard=True)
                break
                
            elif cmd_type == "send_text":
                if active_prompt_task and not active_prompt_task.done():
                    active_prompt_task.cancel()
                    await asyncio.sleep(0.01)
                active_prompt_task = asyncio.create_task(process_prompt(data, prompt_mgr, llm_engine, tts_pipeline, gui_queue, chat_history, voice_mode=voice_enabled))

            elif cmd_type == "send_voice_text":
                voice_triggered = True
                if active_prompt_task and not active_prompt_task.done():
                    active_prompt_task.cancel()
                    await asyncio.sleep(0.01)
                
                async def voice_prompt_with_followup(text):
                    await process_prompt(text, prompt_mgr, llm_engine, tts_pipeline, gui_queue, chat_history, voice_mode=voice_enabled)
                    # Wait for TTS to be enqueued and finish speaking completely
                    await asyncio.sleep(0.3)
                    while tts_pipeline.is_busy:
                        await asyncio.sleep(0.1)
                    await asyncio.sleep(0.5)
                    cmd_queue.put(("voice_followup", None))
                
                active_prompt_task = asyncio.create_task(voice_prompt_with_followup(data))

            elif cmd_type == "wake_by_voice":
                if not is_recording:
                    if active_prompt_task and not active_prompt_task.done():
                        active_prompt_task.cancel()
                    tts_pipeline.stop()
                    gui_queue.put(("wake_overlay", None))
                    await start_recording(is_followup=False)

            elif cmd_type == "voice_followup":
                if not is_recording and voice_triggered:
                    await start_recording(is_followup=True)

            elif cmd_type == "recording_finished":
                path, is_followup = data
                if not voice_triggered:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                    stt_pipeline.resume_wake_word()
                    continue
                
                is_recording = False
                gui_queue.put(("mic_inactive", None))
                
                if path:
                    gui_queue.put(("status", "thinking"))
                    async def transcribe_and_process(file_path, followup):
                        try:
                            prompt = await stt_pipeline.transcribe(file_path)
                            if prompt.strip():
                                gui_queue.put(("user_voice_transcribed", prompt))
                                cmd_queue.put(("send_voice_text", prompt))
                            else:
                                cmd_queue.put(("transcription_empty", followup))
                        except Exception as ex:
                            print(f"[Transcription Task Error]: {ex}")
                            cmd_queue.put(("transcription_empty", followup))
                    asyncio.create_task(transcribe_and_process(path, is_followup))
                else:
                    voice_triggered = False
                    gui_queue.put(("status", "idle"))
                    stt_pipeline.resume_wake_word()

            elif cmd_type == "transcription_empty":
                voice_triggered = False
                gui_queue.put(("status", "idle"))
                stt_pipeline.resume_wake_word()

            elif cmd_type == "stop_speech":
                voice_triggered = False
                if active_prompt_task and not active_prompt_task.done():
                    active_prompt_task.cancel()
                tts_pipeline.stop()
                stop_current_recording(discard=True)
                stt_pipeline.resume_wake_word()

            elif cmd_type == "toggle_voice":
                voice_enabled = data
                tts_pipeline.set_muted(not data)
                
            elif cmd_type == "toggle_mic":
                if not is_recording:
                    await start_recording(is_followup=False)
                else:
                    gui_queue.put(("chime", "stop"))
                    stop_current_recording(discard=False)
                            
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
