"""Finestra di configurazione (tkinter). Salva le impostazioni utente; l'app le ricarica a caldo.

Avvio: ``python -m hand_controller.config_ui``, ``hand-controller --settings`` oppure il pulsante
"config" nell'overlay.
"""
from __future__ import annotations

import copy
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import yaml

from .actions import (ACTION_TYPES, APP_ACTIONS, MOUSE_ACTIONS, PAD_ACTIONS, describe_action,
                      validate_action)
from .backends import BUTTONS, TRIGGERS
from .config import (CONFIG_WINDOW_TITLE, deep_merge, diff_config, load_config,
                     load_default_config, reset_user_config, save_user_config, user_config_path)
from .custom_gestures import POSE_PRESETS, describe_pose
from .gestures import FINGERS

NONE = "— nessuno —"
MODE_LABELS = {"mouse": "Mouse", "gamepad": "Gamepad", "paused": "In pausa"}
FINGER_LABELS = {"thumb": "Pollice", "index": "Indice", "middle": "Medio", "ring": "Anulare",
                 "pinky": "Mignolo"}
PINCH_FINGERS = ("index", "middle", "ring", "pinky")
FINGER_STATE = {"up": "teso", "down": "piegato", "any": "indifferente"}
GESTURE_HANDS = {"any": "Qualsiasi", "Right": "Destra", "Left": "Sinistra"}
PAD_CHOICES = {None: NONE, **{b: b for b in tuple(BUTTONS) + tuple(TRIGGERS)}}


# ---- widget di supporto ------------------------------------------------------------------------
class Tooltip:
    """Spiegazione che compare passando col mouse sopra un widget."""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text, self.tip, self._after = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._after = self.widget.after(450, self._show)

    def _show(self):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", background="#ffffe0", relief="solid",
                 borderwidth=1, wraplength=420, padx=6, pady=4).pack()

    def _hide(self, _=None):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


