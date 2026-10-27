"""Genera i dati dimostrativi della famiglia Conti in ``src/wealth_dashboard/esempio``.

I prezzi sono simulati: rumore giornaliero correlato (moto browniano) vincolato a rendimenti annui scelti per
somigliare, a grandi linee, agli anni 2021-2026 (rialzo del 2021, ribasso di azioni e obbligazioni nel 2022,
ripresa e forte rialzo dell'oro). Non sono quotazioni reali. Il risultato è ripetibile:
``python scripts/genera_esempio.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parents[1] / "src" / "wealth_dashboard" / "esempio"
INIZIO, FINE = "2021-01-04", "2026-09-30"

STRUMENTI = pd.DataFrame(
    [
        # codice, nome, classe, aliquota, fattore (valore = quantità × prezzo × fattore), lotto, prezzo iniziale, vol
        ("AZ_MONDO", "ETF Azionario Mondo", "Azionario", 0.26, 1, 1, 72.0, 0.15),
        ("AZ_EUROPA", "ETF Azionario Europa", "Azionario", 0.26, 1, 1, 41.0, 0.17),
        ("AZ_EMERGENTI", "ETF Azionario Paesi Emergenti", "Azionario", 0.26, 1, 1, 33.0, 0.19),
        ("BTP_2032", "BTP 2,50% 2032", "Obbligazionario", 0.125, 0.01, 1000, 104.0, 0.07),
        ("OBB_CORP", "ETF Obbligazioni Societarie Euro", "Obbligazionario", 0.26, 1, 1, 128.0, 0.05),
        ("OBB_GOV_BREVE", "ETF Governativi Euro 1-3 anni", "Obbligazionario", 0.26, 1, 1, 141.0, 0.02),
        ("ORO", "ETC Oro fisico", "Oro", 0.26, 1, 1, 150.0, 0.15),
    ],
    columns=["codice", "nome", "classe", "aliquota", "fattore", "lotto", "p0", "vol"],
).set_index("codice")

# Rendimenti di prezzo per anno solare (2026: fino a settembre)
RENDIMENTI = {
    "AZ_MONDO": [0.27, -0.13, 0.19, 0.25, 0.07, 0.08],
    "AZ_EUROPA": [0.23, -0.10, 0.16, 0.08, 0.18, 0.07],
    "AZ_EMERGENTI": [0.05, -0.15, 0.06, 0.14, 0.15, 0.12],
    "BTP_2032": [-0.03, -0.16, 0.06, 0.03, 0.01, 0.01],
    "OBB_CORP": [-0.01, -0.13, 0.08, 0.04, 0.03, 0.02],
    "OBB_GOV_BREVE": [-0.005, -0.05, 0.035, 0.03, 0.022, 0.015],
    "ORO": [-0.04, 0.06, 0.09, 0.35, 0.45, 0.20],
}
CORRELAZIONI = np.array(
    [
        [1.00, 0.85, 0.70, 0.10, 0.30, 0.05, 0.10],
        [0.85, 1.00, 0.65, 0.15, 0.30, 0.05, 0.05],
        [0.70, 0.65, 1.00, 0.10, 0.25, 0.05, 0.20],
        [0.10, 0.15, 0.10, 1.00, 0.70, 0.55, 0.20],
        [0.30, 0.30, 0.25, 0.70, 1.00, 0.60, 0.20],
        [0.05, 0.05, 0.05, 0.55, 0.60, 1.00, 0.15],
        [0.10, 0.05, 0.20, 0.20, 0.20, 0.15, 1.00],
    ]
)


def genera_prezzi(seed: int = 7) -> pd.DataFrame:
    date = pd.bdate_range(INIZIO, FINE)
    rng = np.random.default_rng(seed)
    vol = STRUMENTI["vol"].to_numpy()
    rumore = rng.standard_normal((len(date), len(vol))) @ np.linalg.cholesky(CORRELAZIONI).T * vol / np.sqrt(252)
    rumore[0] = 0
    log_p = np.zeros_like(rumore)
    anni = date.year.to_numpy()
    livello = np.zeros(len(vol))
    for k, anno in enumerate(sorted(set(anni))):
        idx = np.flatnonzero(anni == anno)
        # rumore dell'anno trasformato in ponte browniano: somma nulla, il rendimento annuo è quello scelto
        cammino = np.cumsum(rumore[idx], axis=0)
        t = np.arange(1, len(idx) + 1)[:, None] / len(idx)
        ponte = cammino - t * cammino[-1]
        deriva = np.log1p(np.array([RENDIMENTI[c][k] for c in STRUMENTI.index]))
        log_p[idx] = livello + t * deriva + ponte
        livello = log_p[idx[-1]]
    prezzi = pd.DataFrame(np.exp(log_p) * STRUMENTI["p0"].to_numpy(), index=date, columns=STRUMENTI.index)
    return prezzi.round(4).rename_axis("Data")


def genera_movimenti(prezzi: pd.DataFrame) -> pd.DataFrame:
    righe: list[dict] = []
    fattore = STRUMENTI["fattore"]

    def giorno(d: str) -> pd.Timestamp:
        return prezzi.index[prezzi.index.searchsorted(pd.Timestamp(d))]

    def mov(d, conto, tipo, strumento="", quantita=None, prezzo=None, costi=0.0, importo=None):
        righe.append(dict(data=giorno(d), conto=conto, tipo=tipo, strumento=strumento, quantita=quantita,
                          prezzo=prezzo, costi=costi, importo=importo))

    def compra(d, conto, codice, euro, costi=5.0):
        p = prezzi.at[giorno(d), codice]
        lotto = STRUMENTI.at[codice, "lotto"]
        q = np.floor(euro / (p * fattore[codice]) / lotto) * lotto
        mov(d, conto, "ACQUISTO", codice, q, round(p, 4), costi)
        return q

    alfa, beta, deposito = "Banca Alfa - dossier", "Broker Beta - online", "Conto deposito"
    # Patrimonio iniziale
    mov(INIZIO, alfa, "VERSAMENTO", importo=500_000)
    mov(INIZIO, beta, "VERSAMENTO", importo=60_000)
    mov(INIZIO, deposito, "VERSAMENTO", importo=40_000)
    q = {
        "AZ_EUROPA": compra("2021-01-05", alfa, "AZ_EUROPA", 60_000),
        "AZ_EMERGENTI": compra("2021-01-05", alfa, "AZ_EMERGENTI", 30_000),
        "BTP_2032": compra("2021-01-05", alfa, "BTP_2032", 85_000),
        "OBB_CORP": compra("2021-01-05", alfa, "OBB_CORP", 60_000),
        "OBB_GOV_BREVE": compra("2021-01-05", alfa, "OBB_GOV_BREVE", 50_000),
        "ORO": compra("2021-01-05", alfa, "ORO", 25_000),
    }
    q["AZ_MONDO"] = compra("2021-01-05", beta, "AZ_MONDO", 55_000, costi=2.0)

    # Piano di accumulo mensile sul broker online
    for mese in pd.date_range("2021-02-01", FINE, freq="MS"):
        mov(mese, beta, "VERSAMENTO", importo=1_500)
        q["AZ_MONDO"] += compra(mese, beta, "AZ_MONDO", 1_495, costi=2.0)

    # Cedole semestrali del BTP, nette del 12,5%
    for anno in range(2021, 2027):
        for mese in ("02-01", "08-01"):
            d = f"{anno}-{mese}"
            if pd.Timestamp(d) <= pd.Timestamp(FINE):
                mov(d, alfa, "CEDOLA", "BTP_2032", importo=round(q["BTP_2032"] * 0.0125 * 0.875, 2))

    # Acquisto del bilocale a Torino con la liquidità del dossier
    mov("2022-03-15", alfa, "PRELIEVO", importo=-180_000)
    # Affitti netti e spese dell'immobile
    for mese in pd.date_range("2022-05-05", FINE, freq="MS") + pd.Timedelta(days=4):
        mov(mese, deposito, "AFFITTO", "TORINO", importo=750)
    for anno in range(2022, 2027):
        mov(f"{anno}-06-16", deposito, "SPESA_IMMOBILE", "TORINO", importo=-2_900)

    # Spese della famiglia e nuovi risparmi
    mov("2023-06-12", deposito, "PRELIEVO", importo=-25_000)
    mov("2025-09-15", deposito, "VERSAMENTO", importo=20_000)

    # Ribilanciamento parziale nel 2024: vendita di metà degli emergenti, acquisto di governativi a breve
    d = "2024-01-15"
    vendi = np.floor(q["AZ_EMERGENTI"] / 2)
    mov(d, alfa, "VENDITA", "AZ_EMERGENTI", vendi, round(prezzi.at[giorno(d), "AZ_EMERGENTI"], 4), 5.0)
    q["AZ_EMERGENTI"] -= vendi
    q["OBB_GOV_BREVE"] += compra("2024-01-17", alfa, "OBB_GOV_BREVE", 12_000)

    m = pd.DataFrame(righe).sort_values("data", kind="stable")
    # Imposta di bollo (0,2% dei titoli a fine anno) e interessi del conto deposito, calcolati sui saldi effettivi
    extra = []
    for anno in range(2021, 2026):
        fine = prezzi.index[prezzi.index.year == anno][-1]
        fino = m[m["data"] <= fine]
        for conto in (alfa, beta):
            t = fino[(fino["conto"] == conto) & fino["tipo"].isin(["ACQUISTO", "VENDITA"])]
            segno = np.where(t["tipo"] == "ACQUISTO", 1, -1)
            quantita = (t["quantita"] * segno).groupby(t["strumento"]).sum()
            valore = (quantita * prezzi.loc[fine, quantita.index] * fattore[quantita.index]).sum()
            extra.append(dict(data=fine, conto=conto, tipo="COSTO", strumento="", importo=-round(valore * 0.002, 2),
                              costi=0.0))
        tasso = 0.005 if anno < 2023 else 0.025
        saldo = fino.loc[fino["conto"] == deposito, "importo"].sum()
        extra.append(dict(data=fine, conto=deposito, tipo="INTERESSI", strumento="",
                          importo=round(saldo * tasso * 0.74, 2), costi=0.0))
    m = pd.concat([m, pd.DataFrame(extra)]).sort_values("data", kind="stable")
    m["data"] = m["data"].dt.strftime("%Y-%m-%d")
    return m[["data", "conto", "tipo", "strumento", "quantita", "prezzo", "costi", "importo"]]


IMMOBILI = pd.DataFrame(
    [
        dict(id="MILANO", nome="Abitazione principale", citta="Milano", uso="Abitazione principale",
             data_acquisto="2019-06-20", prezzo_acquisto=420_000, costi_acquisto=18_000, mutuo_importo=250_000,
             mutuo_tasso=0.016, mutuo_anni=25, mutuo_inizio="2019-07-01"),
        dict(id="TORINO", nome="Bilocale in affitto", citta="Torino", uso="A reddito",
             data_acquisto="2022-03-15", prezzo_acquisto=165_000, costi_acquisto=15_000, mutuo_importo=0,
             mutuo_tasso=0, mutuo_anni=0, mutuo_inizio=""),
    ]
)

VALUTAZIONI = pd.DataFrame(
    [
        ("2019-06-20", "MILANO", 420_000), ("2021-12-31", "MILANO", 445_000), ("2022-12-31", "MILANO", 458_000),
        ("2023-12-31", "MILANO", 466_000), ("2024-12-31", "MILANO", 484_000), ("2025-12-31", "MILANO", 499_000),
        ("2026-06-30", "MILANO", 508_000),
        ("2022-03-15", "TORINO", 165_000), ("2023-12-31", "TORINO", 167_000), ("2024-12-31", "TORINO", 171_000),
        ("2025-12-31", "TORINO", 176_000),
    ],
    columns=["data", "immobile", "valore"],
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    prezzi = genera_prezzi()
    prezzi.to_csv(OUT / "prezzi.csv", date_format="%Y-%m-%d")
    STRUMENTI.drop(columns=["p0", "vol"]).to_csv(OUT / "strumenti.csv")
    genera_movimenti(prezzi).to_csv(OUT / "movimenti.csv", index=False)
    IMMOBILI.to_csv(OUT / "immobili.csv", index=False)
    VALUTAZIONI.to_csv(OUT / "valutazioni_immobili.csv", index=False)
    print(f"Dati di esempio scritti in {OUT}")


if __name__ == "__main__":
    main()
