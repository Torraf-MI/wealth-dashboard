import tomllib

import pandas as pd
import pytest
from conftest import mov, patrimonio, strategia

from wealth_dashboard import allocazione, integrazioni, operazioni, ribilanciamento, segnali


def sbilanciato(**kwargs):
    """AZ passa da 100 a 120: alla fine Azionario pesa 7.200/11.200 = 64%, con 10 OBB e 3.000 € di liquidità."""
    return patrimonio([
        mov("2024-01-01", "VERSAMENTO", importo=10_000),
        mov("2024-01-01", "ACQUISTO", "AZ", 60, 100, costi=0),
        mov("2024-01-01", "ACQUISTO", "OBB", 10, 100),
    ], **kwargs)


def test_allocazione_per_classe(semplice):
    a = allocazione.per_classe(semplice)
    assert a["peso"].sum() == pytest.approx(1)
    assert not a["fuori_banda"].any()
    assert not [s for s in segnali(semplice) if s.area == "Allocazione"]
    b = allocazione.per_classe(sbilanciato())
    assert b.loc["Obbligazionario", "fuori_banda"] and b.loc["Liquidità", "fuori_banda"]
    assert b.loc["Obbligazionario", "scostamento_euro"] == pytest.approx(1_000 - 0.3 * 11_200)


def test_segnali():
    p = sbilanciato(strategia=strategia(spesa_mensile=1_000, mesi_liquidita_minima=6))
    s = segnali(p)
    titoli = [x.titolo for x in s]
    assert "Obbligazionario sotto la banda di tolleranza" in titoli
    assert "Liquidità sopra la banda di tolleranza" in titoli
    assert "Riserva di liquidità sotto il minimo" in titoli  # 3.000 € contro 6.000
    assert any(x.area == "Concentrazione" for x in s)       # AZ pesa il 64% (limite 30%)
    assert [ribilanciamento.LIVELLI[x.livello] for x in s] == sorted(ribilanciamento.LIVELLI[x.livello] for x in s)


def test_ribilanciamento_all_obiettivo():
    p = sbilanciato()
    ops = operazioni(p, importo_minimo=0)
    dopo = ribilanciamento.allocazione_dopo(p, ops)
    assert (dopo["dopo"] - dopo["obiettivo"]).abs().max() < 0.015  # resta solo l'arrotondamento al lotto
    vendita = ops[ops["operazione"] == "Vendi"].iloc[0]
    assert vendita["strumento"] == "AZ"
    assert vendita["plusvalenza_realizzata"] == pytest.approx(vendita["quantita"] * 20)
    assert vendita["imposta_stimata"] == pytest.approx(vendita["plusvalenza_realizzata"] * 0.26)


def test_solo_acquisti_non_vende():
    p = sbilanciato()
    ops = operazioni(p, metodo="solo_acquisti", importo_minimo=0)
    assert (ops["operazione"] == "Acquista").all()
    assert set(ops["classe"]) == {"Obbligazionario"}
    disponibile = 3_000 - 0.1 * 11_200
    assert 0 < ops["importo"].sum() <= disponibile
    assert ops["imposta_stimata"].sum() == 0
    con_nuovi = operazioni(p, metodo="solo_acquisti", nuova_liquidita=5_000, importo_minimo=0)
    assert con_nuovi["importo"].sum() > ops["importo"].sum()
    with pytest.raises(ValueError):
        operazioni(p, metodo="vendi_tutto")


def test_strumento_preferito_e_lotti():
    p = sbilanciato(strategia=strategia(strumenti_preferiti={"Obbligazionario": "BTP"}))
    ops = operazioni(p, importo_minimo=0)
    btp = ops[ops["strumento"] == "BTP"].iloc[0]
    assert btp["quantita"] % 1000 == 0 and btp["importo"] == pytest.approx(btp["quantita"])


def test_esportazioni_per_gli_altri_progetti(semplice):
    piano = tomllib.loads(integrazioni.toml_per_planner(semplice, eta=55))
    assert piano["flussi"]["patrimonio_iniziale"] == pytest.approx(11_200, abs=1)
    assert sum(piano["portafoglio"]["pesi"].values()) == pytest.approx(1)
    assert piano["cliente"] == {"eta": 55, "eta_pensione": 67}
    try:
        from wealth_planner.modello import Piano
    except ImportError:
        pass
    else:
        assert Piano.from_dict(piano).flussi.patrimonio_iniziale == pytest.approx(11_200, abs=1)
    import io
    prezzi = pd.read_csv(io.StringIO(integrazioni.prezzi_per_optimizer(semplice)))
    assert list(prezzi.columns) == ["Data", "Azioni", "Obbligazioni"]
