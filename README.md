# Hand Controller

Usa il PC con le mani davanti alla webcam: **mouse virtuale** sul desktop per avviare i giochi,
**controller Xbox virtuale** dentro i giochi. Il passaggio tra le due modalità può essere
automatico (in base al gioco in primo piano), con un gesto o con un tasto.

## Architettura

```
webcam ─► capture (thread) ─► tracker (MediaPipe, 21 punti/mano) ─► One Euro filter
      ─► gestures (pinch, pugno, corna) ─► mouse_mode | gamepad_mode ─► backends
```

Tutta la logica è indipendente dalla piattaforma; solo `backends/` e `desktop/` contengono codice
specifico per sistema operativo:

| Funzione | Windows | Linux | macOS |
|---|---|---|---|
| Mouse virtuale | pynput | pynput (X11) | pynput |
| Controller Xbox | vgamepad (ViGEmBus) | uinput (evdev) | — (non supportato) |
| Rilevamento gioco in primo piano | Win32 API | xdotool (X11) | osascript |

Per portare il progetto su un nuovo sistema basta aggiungere un backend che implementa
`GamepadBackend` / `MouseBackend` (vedi `backends/base.py`).

## Installazione

Richiede Python 3.9–3.12.

**Windows**
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[windows,dev]"     # installa anche il driver ViGEmBus (serve conferma admin)
```

**Linux**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[linux,dev]"
sudo modprobe uinput
# permesso su /dev/uinput, es.:
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo usermod -aG input $USER       # poi rifai il login
```

Al primo avvio il modello di MediaPipe (~8 MB) viene scaricato in `~/.cache/hand_controller/`.

## Uso

```bash
hand-controller                     # avvio normale
hand-controller --dry-run           # solo overlay, nessun input reale (per prove)
hand-controller --list-cameras
hand-controller --config profiles/esempio.yaml
```

### Comandi

| | Modalità **mouse** (mano destra) | Modalità **gamepad** |
|---|---|---|
| Movimento | il palmo muove il cursore come un trackpad (vedi sotto) | mano sinistra = stick sinistro, mano destra = stick destro |
| Pollice + indice | click sinistro (tieni premuto = drag) | sx: **LB** · dx: **A** |
| Pollice + medio | click destro | sx: **Back** · dx: **B** |
| Pollice + anulare | tieni premuto e muovi su/giù = scroll | sx: **LS** · dx: **X** |
| Pollice + mignolo | click centrale | sx: **Start** · dx: **Y** |
| Pugno | cursore al centro dello schermo e nuovo centro del movimento | sx: **LT** · dx: **RT** (analogico) |

- **Centrare il mouse** (`mouse.motion: anchor`, default): chiudi il pugno e il cursore va al centro
  dello schermo; la mano in quel punto diventa il centro del movimento. Intorno c'è un rettangolo
  largo quanto la mano (disegnato nell'overlay) che corrisponde all'intero monitor: bastano piccoli
  movimenti del polso col gomito appoggiato. **+ / -** nell'overlay rimpiccioliscono o allargano il
  rettangolo. Con `motion: absolute` il rettangolo è fisso nel fotogramma (`active_region`).
- **Ricentrare lo stick**: lo stick si azzera nel punto in cui la mano entra nell'inquadratura;
  togli la mano e rimettila.
- **Cambio modalità**: gesto "corna" 🤘 (indice + mignolo tesi) per 1 secondo, oppure **F9**.
- **Pausa** (nessun input generato): **F10**. **Chiudi l'app**: **Ctrl+F10** (da qualsiasi finestra).
- **Automatico**: se l'eseguibile in primo piano è in `auto_switch.game_processes` si passa a
  gamepad, altrimenti a mouse.

### Configurazione

Pulsante **config** in basso a destra nell'overlay (o tasto **c**, o `hand-controller --settings`):
si apre una finestra con tutte le impostazioni (generale, mouse, gamepad, gesti personalizzati,
riconoscimento, webcam, overlay). **Applica** salva e l'app in esecuzione si aggiorna subito.
**Ripristina default** riporta tutto ai valori originali.

Le impostazioni utente sono in `%APPDATA%\hand-controller\config.yaml` (Linux:
`~/.config/hand-controller/config.yaml`) e contengono solo le differenze rispetto a
`src/hand_controller/default_config.yaml`. Con **Esporta/Importa** si salvano e caricano profili.

### Gesti personalizzati

Una posa della mano (ogni dito teso / piegato / indifferente) tenuta per un certo tempo esegue
un'azione: comando dell'app (cambia modalità, pausa, ricentra, configurazione, esci), tasto o
combinazione (`alt+tab`, `win+d`, `media_volume_up`…), click del mouse, pulsante del gamepad
(es. croce direzionale, RB) o avvio di un programma. L'azione può scattare una volta o restare
premuta finché si tiene la posa. Le "corna" per il cambio modalità sono il primo gesto della lista;
altri esempi sono presenti ma disattivati.

## Test

```bash
pytest
```
