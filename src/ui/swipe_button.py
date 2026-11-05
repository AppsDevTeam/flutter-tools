# src/ui/swipe_button.py
import sys
import tkinter as tk
from tkinter import ttk, font as tkfont


class SwipeButton(tk.Canvas):
    """
    Tlačítko, které se spustí až dotažením knoflíku doprava — pro akce, které se
    nesmí spustit omylem (přerušení buildu). Puštění před koncem knoflík vrátí.
    """

    _TRACK_COLOR = "#D32F2F"
    _BUSY_COLOR = "#8E2424"
    _LOCKED_COLOR = "#9E9E9E"
    _KNOB_COLOR = "#FFFFFF"
    _TEXT_COLOR = "#FFFFFF"
    # Podíl dráhy, od kterého se tažení počítá jako dokončené.
    _TRIGGER_RATIO = 0.85
    _KNOB_PAD = 3
    _ANIMATION_STEP_MS = 10

    def __init__(self, parent, text, command, width=200, height=28):
        super().__init__(
            parent, width=width, height=height, highlightthickness=0, bd=0,
            bg=self._parent_background(), cursor="arrow",
        )
        self._text = text
        self._command = command
        self._width = width
        self._height = height
        self._knob_size = height - 2 * self._KNOB_PAD
        self._min_x = self._KNOB_PAD
        self._max_x = width - self._KNOB_PAD - self._knob_size
        self._knob_x = self._min_x
        self._drag_offset = None
        self._enabled = True
        self._animation = None

        base_font = tkfont.nametofont("TkDefaultFont")
        self._label_font = base_font.copy()
        self._label_font.configure(weight="bold")
        self._knob_font = base_font.copy()
        self._knob_font.configure(weight="bold", size=14)

        self.tag_bind("knob", "<ButtonPress-1>", self._on_press)
        self.tag_bind("knob", "<Enter>", lambda e: self._enabled and self.config(cursor="hand2"))
        self.tag_bind("knob", "<Leave>", lambda e: self.config(cursor="arrow"))
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

        self.reset()

    def reset(self, text=None):
        """Výchozí stav: knoflík vlevo, tažením jde akci spustit."""
        if text is not None:
            self._text = text
        self._stop_animation()
        self._enabled = True
        self._knob_x = self._min_x
        self._redraw(self._TRACK_COLOR, f"{self._text}  ›››", show_knob=True, text_area=(self._min_x + self._knob_size, self._width))

    def set_busy(self, text):
        """Akce běží: knoflík zůstane vpravo a nejde s ním hýbat."""
        self._stop_animation()
        self._enabled = False
        self._knob_x = self._max_x
        self._redraw(self._BUSY_COLOR, text, show_knob=True, text_area=(0, self._max_x))

    def set_locked(self, text):
        """Akci už nejde spustit: šedá dráha bez knoflíku."""
        self._stop_animation()
        self._enabled = False
        self._drag_offset = None
        self._redraw(self._LOCKED_COLOR, text, show_knob=False, text_area=(0, self._width))

    def _parent_background(self):
        background = ttk.Style().lookup("TFrame", "background")
        if background:
            return background
        return "systemWindowBackgroundColor" if sys.platform == "darwin" else "#F0F0F0"

    def _redraw(self, track_color, label, show_knob, text_area):
        self.delete("all")
        h = self._height
        w = self._width
        # Dráha ve tvaru pilulky: dva půlkruhy a obdélník mezi nimi
        self.create_oval(0, 0, h, h, fill=track_color, outline="")
        self.create_oval(w - h, 0, w, h, fill=track_color, outline="")
        self.create_rectangle(h / 2, 0, w - h / 2, h, fill=track_color, outline="")

        # Text je vycentrovaný na části dráhy, kterou knoflík v daném stavu nezakrývá
        text_left, text_right = text_area
        self.create_text(
            (text_left + text_right) / 2, h / 2, text=label, fill=self._TEXT_COLOR, font=self._label_font
        )

        if show_knob:
            x = self._knob_x
            y = self._KNOB_PAD
            size = self._knob_size
            self.create_oval(x, y, x + size, y + size, fill=self._KNOB_COLOR, outline="", tags="knob")
            self.create_text(
                x + size / 2, y + size / 2 - 1, text="›", fill=track_color,
                font=self._knob_font, tags="knob"
            )

    def _move_knob_to(self, x):
        x = max(self._min_x, min(self._max_x, x))
        self.move("knob", x - self._knob_x, 0)
        self._knob_x = x

    def _on_press(self, event):
        if not self._enabled:
            return
        self._stop_animation()
        self._drag_offset = event.x - self._knob_x

    def _on_drag(self, event):
        if self._drag_offset is None:
            return
        self._move_knob_to(event.x - self._drag_offset)

    def _on_release(self, event):
        if self._drag_offset is None:
            return
        self._drag_offset = None
        travel = self._max_x - self._min_x
        if travel > 0 and (self._knob_x - self._min_x) / travel >= self._TRIGGER_RATIO:
            self._move_knob_to(self._max_x)
            self._command()
        else:
            self._animate_back()

    def _animate_back(self):
        """Knoflík puštěný před koncem odjede zpět doleva."""
        if self._knob_x <= self._min_x:
            self._animation = None
            return
        step = max(4, (self._knob_x - self._min_x) / 4)
        self._move_knob_to(self._knob_x - step)
        self._animation = self.after(self._ANIMATION_STEP_MS, self._animate_back)

    def _stop_animation(self):
        if self._animation is not None:
            self.after_cancel(self._animation)
            self._animation = None