class ScrollFrame(ttk.Frame):
    """Frame con barra di scorrimento verticale (e rotellina del mouse)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(12, 10))
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, e):
        if not self.winfo_ismapped():
            return
        w = self.winfo_containing(e.x_root, e.y_root)
        while w is not None:
            if w is self:
                self.canvas.yview_scroll(int(-e.delta / 120), "units")
                return
            w = w.master


class Field:
    """Collega un widget a un percorso nella configurazione, es. ("mouse", "anchor", "span")."""

    def __init__(self, path: tuple, get, set_):
        self.path, self.get, self.set = path, get, set_


def _get_path(cfg: dict, path: tuple):
    for p in path:
        cfg = cfg[p]
    return cfg


def _set_path(cfg: dict, path: tuple, value) -> None:
    for p in path[:-1]:
        cfg = cfg.setdefault(p, {})
    cfg[path[-1]] = value


# ---- finestra principale -----------------------------------------------------------------------
class ConfigUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.fields: list[Field] = []
        self.cfg = load_config()                 # default + impostazioni utente (no profilo)
        self.gestures: list[dict] = copy.deepcopy(self.cfg.get("custom_gestures", []))

        root.title(CONFIG_WINDOW_TITLE)
        inch = root.winfo_fpixels("1i")
        w, h = int(inch * 7.6), int(inch * 7.2)
        x = (root.winfo_screenwidth() - w) // 2
        y = max(0, (root.winfo_screenheight() - h) // 2 - int(inch * 0.3))
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(int(inch * 6), int(inch * 5))

        style = ttk.Style()
        style.configure("Help.TLabel", foreground="#555555")
        style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"))

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self._tab_general()
        self._tab_mouse()
        self._tab_gamepad()
        self._tab_gestures()
        self._tab_audio()
        self._tab_recognition()
        self._tab_camera()
        self._tab_overlay()
        self._buttons()
        self._load_widgets(self.cfg)
        root.protocol("WM_DELETE_WINDOW", self.close)

    # ---- costruzione dei campi --------------------------------------------------------------
    def _tab(self, title: str, intro: str) -> ttk.Frame:
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text=title)
        sf.inner.columnconfigure(1, weight=1)
        ttk.Label(sf.inner, text=intro, style="Help.TLabel", wraplength=600,
                  justify="left").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        sf.inner._row = 1
        return sf.inner

    def _section(self, parent, title: str) -> None:
        r = parent._row
        ttk.Label(parent, text=title, style="Section.TLabel").grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(12, 4))
        ttk.Separator(parent).grid(row=r + 1, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        parent._row += 2

    def _row(self, parent, label: str, widget: tk.Widget, help_: str = "", extra=None):
        r = parent._row
        lbl = ttk.Label(parent, text=label)
        lbl.grid(row=r, column=0, sticky="w", padx=(0, 12), pady=3)
        widget.grid(row=r, column=1, sticky="w", pady=3)
        if extra is not None:
            extra.grid(row=r, column=2, sticky="w", padx=6)
        if help_:
            Tooltip(lbl, help_)
            Tooltip(widget, help_)
        parent._row += 1

    def num(self, parent, path, label, lo, hi, step, help_="", integer=False, nullable=False):
        var = tk.StringVar()
        sb = ttk.Spinbox(parent, from_=lo, to=hi, increment=step, textvariable=var, width=10)

        def get():
            s = var.get().strip().replace(",", ".")
            if s == "" and nullable:
                return None
            try:
                v = float(s)
            except ValueError:
                raise ValueError(f"«{label}»: valore non valido ({s!r})")
            if not lo <= v <= hi:
                raise ValueError(f"«{label}»: deve essere tra {lo} e {hi}")
            return int(round(v)) if integer else round(v, 4)

        def set_(v):
            var.set("" if v is None else (str(int(v)) if integer else f"{float(v):g}"))

        self.fields.append(Field(path, get, set_))
        hint = ttk.Label(parent, text="vuoto = automatico", style="Help.TLabel") if nullable else None
        self._row(parent, label, sb, help_, hint)

    def check(self, parent, path, label, help_=""):
        var = tk.BooleanVar()
        cb = ttk.Checkbutton(parent, variable=var)
        self.fields.append(Field(path, var.get, lambda v: var.set(bool(v))))
        self._row(parent, label, cb, help_)

    def choice(self, parent, path, label, options: dict, help_="", width=28):
        var = tk.StringVar()
        cb = ttk.Combobox(parent, textvariable=var, values=list(options.values()), state="readonly",
                          width=width)
        rev = {v: k for k, v in options.items()}
        self.fields.append(Field(path, lambda: rev.get(var.get()),
                                 lambda v: var.set(options.get(v, options.get(None, str(v))))))
        self._row(parent, label, cb, help_)

    def text(self, parent, path, label, help_="", width=30, validate=None):
        var = tk.StringVar()
        e = ttk.Entry(parent, textvariable=var, width=width)

        def get():
            v = var.get().strip()
            if validate:
                err = validate(v)
                if err:
                    raise ValueError(f"«{label}»: {err}")
            return v

        self.fields.append(Field(path, get, lambda v: var.set("" if v is None else str(v))))
        self._row(parent, label, e, help_)

    # ---- schede -----------------------------------------------------------------------------
    def _tab_general(self):
        t = self._tab("Generale", "Impostazioni di base. Passa col mouse sopra una voce per la "
                      "spiegazione. 'Applica' salva e aggiorna subito l'app in esecuzione.")
        self.choice(t, ("startup_mode",), "Modalità all'avvio", MODE_LABELS,
                    "Modalità con cui parte l'app.")
        self._section(t, "Tasti rapidi globali (funzionano anche dentro i giochi)")
        hk_help = ("Tasto o combinazione, es. f9, ctrl+f10, alt+shift+h. Lascia vuoto per "
                   "disattivarlo.")
        for key, label in (("toggle_mode", "Cambia modalità"), ("toggle_pause", "Pausa / riprendi"),
                           ("quit", "Chiudi l'app"), ("open_config", "Apri la configurazione")):
            self.text(t, ("hotkeys", key), label, hk_help, 20, validate=_validate_hotkey)

        self._section(t, "Cambio automatico mouse ↔ gamepad")
        self.check(t, ("auto_switch", "enabled"), "Attivo",
                   "Quando uno dei programmi qui sotto è in primo piano si passa al gamepad, "
                   "altrimenti al mouse.")
        box = ttk.Frame(t)
        self.games = tk.Listbox(box, height=7, width=34, activestyle="none")
        self.games.pack(side="left", fill="y")
        btns = ttk.Frame(box)
        btns.pack(side="left", padx=8, anchor="n")
        ttk.Button(btns, text="Dai programmi aperti…", command=self._pick_process).pack(fill="x")
        ttk.Button(btns, text="Aggiungi a mano…", command=self._add_game).pack(fill="x", pady=4)
        ttk.Button(btns, text="Rimuovi", command=self._remove_game).pack(fill="x")
        self._row(t, "Giochi (eseguibili)", box,
                  "Nome del file eseguibile del gioco, es. witcher3.exe.")
        self.fields.append(Field(("auto_switch", "game_processes"),
                                 lambda: list(self.games.get(0, "end")),
                                 self._set_games))

        self._section(t, "Avanzate")
        self.choice(t, ("backend", "gamepad"), "Driver gamepad",
                    {"auto": "Automatico", "vgamepad": "vgamepad (Windows)",
                     "uinput": "uinput (Linux)", "null": "Nessuno (disattivato)"},
                    "Richiede il riavvio dell'app.")
        self.choice(t, ("backend", "mouse"), "Driver mouse",
                    {"auto": "Automatico", "pynput": "pynput", "null": "Nessuno (disattivato)"},
                    "Richiede il riavvio dell'app.")

    def _tab_mouse(self):
        t = self._tab("Mouse", "Come la mano muove il cursore e cosa fanno i pinch (pollice che "
                      "tocca un dito).")
        self.choice(t, ("mouse", "hand"), "Mano", {"right": "Destra", "left": "Sinistra",
                                                   "any": "Qualsiasi"},
                    "Mano che controlla il mouse.")
        self.choice(t, ("mouse", "motion"), "Sistema di movimento",
                    {"anchor": "Centro col pugno (consigliato)", "absolute": "Rettangolo fisso"},
                    "Centro col pugno: chiudi il pugno per portare il cursore al centro dello "
                    "schermo; un rettangolo grande quanto la mano intorno a quel punto copre tutto "
                    "il monitor.\nRettangolo fisso: una zona fissa dell'inquadratura corrisponde "
                    "allo schermo.")
        self._section(t, "Centro col pugno")
        self.num(t, ("mouse", "anchor", "span"), "Grandezza area (mani)", 0.3, 4.0, 0.05,
                 "Larghezza del rettangolo di movimento in 'dimensioni mano' (dal polso alla nocca "
                 "del medio). Più piccolo = cursore più sensibile. Anche +/- nell'overlay.")
        self.num(t, ("mouse", "anchor", "recenter_curl"), "Chiusura per il pugno", 0.3, 0.95, 0.05,
                 "Quanto chiusa deve essere la mano perché il pugno ricentri (0 = aperta, 1 = "
                 "pugno stretto).")
        self.num(t, ("mouse", "anchor", "smoothing", "min_cutoff"), "Fermezza cursore", 0.05, 5.0,
                 0.05, "Più basso = cursore più fermo quando la mano è ferma (ma un po' più "
                 "'morbido').")
        self.num(t, ("mouse", "anchor", "smoothing", "beta"), "Reattività cursore", 0.0, 30.0, 0.5,
                 "Più alto = il cursore segue più rapidamente i movimenti veloci.")
        self._section(t, "Rettangolo fisso (x0, y0, x1, y1 da 0 a 1 nell'inquadratura)")
        for i, name in enumerate(("Sinistra (x0)", "Alto (y0)", "Destra (x1)", "Basso (y1)")):
            self._region_field(t, i, name)
        self._section(t, "Pinch e click")
        actions = {"left": "Click sinistro (tieni = trascina)", "right": "Click destro",
                   "middle": "Click centrale", "double": "Doppio click",
                   "scroll": "Scroll (tieni e muovi su/giù)", None: NONE}
        for finger in PINCH_FINGERS:
            self.choice(t, ("mouse", "bindings", finger), f"Pollice + {FINGER_LABELS[finger].lower()}",
                        actions, "Azione quando il pollice tocca questo dito.")
        self.num(t, ("mouse", "click_freeze_ms"), "Blocco cursore al click (ms)", 0, 600, 10,
                 "Il cursore resta fermo per questo tempo dopo un pinch, così il click non finisce "
                 "spostato.", integer=True)
        self.num(t, ("mouse", "scroll_speed"), "Velocità scroll", 5, 300, 5,
                 "Tacche di scroll per movimento della mano.", integer=True)

    def _region_field(self, t, i, name):
        var = tk.StringVar()
        sb = ttk.Spinbox(t, from_=0, to=1, increment=0.01, textvariable=var, width=10)

        def get():
            v = float(var.get().replace(",", "."))
            if not 0 <= v <= 1:
                raise ValueError(f"«{name}»: deve essere tra 0 e 1")
            return round(v, 3)

        self.fields.append(Field(("mouse", "active_region", i), get,
                                 lambda v: var.set(f"{float(v):g}")))
        self._row(t, name, sb, "Usato solo con il sistema 'Rettangolo fisso'.")

    def _tab_gamepad(self):
        t = self._tab("Gamepad", "Ogni mano è uno stick: lo stick si centra dove la mano entra "
                      "nell'inquadratura (toglila e rimettila per ricentrare). Il pugno preme un "
                      "grilletto in modo analogico, i pinch premono i pulsanti.")
        self.num(t, ("gamepad", "stick", "radius"), "Corsa dello stick (mani)", 0.2, 2.5, 0.05,
                 "Spostamento della mano (in dimensioni mano) per avere lo stick tutto inclinato. "
                 "Più piccolo = più sensibile.")
        self.num(t, ("gamepad", "stick", "deadzone"), "Zona morta stick", 0.0, 0.6, 0.01,
                 "Movimenti più piccoli di questa frazione vengono ignorati (evita derive).")
        self.num(t, ("gamepad", "trigger_threshold"), "Soglia grilletti", 0.0, 0.9, 0.01,
                 "Chiusura minima della mano prima che il grilletto inizi a premere.")
        for hand_key, title in (("left_hand", "Mano sinistra"), ("right_hand", "Mano destra")):
            self._section(t, title)
            self.choice(t, ("gamepad", hand_key, "stick"), "Stick",
                        {"left": "Stick sinistro", "right": "Stick destro", None: NONE})
            self.choice(t, ("gamepad", hand_key, "fist"), "Pugno", PAD_CHOICES,
                        "LT/RT = grilletto analogico; un pulsante viene premuto oltre metà chiusura.")
            for finger in PINCH_FINGERS:
                self.choice(t, ("gamepad", hand_key, "pinch", finger),
                            f"Pollice + {FINGER_LABELS[finger].lower()}", PAD_CHOICES)

    def _tab_gestures(self):
        t = self._tab("Gesti personalizzati",
                      "Una posa della mano (dita tese/piegate) tenuta per un certo tempo esegue "
                      "un'azione: comandi dell'app, tasti o combinazioni, click, pulsanti del "
                      "gamepad (es. croce direzionale, RB) o avvio di programmi. Doppio click su "
                      "una riga per modificarla.")
        cols = ("on", "name", "pose", "hand", "hold", "action", "modes")
        heads = ("Attivo", "Nome", "Posa", "Mano", "Tenuta", "Azione", "Modalità")
        widths = (50, 170, 110, 70, 55, 160, 130)
        box = ttk.Frame(t)
        box.grid(row=t._row, column=0, columnspan=3, sticky="nsew")
        t._row += 1
        self.tree = ttk.Treeview(box, columns=cols, show="headings", height=10, selectmode="browse")
        for c, hd, w in zip(cols, heads, widths):
            self.tree.heading(c, text=hd)
            self.tree.column(c, width=w, stretch=c in ("name", "action"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit_gesture())
        btns = ttk.Frame(t)
        btns.grid(row=t._row, column=0, columnspan=3, sticky="w", pady=6)
        t._row += 1
        for text, cmd in (("Aggiungi…", self._add_gesture), ("Modifica…", self._edit_gesture),
                          ("Duplica", self._dup_gesture), ("Attiva/disattiva", self._toggle_gesture),
                          ("Elimina", self._del_gesture), ("↑", lambda: self._move_gesture(-1)),
                          ("↓", lambda: self._move_gesture(1))):
            ttk.Button(btns, text=text, command=cmd,
                       width=3 if len(text) == 1 else None).pack(side="left", padx=(0, 4))
        ttk.Label(t, style="Help.TLabel", wraplength=600, justify="left", text=(
            "Suggerimenti: le pose con tutte le dita piegate somigliano al pugno, che in modalità "
            "mouse ricentra il cursore e in gamepad preme il grilletto. Le pose valgono solo "
            "senza pinch attivi. 'Finché tieni' tiene premuto il tasto/pulsante finché mantieni "
            "la posa.")).grid(row=t._row, column=0, columnspan=3, sticky="w")
        t._row += 1

    def _tab_audio(self):
        t = self._tab("Audio", "Battiti di mani e schiocchi di dita. Il microfono è spento finché "
                      "non fai il gesto di ascolto (di default: indice alzato per 2 secondi). "
                      "Poi hai qualche secondo per battere le mani o schioccare le dita: "
                      "il numero di colpi sceglie l'azione.")
        self.check(t, ("audio", "enabled"), "Attivo",
                   "Se disattivato, il gesto di ascolto non apre il microfono.")
        var = tk.StringVar()
        devices = ["Predefinito di sistema"]
        try:
            from .audio import list_input_devices
            devices += list_input_devices()
        except Exception:
            pass
        cb = ttk.Combobox(t, textvariable=var, values=devices, state="readonly", width=44)
        self.fields.append(Field(("audio", "device"),
                                 lambda: "" if var.get() == devices[0] else var.get(),
                                 lambda v: var.set(v or devices[0])))
        self._row(t, "Microfono", cb, "Quello della webcam di solito va benissimo: è puntato verso "
                  "di te.")

        self._section(t, "Cosa fanno i colpi")
        self.clap_fields = {}
        for n, label in (("1", "1 colpo"), ("2", "2 colpi"), ("3", "3 colpi")):
            af = ActionField(t)
            self.clap_fields[n] = af
            self._row(t, label, af.frame, "Azione eseguita quando senti questo numero di colpi "
                      "nella finestra di ascolto.")

        self._section(t, "Finestra di ascolto")
        self.num(t, ("audio", "window_s"), "Durata massima (s)", 1.0, 10.0, 0.5,
                 "Per quanto tempo il microfono resta in ascolto dopo il gesto.")
        self.num(t, ("audio", "end_after_silence_s"), "Chiudi dopo silenzio (s)", 0.3, 5.0, 0.1,
                 "Dopo l'ultimo colpo, questo silenzio chiude subito l'ascolto senza aspettare la "
                 "fine. Più lungo = più tempo per il colpo successivo.")

        self._section(t, "Sensibilità")
        self.num(t, ("audio", "min_level_db"), "Volume minimo (dB)", -60, 0, 1,
                 "Un colpo deve superare questo volume (0 = massimo del microfono). Più basso = "
                 "sente anche colpi deboli, ma anche più rumori.", integer=True)
        self.num(t, ("audio", "jump_db"), "Salita improvvisa (dB)", 5, 60, 1,
                 "Di quanto il suono deve salire in 10 millisecondi: è ciò che distingue un colpo "
                 "secco dalla voce o dalla musica.", integer=True)
        self.num(t, ("audio", "rise_db"), "Sopra il rumore di fondo (dB)", 5, 60, 1,
                 "Quanto il colpo deve superare il rumore della stanza.", integer=True)
        self.num(t, ("audio", "min_gap_ms"), "Distanza minima tra colpi (ms)", 50, 1000, 10,
                 "Due colpi più vicini di così contano come uno (evita di contare l'eco).",
                 integer=True)

        box = ttk.Frame(t)
        ttk.Button(box, text="Prova microfono", command=self._test_mic).pack(side="left")
        self.mic_result = ttk.Label(box, style="Help.TLabel", wraplength=440, justify="left")
        self.mic_result.pack(side="left", padx=10)
        self._row(t, "", box, "Ascolta per qualche secondo con le impostazioni qui sopra (anche "
                  "senza averle applicate) e mostra cosa ha sentito.")

    def _test_mic(self):
        from .audio import ClapListener
        try:
            cfg = self.collect()["audio"]
        except ValueError as exc:
            messagebox.showerror("Valore non valido", str(exc), parent=self.root)
            return
        lst = ClapListener(cfg)
        if not lst.start():
            self.mic_result.configure(text=f"Errore: {lst.error}")
            return

        def tick():
            n = lst.poll()
            if n is None:
                left, hits = lst.status()
                self.mic_result.configure(text=f"In ascolto: batti le mani o schiocca le dita. "
                                               f"Colpi: {hits}  ({left * lst.window_s:0.1f} s)")
                self.root.after(100, tick)
                return
            peaks = ", ".join(f"{db:.0f} dB" for _, db, _ in lst.events) or "nessuno"
            floor = lst.events[0][2] if lst.events else None
            action = (cfg.get("clap_actions") or {}).get(str(n))
            what = describe_action(action) if action else "nessuna azione"
            self.mic_result.configure(text=f"Sentiti {n} colpi: {what}.\nPicchi: {peaks}"
                                      + (f"; rumore di fondo {floor:.0f} dB" if floor else ""))

        tick()

    def _tab_recognition(self):
        t = self._tab("Riconoscimento", "Sensibilità del riconoscimento di pinch e pugno, e "
                      "filtro anti-tremolio della mano. Cambia solo se qualcosa non viene "
                      "riconosciuto bene.")
        self._section(t, "Pinch (pollice che tocca un dito)")
        self.num(t, ("gestures", "pinch_on"), "Soglia di contatto", 0.1, 0.7, 0.01,
                 "Distanza pollice-dito (in dimensioni mano) sotto cui il pinch scatta. Più alta "
                 "= scatta prima.")
        self.num(t, ("gestures", "pinch_off"), "Soglia di rilascio", 0.15, 0.9, 0.01,
                 "Distanza sopra cui il pinch si rilascia. Deve essere maggiore della soglia di "
                 "contatto (evita click ripetuti).")
        self._section(t, "Chiusura della mano")
        self.num(t, ("gestures", "curl_open"), "Valore mano aperta", 1.2, 2.5, 0.01,
                 "Rapporto punte-polso con la mano aperta.")
        self.num(t, ("gestures", "curl_closed"), "Valore pugno chiuso", 0.6, 1.6, 0.01,
                 "Rapporto punte-polso col pugno chiuso.")
        self._section(t, "Filtro anti-tremolio della mano")
        self.num(t, ("filter", "min_cutoff"), "Fermezza", 0.05, 10.0, 0.05,
                 "Più basso = punti della mano più stabili da fermi, ma più ritardo.")
        self.num(t, ("filter", "beta"), "Reattività", 0.0, 50.0, 0.5,
                 "Più alto = meno ritardo nei movimenti rapidi.")
        self._section(t, "Tracciamento (MediaPipe)")
        self.num(t, ("tracking", "max_hands"), "Mani massime", 1, 2, 1, "1 o 2 mani.", integer=True)
        self.num(t, ("tracking", "min_detection_confidence"), "Confidenza rilevamento", 0.1, 0.95,
                 0.05, "Più alta = meno falsi positivi, ma la mano può essere persa più spesso.")
        self.num(t, ("tracking", "min_presence_confidence"), "Confidenza presenza", 0.1, 0.95, 0.05)
        self.num(t, ("tracking", "min_tracking_confidence"), "Confidenza tracciamento", 0.1, 0.95,
                 0.05)

    def _tab_camera(self):
        t = self._tab("Webcam", "Le modifiche riaprono la webcam: l'app si ferma un istante.")
        self.num(t, ("camera", "index"), "Indice webcam", 0, 9, 1,
                 "0 = prima webcam, 1 = seconda, ...", integer=True)
        self.num(t, ("camera", "width"), "Larghezza", 160, 1920, 160, integer=True)
        self.num(t, ("camera", "height"), "Altezza", 120, 1080, 120, integer=True)
        self.num(t, ("camera", "fps"), "Fotogrammi al secondo", 10, 60, 5, integer=True)
        self.choice(t, ("camera", "backend"), "Sistema di acquisizione",
                    {"auto": "Automatico (consigliato)", "msmf": "Media Foundation",
                     "dshow": "DirectShow"},
                    "Come Windows legge la webcam. Automatico usa Media Foundation (più fluido) e "
                    "passa a DirectShow se la webcam non risponde.")
        self.check(t, ("camera", "mirror"), "Immagine a specchio",
                   "Consigliato: i movimenti risultano naturali.")
        self.num(t, ("camera", "exposure"), "Esposizione", -13, 0, 1,
                 "Vuoto = automatica. Con poca luce l'automatica abbassa gli fps: un valore "
                 "fisso (es. -6) li mantiene alti.", integer=True, nullable=True)

    def _tab_overlay(self):
        t = self._tab("Overlay", "La finestrella con l'immagine della webcam.")
        self.check(t, ("overlay", "enabled"), "Mostra overlay",
                   "Senza overlay l'app si chiude solo con il tasto rapido 'Chiudi l'app'. "
                   "Richiede il riavvio.")
        self.choice(t, ("overlay", "position"), "Posizione",
                    {"bottom-right": "In basso a destra", "bottom-left": "In basso a sinistra",
                     "top-right": "In alto a destra", "top-left": "In alto a sinistra"})
        self.num(t, ("overlay", "width"), "Larghezza (pixel)", 200, 1280, 20, integer=True)
        self.num(t, ("overlay", "font_scale"), "Grandezza scritte", 0.6, 2.5, 0.1)
        self.num(t, ("overlay", "margin"), "Distanza dai bordi (pixel)", 0, 200, 2, integer=True)
        self.check(t, ("overlay", "always_on_top"), "Sempre in primo piano",
                   "Resta sopra le altre finestre, anche sopra i giochi in finestra o a schermo "
                   "intero senza bordi.")

    def _buttons(self):
        bar = ttk.Frame(self.root, padding=(8, 4, 8, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="Ripristina default", command=self.reset).pack(side="left")
        ttk.Button(bar, text="Importa…", command=self.import_profile).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Esporta…", command=self.export_profile).pack(side="left", padx=4)
        ttk.Button(bar, text="Manuale", command=self.open_manual).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Chiudi", command=self.close).pack(side="right")
        ttk.Button(bar, text="OK", command=self.ok).pack(side="right", padx=4)
        ttk.Button(bar, text="Applica", command=self.apply).pack(side="right")
        self.status = ttk.Label(self.root, style="Help.TLabel", padding=(10, 0, 10, 6),
                                text=f"Impostazioni in {user_config_path()}")
        self.status.pack(fill="x")

    # ---- giochi --------------------------------------------------------------------------
    def _set_games(self, items):
        self.games.delete(0, "end")
        for g in items or []:
            self.games.insert("end", g)

    def _add_game_name(self, name: str):
        name = name.strip().lower()
        if name and name not in self.games.get(0, "end"):
            self.games.insert("end", name)

    def _add_game(self):
        win = tk.Toplevel(self.root)
        win.title("Aggiungi gioco")
        win.transient(self.root)
        var = tk.StringVar()
        ttk.Label(win, text="Nome dell'eseguibile (es. gioco.exe):").pack(padx=12, pady=(12, 4))
        e = ttk.Entry(win, textvariable=var, width=32)
        e.pack(padx=12)
        e.focus_set()

        def ok(_=None):
            self._add_game_name(var.get())
            win.destroy()

        e.bind("<Return>", ok)
        ttk.Button(win, text="Aggiungi", command=ok).pack(pady=10)
        win.grab_set()

    def _remove_game(self):
        for i in reversed(self.games.curselection()):
            self.games.delete(i)

    def _pick_process(self):
        names = running_processes()
        win = tk.Toplevel(self.root)
        win.title("Programmi aperti")
        win.transient(self.root)
        ttk.Label(win, text="Apri il gioco, poi sceglilo qui (filtra scrivendo):").pack(
            padx=10, pady=(10, 4), anchor="w")
        flt = tk.StringVar()
        ttk.Entry(win, textvariable=flt, width=40).pack(padx=10, fill="x")
        lb = tk.Listbox(win, height=16, width=44, selectmode="extended")
        lb.pack(padx=10, pady=6, fill="both", expand=True)

        def refresh(*_):
            lb.delete(0, "end")
            q = flt.get().lower()
            for n in names:
                if q in n:
                    lb.insert("end", n)

        flt.trace_add("write", refresh)
        refresh()

        def ok(_=None):
            for i in lb.curselection():
                self._add_game_name(lb.get(i))
            win.destroy()

        lb.bind("<Double-1>", ok)
        ttk.Button(win, text="Aggiungi selezionati", command=ok).pack(pady=(0, 10))
        win.grab_set()

    # ---- gesti personalizzati ---------------------------------------------------------------
    def _refresh_tree(self, select: int | None = None):
        self.tree.delete(*self.tree.get_children())
        for i, g in enumerate(self.gestures):
            ms = g.get("modes", list(MODE_LABELS))
            modes = "Tutte" if set(ms) >= set(MODE_LABELS) else ", ".join(
                MODE_LABELS.get(m, m) for m in ms)
            hold = f"{float(g.get('hold_s', 0)):g} s" + {"hold": " ⟳", "release": " ↓"}.get(
                g.get("trigger"), "")
            self.tree.insert("", "end", iid=str(i), values=(
                "✔" if g.get("enabled", True) else "—", g.get("name", ""),
                describe_pose(g.get("fingers", {})), GESTURE_HANDS.get(g.get("hand", "any"), "?"),
                hold, describe_action(g.get("action", {})), modes))
        if select is not None and 0 <= select < len(self.gestures):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))

    def _selected(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _add_gesture(self):
        new = {"name": "Nuovo gesto", "enabled": True, "hand": "any",
               "fingers": dict(POSE_PRESETS["V (indice + medio)"]), "hold_s": 0.8,
               "trigger": "once", "modes": ["mouse"], "action": {"type": "key", "value": "alt+tab"}}
        GestureEditor(self.root, new, self._on_new_gesture)

    def _on_new_gesture(self, g: dict):
        self.gestures.append(g)
        self._refresh_tree(len(self.gestures) - 1)

    def _edit_gesture(self):
        i = self._selected()
        if i is None:
            return

        def done(g, i=i):
            self.gestures[i] = g
            self._refresh_tree(i)

        GestureEditor(self.root, copy.deepcopy(self.gestures[i]), done)

    def _dup_gesture(self):
        i = self._selected()
        if i is not None:
            g = copy.deepcopy(self.gestures[i])
            g["name"] = g.get("name", "") + " (copia)"
            self.gestures.insert(i + 1, g)
            self._refresh_tree(i + 1)

    def _toggle_gesture(self):
        i = self._selected()
        if i is not None:
            self.gestures[i]["enabled"] = not self.gestures[i].get("enabled", True)
            self._refresh_tree(i)

    def _del_gesture(self):
        i = self._selected()
        if i is not None and messagebox.askyesno(
                "Elimina gesto", f"Eliminare «{self.gestures[i].get('name', '')}»?", parent=self.root):
            del self.gestures[i]
            self._refresh_tree(min(i, len(self.gestures) - 1))

    def _move_gesture(self, d: int):
        i = self._selected()
        if i is None or not 0 <= i + d < len(self.gestures):
            return
        self.gestures[i], self.gestures[i + d] = self.gestures[i + d], self.gestures[i]
        self._refresh_tree(i + d)

    # ---- caricamento / raccolta -------------------------------------------------------------
    def _load_widgets(self, cfg: dict):
        for f in self.fields:
            try:
                f.set(_get_path(cfg, f.path))
            except (KeyError, IndexError, TypeError):
                f.set(None)
        self.gestures = copy.deepcopy(cfg.get("custom_gestures", []))
        self._refresh_tree()
        acts = (cfg.get("audio") or {}).get("clap_actions") or {}
        for n, af in self.clap_fields.items():
            af.set(acts.get(n))

    def collect(self) -> dict:
        cfg = copy.deepcopy(self.cfg)
        for f in self.fields:
            _set_path(cfg, f.path, f.get())
        cfg["custom_gestures"] = copy.deepcopy(self.gestures)
        cfg.setdefault("audio", {})["clap_actions"] = {}
        for n, af in self.clap_fields.items():
            action = af.get()
            if action:
                err = validate_action(action)
                if err:
                    raise ValueError(f"Audio, {n} colpi: {err}")
            cfg["audio"]["clap_actions"][n] = action
        g = cfg["gestures"]
        if g["pinch_off"] <= g["pinch_on"]:
            raise ValueError("La soglia di rilascio del pinch deve essere maggiore di quella di "
                             "contatto.")
        if g["curl_closed"] >= g["curl_open"]:
            raise ValueError("Il valore 'pugno chiuso' deve essere minore di 'mano aperta'.")
        x0, y0, x1, y1 = cfg["mouse"]["active_region"]
        if x1 <= x0 or y1 <= y0:
            raise ValueError("Rettangolo fisso: destra/basso devono essere maggiori di "
                             "sinistra/alto.")
        for gest in cfg["custom_gestures"]:
            err = validate_action(gest.get("action"))
            if err:
                raise ValueError(f"Gesto «{gest.get('name')}»: {err}")
        return cfg

    # ---- pulsanti ---------------------------------------------------------------------------
    def _say(self, msg: str):
        self.status.configure(text=msg)

    def apply(self) -> bool:
        try:
            cfg = self.collect()
        except ValueError as exc:
            messagebox.showerror("Valore non valido", str(exc), parent=self.root)
            return False
        path = save_user_config(cfg)
        self.cfg = cfg
        changed = len(diff_config(load_default_config(), cfg))
        self._say(f"Salvato in {path} — applicato all'app"
                  + ("" if changed else " (tutto ai valori di default)"))
        return True

    def ok(self):
        if self.apply():
            self.root.destroy()

    def reset(self):
        if not messagebox.askyesno(
                "Ripristina default",
                "Riportare TUTTE le impostazioni ai valori di default?\n"
                "Le tue modifiche e i gesti personalizzati aggiunti andranno persi.",
                icon="warning", parent=self.root):
            return
        reset_user_config()
        self.cfg = load_default_config()
        self._load_widgets(self.cfg)
        self._say("Impostazioni riportate ai valori di default — applicate all'app")

    def import_profile(self):
        p = filedialog.askopenfilename(parent=self.root, title="Importa profilo",
                                       filetypes=[("Profilo YAML", "*.yaml *.yml"), ("Tutti", "*.*")])
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            cfg = deep_merge(load_default_config(), data)
        except Exception as exc:
            messagebox.showerror("Importa profilo", f"File non valido:\n{exc}", parent=self.root)
            return
        self.cfg = cfg
        self._load_widgets(cfg)
        self._say(f"Importato {Path(p).name} — premi Applica per usarlo")

    def export_profile(self):
        try:
            cfg = self.collect()
        except ValueError as exc:
            messagebox.showerror("Valore non valido", str(exc), parent=self.root)
            return
        p = filedialog.asksaveasfilename(parent=self.root, title="Esporta profilo",
                                         defaultextension=".yaml", initialfile="profilo.yaml",
                                         filetypes=[("Profilo YAML", "*.yaml")])
        if not p:
            return
        with open(p, "w", encoding="utf-8") as f:
            f.write("# Profilo di Hand Controller (differenze dal default)\n")
            yaml.safe_dump(diff_config(load_default_config(), cfg), f, allow_unicode=True,
                           sort_keys=False)
        self._say(f"Esportato in {p}")

    def open_manual(self):
        from .manual import open_manual
        try:
            cfg = self.collect()
        except ValueError:
            cfg = self.cfg
        open_manual(cfg)

    def close(self):
        try:
            unsaved = self.collect() != self.cfg
        except ValueError:
            unsaved = True
        if unsaved:
            ans = messagebox.askyesnocancel("Modifiche non salvate",
                                            "Applicare le modifiche prima di chiudere?",
                                            parent=self.root)
            if ans is None or (ans and not self.apply()):
                return
        self.root.destroy()


# ---- scelta di un'azione (tipo + valore) ------------------------------------------------------
HC_VARS_HELP = ("Lo script riceve queste variabili d'ambiente:\n"
                "HC_SOURCE = gesto oppure audio\n"
                "HC_NAME = nome del gesto (o «2 colpi»)\n"
                "HC_COUNT = numero di colpi (solo audio)\n"
                "HC_MODE = mouse, gamepad o paused")
VALUE_HINTS = {
    "key": "Es. alt+tab, ctrl+c, win+d, f5, space, enter, media_play_pause, media_volume_up.",
    "pad": "Es. DPAD_UP/DOWN/LEFT/RIGHT per la croce direzionale, RB, RS, GUIDE.",
    "run": "Programma o script con argomenti: .exe, .py, .ps1, .bat, .vbs, collegamenti .lnk, "
           "oppure un link come steam://rungameid/123 o https://… Percorsi con spazi tra virgolette.",
    "shell": "Riga di comando per cmd: es. start ms-settings:sound, taskkill /im gioco.exe, "
             "echo %HC_NAME% >> C:\\log.txt",
}


class ActionField:
    """Tipo di azione + valore (+ opzioni per programmi e comandi). get() -> dict | None."""

    def __init__(self, parent, allow_none: bool = True):
        self.types = {None: NONE, **ACTION_TYPES} if allow_none else dict(ACTION_TYPES)
        self.frame = ttk.Frame(parent)
        self.type = tk.StringVar()
        cb = ttk.Combobox(self.frame, textvariable=self.type, values=list(self.types.values()),
                          state="readonly", width=24)
        cb.grid(row=0, column=0, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._value_widget(""))
        self.value_box = ttk.Frame(self.frame)
        self.value_box.grid(row=0, column=1, sticky="w", padx=6)
        self.extra = ttk.Frame(self.frame)
        self.extra.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.hint = ttk.Label(self.frame, style="Help.TLabel", wraplength=520, justify="left")
        self.hint.grid(row=2, column=0, columnspan=2, sticky="w")
        self.value = tk.StringVar()
        self.hidden = tk.BooleanVar(value=True)
        self._opts = None

    def _code(self):
        return {v: k for k, v in self.types.items()}.get(self.type.get())

    def _value_widget(self, value):
        for box in (self.value_box, self.extra):
            for w in box.winfo_children():
                w.destroy()
        t = self._code()
        self._opts = {"app": APP_ACTIONS, "mouse": MOUSE_ACTIONS,
                      "pad": {b: b for b in PAD_ACTIONS}}.get(t)
        self.hint.configure(text=VALUE_HINTS.get(t, ""))
        if t is None:
            return
        if self._opts:
            self.value.set(self._opts.get(value, next(iter(self._opts.values()))))
            ttk.Combobox(self.value_box, textvariable=self.value, values=list(self._opts.values()),
                         state="readonly", width=32).pack(side="left")
            return
        self.value.set(value or "")
        width = 44 if t in ("run", "shell") else 30
        ttk.Entry(self.value_box, textvariable=self.value, width=width).pack(side="left")
        if t in ("run", "shell"):
            if t == "run":
                ttk.Button(self.extra, text="Sfoglia…", command=self._browse).pack(side="left")
            cb = ttk.Checkbutton(self.extra, text="Nascondi la finestra della console",
                                 variable=self.hidden)
            cb.pack(side="left", padx=8)
            Tooltip(cb, "Per script e comandi che non devono mostrare la finestra nera.")
            ttk.Button(self.extra, text="Prova", command=self._try).pack(side="left")
            info = ttk.Label(self.extra, text="variabili HC_*", style="Help.TLabel",
                             cursor="question_arrow")
            info.pack(side="left", padx=8)
            Tooltip(info, HC_VARS_HELP)

    def _browse(self):
        p = filedialog.askopenfilename(
            parent=self.frame.winfo_toplevel(), title="Scegli il programma o lo script",
            filetypes=[("Programmi e script", "*.exe *.py *.pyw *.ps1 *.bat *.cmd *.vbs *.lnk"),
                       ("Tutti i file", "*.*")])
        if p:
            p = p.replace("/", "\\") if sys.platform == "win32" else p
            self.value.set(f'"{p}"' if " " in p else p)

    def _try(self):
        from .launcher import launch
        action = self.get()
        err = validate_action(action) or launch(action, {"source": "prova", "name": "Prova",
                                                        "mode": "mouse"})
        if err:
            messagebox.showerror("Prova", err, parent=self.frame.winfo_toplevel())
        else:
            self.hint.configure(text="Avviato.")

    def set(self, action):
        action = action or {}
        first = next(iter(self.types.values()))
        self.type.set(self.types.get(action.get("type"), first))
        self.hidden.set(bool(action.get("hidden", True)))
        self._value_widget(action.get("value", ""))

    def get(self):
        t = self._code()
        if t is None:
            return None
        if self._opts:
            rev = {v: k for k, v in self._opts.items()}
            return {"type": t, "value": rev.get(self.value.get())}
        action = {"type": t, "value": self.value.get().strip()}
        if t in ("run", "shell"):
            action["hidden"] = bool(self.hidden.get())
        return action


# ---- editor di un gesto -----------------------------------------------------------------------
class GestureEditor:
    def __init__(self, master, gesture: dict, on_ok):
        self.g, self.on_ok = gesture, on_ok
        self.win = win = tk.Toplevel(master)
        win.title("Gesto personalizzato")
        win.transient(master)
        f = ttk.Frame(win, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        r = 0

        def row(label, widget, help_=""):
            nonlocal r
            lbl = ttk.Label(f, text=label)
            lbl.grid(row=r, column=0, sticky="nw", padx=(0, 10), pady=4)
            widget.grid(row=r, column=1, sticky="w", pady=4)
            if help_:
                Tooltip(lbl, help_)
            r += 1

        self.name = tk.StringVar(value=gesture.get("name", ""))
        row("Nome", ttk.Entry(f, textvariable=self.name, width=36))
        self.enabled = tk.BooleanVar(value=gesture.get("enabled", True))
        row("Attivo", ttk.Checkbutton(f, variable=self.enabled))

        self.preset = tk.StringVar()
        pc = ttk.Combobox(f, textvariable=self.preset, values=list(POSE_PRESETS), state="readonly",
                          width=34)
        pc.bind("<<ComboboxSelected>>", self._apply_preset)
        cur = gesture.get("fingers", {})
        for pname, preset in POSE_PRESETS.items():
            if all(preset.get(k, "any") == cur.get(k, "any") for k in FINGERS):
                self.preset.set(pname)
                break
        row("Posa pronta", pc, "Scegli una posa per compilare le dita qui sotto.")

        fingers = ttk.Frame(f)
        self.finger_vars = {}
        for i, name in enumerate(FINGERS):
            ttk.Label(fingers, text=FINGER_LABELS[name], width=9).grid(row=i, column=0, sticky="w")
            v = tk.StringVar(value=gesture.get("fingers", {}).get(name, "any"))
            self.finger_vars[name] = v
            for j, (code, lab) in enumerate(FINGER_STATE.items()):
                ttk.Radiobutton(fingers, text=lab, value=code, variable=v).grid(
                    row=i, column=j + 1, sticky="w", padx=4)
        row("Dita", fingers, "Teso = dito disteso, piegato = chiuso verso il palmo, "
            "indifferente = non conta.")

        self.hand = tk.StringVar(value=GESTURE_HANDS.get(gesture.get("hand", "any")))
        row("Mano", ttk.Combobox(f, textvariable=self.hand, values=list(GESTURE_HANDS.values()),
                                 state="readonly", width=14))
        self.hold = tk.StringVar(value=f"{float(gesture.get('hold_s', 0.8)):g}")
        row("Tenuta (secondi)", ttk.Spinbox(f, from_=0, to=5, increment=0.1, textvariable=self.hold,
                                            width=8),
            "Per quanto tempo tenere la posa prima che l'azione scatti. 0 = subito.")
        self.trigger = tk.StringVar(value=gesture.get("trigger") if gesture.get("trigger") in
                                    ("hold", "release") else "once")
        trig = ttk.Frame(f)
        ttk.Radiobutton(trig, text="Una volta", value="once", variable=self.trigger).pack(side="left")
        ttk.Radiobutton(trig, text="Finché tieni la posa", value="hold",
                        variable=self.trigger).pack(side="left", padx=8)
        ttk.Radiobutton(trig, text="Quando la abbassi", value="release",
                        variable=self.trigger).pack(side="left")
        row("Scatta", trig, "Una volta: l'azione viene eseguita appena raggiunta la tenuta.\n"
            "Finché tieni: tasto/pulsante/click restano premuti finché mantieni la posa.\n"
            "Quando la abbassi: dopo la tenuta, scatta quando sciogli la posa (comodo per "
            "l'ascolto: abbassi il dito e batti le mani).")
        modes = ttk.Frame(f)
        self.mode_vars = {}
        for m, lab in MODE_LABELS.items():
            v = tk.BooleanVar(value=m in gesture.get("modes", ["mouse", "gamepad", "paused"]))
            self.mode_vars[m] = v
            ttk.Checkbutton(modes, text=lab, variable=v).pack(side="left", padx=(0, 8))
        row("Attivo in", modes)

        ttk.Separator(f).grid(row=r, column=0, columnspan=2, sticky="ew", pady=8)
        r += 1
        self.action = ActionField(f, allow_none=False)
        self.action.set(gesture.get("action", {"type": "app", "value": "toggle_mode"}))
        row("Azione", self.action.frame)

        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Annulla", command=win.destroy).pack(side="right")
        ttk.Button(b, text="OK", command=self._ok).pack(side="right", padx=6)
        win.grab_set()

    def _ok(self):
        action = self.action.get()
        err = validate_action(action)
        fingers = {k: v.get() for k, v in self.finger_vars.items()}
        try:
            hold = float(self.hold.get().replace(",", "."))
            if not 0 <= hold <= 10:
                raise ValueError
        except ValueError:
            err = err or "tenuta non valida (0-10 secondi)"
        if not self.name.get().strip():
            err = err or "manca il nome"
        if all(v == "any" for v in fingers.values()):
            err = err or "imposta almeno un dito su 'teso' o 'piegato'"
        modes = [m for m, v in self.mode_vars.items() if v.get()]
        if not modes:
            err = err or "scegli almeno una modalità"
        if err:
            messagebox.showerror("Gesto non valido", err, parent=self.win)
            return
        rev_hand = {v: k for k, v in GESTURE_HANDS.items()}
        self.on_ok({"name": self.name.get().strip(), "enabled": self.enabled.get(),
                    "hand": rev_hand.get(self.hand.get(), "any"), "fingers": fingers,
                    "hold_s": round(hold, 2), "trigger": self.trigger.get(), "modes": modes,
                    "action": action})
        self.win.destroy()

    def _apply_preset(self, _=None):
        preset = POSE_PRESETS.get(self.preset.get())
        if preset:
            for k, v in preset.items():
                self.finger_vars[k].set(v)


# ---- utilità -------------------------------------------------------------------------------------
def _validate_hotkey(combo: str) -> str | None:
    if not combo:
        return None
    try:
        from pynput import keyboard

        from .main import to_pynput_hotkey
        keyboard.HotKey.parse(to_pynput_hotkey(combo))
    except Exception:
        return f"tasto non riconosciuto: {combo!r} (es. f9, ctrl+f10)"
    return None


def running_processes() -> list[str]:
    """Nomi degli eseguibili in esecuzione (senza duplicati, in ordine alfabetico)."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            names = {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line}
        else:
            out = subprocess.run(["ps", "-eo", "comm="], capture_output=True, text=True).stdout
            names = {line.strip().split("/")[-1].lower() for line in out.splitlines() if line.strip()}
    except Exception:
        return []
    skip = {"system", "system idle process", "registry", "svchost.exe", "csrss.exe", "smss.exe",
            "wininit.exe", "services.exe", "lsass.exe", "conhost.exe", "dwm.exe", "fontdrvhost.exe"}
    return sorted(n for n in names if n and n not in skip)


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # testo nitido con lo scaling di Windows
        except Exception:
            pass
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except tk.TclError:
        pass
    ConfigUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
