# prompt_manager.py - Manages system prompts and context formatting

class PromptManager:
    def __init__(self):
        self.default_system_prompt = (
            "You are Tirakot, a local, task-integrated, resource-aware OS assistant for Windows. "
            "Your responses must be clear, concise, and helpful. You prefer brief, precise explanations. "
            "You are aware that the host system is running Windows, has an i5 CPU, 16GB RAM, and an RTX 3050 GPU. "
            "IMPORTANT TRUTHFULNESS RULES: You must stick strictly to verified historical facts. If you do not "
            "know the answer to a question, or if you are not 100% certain about names, dates, or relationships, "
            "DO NOT make them up or guess. State clearly: 'I am not sure about that.' or 'I do not have that factual information locally.'"
        )

    def get_system_prompt(self, custom_prompt: str = None) -> str:
        """Returns the system prompt to instruct the model."""
        return custom_prompt or self.default_system_prompt

    def format_chat_history(self, history: list, new_prompt: str) -> list:
        """
        Formats chat history to pass to Ollama's chat API.
        history: List of dicts with keys 'role' and 'content'.
        """
        messages = []
        # Add system message at the beginning
        messages.append({"role": "system", "content": self.get_system_prompt()})
        
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
            
        messages.append({"role": "user", "content": new_prompt})
        return messages
