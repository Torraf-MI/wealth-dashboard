import numpy as np
import pandas as pd
import pytest
from conftest import DATE, mov, patrimonio

from wealth_dashboard import immobili, performance, posizioni


def test_xirr():
    f = pd.Series([-100.0, 110.0], index=pd.to_datetime(["2023-01-01", "2024-01-01"]))
    assert performance.xirr(f) == pytest.approx(0.10, abs=1e-6)
    f = pd.Series([-100.0, -100.0, 230.0], index=pd.to_datetime(["2020-01-01", "2021-01-01", "2022-01-01"]))
    t = performance.xirr(f)
    assert 100 * (1 + t) ** (731 / 365) + 100 * (1 + t) ** (365 / 365) == pytest.approx(230, abs=1e-4)
    assert np.isnan(performance.xirr(pd.Series([100.0, 10.0], index=f.index[:2])))


def test_twr_e_rendimento_di_prezzo_senza_flussi():
    p = patrimonio([mov("2024-01-01", "VERSAMENTO", importo=10_000), mov("2024-01-01", "ACQUISTO", "AZ", 100, 100)])
    r = performance.rendimenti_giornalieri(p)
    assert (1 + r).prod() - 1 == pytest.approx(0.20)


def test_twr_non_dipende_dai_versamenti_ma_mwr_si():
    prezzi = pd.DataFrame({"AZ": np.r_[np.linspace(100, 150, 130), np.linspace(150, 120, len(DATE) - 130)],
                           "OBB": 100.0, "BTP": 100.0}, index=DATE)
    giorno = DATE[129]  # massimo dei prezzi: il secondo versamento arriva nel momento peggiore
    p = patrimonio([
        mov("2024-01-01", "VERSAMENTO", importo=10_000), mov("2024-01-01", "ACQUISTO", "AZ", 100, 100),
        mov(giorno, "VERSAMENTO", importo=150_000), mov(giorno, "ACQUISTO", "AZ", 1_000, 150),
    ], prezzi=prezzi)
    twr = (1 + performance.rendimenti_giornalieri(p)).prod() - 1
    assert twr == pytest.approx(0.20)
    assert performance.mwr(p, None, DATE[-1]) < 0  # il cliente ha perso: ha investito molto prima del calo


def test_contributi_sommano_all_utile(semplice):
    c = performance.contributi(semplice)
    v = performance.valore_totale(semplice)
    assert c["utile"].sum() == pytest.approx(v.iloc[-1] - posizioni.flussi_esterni(semplice).sum())
    assert c.loc["AZ", "utile"] == pytest.approx(60 * 20)


def test_benchmark_periodi_e_mensili(semplice):
    b = performance.rendimenti_benchmark(semplice)
    atteso = (1 + 0.6 * semplice.prezzi["AZ"].pct_change().fillna(0)).prod() - 1  # pesi costanti ogni giorno
    assert (1 + b).prod() - 1 == pytest.approx(atteso)
    t = performance.periodi(semplice)
    assert t.loc["Da inizio anno", "Portafoglio (TWR)"] == pytest.approx(1_200 / 10_000)
    assert t.loc["Da inizio anno", "Rendimento del cliente (MWR)"] == pytest.approx(0.12, abs=1e-3)
    m = performance.rendimenti_mensili(semplice)
    assert (1 + m.loc[2024, "Gen":"Dic"]).prod() - 1 == pytest.approx(m.loc[2024, "Anno"])
    rischio = performance.rischio(semplice)
    assert rischio["Massima perdita dal picco"] == pytest.approx(0)


def test_mutuo_alla_francese():
    assert immobili.rata(100_000, 0.03, 20) == pytest.approx(554.60, abs=0.01)
    inizio = pd.Timestamp("2020-01-15")
    assert immobili.debito_residuo(100_000, 0.03, 20, inizio, inizio) == 100_000
    assert immobili.debito_residuo(100_000, 0.03, 20, inizio, pd.Timestamp("2040-02-01")) == pytest.approx(0, abs=1e-6)
    debito = 100_000.0
    for _ in range(12):  # dodici rate pagate entro il 15/01/2021
        debito = debito * (1 + 0.03 / 12) - immobili.rata(100_000, 0.03, 20)
    assert immobili.debito_residuo(100_000, 0.03, 20, inizio, pd.Timestamp("2021-01-15")) == pytest.approx(debito)
    assert immobili.debito_residuo(100_000, 0.03, 20, inizio, pd.Timestamp("2021-01-14")) > debito
    assert immobili.debito_residuo(120_000, 0.0, 10, inizio, pd.Timestamp("2025-01-15")) == pytest.approx(60_000)


def _con_immobile(semplice_movimenti=None):
    imm = pd.DataFrame([{
        "nome": "Casa", "citta": "Roma", "uso": "A reddito", "data_acquisto": pd.Timestamp("2024-03-01"),
        "prezzo_acquisto": 200_000, "costi_acquisto": 10_000, "mutuo_importo": 100_000, "mutuo_tasso": 0.0,
        "mutuo_anni": 10, "mutuo_inizio": pd.Timestamp("2024-03-01")}], index=pd.Index(["CASA"], name="id"))
    val = pd.DataFrame({"data": pd.to_datetime(["2024-03-01", "2024-09-01"]), "immobile": "CASA",
                        "valore": [200_000.0, 220_000.0]})
    movimenti = [mov("2024-01-01", "VERSAMENTO", importo=10_000)] + [
        mov(f"2024-{m:02d}-05", "AFFITTO", "CASA", importo=1_000) for m in range(4, 13)]
    return patrimonio(movimenti, immobili=imm, valutazioni=val)


def test_valori_debiti_e_riepilogo_immobili():
    p = _con_immobile()
    v = immobili.valori(p)["CASA"]
    assert v[pd.Timestamp("2024-02-29")] == 0
    assert v[pd.Timestamp("2024-06-03")] == pytest.approx(200_000 + 20_000 * 94 / 184)
    assert v.iloc[-1] == 220_000
    r = immobili.riepilogo(p).loc["CASA"]
    assert r["debito"] == pytest.approx(100_000 * (1 - 9 / 120))  # 9 rate al 31/12
    assert r["ltv"] == pytest.approx(r["debito"] / 220_000)
    assert r["canoni_12m"] == 9_000 and r["rendimento_netto"] == pytest.approx(9_000 / 220_000)
    assert r["rendimento_totale_annuo"] > 0.1
    # gli affitti entrano nel patrimonio finanziario come flussi esterni, non come rendimento
    assert performance.rendimenti_giornalieri(p).abs().max() == 0
