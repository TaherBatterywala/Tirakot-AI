import os
# Mute Hugging Face symlink warnings on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import asyncio
import sys
import re
from core.llm_engine import LLMEngine
from core.prompt_manager import PromptManager
from audio.stt_pipeline import STTPipeline
from audio.tts_pipeline import TTSPipeline

async def main():
    print("=" * 60)
    print("TIRAKOT: Local Task-Integrated OS Assistant (Phase 1)")
    print("=" * 60)
    
    # Environment Diagnostics (Lazy import torch to prevent 2.5s startup delay)
    import torch
    print(f"CUDA Available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"CUDA Device: {torch.cuda.get_device_name(0)}")
    print("-" * 60)

    # Initialize Modules
    print("Initializing engine components...")
    prompt_mgr = PromptManager()
    llm_engine = LLMEngine()
    
    stt_pipeline = STTPipeline()
    # Pre-load STT model in background concurrently (does not block startup!)
    stt_load_task = asyncio.create_task(asyncio.to_thread(stt_pipeline.load_model))
    
    tts_pipeline = TTSPipeline()
    
    chat_history = []
    print("\nTirakot Core Engine successfully initialized.")
    print("Commands:")
    print("  [Press ENTER] to toggle recording (Start / Stop)")
    print("  Type 'stop' to stop current speech playback.")
    print("  Type 'exit' to quit.")
    print("  Press Ctrl+C to exit the program.")
    print("-" * 60)

    while True:
        try:
            user_choice = await asyncio.to_thread(input, "\n[Press ENTER to record, or type a text message]: ")
            
            # Immediately stop speech if user inputs anything or requests a stop
            if user_choice.strip().lower() == "stop":
                tts_pipeline.stop()
                continue
                
            if user_choice.strip().lower() == "exit":
                tts_pipeline.stop()
                break
                
            prompt = ""
            if user_choice.strip() == "":
                # Check if the Whisper model is still loading in the background
                if not stt_pipeline.is_loaded:
                    print("[System]: Whisper model is still loading in the background. Please wait a few seconds and try again.")
                    continue
                
                # User started recording - stop any current speech playback
                tts_pipeline.stop()
                
                # Toggle recording mode
                stop_event = asyncio.Event()
                
                # Function to wait for user to press ENTER to stop
                async def wait_for_stop():
                    await asyncio.to_thread(input, "")
                    stop_event.set()

                # Start recording task
                record_task = asyncio.create_task(stt_pipeline.record_until_stopped(stop_event))
                # Start listener task for the ENTER keypress
                stop_listener_task = asyncio.create_task(wait_for_stop())
                
                await asyncio.gather(record_task, stop_listener_task)
                
                wav_path = record_task.result()
                if wav_path:
                    print("[Processing Speech...]")
                    prompt = await stt_pipeline.transcribe(wav_path)
                    print(f"User (STT): {prompt}")
                else:
                    print("[System]: No audio recorded.")
                    continue
            else:
                # User typed a text message - stop current speech
                tts_pipeline.stop()
                prompt = user_choice

            if not prompt:
                continue

            # Format history & context
            formatted_messages = prompt_mgr.format_chat_history(chat_history, prompt)
            
            # Reset block state right before we start generating the response,
            # so the assistant is allowed to speak this new turn's response.
            tts_pipeline.reset()
            
            # Stream LLM Response and queue sentences on-the-fly for near-zero TTS latency
            print("Assistant: ", end="", flush=True)
            response_chunks = []
            current_sentence = ""
            speech_buffer = []
            
            async for chunk in llm_engine.stream_response(formatted_messages):
                print(chunk, end="", flush=True)
                response_chunks.append(chunk)
                current_sentence += chunk
                
                # Check for sentence boundaries (. ! ? or newline)
                if any(p in chunk for p in ['.', '!', '?', '\n']):
                    # Split completed sentences from the buffer
                    parts = re.split(r'(?<=[.!?])\s+|\n+', current_sentence)
                    if len(parts) > 1:
                        for p in parts[:-1]:
                            if p.strip():
                                speech_buffer.append(p.strip())
                        current_sentence = parts[-1]
                        
                        # Only speak if we have accumulated a reasonable sentence length
                        joined_speech = " ".join(speech_buffer)
                        if len(joined_speech) >= 60 or '\n' in chunk:
                            await tts_pipeline.speak(joined_speech)
                            speech_buffer.clear()
            
            # Speak any leftover text in buffers
            if current_sentence.strip():
                speech_buffer.append(current_sentence.strip())
            
            if speech_buffer:
                await tts_pipeline.speak(" ".join(speech_buffer))
                
            print() # Print newline
            full_response = "".join(response_chunks)
            
            # Keep history under control (last 10 turns)
            chat_history.append({"role": "user", "content": prompt})
            chat_history.append({"role": "assistant", "content": full_response})
            if len(chat_history) > 20:
                chat_history = chat_history[-20:]

        except KeyboardInterrupt:
            # Let Ctrl+C exit the program directly as standard terminal behavior
            tts_pipeline.stop()
            break
        except Exception as e:
            print(f"\n[Runtime Error]: {e}")

    print("\nTirakot shut down cleanly. Goodbye!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTirakot shut down cleanly. Goodbye!")
