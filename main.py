import json
import os
import re
import threading
import tkinter as tk
from tkinter import messagebox, filedialog
from datetime import datetime
import requests

API_URL = "http://127.0.0.1:8000"
WINDOW_TITLE = "SharpAI"

LIGHT = dict(
    bg="#FFFFFF", black="#000000", text="#111111", muted="#666666",
    light="#F2F2F2", border="#D0D0D0", bubble_user="#000000",
    bubble_ai="#F2F2F2", user_fg="#FFFFFF", ai_fg="#111111",
    code_bg="#2B2B2B", code_fg="#F2F2F2", accent="#000000",
    online="#1FA34A", offline="#C0392B", thinking="#E0A800",
)
DARK = dict(
    bg="#181818", black="#F2F2F2", text="#EDEDED", muted="#999999",
    light="#262626", border="#3A3A3A", bubble_user="#F2F2F2",
    bubble_ai="#262626", user_fg="#111111", ai_fg="#EDEDED",
    code_bg="#0F0F0F", code_fg="#F2F2F2", accent="#F2F2F2",
    online="#3DDC84", offline="#FF6B6B", thinking="#FFC94D",
)

# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

INLINE_PATTERN = re.compile(
    r'(?P<bolditalic>\*\*\*(?P<bi_text>.+?)\*\*\*)'
    r'|(?P<bold>\*\*(?P<b_text>.+?)\*\*)'
    r'|(?P<italic>\*(?P<i_text>.+?)\*)'
    r'|(?P<code>`(?P<c_text>[^`]+?)`)'
)
HEADER_PATTERN = re.compile(r'^(#{1,6})\s+(.*)$')
BULLET_PATTERN = re.compile(r'^(\s*)[-*]\s+(.*)$')
CODEBLOCK_PATTERN = re.compile(r'```.*?```', re.DOTALL)


def configure_markdown_tags(tw, theme, base_size=11):
    tw.tag_configure("bold", font=("Arial", base_size, "bold"))
    tw.tag_configure("italic", font=("Arial", base_size, "italic"))
    tw.tag_configure("bold_italic", font=("Arial", base_size, "bold italic"))
    tw.tag_configure(
        "code_inline", font=("Consolas", base_size - 1),
        background=theme["border"], foreground=tw.cget("fg")
    )
    tw.tag_configure(
        "code_block", font=("Consolas", base_size - 1),
        background=theme["code_bg"], foreground=theme["code_fg"],
        spacing1=8, spacing3=8, lmargin1=10, lmargin2=10,
        rmargin=10, wrap="none"
    )
    tw.tag_configure("h1", font=("Arial", base_size + 6, "bold"), spacing1=4, spacing3=4)
    tw.tag_configure("h2", font=("Arial", base_size + 3, "bold"), spacing1=3, spacing3=3)
    tw.tag_configure("h3", font=("Arial", base_size + 1, "bold"), spacing1=2, spacing3=2)
    for t in ("bold", "italic", "bold_italic", "code_inline", "h3", "h2", "h1"):
        tw.tag_raise(t)


def _insert_inline(tw, line, extra_tags=()):
    pos = 0
    for m in INLINE_PATTERN.finditer(line):
        if m.start() > pos:
            tw.insert("end", line[pos:m.start()], extra_tags)
        if m.group("bolditalic"):
            tw.insert("end", m.group("bi_text"), extra_tags + ("bold_italic",))
        elif m.group("bold"):
            tw.insert("end", m.group("b_text"), extra_tags + ("bold",))
        elif m.group("italic"):
            tw.insert("end", m.group("i_text"), extra_tags + ("italic",))
        elif m.group("code"):
            tw.insert("end", m.group("c_text"), extra_tags + ("code_inline",))
        pos = m.end()
    if pos < len(line):
        tw.insert("end", line[pos:], extra_tags)


