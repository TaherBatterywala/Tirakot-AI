# prompt_manager.py - Manages system prompts and context formatting
# Supports two modes: VOICE (Jarvis-like concise) and TEXT (detailed chatbot)

class PromptManager:
    def __init__(self):
        # ── Shared identity & truthfulness rules ──
        self._identity = (
            "You are Tirakot, a smart local AI assistant running on a Windows PC "
            "(i5, 16GB RAM, RTX 3050). You run fully offline via a local LLM.\n"
            "TRUTHFULNESS: Stick to verified facts. If unsure, say so honestly. "
            "Never fabricate names, dates, or relationships."
        )

        # ── TEXT MODE: detailed, structured, like a chatbot ──
        self._text_rules = (
            "TEXT MODE — the user is reading your response on screen.\n"
            "- Give detailed, well-structured responses.\n"
            "- Use markdown: headers, bullet points, numbered lists, **bold**.\n"
            "- For code: use fenced code blocks with the language name (```python etc.).\n"
            "- Explain your reasoning and provide context.\n"
            "- Be thorough but organized."
        )

        # ── VOICE MODE: Jarvis-style, short and natural ──
        self._voice_rules = (
            "VOICE MODE — your response will be read aloud. You MUST act like a smart, ultra-concise assistant (like Jarvis).\n\n"
            "CRITICAL RULES FOR VOICE MODE:\n"
            "- Be brief: 1 or 2 spoken sentences maximum.\n"
            "- Speak naturally: use short, direct phrases ('Sure thing', 'Got it', 'On it', 'Here you go').\n"
            "- FOR CODE REQUESTS: Say exactly ONE short introductory sentence (e.g., 'Sure, here is that Python script for you:') and then output the code block. Do NOT write any explanations, instructions, or analysis of the code outside the code block.\n"
            "- NEVER describe coding syntax, operators, or imports in spoken prose.\n"
            "- Avoid list structures, bullet points, headers, or bold markdown outside code blocks, as they sound unnatural when read aloud.\n"
            "- For factual queries: State the answer directly and concisely."
        )

    def get_system_prompt(self, voice_mode: bool = False) -> str:
        """Returns the full system prompt based on current mode."""
        rules = self._voice_rules if voice_mode else self._text_rules
        return f"{self._identity}\n\n{rules}"

    def format_chat_history(self, history: list, new_prompt: str,
                            voice_mode: bool = False) -> list:
        """
        Formats chat history to pass to Ollama's chat API.
        history: List of dicts with keys 'role' and 'content'.
        voice_mode: Whether TTS is active (changes system prompt personality).
        """
        messages = [{"role": "system", "content": self.get_system_prompt(voice_mode)}]

        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": new_prompt})
        return messages
