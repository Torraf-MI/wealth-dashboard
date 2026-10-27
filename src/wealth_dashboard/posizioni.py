"""Dai movimenti alle posizioni: quantità e liquidità giorno per giorno, costo medio, plusvalenze.

Il prezzo di carico segue il **metodo del costo medio ponderato** usato dagli intermediari italiani: gli acquisti
(commissioni comprese) aumentano il costo, le vendite lo riducono in proporzione alle quantità vendute.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .dati import LIQUIDITA, TIPI_TITOLI, Patrimonio


def importi(p: Patrimonio) -> pd.Series:
    """Effetto di ogni movimento sulla liquidità del conto (positivo = entrata).

    Per acquisti e vendite, se la colonna ``importo`` è vuota, l'importo è quantità × prezzo × fattore ± costi.
    """
    m = p.movimenti
    fattore = m["strumento"].map(p.strumenti["fattore"]).fillna(1.0)
    controvalore = m["quantita"] * m["prezzo"] * fattore
    calcolato = np.where(m["tipo"] == "ACQUISTO", -(controvalore + m["costi"]),
                         np.where(m["tipo"] == "VENDITA", controvalore - m["costi"], np.nan))
    return m["importo"].fillna(pd.Series(calcolato, index=m.index)).fillna(0.0)


def _allinea(p: Patrimonio, date: pd.Series) -> pd.DatetimeIndex:
    """Porta ogni data al primo giorno di borsa disponibile (movimenti nel fine settimana)."""
    pos = p.date.searchsorted(date.to_numpy())
    return p.date[np.minimum(pos, len(p.date) - 1)]


def quantita(p: Patrimonio, per_conto: bool = False) -> pd.DataFrame:
    """Quantità detenute a fine giornata per ogni strumento (colonne), su tutti i giorni di borsa."""
    m = p.movimenti[p.movimenti["tipo"].isin(TIPI_TITOLI)]
    if m.empty:
        return pd.DataFrame(0.0, index=p.date, columns=[] if per_conto else p.strumenti.index)
    segno = m["tipo"].map(TIPI_TITOLI).astype(float)
    chiavi = [m["conto"], m["strumento"]] if per_conto else [m["strumento"]]
    delta = (m["quantita"] * segno).groupby([_allinea(p, m["data"]), *chiavi]).sum()
    livelli = list(range(1, len(chiavi) + 1))
    tabella = delta.unstack(livelli)
    tabella = tabella.reindex(p.date).fillna(0.0).cumsum()
    if not per_conto:
        tabella = tabella.reindex(columns=p.strumenti.index, fill_value=0.0)
    return tabella


def liquidita(p: Patrimonio) -> pd.DataFrame:
    """Saldo di liquidità a fine giornata per ogni conto."""
    m = p.movimenti
    delta = importi(p).groupby([_allinea(p, m["data"]), m["conto"]]).sum().unstack(1)
    return delta.reindex(p.date).fillna(0.0).cumsum().reindex(columns=p.conti, fill_value=0.0)


def valori(p: Patrimonio) -> pd.DataFrame:
    """Valore di mercato giornaliero di ogni strumento più la colonna della liquidità totale."""
    v = quantita(p) * p.prezzi[p.strumenti.index] * p.strumenti["fattore"]
    v[LIQUIDITA] = liquidita(p).sum(axis=1)
    return v


def flussi_esterni(p: Patrimonio) -> pd.Series:
    """Versamenti (+) e prelievi (−) del patrimonio finanziario per giorno: non fanno parte del rendimento."""
    m = p.movimenti
    esterni = m["tipo"].isin(["VERSAMENTO", "PRELIEVO", "AFFITTO", "SPESA_IMMOBILE"])
    serie = importi(p)[esterni].groupby(_allinea(p, m.loc[esterni, "data"])).sum()
    return serie.reindex(p.date).fillna(0.0)


def costo_medio(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> pd.DataFrame:
    """Per ogni conto e strumento: quantità, costo di carico residuo e plusvalenze realizzate fino alla data."""
    m = p.movimenti[p.movimenti["tipo"].isin(TIPI_TITOLI)]
    if alla_data is not None:
        m = m[m["data"] <= alla_data]
    fattore = p.strumenti["fattore"]
    stato: dict[tuple[str, str], list[float]] = {}  # quantità, costo, realizzato
    for r in m.itertuples(index=False):
        q, costo, realizzato = stato.setdefault((r.conto, r.strumento), [0.0, 0.0, 0.0])
        lordo = r.quantita * r.prezzo * fattore[r.strumento]
        if r.tipo == "ACQUISTO":
            q, costo = q + r.quantita, costo + lordo + r.costi
        else:
            if r.quantita > q + 1e-9:
                raise ValueError(f"Vendita di {r.quantita:g} {r.strumento} su {r.conto}: in portafoglio {q:g}")
            quota = costo * r.quantita / q
            realizzato += lordo - r.costi - quota
            q, costo = q - r.quantita, costo - quota
        stato[(r.conto, r.strumento)] = [q, costo, realizzato]
    righe = [(c, s, *v) for (c, s), v in stato.items()]
    return pd.DataFrame(righe, columns=["conto", "strumento", "quantita", "costo", "realizzato"])


def situazione(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> pd.DataFrame:
    """Fotografia delle posizioni a una data: una riga per conto e strumento più una per la liquidità di ogni conto.

    Colonne: conto, strumento, nome, classe, quantita, prezzo, valore, costo, plusvalenza, plusvalenza_pct,
    imposta_latente, peso (sul patrimonio finanziario).
    """
    data = data_valida(p, alla_data)
    cm =costo_medio(p, data)
    cm = cm[cm["quantita"].abs() > 1e-9].copy()
    s = p.strumenti
    cm["nome"] = cm["strumento"].map(s["nome"])
    cm["classe"] = cm["strumento"].map(s["classe"])
    cm["prezzo"] = cm["strumento"].map(p.prezzi.loc[data])
    cm["valore"] = cm["quantita"] * cm["prezzo"] * cm["strumento"].map(s["fattore"])
    cm["plusvalenza"] = cm["valore"] - cm["costo"]
    cm["imposta_latente"] = cm["plusvalenza"].clip(lower=0) * cm["strumento"].map(s["aliquota"])

    cassa = liquidita(p).loc[data]
    righe_cassa = pd.DataFrame({"conto": cassa.index, "strumento": LIQUIDITA, "nome": "Liquidità",
                                "classe": LIQUIDITA, "quantita": np.nan, "prezzo": np.nan, "valore": cassa.values,
                                "costo": cassa.values, "plusvalenza": 0.0, "imposta_latente": 0.0, "realizzato": 0.0})
    t = pd.concat([cm, righe_cassa[righe_cassa["valore"].abs() > 0.005]], ignore_index=True)
    titoli = (t["costo"] > 0) & (t["classe"] != LIQUIDITA)
    t["plusvalenza_pct"] = np.where(titoli, t["plusvalenza"] / t["costo"], np.nan)
    totale = t["valore"].sum()
    t["peso"] = t["valore"] / totale if totale else 0.0
    colonne = ["conto", "strumento", "nome", "classe", "quantita", "prezzo", "valore", "costo", "plusvalenza",
               "plusvalenza_pct", "imposta_latente", "realizzato", "peso"]
    return t[colonne].sort_values(["conto", "classe", "valore"], ascending=[True, True, False]).reset_index(drop=True)


def data_valida(p: Patrimonio, alla_data: pd.Timestamp | None) -> pd.Timestamp:
    """Ultimo giorno di borsa non successivo alla data richiesta."""
    if alla_data is None:
        return p.date[-1]
    i = p.date.searchsorted(pd.Timestamp(alla_data), side="right") - 1
    return p.date[max(i, 0)]
