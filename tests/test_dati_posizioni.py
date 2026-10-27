import numpy as np
import pandas as pd
import pytest
from conftest import DATE, mov, patrimonio, strategia

from wealth_dashboard import carica_zip, esempio, posizioni, zip_esempio
from wealth_dashboard.dati import Strategia


def test_esempio_e_zip_coincidono():
    a, b = esempio(), carica_zip(zip_esempio())
    pd.testing.assert_frame_equal(a.prezzi, b.prezzi)
    pd.testing.assert_frame_equal(a.movimenti, b.movimenti)
    assert a.strategia == b.strategia
    assert set(a.strumenti["classe"]) | {"Liquidità"} == set(a.strategia.obiettivo)


def test_validazione():
    with pytest.raises(ValueError, match="sommare a 1"):
        Strategia.from_dict({"obiettivo": {"Azionario": {"peso": 0.5}}})
    with pytest.raises(ValueError, match="non riconosciuti"):
        patrimonio([mov("2024-01-02", "BONIFICO", importo=1)])
    with pytest.raises(ValueError, match="non in strumenti.csv"):
        patrimonio([mov("2024-01-02", "ACQUISTO", "XYZ", 1, 10)])
    with pytest.raises(ValueError, match="peso obiettivo"):
        patrimonio([], strategia=strategia(obiettivo={"Azionario": {"peso": 0.9}, "Liquidità": {"peso": 0.1}}))
    with pytest.raises(FileNotFoundError, match="strategia.toml"):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("prezzi.csv", "Data,A\n")
        carica_zip(buf.getvalue())


def test_quantita_liquidita_e_valori(semplice):
    q = posizioni.quantita(semplice)
    assert q.loc[DATE[-1], "AZ"] == 60 and q.loc[DATE[-1], "OBB"] == 30
    assert posizioni.liquidita(semplice).iloc[-1, 0] == pytest.approx(1_000)
    v = posizioni.valori(semplice).sum(axis=1)
    assert v.iloc[0] == pytest.approx(10_000)
    assert v.iloc[-1] == pytest.approx(60 * 120 + 3_000 + 1_000)


def test_movimento_nel_fine_settimana_va_al_lunedi(semplice):
    p = patrimonio([mov("2024-01-01", "VERSAMENTO", importo=100), mov("2024-01-06", "VERSAMENTO", importo=50)])
    cassa = posizioni.liquidita(p).iloc[:, 0]
    assert cassa[pd.Timestamp("2024-01-05")] == 100 and cassa[pd.Timestamp("2024-01-08")] == 150


def test_costo_medio_e_plusvalenze_realizzate():
    p = patrimonio([
        mov("2024-01-01", "VERSAMENTO", importo=5_000),
        mov("2024-01-02", "ACQUISTO", "AZ", 10, 100, costi=10),   # costo 1.010
        mov("2024-02-01", "ACQUISTO", "AZ", 10, 120, costi=10),   # costo totale 2.220, medio 111
        mov("2024-03-01", "VENDITA", "AZ", 5, 130, costi=5),      # incasso 645, costo 555
    ])
    cm = posizioni.costo_medio(p).iloc[0]
    assert cm["quantita"] == 15
    assert cm["costo"] == pytest.approx(2_220 - 555)
    assert cm["realizzato"] == pytest.approx(645 - 555)
    assert posizioni.liquidita(p).iloc[-1, 0] == pytest.approx(5_000 - 1_010 - 1_210 + 645)


def test_vendita_oltre_la_quantita():
    p = patrimonio([mov("2024-01-01", "VERSAMENTO", importo=1_000), mov("2024-01-02", "ACQUISTO", "AZ", 1, 100),
                    mov("2024-01-03", "VENDITA", "AZ", 2, 100)])
    with pytest.raises(ValueError, match="in portafoglio 1"):
        posizioni.costo_medio(p)


def test_situazione_pesi_imposte_e_fattore():
    p = patrimonio([
        mov("2024-01-01", "VERSAMENTO", importo=20_000),
        mov("2024-01-01", "ACQUISTO", "AZ", 50, 100),
        mov("2024-01-01", "ACQUISTO", "BTP", 10_000, 90),  # nominale 10.000 a 90: 9.000 €
    ])
    s = posizioni.situazione(p).set_index("strumento")
    assert s["peso"].sum() == pytest.approx(1)
    assert s.loc["BTP", "valore"] == pytest.approx(10_000)
    assert s.loc["BTP", "imposta_latente"] == pytest.approx(1_000 * 0.125)
    assert s.loc["AZ", "imposta_latente"] == pytest.approx(50 * 20 * 0.26)
    assert s.loc["Liquidità", "valore"] == pytest.approx(6_000)
    assert np.isnan(s.loc["Liquidità", "plusvalenza_pct"])
    # a una data precedente
    meta = posizioni.situazione(p, pd.Timestamp("2024-07-01")).set_index("strumento")
    assert 100 < meta.loc["AZ", "prezzo"] < 120
