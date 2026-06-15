import asyncio
import yaml
from ollama import AsyncClient

class LLMEngine:
    def __init__(self, config_path: str = "config.yaml"):
        # Load configuration
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
        except Exception:
            self.config = {
                "llm_model": "qwen2.5:1.5b",
                "llm_api_base": "http://localhost:11434"
            }
        
        self.model_name = self.config.get("llm_model", "qwen2.5:1.5b")
        api_base = self.config.get("llm_api_base", "http://localhost:11434")
        self.client = AsyncClient(host=api_base)

    async def stream_response(self, messages: list):
        """
        Streams responses from the local Ollama LLM.
        messages: Formatted list of chat messages.
        Yields: Chunks of text response.
        """
        try:
            response_stream = await self.client.chat(
                model=self.model_name,
                messages=messages,
                stream=True
            )
            async for chunk in response_stream:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                

        except Exception as e:
            yield f"\n[LLMEngine Error]: Failed to connect to Ollama or process query. Details: {e}\n"
            yield "Please ensure Ollama is running (`ollama serve`) and the model is downloaded (`ollama pull qwen2.5:1.5b`)."
