import datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from wealth_dashboard import esempio, grafici, segnali
from wealth_dashboard.cli import main

APP = str(Path(__file__).parents[1] / "streamlit_app.py")


@pytest.fixture(scope="module")
def app():
    return AppTest.from_file(APP, default_timeout=120).run()


def test_app_si_avvia_sull_esempio(app):
    assert not app.exception
    assert app.title[0].value == "Patrimonio della Famiglia Conti"
    assert len(app.tabs) == 7
    assert app.metric[0].label == "Patrimonio netto"


def test_app_metodo_e_data(app):
    [r for r in app.radio if r.label == "Metodo"][0].set_value("Solo acquisti, senza vendite").run()
    assert not app.exception
    app.date_input[0].set_value(datetime.date(2022, 10, 14)).run()
    assert not app.exception
    assert "14/10/2022" in app.caption[0].value


def test_grafici_esempio():
    p = esempio()
    for f in (grafici.patrimonio_netto, grafici.composizione, grafici.performance_cumulata, grafici.drawdown,
              grafici.versato_e_valore, grafici.immobili_valore, grafici.immobili_storico):
        assert f(p).data


def test_esempio_ha_segnali_da_mostrare():
    livelli = {s.livello for s in segnali(esempio())}
    assert "alto" in livelli


def test_cli(tmp_path, capsys):
    assert main(["segnali", "--metodo", "solo_acquisti", "--liquidita", "10000"]) == 0
    out = capsys.readouterr().out
    assert "Famiglia Conti" in out and "Operazioni proposte (metodo: solo_acquisti)" in out
    destinazione = tmp_path / "piano.toml"
    assert main(["planner", "--eta", "52", "--output", str(destinazione)]) == 0
    assert "patrimonio_iniziale" in destinazione.read_text(encoding="utf-8")
