import importlib.util
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("correr", Path(__file__).resolve().parents[2] / "correr.py")
correr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(correr)


def cmd(*args):
    return correr.construir(correr.parse(list(args)))[1:]


def test_exp2_parametros_traducidos():
    c = cmd("exp=2", "fact=300", "caso=a", "matar=3", "fallos=0.4", "ventana=60", "dupl=20", "retardo=1", "sinpausa=1", "ensayo=1", "si=1", "resultados=0")
    assert c[:4] == ["-m", "runner", "demo", "exp2"]
    assert c[c.index("--n") + 1] == "300" and c[c.index("--case") + 1] == "A" and c[c.index("--kill-pods") + 1] == "3"
    assert c[c.index("--fail-rate") + 1] == "0.4" and c[c.index("--fault-window") + 1] == "60" and c[c.index("--dupl") + 1] == "20"
    assert c[c.index("--delay") + 1] == "1"
    assert {"--no-pause", "--dry-run", "--yes", "--no-resultados"} <= set(c)


def test_exp2_defectos():
    c = cmd("exp=2")
    assert c[c.index("--n") + 1] == "150" and c[c.index("--case") + 1] == "B" and c[c.index("--dupl") + 1] == "30"
    assert c[c.index("--kill-pods") + 1] == "2" and c[c.index("--delay") + 1] == "1"
    assert c[c.index("--fault-window") + 1] == "30" and c[c.index("--observe") + 1] == "15"


def test_exp3_es_alias_de_exp2_y_avisa(capsys):
    c = cmd("exp=3", "fact=100")
    assert c[3] == "exp2" and c[c.index("--dupl") + 1] == "30"
    assert "se unio al Exp. 2" in capsys.readouterr().err


def test_exp1_sin_cambios_y_parametros_de_exp2_no_validos():
    c = cmd("fact=1500")
    assert c[3] == "exp1" and c[c.index("--delay") + 1] == "0.1" and "--case" not in c
    with pytest.raises(SystemExit):
        cmd("exp=1", "dupl=5")
