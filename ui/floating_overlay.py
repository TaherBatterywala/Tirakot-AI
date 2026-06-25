import math
import tkinter as tk
import customtkinter as ctk

class TirakotFloatingOverlay(ctk.CTkToplevel):
    """Draggable, premium Siri-style floating overlay — top-right of screen
    with header close button, waveform animation, transcript, and text input box."""
    
    def __init__(self, parent, cmd_queue, gui_queue, on_mic_click_cb):
        super().__init__(parent)
        self.parent = parent
        self.cmd_queue = cmd_queue
        self.gui_queue = gui_queue
        self.on_mic_click_cb = on_mic_click_cb
        
        # Borderless, topmost, transparent background
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-transparentcolor", "#010101")
        self.configure(fg_color="#010101")
        
        # ── Geometry: top-right, 460px wide, 365px tall ──
        self.overlay_w = 460
        self.overlay_h = 365
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = sw - self.overlay_w - 40
        y = 40
        self.geometry(f"{self.overlay_w}x{self.overlay_h}+{x}+{y}")
        
        # ── State ──
        self.status = "idle"
        self.wave_phase = 0.0
        self._transcript_text = ""
        self._response_text = ""
        
        # ── Drag State ──
        self._drag_x = 0
        self._drag_y = 0
        
        # ── Main container with dark glassmorphism ──
        self.container = ctk.CTkFrame(
            self, fg_color="#0D0D0F", corner_radius=24,
            border_width=1, border_color="#1E1E24"
        )
        self.container.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Bind dragging to the container frame
        self.container.bind("<Button-1>", self._start_drag)
        self.container.bind("<B1-Motion>", self._drag)
        
        # ── Header ──
        self.header_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=18, pady=(12, 0))
        self.header_frame.bind("<Button-1>", self._start_drag)
        self.header_frame.bind("<B1-Motion>", self._drag)
        
        self.title_label = ctk.CTkLabel(
            self.header_frame, text="Tirakot Assistant",
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
            text_color="#A1A1AA"
        )
        self.title_label.pack(side="left")
        self.title_label.bind("<Button-1>", self._start_drag)
        self.title_label.bind("<B1-Motion>", self._drag)
        
        self.close_btn = ctk.CTkButton(
            self.header_frame, text="✕", width=28, height=28,
            fg_color="transparent", hover_color="#1E1E24",
            text_color="#71717A", font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=14, command=self._dismiss
        )
        self.close_btn.pack(side="right")
        
        # ── Waveform canvas ──
        self.canvas = tk.Canvas(
            self.container, width=420, height=75,
            bg="#0D0D0F", highlightthickness=0
        )
        self.canvas.pack(pady=(4, 0))
        self.canvas.bind("<Button-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        
        # ── Transcript text (what user said) ──
        self.transcript_label = ctk.CTkLabel(
            self.container, text="",
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            text_color="#F4F4F5",
            wraplength=400, justify="center"
        )
        self.transcript_label.pack(pady=(4, 0))
        self.transcript_label.bind("<Button-1>", self._start_drag)
        self.transcript_label.bind("<B1-Motion>", self._drag)
        
        # ── Input Tray (Footer) packed at the bottom first! ──
        self.footer_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.footer_frame.pack(side="bottom", fill="x", padx=16, pady=(0, 16))
        
        self.entry = ctk.CTkEntry(
            self.footer_frame, placeholder_text="Ask Tirakot...",
            fg_color="#18181B", border_color="#27272A",
            text_color="#F4F4F5", placeholder_text_color="#71717A",
            font=ctk.CTkFont(family="Inter", size=12), corner_radius=10,
            height=34, border_width=1
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry.bind("<Return>", lambda _: self._send_text())
        
        # Mic Toggle Button on Overlay
        self.mic_btn = ctk.CTkButton(
            self.footer_frame, text="🎙️", width=34, height=34,
            fg_color="#27272A", hover_color="#3F3F46",
            text_color="#A1A1AA", font=ctk.CTkFont(size=13),
            corner_radius=17, border_width=1, border_color="#3F3F46",
            command=self.on_mic_click_cb
        )
        self.mic_btn.pack(side="right", padx=(0, 0))
        
        self.send_btn = ctk.CTkButton(
            self.footer_frame, text="Send", width=48, height=34,
            fg_color="#3B82F6", hover_color="#2563EB",
            text_color="#FFFFFF", font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            corner_radius=10, command=self._send_text
        )
        self.send_btn.pack(side="right", padx=(0, 6))

        self.stop_btn = ctk.CTkButton(
            self.footer_frame, text="Stop", width=48, height=34,
            fg_color="#EF4444", hover_color="#DC2626",
            text_color="#FFFFFF", font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            corner_radius=10, command=self._stop_response
        )
        self.stop_btn.pack(side="right", padx=(0, 6))

        # ── Response text (what Tirakot says) - packed top with expand=True ──
        self.response_box = ctk.CTkTextbox(
            self.container, fg_color="#0D0D0F", text_color="#9CA3AF",
            font=ctk.CTkFont(family="Inter", size=12),
            wrap="word", corner_radius=0, border_spacing=0
        )
        self.response_box.pack(side="top", pady=(2, 6), fill="both", expand=True, padx=18)
        self.response_box.configure(state="disabled")
        
        # Start animation loop
        self._animate_waveform()
        
    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y
        
    def _drag(self, event):
        deltax = event.x - self._drag_x
        deltay = event.y - self._drag_y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")
        
    def _send_text(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        # Delegate text submission to parent app coordinator
        self.parent._send_text_action(text)
        
    def _dismiss(self):
        """Dismiss the overlay and stop any voice interaction."""
        self.cmd_queue.put(("stop_speech", None))
        self.withdraw()
        
    def set_status(self, status):
        """Update the overlay state and mic button visual appearance."""
        self.status = status
        
        # Style the mic button depending on listening state
        if status == "listening":
            self.mic_btn.configure(fg_color="#EF4444", hover_color="#DC2626", text_color="#FFFFFF", border_color="#EF4444")
        else:
            self.mic_btn.configure(fg_color="#27272A", hover_color="#3F3F46", text_color="#A1A1AA", border_color="#3F3F46")
            
    def set_transcript(self, text):
        """Set the user's transcribed speech text."""
        self._transcript_text = text
        self.transcript_label.configure(text=f'"{text}"' if text else "")
        
    def set_response(self, text):
        """Set Tirakot's response text."""
        self._response_text = text
        self.response_box.configure(state="normal")
        self.response_box.delete("1.0", tk.END)
        self.response_box.insert("1.0", text)
        self.response_box.configure(state="disabled")
        self.response_box.see(tk.END)
        
    def clear_text(self):
        """Clear all displayed text."""
        self._transcript_text = ""
        self._response_text = ""
        self.transcript_label.configure(text="")
        self.response_box.configure(state="normal")
        self.response_box.delete("1.0", tk.END)
        self.response_box.configure(state="disabled")
        
    def show_followup(self):
        """Show follow-up listening state."""
        self.response_box.configure(state="normal")
        self.response_box.insert(tk.END, "\n\n(Listening...)")
        self.response_box.configure(state="disabled")
        self.response_box.see(tk.END)
        
    def _stop_response(self):
        """Stops speech playback/thinking and triggers mic listening immediately."""
        self.cmd_queue.put(("stop_speech", None))
        self.after(80, lambda: self.cmd_queue.put(("toggle_mic", None)))
        
    def _animate_waveform(self):
        """Draws an animated multi-color Siri-style waveform."""
        if not self.winfo_exists():
            return
            
        self.canvas.delete("all")
        
        w = 420
        h = 75
        cx = w / 2
        cy = h / 2
        
        self.wave_phase += 0.12
        
        colors = [
            "#00F2FE",  # Cyan
            "#4FACFE",  # Blue  
            "#B721FF",  # Purple
            "#FF6BCA",  # Pink
        ]
        
        # Determine amplitude based on state
        if self.status == "listening":
            base_amp = 18
            speed_mult = 1.5
            num_waves = 4
        elif self.status == "thinking":
            base_amp = 10
            speed_mult = 2.5
            num_waves = 3
        elif self.status == "speaking":
            base_amp = 22
            speed_mult = 1.2
            num_waves = 4
        else:  # idle
            base_amp = 4
            speed_mult = 0.5
            num_waves = 2
            
        for wave_idx in range(num_waves):
            points = []
            color = colors[wave_idx % len(colors)]
            phase_offset = wave_idx * (math.pi / 2.5)
            freq = 2.5 + wave_idx * 0.4
            
            amp = base_amp * (1.0 - wave_idx * 0.15)
            amp *= (0.7 + 0.3 * math.sin(self.wave_phase * speed_mult + phase_offset))
            
            num_points = 120
            for i in range(num_points + 1):
                x = (i / num_points) * w
                dist = abs(x - cx) / (w / 2)
                taper = max(0, 1.0 - dist ** 1.8)
                
                y = cy + amp * taper * (
                    math.sin((x / w) * freq * math.pi * 2 + self.wave_phase * speed_mult + phase_offset)
                    + 0.3 * math.sin((x / w) * freq * 2 * math.pi * 2 + self.wave_phase * speed_mult * 1.5 + phase_offset)
                )
                points.append(x)
                points.append(y)
                
            if len(points) >= 4:
                line_width = max(1, 3 - wave_idx)
                self.canvas.create_line(
                    *points, fill=color, width=line_width,
                    smooth=True, splinesteps=36
                )
                
        # Subtle white center line
        center_points = []
        center_amp = base_amp * 0.4
        for i in range(121):
            x = (i / 120) * w
            dist = abs(x - cx) / (w / 2)
            taper = max(0, 1.0 - dist ** 1.5)
            y = cy + center_amp * taper * math.sin((x / w) * 3 * math.pi * 2 + self.wave_phase * speed_mult)
            center_points.extend([x, y])
            
        if len(center_points) >= 4:
            self.canvas.create_line(*center_points, fill="#FFFFFF", width=1, smooth=True, splinesteps=36)
            
        ms = 25 if self.status != "idle" else 50
        self.after(ms, self._animate_waveform)
        
    def withdraw(self):
        """Override withdraw to cancel any pending dismiss and stop active recording."""
        self.clear_text()
        self.cmd_queue.put(("stop_speech", None))
        super().withdraw()