def render_markdown(tw, content):
    tw.config(state="normal")
    tw.delete("1.0", "end")
    segments = re.split(f'({CODEBLOCK_PATTERN.pattern})', content, flags=re.DOTALL)

    for seg in segments:
        if not seg:
            continue
        if seg.startswith("```") and seg.endswith("```"):
            inner = seg[3:-3]
            lines = inner.split("\n")
            if lines and lines[0].strip() and re.match(r'^\w+$', lines[0].strip()):
                lines = lines[1:]
            code_text = "\n".join(lines).strip("\n")
            if tw.index("end-1c") != "1.0":
                tw.insert("end", "\n")
            tw.insert("end", code_text + "\n", ("code_block",))
            continue

        lines = seg.split("\n")
        for i, line in enumerate(lines):
            header_match = HEADER_PATTERN.match(line)
            bullet_match = BULLET_PATTERN.match(line)
            if header_match:
                level = min(len(header_match.group(1)), 3)
                _insert_inline(tw, header_match.group(2), (f"h{level}",))
            elif bullet_match:
                tw.insert("end", bullet_match.group(1) + "• ")
                _insert_inline(tw, bullet_match.group(2))
            else:
                _insert_inline(tw, line)
            if i < len(lines) - 1:
                tw.insert("end", "\n")

    tw.config(state="disabled")


def autosize_text_widget(tw, min_height=1):
    tw.update_idletasks()
    try:
        result = tw.count("1.0", "end", "displaylines")
        lines = result[0] if result else min_height
    except (tk.TclError, TypeError):
        lines = int(tw.index("end-1c").split(".")[0])
    tw.config(height=max(lines, min_height))


class MarkdownText(tk.Text):
    def __init__(self, master, theme, bg, fg, **kwargs):
        super().__init__(
            master, wrap="word", bd=0, highlightthickness=0,
            bg=bg, fg=fg, font=("Arial", 11), padx=14, pady=12,
            cursor="arrow", **kwargs
        )
        configure_markdown_tags(self, theme)
        self.config(state="disabled")

    def set_content(self, content):
        render_markdown(self, content)
        autosize_text_widget(self)


# ---------------------------------------------------------------------------
# Small animation helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _lerp_color(c1, c2, t):
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


