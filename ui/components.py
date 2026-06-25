"""
ui/components.py - Custom widgets for Tirakot AI (CodeBlock, ChatBubble, AvatarWidget)
"""
import re
import math
import tkinter as tk
import customtkinter as ctk

class CodeBlockWidget(ctk.CTkFrame):
    """Styled code-block with language header and copy button."""
    def __init__(self, master, code: str, language: str, theme: dict, **kw):
        super().__init__(master, fg_color=theme["code_bg"], corner_radius=12, **kw)
        self._code = code
        t = theme

        # header bar
        header = ctk.CTkFrame(self, fg_color=theme["code_header"], corner_radius=10, height=28)
        header.pack(fill="x", padx=2, pady=(2, 0))
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text=language,
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"), text_color=theme["text_muted"],
        ).pack(side="left", padx=8, pady=4)

        self._copy_btn = ctk.CTkButton(
            header, text="Copy", width=44, height=20,
            fg_color=theme["border"], hover_color=theme["accent"],
            text_color=theme["text_muted"],
            font=ctk.CTkFont(size=10), corner_radius=6,
            command=self._copy,
        )
        self._copy_btn.pack(side="right", padx=6, pady=4)

        # code body
        lines = code.split("\n")
        visible = min(len(lines), 20)
        h = max(visible * 19 + 14, 48)

        # Use width=430 and pack with fill to adjust properly
        self._textbox = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=theme["code_bg"], text_color=theme["code_text"],
            height=h, width=430, wrap="none", corner_radius=0,
            border_width=0, activate_scrollbars=True,
        )
        self._textbox.insert("1.0", code)
        self._textbox.configure(state="disabled")
        self._textbox.pack(fill="x", padx=8, pady=(4, 8))

    def _copy(self):
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(self._code)
        self._copy_btn.configure(text="Copied!")
        self.after(1500, lambda: self._copy_btn.configure(text="Copy"))


