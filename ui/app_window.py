"""
ui/app_window.py - Tirakot AI Premium Desktop GUI Coordinator
"""
import math
import queue
import tkinter as tk
import customtkinter as ctk

from ui.themes import THEMES
from ui.components import ChatBubble, AvatarWidget

class TirakotApp(ctk.CTk):
    def __init__(self, cmd_queue: queue.Queue, gui_queue: queue.Queue):
        super().__init__()

        self.cmd_queue = cmd_queue
        self.gui_queue = gui_queue

        # ── State ──
        self._theme_name = "dark"
        self._t = THEMES["dark"]
        self._bubbles: list[ChatBubble] = []
        self.active_bubble: ChatBubble | None = None
        self._input_hist: list[str] = []
        self._hist_idx = -1
        self._orb_state = "idle"
        self._orb_phase = 0.0
        self._mic_on = False
        self._voice_on = True
        self._has_started = False
        self._current_page = "Home"
        self._chat_sessions = {}
        self._session_buttons = {}
        self._active_session_id = None

        # ── Window Chrome ──
        self.title("Tirakot AI")
        self.geometry("1000x650")
        self.minsize(800, 500)
        self.configure(fg_color=self._t["bg"])
        ctk.set_appearance_mode("dark")

        # Configure 2-Pane grid on main window (Right Panel removed)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0) # Left Sidebar (fixed)
        self.grid_columnconfigure(1, weight=1) # Main Workspace (stretches)

        # Build panes
        self._build_left_sidebar()
        self._build_workspace()

        # Display modern welcome state in workspace
        self._build_welcome_screen()

        # Update initial voice state
        self._apply_voice_state()

        self.after(50, self._poll)
        self.after(40, self._animate_effects)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─────────────────── LEFT NAVIGATION SIDEBAR ───────────────────

    def _build_left_sidebar(self):
        t = self._t
        self._sidebar_left = ctk.CTkFrame(self, width=200, fg_color=t["bg_header"], corner_radius=0, border_width=1, border_color=t["border"])
        self._sidebar_left.grid(row=0, column=0, sticky="nsew")
        self._sidebar_left.grid_propagate(False)
        
        # Brand Header
        self._brand_lbl = ctk.CTkLabel(
            self._sidebar_left, text="Tirakot AI",
            font=ctk.CTkFont(family="Inter", size=16, weight="bold"),
            text_color=t["text"]
        )
        self._brand_lbl.pack(padx=20, pady=(20, 15), anchor="w")
        
        # Home button
        self._home_btn = ctk.CTkButton(
            self._sidebar_left, text="🏠  Home",
            fg_color=t["border"] if self._current_page == "Home" else "transparent",
            hover_color=t["border"],
            text_color=t["text"] if self._current_page == "Home" else t["text_muted"],
            font=ctk.CTkFont(family="Inter", size=12, weight="bold" if self._current_page == "Home" else "normal"),
            anchor="w", height=36, corner_radius=8,
            command=self._on_home_click
        )
        self._home_btn.pack(fill="x", padx=10, pady=4)
        
        # My Chats label
        self._lbl_chats = ctk.CTkLabel(
            self._sidebar_left, text="💬  My Chats",
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            text_color=t["text_muted"]
        )
        self._lbl_chats.pack(padx=20, pady=(15, 6), anchor="w")
        
        # Chats List Scrollable Frame
        self._chats_list = ctk.CTkScrollableFrame(
            self._sidebar_left, fg_color="transparent", corner_radius=0,
            label_text="", height=250
        )
        self._chats_list.pack(fill="both", expand=True, padx=4, pady=2)

    def _on_home_click(self):
        self._current_page = "Home"
        self._active_session_id = None
        self._stop_speech()
        self._apply_theme()
        if self._chat.winfo_ismapped():
            self._chat.grid_forget()
        self._build_welcome_screen()

    def _add_session_to_sidebar(self, session_id: int, title: str):
        t = self._t
        btn = ctk.CTkButton(
            self._chats_list, text=title,
            fg_color="transparent", hover_color=t["border"],
            text_color=t["text_muted"],
            font=ctk.CTkFont(family="Inter", size=11),
            anchor="w", height=28, corner_radius=6,
            command=lambda sid=session_id: self._load_chat_session(sid)
        )
        btn.pack(fill="x", padx=4, pady=2)
        btn.bind("<Double-Button-1>", lambda _, sid=session_id: self._rename_session(sid))
        self._session_buttons[session_id] = btn

    def _rename_session(self, session_id: int):
        self._stop_speech()
        dialog = ctk.CTkInputDialog(text="Enter new name for this chat:", title="Rename Chat")
        new_name = dialog.get_input()
        if new_name and new_name.strip():
            self._chat_sessions[session_id]["title"] = new_name.strip()
            self._session_buttons[session_id].configure(text=new_name.strip())

    def _load_chat_session(self, session_id: int):
        self._current_page = "My Chats"
        self._active_session_id = session_id
        self._stop_speech()
        self._apply_theme()
        
        self._hide_welcome_screen()
        
        # Clear current bubbles on screen
        for w in self._chat.winfo_children():
            w.destroy()
        self._bubbles.clear()
        self.active_bubble = None
        
        # Load messages from history
        session = self._chat_sessions[session_id]
        for msg in session["messages"]:
            b = ChatBubble(self._chat, msg["text"], msg["is_user"], self._t, streaming=False)
            b.pack(fill="x", padx=4, pady=2)
            self._bubbles.append(b)
            
        self.update_idletasks()
        self._chat._parent_canvas.yview_moveto(1.0)

    # ─────────────────── MAIN WORKSPACE ───────────────────

    def _build_workspace(self):
        self._workspace = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self._workspace.grid(row=0, column=1, sticky="nsew")
        
        self._workspace.grid_rowconfigure(1, weight=1)
        self._workspace.grid_columnconfigure(0, weight=1)
        
        # Build interior sub-layouts inside the workspace
        self._build_header()
        self._build_chat()
        self._build_footer()

    # ─────────────────── HEADER ───────────────────

    def _build_header(self):
        t = self._t

        self._hdr_wrap = ctk.CTkFrame(self._workspace, height=56, fg_color=t["border"], corner_radius=0)
        self._hdr_wrap.grid(row=0, column=0, sticky="ew")
        self._hdr_wrap.grid_propagate(False)
        self._hdr_wrap.grid_columnconfigure(0, weight=1)

        self._hdr = ctk.CTkFrame(self._hdr_wrap, fg_color=t["bg_header"], corner_radius=0)
        self._hdr.pack(fill="both", expand=True, pady=(0, 1))
        self._hdr.grid_columnconfigure(0, weight=1)

        # Title
        self._title_lbl = ctk.CTkLabel(
            self._hdr, text="TIRAKOT AI",
            font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
            text_color=t["text"],
        )
        self._title_lbl.pack(side="left", padx=18, pady=14)

        # Theme Button
        self._theme_btn = ctk.CTkButton(
            self._hdr, text="Light", width=50, height=28,
            fg_color=t["border"], hover_color=t["mic_hover"],
            text_color=t["text_muted"],
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            corner_radius=6, command=self._toggle_theme,
        )
        self._theme_btn.pack(side="right", padx=16, pady=14)

        # Voice Toggle
        self._voice_btn = ctk.CTkButton(
            self._hdr, text="Voice: On", width=80, height=28,
            fg_color=t["voice_on"], hover_color=t["accent_dim"],
            text_color="#FFFFFF",
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            corner_radius=6, command=self._toggle_voice,
        )
        self._voice_btn.pack(side="right", padx=(0, 4), pady=14)

    # ─────────────────── CHAT AREA ───────────────────

    def _build_chat(self):
        t = self._t
        self._chat = ctk.CTkScrollableFrame(
            self._workspace, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=t["scrollbar"],
            scrollbar_button_hover_color=t["accent"],
        )
        self._chat.grid_columnconfigure(0, weight=1)
        
        # Bind mouse movement for glowing backdrop effects
        self._chat.bind("<Motion>", self._on_mouse_motion)

    # ─────────────────── MODERN CENTERED WELCOME SCREEN ───────────────────

    def _build_welcome_screen(self):
        if hasattr(self, "welcome_screen") and self.welcome_screen:
            self.welcome_screen.destroy()
            
        if hasattr(self, "_ftr_wrap") and self._ftr_wrap:
            self._ftr_wrap.grid_forget()
            
        t = self._t
        
        self.welcome_screen = ctk.CTkFrame(self._workspace, fg_color="transparent")
        self.welcome_screen.grid(row=1, column=0, sticky="nsew")
        self.welcome_screen.grid_columnconfigure(0, weight=1)
        self.welcome_screen.grid_rowconfigure(0, weight=1)
        
        # Centering container
        inner_welcome = ctk.CTkFrame(self.welcome_screen, fg_color="transparent")
        inner_welcome.grid(row=0, column=0, sticky="")
        
        # 1. Welcome Header
        title_welcome = ctk.CTkLabel(
            inner_welcome, text="Welcome to Tirakot AI.",
            font=ctk.CTkFont(family="Inter", size=24, weight="bold"),
            text_color=t["text"]
        )
        title_welcome.pack(pady=(0, 10))
        
        # 2. Centered Snapchat Bitmoji Avatar (large 120px)
        avatar_holder = ctk.CTkFrame(inner_welcome, fg_color="transparent", width=90, height=120)
        avatar_holder.pack(pady=(0, 15))
        avatar_holder.pack_propagate(False)
        
        self.welcome_avatar = AvatarWidget(avatar_holder, theme=t, size=120)
        self.welcome_avatar.pack(fill="both", expand=True)
        
        # 3. Subtitle
        subtitle = ctk.CTkLabel(
            inner_welcome, text="What can I help you with today?",
            font=ctk.CTkFont(family="Inter", size=18, weight="bold"),
            text_color=t["text"]
        )
        subtitle.pack(pady=(0, 15))
        
        # 4. Search input box
        self.search_frame = ctk.CTkFrame(inner_welcome, fg_color=t["bg_card"], border_color=t["border"], border_width=1, corner_radius=20, height=44, width=460)
        self.search_frame.pack(pady=(0, 25))
        self.search_frame.pack_propagate(False)
        
        self.search_entry = ctk.CTkEntry(
            self.search_frame, placeholder_text="Type your query here...",
            fg_color="transparent", border_width=0,
            text_color=t["text"], placeholder_text_color=t["text_faint"],
            font=ctk.CTkFont(family="Inter", size=12),
        )
        self.search_entry.pack(side="left", fill="both", expand=True, padx=(16, 4))
        self.search_entry.bind("<Return>", lambda _: self._send_search())
        
        self.welcome_mic_lbl = ctk.CTkLabel(self.search_frame, text="🎙️", font=ctk.CTkFont(size=14), text_color=t["mic_rec"] if self._mic_on else t["text_muted"], cursor="hand2")
        self.welcome_mic_lbl.pack(side="right", padx=(4, 16))
        self.welcome_mic_lbl.bind("<Button-1>", lambda _: self._toggle_mic())
        
        # 5. Suggestion Cards
        cards_frame = ctk.CTkFrame(inner_welcome, fg_color="transparent")
        cards_frame.pack()
        
        quick_actions = [
            ("Document Translation", "🌐", "Translate files & text"),
            ("Content Summarization", "📝", "Summarize reports"),
            ("Goal Setting", "🎯", "Set productivity goals")
        ]
        
        for idx, (title, emoji, prompt) in enumerate(quick_actions):
            card = ctk.CTkFrame(
                cards_frame, fg_color=t["bg_card"], border_color=t["border"], border_width=1,
                corner_radius=12, width=150, height=100
            )
            card.grid(row=0, column=idx, padx=8)
            card.grid_propagate(False)
            
            lbl_icon = ctk.CTkLabel(card, text=emoji, font=ctk.CTkFont(size=20))
            lbl_icon.pack(pady=(12, 4))
            
            lbl_title = ctk.CTkLabel(
                card, text=title,
                font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
                text_color=t["text"], justify="center", wraplength=130
            )
            lbl_title.pack(padx=6)
            
            for w in (card, lbl_icon, lbl_title):
                w.bind("<Button-1>", lambda _, p=prompt: self._send_suggestion(p))

    def _send_search(self):
        text = self.search_entry.get().strip()
        if not text:
            return
        self._hide_welcome_screen()
        self._current_page = "My Chats"
        self.add_message(text, is_user=True)
        self.cmd_queue.put(("send_text", text))

    def _send_suggestion(self, prompt: str):
        self._hide_welcome_screen()
        self._current_page = "My Chats"
        self.add_message(prompt, is_user=True)
        self.cmd_queue.put(("send_text", prompt))

    def _hide_welcome_screen(self):
        if hasattr(self, "welcome_screen") and self.welcome_screen:
            self.welcome_screen.grid_forget()
            self.welcome_screen = None
            # Show the chat scroll view in workspace row 1, col 0
            self._chat.grid(row=1, column=0, sticky="nsew")
            # Show the footer
            if hasattr(self, "_ftr_wrap") and self._ftr_wrap:
                self._ftr_wrap.grid(row=2, column=0, sticky="ew")
            self._has_started = True

    # ─────────────────── FOOTER ───────────────────

    def _build_footer(self):
        t = self._t

        self._ftr_wrap = ctk.CTkFrame(self._workspace, height=76, fg_color=t["border"], corner_radius=0)
        self._ftr_wrap.grid(row=2, column=0, sticky="ew")
        self._ftr_wrap.grid_propagate(False)
        self._ftr_wrap.grid_columnconfigure(0, weight=1)

        self._ftr = ctk.CTkFrame(self._ftr_wrap, fg_color=t["bg_header"], corner_radius=0)
        self._ftr.pack(fill="both", expand=True, pady=(1, 0))
        
        # Left: Snapchat Assistant Avatar
        self.avatar_frame = ctk.CTkFrame(self._ftr, fg_color="transparent", width=65, height=54) # Extra width for voice waves
        self.avatar_frame.pack(side="left", padx=(10, 4), pady=10)
        self.avatar_frame.pack_propagate(False)
        
        self.avatar = AvatarWidget(self.avatar_frame, theme=t, size=54)
        self.avatar.pack(fill="both", expand=True)

        # Right: Button tray and Status Orb
        self.right_tray = ctk.CTkFrame(self._ftr, fg_color="transparent")
        self.right_tray.pack(side="right", padx=(4, 12), pady=12)

        # Send Button
        self._send_btn = ctk.CTkButton(
            self.right_tray, text="Send", width=52, height=36,
            fg_color=t["send"], hover_color=t["send_hover"],
            text_color="#FFFFFF",
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
            corner_radius=10, command=self._send,
        )
        self._send_btn.pack(side="right", padx=(4, 0))

        # Stop Button
        self._stop_btn = ctk.CTkButton(
            self.right_tray, text="Stop", width=46, height=36,
            fg_color=t["stop"], hover_color=t["stop_hover"],
            text_color="#FCA5A5",
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            corner_radius=10, command=self._stop_speech,
        )

        # Mic Button
        self._mic_btn = ctk.CTkButton(
            self.right_tray, text="🎙️", width=36, height=36,
            fg_color=t["mic_idle"], hover_color=t["mic_hover"],
            text_color=t["text_muted"],
            font=ctk.CTkFont(size=14),
            corner_radius=18,
            border_width=2, border_color=t["border"],
            anchor="center",
            command=self._toggle_mic,
        )
        self._mic_btn.pack(side="right", padx=(4, 0))

        # Middle: Text Input with Thicker Glowing Border
        self._entry = ctk.CTkEntry(
            self._ftr, placeholder_text="Ask Tirakot...",
            fg_color=t["bg_input"], border_color=t["border"],
            text_color=t["text"], placeholder_text_color=t["text_faint"],
            font=ctk.CTkFont(family="Inter", size=13), corner_radius=10,
            height=38, border_width=2,
        )
        self._entry.pack(side="left", fill="x", expand=True, padx=(4, 4), pady=18)
        self._entry.bind("<Return>", lambda _: self._send())
        self._entry.bind("<Up>", self._hist_up)
        self._entry.bind("<Down>", self._hist_down)

        self._entry.bind("<FocusIn>", self._on_entry_focus_in)
        self._entry.bind("<FocusOut>", self._on_entry_focus_out)

    # ═══════════════════════ GLOW, FOCUS & MOTION EVENTS ══════════════════════════

    def _on_entry_focus_in(self, _):
        if self._orb_state != "thinking":
            self._entry.configure(border_color=self._t["border_glow"])

    def _on_entry_focus_out(self, _):
        if self._orb_state != "thinking":
            self._entry.configure(border_color=self._t["border"])

    def _on_mouse_motion(self, event):
        """Dynamic Ambient backlighting based on cursor position relative to window height."""
        ratio = min(1.0, max(0.0, event.y / max(1, self.winfo_height())))
        t = self._t
        if self._orb_state == "idle":
            # Interpolate subtle borders
            r_glow = int(int(t["border"][1:3], 16) * (1 - ratio) + int(t["border_glow"][1:3], 16) * ratio)
            g_glow = int(int(t["border"][3:5], 16) * (1 - ratio) + int(t["border_glow"][3:5], 16) * ratio)
            b_glow = int(int(t["border"][5:7], 16) * (1 - ratio) + int(t["border_glow"][5:7], 16) * ratio)
            hover_border = f"#{r_glow:02x}{g_glow:02x}{b_glow:02x}"
            self._ftr_wrap.configure(fg_color=hover_border)

    # ═══════════════════════ PUBLIC API ══════════════════════════

    def set_status(self, state: str):
        self._orb_state = state
        
        # Sync Snapchat avatar state with speaking status
        if state == "speaking":
            self.avatar.set_state("speaking")
            self._stop_btn.pack(side="left", padx=(0, 4), before=self._mic_btn)
        else:
            self.avatar.set_state("idle")
            if state in ("idle", "listening"):
                self._stop_btn.pack_forget()

    def add_message(self, text: str, is_user: bool, streaming: bool = False) -> ChatBubble:
        self._hide_welcome_screen()
        
        # Create a new session if none is active
        if self._active_session_id is None:
            session_id = len(self._chat_sessions) + 1
            title = text[:18] + "..." if len(text) > 18 else text
            self._chat_sessions[session_id] = {
                "title": title,
                "messages": []
            }
            self._active_session_id = session_id
            self._add_session_to_sidebar(session_id, title)
            
            # Clear previous chat screen children since we are starting fresh
            for w in self._chat.winfo_children():
                w.destroy()
            self._bubbles.clear()
            self.active_bubble = None
            
        # Append message to session history
        if not streaming:
            self._chat_sessions[self._active_session_id]["messages"].append({
                "text": text,
                "is_user": is_user
            })
            
        b = ChatBubble(self._chat, text, is_user, self._t, streaming=streaming)
        b.pack(fill="x", padx=4, pady=2)
        self._bubbles.append(b)
        self.update_idletasks()
        self._chat._parent_canvas.yview_moveto(1.0)
        return b

    # ═══════════════════════ ACTIONS ═════════════════════════════

    def _send(self):
        text = self._entry.get().strip()
        if not text:
            return
        self._entry.delete(0, tk.END)
        self._input_hist.append(text)
        self._hist_idx = len(self._input_hist)
        self.add_message(text, is_user=True)
        self.cmd_queue.put(("send_text", text))

    def _toggle_mic(self):
        self.cmd_queue.put(("toggle_mic", None))

    def _stop_speech(self):
        self.cmd_queue.put(("stop_speech", None))
        self._stop_btn.pack_forget()
        if self.active_bubble:
            self.active_bubble.reset_colors()
            self.active_bubble = None

    def _toggle_voice(self):
        self._voice_on = not self._voice_on
        self._apply_voice_state()
        self.cmd_queue.put(("toggle_voice", self._voice_on))

    def _apply_voice_state(self):
        t = self._t
        if self._voice_on:
            self._voice_btn.configure(text="Voice: On", fg_color=t["voice_on"])
            self.avatar_frame.pack(side="left", padx=(10, 4), pady=10, before=self._entry)
        else:
            self._voice_btn.configure(text="Voice: Off", fg_color=t["voice_off"])
            self.avatar_frame.pack_forget()

    def _toggle_theme(self):
        if self._theme_name == "dark":
            self._theme_name = "light"
            self._t = THEMES["light"]
            self._theme_btn.configure(text="Dark")
            ctk.set_appearance_mode("light")
        else:
            self._theme_name = "dark"
            self._t = THEMES["dark"]
            self._theme_btn.configure(text="Light")
            ctk.set_appearance_mode("dark")
        self._apply_theme()

    # ═══════════════════════ INTERNALS ══════════════════════════

    def _apply_theme(self):
        t = self._t
        self.configure(fg_color=t["bg"])

        # Left Sidebar
        self._sidebar_left.configure(fg_color=t["bg_header"], border_color=t["border"])
        self._brand_lbl.configure(text_color=t["text"])
        self._lbl_chats.configure(text_color=t["text_muted"])
        self._chats_list.configure(
            fg_color=t["bg_header"],
            scrollbar_button_color=t["scrollbar"],
            scrollbar_button_hover_color=t["accent"]
        )

        if self._current_page == "Home":
            self._home_btn.configure(fg_color=("#81D4FA", "#424242"), text_color=("#01579B", "#E0E0E0"))
        else:
            self._home_btn.configure(fg_color="transparent", text_color=("#03A9F4", "#CCCCCC"))

        for sid, btn in self._session_buttons.items():
            if self._current_page == "My Chats" and self._active_session_id == sid:
                btn.configure(fg_color=("#81D4FA", "#424242"), text_color=("#01579B", "#E0E0E0"))
            else:
                btn.configure(fg_color="transparent", text_color=("#03A9F4", "#CCCCCC"))

        # header
        self._hdr_wrap.configure(fg_color=t["border"])
        self._hdr.configure(fg_color=t["bg_header"])
        self._title_lbl.configure(text_color=t["text"])
        self._voice_btn.configure(fg_color=t["voice_on"] if self._voice_on else t["voice_off"])
        self._theme_btn.configure(fg_color=t["border"], hover_color=t["mic_hover"], text_color=t["text_muted"])

        # chat
        self._chat.configure(fg_color="transparent", scrollbar_button_color=t["scrollbar"], scrollbar_button_hover_color=t["accent"])
        
        for b in self._bubbles:
            b.update_theme(t)
            
        # update welcome screen if visible by rebuilding it
        if hasattr(self, "welcome_screen") and self.welcome_screen:
            self._build_welcome_screen()

        # footer
        self._ftr_wrap.configure(fg_color=t["border"])
        self._ftr.configure(fg_color=t["bg_header"])
        self._entry.configure(fg_color=t["bg_input"], border_color=t["border"], text_color=t["text"], placeholder_text_color=t["text_faint"])
        
        self.avatar.update_theme(t)

        if not self._mic_on:
            self._mic_btn.configure(fg_color=t["mic_idle"], hover_color=t["mic_hover"], text_color=t["text_muted"], border_color=t["border"])
        self._send_btn.configure(fg_color=t["send"], hover_color=t["send_hover"])

    def _animate_effects(self):
        """Animates Status Orb, glowing entry fields, and breathing active chatboxes."""
        t = self._t
        key = {
            "idle": "orb_idle", "listening": "orb_listen",
            "thinking": "orb_think", "speaking": "orb_speak",
        }.get(self._orb_state, "orb_idle")
        base = t[key]

        r, g, b = int(base[1:3], 16), int(base[3:5], 16), int(base[5:7], 16)

        self._orb_phase += 0.09
        if self._orb_phase > 2 * math.pi:
            self._orb_phase -= 2 * math.pi
        pulse = 0.45 + 0.55 * math.sin(self._orb_phase)

        gr = min(255, int(r * (0.35 + 0.65 * pulse)))
        gg = min(255, int(g * (0.35 + 0.65 * pulse)))
        gb = min(255, int(b * (0.35 + 0.65 * pulse)))
        glow_color = f"#{gr:02x}{gg:02x}{gb:02x}"



        # ── Breathing Border on Input Entry ──
        if self._orb_state == "thinking":
            self._entry.configure(border_color=glow_color)
        elif self._orb_state == "speaking":
            self._entry.configure(border_color=t["orb_speak"])
        else:
            if self.focus_get() != self._entry:
                self._entry.configure(border_color=t["border"])
            else:
                self._entry.configure(border_color=t["border_glow"])

        # ── Breathing FULL GLOW on ACTIVE/STREAMING Chat Bubble ──
        if self.active_bubble and self._orb_state in ("thinking", "speaking"):
            # Compute a nice dim background glow (approx 15% brightness of the active state)
            bgr = min(255, int(r * (0.12 + 0.12 * pulse)))
            bgg = min(255, int(g * (0.12 + 0.12 * pulse)))
            bgb = min(255, int(b * (0.12 + 0.12 * pulse)))
            bg_glow = f"#{bgr:02x}{bgg:02x}{bgb:02x}"
            
            # Pulse both border and background together for full block glow
            self.active_bubble.set_glow_color(border_color=glow_color, fg_color=bg_glow)
        elif self.active_bubble:
            self.active_bubble.reset_colors()

        ms = 35 if self._orb_state != "idle" else 65
        self.after(ms, self._animate_effects)

    def _hist_up(self, _):
        if self._input_hist and self._hist_idx > 0:
            self._hist_idx -= 1
            self._entry.delete(0, tk.END)
            self._entry.insert(0, self._input_hist[self._hist_idx])

    def _hist_down(self, _):
        if not self._input_hist:
            return
        if self._hist_idx < len(self._input_hist) - 1:
            self._hist_idx += 1
            self._entry.delete(0, tk.END)
            self._entry.insert(0, self._input_hist[self._hist_idx])
        else:
            self._hist_idx = len(self._input_hist)
            self._entry.delete(0, tk.END)

    def _poll(self):
        t = self._t
        while not self.gui_queue.empty():
            try:
                kind, data = self.gui_queue.get_nowait()

                if kind == "status":
                    self.set_status(data)

                elif kind == "user_voice_transcribed":
                    if self._current_page == "Home" and hasattr(self, "search_entry") and self.search_entry and self.search_entry.winfo_exists():
                        self.search_entry.delete(0, tk.END)
                        self.search_entry.insert(0, data)
                        self.search_entry.focus()
                    else:
                        self._entry.delete(0, tk.END)
                        self._entry.insert(0, data)
                        self._entry.focus()

                elif kind == "stream_start":
                    self.active_bubble = self.add_message("", is_user=False, streaming=True)
                    if self.active_bubble:
                        self.active_bubble.session_id = self._active_session_id

                elif kind == "stream_token":
                    if self.active_bubble:
                        self.active_bubble.append_text(data)
                        self._chat._parent_canvas.yview_moveto(1.0)

                elif kind == "stream_end":
                    if self.active_bubble:
                        full_text = self.active_bubble._raw_text
                        bubble_session_id = getattr(self.active_bubble, "session_id", self._active_session_id)
                        self.active_bubble.finalize()
                        self.active_bubble.reset_colors()
                        if bubble_session_id is not None and bubble_session_id in self._chat_sessions:
                            self._chat_sessions[bubble_session_id]["messages"].append({
                                "text": full_text,
                                "is_user": False
                            })
                        self.update_idletasks()
                        self._chat._parent_canvas.yview_moveto(1.0)
                        self.active_bubble = None

                elif kind == "mic_active":
                    self._mic_on = True
                    self._mic_btn.configure(
                        fg_color=t["mic_rec"],
                        hover_color=t["mic_rec_hover"],
                        text_color="#FFFFFF",
                        border_color=t["mic_rec"],
                    )
                    if hasattr(self, "welcome_mic_lbl") and self.welcome_mic_lbl and self.welcome_mic_lbl.winfo_exists():
                        self.welcome_mic_lbl.configure(text_color=t["border_glow"])
                    if hasattr(self, "search_frame") and self.search_frame and self.search_frame.winfo_exists():
                        self.search_frame.configure(border_color=t["border_glow"], border_width=2)

                elif kind == "mic_inactive":
                    self._mic_on = False
                    self._mic_btn.configure(
                        fg_color=t["mic_idle"],
                        hover_color=t["mic_hover"],
                        text_color=t["text_muted"],
                        border_color=t["border"],
                    )
                    if hasattr(self, "welcome_mic_lbl") and self.welcome_mic_lbl and self.welcome_mic_lbl.winfo_exists():
                        self.welcome_mic_lbl.configure(text_color=t["text_muted"])
                    if hasattr(self, "search_frame") and self.search_frame and self.search_frame.winfo_exists():
                        self.search_frame.configure(border_color=t["border"], border_width=1)

                self.gui_queue.task_done()
            except queue.Empty:
                break

        self.after(50, self._poll)

    def _on_close(self):
        self.cmd_queue.put(("exit", None))
        self.destroy()