class Animator:
    """Coalesced animation driver: one after()-loop per animation."""

    EASE = staticmethod(lambda t: 1 - (1 - t) ** 3)  # ease-out cubic

    def __init__(self, widget):
        self.widget = widget

    def run(self, duration_ms, on_step, on_done=None, fps=60):
        steps = max(1, int(duration_ms / (1000 / fps)))
        interval = max(1, duration_ms // steps)

        def tick(i=0):
            if not self.widget.winfo_exists():
                return
            t = self.EASE(min(1.0, i / steps))
            on_step(t)
            if i < steps:
                self.widget.after(interval, tick, i + 1)
            elif on_done:
                on_done()

        tick()


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class SharpAIApp:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1020x740")
        self.root.minsize(700, 500)

        self.theme = LIGHT
        self.dark_mode = False
        self.root.configure(bg=self.theme["bg"])

        self.messages = []          # API-format history: [{role, content}]
        self.bubbles = []           # UI metadata for redraw on theme change
        self.waiting = False
        self.cancel_event = None
        self.stream_buffer = ""
        self.stream_dirty = False
        self.pinned_to_bottom = True

        self._resize_job = None

        self.build_ui()
        self.add_message(
            "assistant",
            "Hey! I'm SharpAI.\n\n"
            "You can talk to me freely about whatever you want. "
            "Ask questions, brainstorm, write code, learn something, "
            "or just have a normal conversation."
        )
        self.root.after(300, self.check_api)
        self.root.after(50, self._stream_flush_loop)

    # ------------------------------------------------------------------ UI

    def build_ui(self):
        th = self.theme

        self.top = tk.Frame(self.root, bg=th["bg"], height=62)
        self.top.pack(fill="x")
        self.top.pack_propagate(False)

        self.title_lbl = tk.Label(
            self.top, text="SharpAI", font=("Arial", 20, "bold"),
            bg=th["bg"], fg=th["black"]
        )
        self.title_lbl.pack(side="left", padx=22)

        self.status_dot = tk.Canvas(
            self.top, width=10, height=10, bg=th["bg"],
            highlightthickness=0
        )
        self.status_dot.pack(side="left", padx=(4, 4))
        self._dot_id = self.status_dot.create_oval(1, 1, 9, 9, fill=th["muted"], outline="")
        self._dot_phase = 0
        self._dot_pulsing = False

        self.status = tk.Label(
            self.top, text="CONNECTING", font=("Arial", 8, "bold"),
            bg=th["bg"], fg=th["muted"]
        )
        self.status.pack(side="left", padx=4)

        self.word_count_lbl = tk.Label(
            self.top, text="", font=("Arial", 8), bg=th["bg"], fg=th["muted"]
        )
        self.word_count_lbl.pack(side="left", padx=14)

        self.clear_btn = self._make_button(self.top, "CLEAR", self.clear_chat)
        self.clear_btn.pack(side="right", padx=(0, 22))

        self.export_btn = self._make_button(self.top, "EXPORT", self.export_chat)
        self.export_btn.pack(side="right", padx=(0, 10))

        self.theme_btn = self._make_button(self.top, "DARK MODE", self.toggle_theme)
        self.theme_btn.pack(side="right", padx=(0, 10))

        self.divider1 = tk.Frame(self.root, bg=th["black"], height=1)
        self.divider1.pack(fill="x")

        chat = tk.Frame(self.root, bg=th["bg"])
        chat.pack(fill="both", expand=True)
        self.chat_frame = chat

        self.canvas = tk.Canvas(chat, bg=th["bg"], highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(
            chat, orient="vertical", command=self.canvas.yview,
            width=12, bd=0, relief="flat"
        )
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self._on_scrollbar)

        self.messages_frame = tk.Frame(self.canvas, bg=th["bg"])
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.messages_frame, anchor="nw"
        )
        self.messages_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

        # Floating "scroll to bottom" pill, hidden until needed
        self.scroll_btn = tk.Label(
            chat, text="↓ New", font=("Arial", 9, "bold"),
            bg=th["black"], fg=th["bg"], padx=10, pady=4, cursor="hand2"
        )
        self.scroll_btn.bind("<Button-1>", lambda e: self.smooth_scroll_to_bottom(force=True))
        self._scroll_btn_visible = False

        self.divider2 = tk.Frame(self.root, bg=th["black"], height=1)
        self.divider2.pack(fill="x")

        bottom = tk.Frame(self.root, bg=th["bg"], height=92)
        bottom.pack(fill="x")
        bottom.pack_propagate(False)
        self.bottom_frame = bottom

        self.input = tk.Text(
            bottom, height=3, wrap="word", font=("Arial", 11),
            bg=th["bg"], fg=th["text"], insertbackground=th["black"],
            selectbackground=th["black"], selectforeground=th["bg"],
            relief="solid", bd=1, highlightthickness=0, padx=12, pady=10
        )
        self.input.pack(side="left", fill="both", expand=True, padx=(18, 8), pady=14)
        self.input.bind("<Return>", self.on_enter)
        self.input.bind("<KeyRelease>", self._on_input_change)

        self.send = self._make_button(
            bottom, "SEND", self.send_message, primary=True
        )
        self.send.pack(side="right", fill="y", padx=(0, 18), pady=14)

    def _make_button(self, parent, text, command, primary=False):
        th = self.theme
        bg = th["black"] if primary else th["bg"]
        fg = th["bg"] if primary else th["black"]
        btn = tk.Button(
            parent, text=text, command=command, font=("Arial", 9, "bold"),
            bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
            relief="solid", bd=1, padx=15, pady=7, cursor="hand2"
        )
        btn._primary = primary
        btn.bind("<Enter>", lambda e: self._hover(btn, True))
        btn.bind("<Leave>", lambda e: self._hover(btn, False))
        return btn

    def _hover(self, btn, entering):
        th = self.theme
        if btn._primary:
            btn.config(bg="#333333" if not self.dark_mode else "#CCCCCC")
        else:
            btn.config(bg=th["light"] if entering else th["bg"])

    # ------------------------------------------------------------ scrolling

    def _on_frame_configure(self, e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self.pinned_to_bottom:
            self.canvas.yview_moveto(1.0)

    def _on_canvas_configure(self, e):
        self.canvas.itemconfigure(self.canvas_window, width=e.width)
        # Debounce bubble re-wrap on resize instead of recalculating every pixel
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self._reflow_bubbles)

    def _reflow_bubbles(self):
        width = max(300, self.canvas.winfo_width() - 90)
        for meta in self.bubbles:
            meta["md"].config(width=max(40, width // 8))

    def _on_scrollbar(self, first, last):
        self.scrollbar.set(first, last)
        at_bottom = float(last) > 0.995
        self.pinned_to_bottom = at_bottom
        self._toggle_scroll_btn(not at_bottom)

    def on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _toggle_scroll_btn(self, show):
        if show and not self._scroll_btn_visible:
            self.scroll_btn.place(relx=0.5, rely=0.95, anchor="center")
            self._scroll_btn_visible = True
        elif not show and self._scroll_btn_visible:
            self.scroll_btn.place_forget()
            self._scroll_btn_visible = False

    def smooth_scroll_to_bottom(self, force=False):
        if not (self.pinned_to_bottom or force):
            return
        self.pinned_to_bottom = True
        self._toggle_scroll_btn(False)
        start = self.canvas.yview()[0]
        end = 1.0
        Animator(self.canvas).run(
            220, lambda t: self.canvas.yview_moveto(start + (end - start) * t)
        )

    # ------------------------------------------------------------- bubbles

    def add_message(self, role, text, animate=True):
        th = self.theme
        row = tk.Frame(self.messages_frame, bg=th["bg"])
        row.pack(fill="x", padx=28, pady=(12, 4))

        header = tk.Frame(row, bg=th["bg"])
        header.pack(fill="x", pady=(0, 5))

        label = "YOU" if role == "user" else "SHARPAI"
        label_fg = th["muted"] if role == "user" else th["black"]
        role_lbl = tk.Label(
            header, text=label, font=("Arial", 8, "bold"),
            bg=th["bg"], fg=label_fg, anchor="w"
        )
        role_lbl.pack(side="left")

        time_lbl = tk.Label(
            header, text=datetime.now().strftime("%H:%M"),
            font=("Arial", 8), bg=th["bg"], fg=th["muted"]
        )
        time_lbl.pack(side="left", padx=(6, 0))

        copy_lbl = tk.Label(
            header, text="copy", font=("Arial", 8, "underline"),
            bg=th["bg"], fg=th["muted"], cursor="hand2"
        )
        copy_lbl.pack(side="left", padx=(10, 0))
        copy_lbl.bind("<Button-1>", lambda e: self.copy_to_clipboard(text, copy_lbl))

        bubble_wrap = tk.Frame(row, bg=th["bg"])
        bubble_wrap.pack(anchor="e" if role == "user" else "w")

        bg = th["bubble_user"] if role == "user" else th["bubble_ai"]
        fg = th["user_fg"] if role == "user" else th["ai_fg"]
        md = MarkdownText(bubble_wrap, th, bg, fg, width=68)
        md.pack()
        md.set_content(text)

        meta = dict(role=role, text=text, row=row, md=md, bg=bg, fg=fg,
                    role_lbl=role_lbl, time_lbl=time_lbl, copy_lbl=copy_lbl,
                    header=header, bubble_wrap=bubble_wrap)
        self.bubbles.append(meta)

        if animate:
            self._fade_in(md, bg, fg)
        self.root.after(20, self.smooth_scroll_to_bottom)
        self._update_word_count()

    def _fade_in(self, md_widget, bg, fg):
        md_widget.config(state="normal")
        Animator(md_widget).run(
            200,
            lambda t: md_widget.config(fg=_lerp_color(bg, fg, t)),
            on_done=lambda: md_widget.config(state="disabled")
        )

    def copy_to_clipboard(self, text, label):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        original = label.cget("text")
        label.config(text="copied!")
        self.root.after(1200, lambda: label.winfo_exists() and label.config(text=original))

    def _update_word_count(self):
        words = sum(len(m["content"].split()) for m in self.messages)
        self.word_count_lbl.config(text=f"{len(self.messages)} msgs · {words} words")

    # ------------------------------------------------------------- typing

    def show_typing_indicator(self):
        th = self.theme
        self.typing_row = tk.Frame(self.messages_frame, bg=th["bg"])
        self.typing_row.pack(fill="x", padx=28, pady=(12, 4))
        tk.Label(
            self.typing_row, text="SHARPAI", font=("Arial", 8, "bold"),
            bg=th["bg"], fg=th["black"], anchor="w"
        ).pack(fill="x", pady=(0, 5))

        bubble = tk.Frame(self.typing_row, bg=th["bubble_ai"], padx=16, pady=12)
        bubble.pack(anchor="w")
        self.dot_canvas = tk.Canvas(
            bubble, width=40, height=14, bg=th["bubble_ai"], highlightthickness=0
        )
        self.dot_canvas.pack()
        self._dots = [
            self.dot_canvas.create_oval(4 + i * 14, 4, 12 + i * 14, 12,
                                         fill=th["muted"], outline="")
            for i in range(3)
        ]
        self._typing_active = True
        self._animate_typing_dots(0)
        self.root.after(20, self.smooth_scroll_to_bottom)

    def _animate_typing_dots(self, frame):
        if not getattr(self, "_typing_active", False) or not self.dot_canvas.winfo_exists():
            return
        import math
        for i, dot in enumerate(self._dots):
            offset = math.sin((frame + i * 6) / 8) * 3
            coords = self.dot_canvas.coords(dot)
            self.dot_canvas.move(dot, 0, offset - getattr(self, f"_last_offset_{i}", 0))
            setattr(self, f"_last_offset_{i}", offset)
        self.root.after(45, self._animate_typing_dots, frame + 1)

    def hide_typing_indicator(self):
        self._typing_active = False
        if hasattr(self, "typing_row") and self.typing_row.winfo_exists():
            self.typing_row.destroy()

    # ------------------------------------------------------------- sending

    def _on_input_change(self, event):
        pass  # reserved for live char-count / slash-command hooks

    def on_enter(self, event):
        if event.state & 0x0001:
            return
        self.send_message()
        return "break"

    def send_message(self):
        if self.waiting:
            return
        text = self.input.get("1.0", "end-1c").strip()
        if not text:
            return
        self.input.delete("1.0", "end")
        self._dispatch(text)

    def _dispatch(self, text):
        self.add_message("user", text)
        self.messages.append({"role": "user", "content": text})

        self.waiting = True
        self.pinned_to_bottom = True
        self.status.config(text="THINKING...")
        self._set_dot_color(self.theme["thinking"], pulse=True)
        self.send.config(text="STOP", command=self.stop_generation)
        self.show_typing_indicator()

        self.cancel_event = threading.Event()
        self.stream_buffer = ""
        self.stream_dirty = False
        threading.Thread(target=self.request_ai, args=(self.cancel_event,), daemon=True).start()

    def stop_generation(self):
        if self.cancel_event:
            self.cancel_event.set()

    def regenerate_last(self):
        if self.waiting or not self.messages:
            return
        # drop trailing assistant reply, resend the last user turn
        while self.messages and self.messages[-1]["role"] == "assistant":
            self.messages.pop()
        if not self.messages:
            return
        last_user = self.messages[-1]["content"]
        self.messages.pop()
        for meta in self.bubbles[-2:]:
            meta["row"].destroy()
        self.bubbles = self.bubbles[:-2]
        self._dispatch(last_user)

    # -------------------------------------------------------- network / IO

    def request_ai(self, cancel_event):
        assistant_text = ""
        try:
            response = requests.post(
                API_URL + "/chat",
                json={"messages": self.messages, "stream": True},
                stream=True, timeout=300
            )
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if cancel_event.is_set():
                    response.close()
                    break
                if not line:
                    continue
                data = json.loads(line)
                if data.get("error"):
                    raise RuntimeError(data["error"])
                if data.get("done"):
                    break
                token = data.get("token", "")
                if token:
                    assistant_text += token
                    # Just buffer; a single throttled loop flushes to the UI
                    self.stream_buffer = assistant_text
                    self.stream_dirty = True

            self.root.after(0, self.finish_response, assistant_text, cancel_event.is_set())

        except Exception as exc:
            self.root.after(0, self.receive_error, str(exc))

    def _stream_flush_loop(self):
        """Single periodic UI update instead of one after() call per token —
        keeps the GUI responsive even at very high token rates."""
        if self.stream_dirty and self.waiting:
            self.stream_dirty = False
            self.update_stream(self.stream_buffer)
        self.root.after(40, self._stream_flush_loop)

    def update_stream(self, text):
        if hasattr(self, "stream_label") and self.stream_label.winfo_exists():
            self.stream_label.config(text=text)
        else:
            self.hide_typing_indicator()
            self.create_stream_bubble(text)
        if self.pinned_to_bottom:
            self.canvas.yview_moveto(1.0)

    def create_stream_bubble(self, text):
        th = self.theme
        self.stream_row = tk.Frame(self.messages_frame, bg=th["bg"])
        self.stream_row.pack(fill="x", padx=28, pady=(12, 4))
        tk.Label(
            self.stream_row, text="SHARPAI", font=("Arial", 8, "bold"),
            bg=th["bg"], fg=th["black"], anchor="w"
        ).pack(fill="x", pady=(0, 5))
        self.stream_label = tk.Label(
            self.stream_row, text=text, font=("Arial", 11),
            bg=th["bubble_ai"], fg=th["ai_fg"], justify="left",
            anchor="w", wraplength=760, padx=14, pady=12
        )
        self.stream_label.pack(anchor="w")

    def finish_response(self, text, was_cancelled):
        self.hide_typing_indicator()
        if hasattr(self, "stream_row") and self.stream_row.winfo_exists():
            self.stream_row.destroy()
            del self.stream_label

        if text.strip():
            self.messages.append({"role": "assistant", "content": text})
            self.add_message("assistant", text + ("  *(stopped)*" if was_cancelled else ""))

        self.waiting = False
        self.status.config(text="READY")
        self._set_dot_color(self.theme["online"], pulse=False)
        self.send.config(text="SEND", command=self.send_message, state="normal")
        self.input.focus_set()

    def receive_error(self, error):
        self.hide_typing_indicator()
        if hasattr(self, "stream_row") and self.stream_row.winfo_exists():
            self.stream_row.destroy()
        self.add_message(
            "assistant",
            "I couldn't connect to the SharpAI server.\n\n" + error +
            "\n\nMake sure Ollama is installed, the model is downloaded, "
            "and api.py is running."
        )
        self.waiting = False
        self.status.config(text="ERROR")
        self._set_dot_color(self.theme["offline"], pulse=False)
        self.send.config(text="SEND", command=self.send_message, state="normal")

    # ------------------------------------------------------------- chat mgmt

    def clear_chat(self):
        if self.waiting:
            return
        if not messagebox.askyesno("Clear Chat", "Clear the current conversation?"):
            return
        self.messages.clear()
        self.bubbles.clear()
        for widget in self.messages_frame.winfo_children():
            widget.destroy()
        self.add_message("assistant", "Chat cleared. I'm ready for a new conversation.")

    def export_chat(self):
        if not self.messages:
            messagebox.showinfo("Export", "Nothing to export yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("JSON", "*.json")],
            initialfile="sharpai_chat"
        )
        if not path:
            return
        try:
            if path.endswith(".json"):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.messages, f, indent=2)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    for m in self.messages:
                        f.write(f"[{m['role'].upper()}]\n{m['content']}\n\n")
            messagebox.showinfo("Export", f"Saved to {os.path.basename(path)}")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    # --------------------------------------------------------------- theme

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.theme = DARK if self.dark_mode else LIGHT
        self.theme_btn.config(text="LIGHT MODE" if self.dark_mode else "DARK MODE")
        self._apply_theme_colors()
        self._redraw_all_bubbles()

    def _apply_theme_colors(self):
        th = self.theme
        self.root.configure(bg=th["bg"])
        self.top.configure(bg=th["bg"])
        self.title_lbl.configure(bg=th["bg"], fg=th["black"])
        self.status.configure(bg=th["bg"], fg=th["muted"])
        self.status_dot.configure(bg=th["bg"])
        self.word_count_lbl.configure(bg=th["bg"], fg=th["muted"])
        self.divider1.configure(bg=th["black"])
        self.divider2.configure(bg=th["black"])
        self.chat_frame.configure(bg=th["bg"])
        self.canvas.configure(bg=th["bg"])
        self.messages_frame.configure(bg=th["bg"])
        self.bottom_frame.configure(bg=th["bg"])
        self.input.configure(
            bg=th["bg"], fg=th["text"], insertbackground=th["black"],
            selectbackground=th["black"], selectforeground=th["bg"]
        )
        self.scroll_btn.configure(bg=th["black"], fg=th["bg"])
        for btn in (self.clear_btn, self.export_btn, self.theme_btn):
            btn.configure(bg=th["bg"], fg=th["black"],
                          activebackground=th["bg"], activeforeground=th["black"])
        self.send.configure(bg=th["black"], fg=th["bg"],
                             activebackground=th["black"], activeforeground=th["bg"])

    def _redraw_all_bubbles(self):
        for widget in self.messages_frame.winfo_children():
            widget.destroy()
        self.bubbles.clear()
        saved = list(self.messages)
        # rebuild without re-appending to history
        for m in saved:
            self.add_message(m["role"], m["content"], animate=False)
        self.messages = saved

    # --------------------------------------------------------------- status

    def _set_dot_color(self, color, pulse):
        self._dot_pulsing = pulse
        self.status_dot.itemconfig(self._dot_id, fill=color)
        if pulse:
            self._pulse_dot(color, 0)

    def _pulse_dot(self, color, phase):
        if not self._dot_pulsing or not self.status_dot.winfo_exists():
            return
        import math
        r = 3 + math.sin(phase / 6) * 1.5
        cx, cy = 5, 5
        self.status_dot.coords(self._dot_id, cx - r, cy - r, cx + r, cy + r)
        self.root.after(60, self._pulse_dot, color, phase + 1)

    def check_api(self):
        try:
            r = requests.get(API_URL + "/health", timeout=3)
            online = r.ok
        except requests.RequestException:
            online = False

        if not self.waiting:
            if online:
                self.status.config(text="ONLINE")
                self._set_dot_color(self.theme["online"], pulse=False)
            else:
                self.status.config(text="OFFLINE")
                self._set_dot_color(self.theme["offline"], pulse=False)

        self.root.after(5000, self.check_api)


def main():
    root = tk.Tk()
    SharpAIApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