class ChatBubble(ctk.CTkFrame):
    """
    Chat message bubble.
    • Single frame implementation (eliminates overlapping border leakage).
    • Highly rounded edges.
    • Side-by-side avatar layout.
    """
    def __init__(self, master, message: str, is_user: bool, theme: dict,
                 streaming: bool = False, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._theme = theme
        self._is_user = is_user
        self._streaming = streaming
        self._raw_text = "" if streaming else message

        # Translucent glass faking
        self._base_bg = theme["user_bubble"] if is_user else theme["bot_bubble"]
        self._base_bd = theme["user_border"] if is_user else theme["bot_border"]
        cr_outer = 20  # Highly rounded edges

        # Single frame border structure
        self._border_frame = ctk.CTkFrame(
            self,
            fg_color=self._base_bg,
            border_color=self._base_bd,
            border_width=1.5,
            corner_radius=cr_outer
        )

        # Content container inside the bubble
        self._content = ctk.CTkFrame(self._border_frame, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=16, pady=12)

        # Build content
        if streaming:
            self._stream_label = ctk.CTkLabel(
                self._content, text="",
                text_color=theme["text"],
                font=ctk.CTkFont(family="Inter", size=13),
                justify="left", anchor="nw",
                wraplength=440
            )
            self._stream_label.pack(anchor="w", fill="x")
        else:
            self._render_formatted(message)

        # Side-by-side layout configuration
        if is_user:
            self.grid_columnconfigure(0, weight=1)
            
            # Left: Text Bubble (aligned to right)
            self._border_frame.grid(row=0, column=0, sticky="e", padx=(48, 6), pady=6)
            
            # Right: User Avatar (Silhouette round label)
            self.avatar = ctk.CTkLabel(
                self, text="👤", font=ctk.CTkFont(size=14),
                text_color=theme["text_muted"], fg_color=theme["border"],
                corner_radius=18, width=36, height=36
            )
            self.avatar.grid(row=0, column=1, sticky="n", padx=(6, 12), pady=6)
        else:
            self.grid_columnconfigure(1, weight=1)
            
            # Left: Bot Avatar (Girl Bitmoji)
            aspect = 0.706
            avatar_w = int(36 * aspect)
            self.avatar_holder = ctk.CTkFrame(self, fg_color="transparent", width=avatar_w, height=36)
            self.avatar_holder.grid(row=0, column=0, sticky="n", padx=(12, 6), pady=6)
            self.avatar_holder.grid_propagate(False)
            
            self.avatar = AvatarWidget(self.avatar_holder, theme=theme, size=36, static=True)
            self.avatar.pack(fill="both", expand=True)
            
            # Right: Text Bubble (aligned to left)
            self._border_frame.grid(row=0, column=1, sticky="w", padx=(6, 48), pady=6)

    def set_glow_color(self, border_color, fg_color):
        """Dynamic color updates for the breathing active glow effect."""
        self._border_frame.configure(border_color=border_color, fg_color=fg_color)

    def reset_colors(self):
        """Reset colors to theme defaults."""
        self._border_frame.configure(border_color=self._base_bd, fg_color=self._base_bg)

    def append_text(self, token: str):
        self._raw_text += token
        if hasattr(self, "_stream_label"):
            self._stream_label.configure(text=self._raw_text)

    def finalize(self):
        self._streaming = False
        if hasattr(self, "_stream_label"):
            self._stream_label.destroy()
        for w in self._content.winfo_children():
            w.destroy()
        self._render_formatted(self._raw_text)

    def _render_formatted(self, text: str):
        segments = self._parse_blocks(text)
        for kind, body, lang in segments:
            if kind == "text" and body.strip():
                lbl = ctk.CTkLabel(
                    self._content, text=body.strip(),
                    text_color=self._theme["text"],
                    font=ctk.CTkFont(family="Inter", size=13),
                    justify="left", anchor="nw",
                    wraplength=440
                )
                lbl.pack(anchor="w", fill="x", pady=2)
            elif kind == "code":
                cb = CodeBlockWidget(self._content, body, lang, self._theme)
                cb.pack(fill="x", pady=4)

    @staticmethod
    def _parse_blocks(text: str):
        segs = []
        pat = r"```(\w*)\n?(.*?)```"
        last = 0
        for m in re.finditer(pat, text, re.DOTALL):
            if m.start() > last:
                segs.append(("text", text[last:m.start()], None))
            segs.append(("code", m.group(2).rstrip(), m.group(1) or "code"))
            last = m.end()
        if last < len(text):
            segs.append(("text", text[last:], None))
        if not segs:
            segs.append(("text", text, None))
        return segs

    def update_theme(self, theme: dict):
        self._theme = theme
        self._base_bg = theme["user_bubble"] if self._is_user else theme["bot_bubble"]
        self._base_bd = theme["user_border"] if self._is_user else theme["bot_border"]
        self.reset_colors()
        
        if self._is_user:
            self.avatar.configure(text_color=theme["text_muted"], fg_color=theme["border"])
        else:
            self.avatar.update_theme(theme)

        for w in self._content.winfo_children():
            if isinstance(w, ctk.CTkLabel):
                w.configure(text_color=theme["text"])


class AvatarWidget(ctk.CTkFrame):
    """
    Snapchat-style Assistant Avatar.
    Displays a premium generated Snapchat bitmoji image.
    Animates with bobbing motion and a pulsing audio wave during speech.
    """
    def __init__(self, master, theme: dict, size: int = 60, static: bool = False, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.theme = theme
        self.size = size
        self.state = "idle"
        self.static = static
        
        # Load the stable generated image
        import os
        from PIL import Image
        
        img_path = "ui/png/girl_bitmoji.png"
        if os.path.exists(img_path):
            pil_img = Image.open(img_path)
            # Handle aspect ratio
            w, h = pil_img.size
            aspect = w / h
            img_w = int(size * aspect)
            img_h = size
        else:
            # Fallback circle if image is missing
            pil_img = Image.new("RGBA", (128, 128), (123, 92, 240, 255))
            img_w = size
            img_h = size
            
        self.avatar_image = ctk.CTkImage(
            light_image=pil_img,
            dark_image=pil_img,
            size=(img_w, img_h)
        )
        
        self.img_label = ctk.CTkLabel(self, text="", image=self.avatar_image)
        self.img_label.pack(side="left")
        
        if not static:
            # Waveform Canvas
            self.wave_frame = ctk.CTkFrame(self, fg_color="transparent", width=22, height=size)
            self.wave_canvas = tk.Canvas(self.wave_frame, width=18, height=size, bg=theme["bg_header"], highlightthickness=0, bd=0)
            self.wave_canvas.pack(fill="both", expand=True)
            
            self.speak_phase = 0.0
            self.wave_bars = []
            
            # Draw 3 vertical audio bars
            self.wave_bars.append(self.wave_canvas.create_rectangle(3, 20, 5, 30, fill=theme["accent"], outline=""))
            self.wave_bars.append(self.wave_canvas.create_rectangle(8, 15, 10, 35, fill=theme["accent"], outline=""))
            self.wave_bars.append(self.wave_canvas.create_rectangle(13, 20, 15, 30, fill=theme["accent"], outline=""))
            
            self._speak_loop()
        
    def set_state(self, state: str):
        if self.static or state == self.state:
            return
        self.state = state
        if state == "speaking":
            self.wave_frame.pack(side="left", padx=(6, 0))
        else:
            self.wave_frame.pack_forget()
            
    def update_theme(self, theme: dict):
        self.theme = theme
        if not self.static:
            self.wave_canvas.configure(bg=theme["bg_header"])
            for bar in self.wave_bars:
                self.wave_canvas.itemconfig(bar, fill=theme["accent"])

    def _speak_loop(self):
        if self.state == "speaking":
            self.speak_phase += 0.35
            
            # Animate the avatar bobbing up and down
            bob = 4.0 * math.sin(self.speak_phase)
            self.img_label.pack_configure(pady=(max(0.0, bob), max(0.0, -bob)))
            
            # Animate wave bars heights
            h1 = 12 + 8 * math.sin(self.speak_phase)
            h2 = 18 + 10 * math.cos(self.speak_phase * 0.8)
            h3 = 14 + 6 * math.sin(self.speak_phase * 1.2)
            
            cy = self.size // 2
            self.wave_canvas.coords(self.wave_bars[0], 3, cy - h1, 5, cy + h1)
            self.wave_canvas.coords(self.wave_bars[1], 8, cy - h2, 10, cy + h2)
            self.wave_canvas.coords(self.wave_bars[2], 13, cy - h3, 15, cy + h3)
            
            self.after(80, self._speak_loop)
        else:
            self.img_label.pack_configure(pady=0)
            self.after(200, self._speak_loop)
