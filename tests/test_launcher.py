import sys
import time

import pytest

from hand_controller.actions import ActionExecutor, describe_action, validate_action
from hand_controller.backends.null import NullMouseBackend
from hand_controller.launcher import build_launch, launch, split_command_line

WIN = sys.platform == "win32"


def test_split_command_line_keeps_quoted_paths():
    parts = split_command_line(r'"C:\Giochi\Il mio gioco\gioco.exe" --livello 3')
    assert parts[0] == r"C:\Giochi\Il mio gioco\gioco.exe" if WIN else True
    assert parts[-2:] == ["--livello", "3"]


@pytest.mark.parametrize("ext, expect", [
    (".py", "py"), (".ps1", "powershell"), (".bat", "cmd"),
])
def test_scripts_get_the_right_interpreter(tmp_path, ext, expect):
    if ext in (".ps1", ".bat") and not WIN:
        pytest.skip("solo Windows")
    script = tmp_path / f"prova{ext}"
    script.write_text("rem\n", encoding="utf-8")
    spec = build_launch({"type": "run", "value": f'"{script}" uno due'})
    assert spec.kind == "exec"
    joined = " ".join(spec.argv).lower()
    assert expect in joined or (expect == "py" and "python" in joined) or (
        expect == "powershell" and "pwsh" in joined)
    assert str(script) in spec.argv and spec.argv[-2:] == ["uno", "due"]
    assert spec.cwd == str(tmp_path)


def test_links_and_documents_open_with_association(tmp_path):
    assert build_launch({"type": "run", "value": "steam://rungameid/292030"}).kind == "open"
    assert build_launch({"type": "run", "value": "https://example.com"}).kind == "open"
    doc = tmp_path / "note.txt"
    doc.write_text("x")
    assert build_launch({"type": "run", "value": str(doc)}).kind == "open"


def test_shell_and_validation():
    assert build_launch({"type": "shell", "value": "echo ciao && dir"}).kind == "shell"
    assert validate_action({"type": "shell", "value": "  "})
    assert "non trovato" in validate_action({"type": "run", "value": r"C:\non\esiste\script.py"})
    assert validate_action({"type": "run", "value": "notepad.exe"}) is None
    assert describe_action({"type": "run", "value": r'"C:\Script dir\luci.py" --on'}) == (
        "Avvia luci.py" if WIN else describe_action({"type": "run", "value": "luci.py"}))


def test_launch_passes_context_in_environment(tmp_path):
    out = tmp_path / "out.txt"
    script = tmp_path / "scrivi.py"
    script.write_text(
        "import os, sys\n"
        "open(sys.argv[1], 'w').write(os.environ.get('HC_SOURCE','') + '|' +"
        " os.environ.get('HC_NAME','') + '|' + os.environ.get('HC_MODE',''))\n", encoding="utf-8")
    action = {"type": "run", "value": f'"{sys.executable}" "{script}" "{out}"', "hidden": True}
    assert launch(action, {"source": "gesto", "name": "Prova", "mode": "mouse"}) is None
    for _ in range(100):
        if out.exists() and out.read_text():
            break
        time.sleep(0.05)
    assert out.read_text() == "gesto|Prova|mouse"


def test_executor_reports_missing_program():
    messages = []
    ex = ActionExecutor(NullMouseBackend(), {}, notify=messages.append)
    ex.fire({"type": "run", "value": r"C:\non\esiste\programma.exe"}, 0.0)
    assert messages and "non trovato" in messages[0]
