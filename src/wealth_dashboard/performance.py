"""Performance del patrimonio finanziario: rendimento ponderato per il tempo (TWR) e per il denaro (MWR), rischio,
confronto con il benchmark e contributo di ogni strumento.

- **TWR** (*time-weighted return*): misura la bontà delle scelte di investimento, indipendentemente da quando il
  cliente ha versato o prelevato. I rendimenti giornalieri sono concatenati e i flussi esterni del giorno sono
  considerati a fine giornata: ``r_t = (V_t − F_t) / V_{t−1} − 1``.
- **MWR** (*money-weighted return*, TIR): il rendimento effettivamente ottenuto dal cliente, che dipende anche dai
  tempi dei versamenti. È il tasso che azzera il valore attuale dei flussi (metodo XIRR, giorni effettivi / 365).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import posizioni
from .dati import LIQUIDITA, TIPI_PROVENTI, TIPI_TITOLI, Patrimonio

GIORNI_ANNO = 252
MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def xirr(flussi: pd.Series) -> float:
    """Tasso interno di rendimento annuo di flussi datati (indice = date, valori con segno).

    Restituisce ``nan`` se i flussi non cambiano segno. Il tasso si trova per bisezione, che converge sempre
    quando la soluzione è nell'intervallo (−99%, +1000%).
    """
    flussi = flussi[flussi != 0]
    if flussi.empty or (flussi > 0).all() or (flussi < 0).all():
        return float("nan")
    anni = ((flussi.index - flussi.index[0]).days / 365.0).to_numpy()
    importi = flussi.to_numpy(dtype=float)

    def van(t: float) -> float:
        return float(np.sum(importi / (1 + t) ** anni))

    basso, alto = -0.99, 10.0
    f_basso = van(basso)
    if f_basso * van(alto) > 0:
        return float("nan")
    for _ in range(200):
        medio = (basso + alto) / 2
        f_medio = van(medio)
        if abs(f_medio) < 1e-9 or alto - basso < 1e-12:
            break
        if f_basso * f_medio < 0:
            alto = medio
        else:
            basso, f_basso = medio, f_medio
    return medio


def valore_totale(p: Patrimonio) -> pd.Series:
    return posizioni.valori(p).sum(axis=1)


def rendimenti_giornalieri(p: Patrimonio) -> pd.Series:
    """Rendimenti TWR giornalieri del patrimonio finanziario, dal primo giorno con un valore positivo."""
    v = valore_totale(p)
    f = posizioni.flussi_esterni(p)
    precedente = v.shift(1)
    r = (v - f) / precedente - 1
    r = r.where(precedente > 0, 0.0)
    inizio = v.index[(v > 0).to_numpy().argmax()]
    return r.loc[inizio:].iloc[1:].rename("Portafoglio")


def rendimenti_benchmark(p: Patrimonio) -> pd.Series | None:
    """Benchmark a pesi costanti (ribilanciato ogni giorno) sugli strumenti indicati in ``strategia.toml``."""
    pesi = {k: v for k, v in p.strategia.benchmark.items() if k != LIQUIDITA}
    if not pesi:
        return None
    r = p.prezzi[list(pesi)].pct_change().fillna(0.0)
    return (r * pd.Series(pesi)).sum(axis=1).rename("Benchmark")


def indice(rendimenti: pd.Series, base: float = 100.0) -> pd.Series:
    return base * (1 + rendimenti).cumprod()


def drawdown(rendimenti: pd.Series) -> pd.Series:
    """Perdita percentuale dal massimo precedente (valori ≤ 0)."""
    livello = (1 + rendimenti).cumprod()
    return livello / livello.cummax().clip(lower=1.0) - 1


def _composto(r: pd.Series) -> float:
    return float((1 + r).prod() - 1)


def _annualizza(totale: float, giorni_calendario: int) -> float:
    anni = giorni_calendario / 365.0
    return (1 + totale) ** (1 / anni) - 1 if anni > 0 else float("nan")


def mwr(p: Patrimonio, inizio: pd.Timestamp | None, fine: pd.Timestamp) -> float:
    """Rendimento ponderato per il denaro (annuo) tra due date: valore iniziale, flussi esterni, valore finale."""
    v = valore_totale(p)
    f = posizioni.flussi_esterni(p)
    if inizio is None:
        flussi = -f.loc[:fine]
    else:
        flussi = pd.concat([pd.Series({inizio: -v.loc[inizio]}), -f.loc[inizio:fine].iloc[1:]])
    flussi = flussi.groupby(level=0).sum()
    flussi.loc[fine] = flussi.get(fine, 0.0) + v.loc[fine]
    return xirr(flussi.sort_index())


def periodi(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> pd.DataFrame:
    """Rendimenti per periodo standard: da inizio anno, 12 mesi, 3 anni (annuo), dall'inizio (annuo)."""
    fine = posizioni.data_valida(p, alla_data)
    r = rendimenti_giornalieri(p).loc[:fine]
    b = rendimenti_benchmark(p)
    b = b.loc[r.index] if b is not None else None
    primo = r.index[0] - pd.Timedelta(days=1)
    date = p.date
    definizioni = [
        ("Da inizio anno", pd.Timestamp(year=fine.year, month=1, day=1) - pd.Timedelta(days=1), False),
        ("Ultimi 12 mesi", fine - pd.DateOffset(years=1), False),
        ("Ultimi 3 anni (annuo)", fine - pd.DateOffset(years=3), True),
        ("Dall'inizio (annuo)", None, True),
    ]
    righe = []
    for nome, da, annuo in definizioni:
        if da is not None and da < primo - pd.Timedelta(days=7):
            continue
        sel = r.loc[r.index > da] if da is not None else r
        tot = _composto(sel)
        bench = _composto(b.loc[sel.index]) if b is not None else np.nan
        giorni = (fine - (da if da is not None else primo)).days
        if annuo:
            tot, bench = _annualizza(tot, giorni), _annualizza(bench, giorni)
        partenza = None if da is None else date[max(date.searchsorted(da, side="right") - 1, 0)]
        m = mwr(p, partenza, fine)
        if not annuo:
            m = (1 + m) ** (giorni / 365.0) - 1 if not np.isnan(m) else m
        righe.append({"Periodo": nome, "Portafoglio (TWR)": tot, "Benchmark": bench,
                      "Differenza": tot - bench, "Rendimento del cliente (MWR)": m})
    return pd.DataFrame(righe).set_index("Periodo")


def rischio(p: Patrimonio, alla_data: pd.Timestamp | None = None, anni: int = 3) -> dict[str, float]:
    """Volatilità, massima perdita, perdita attuale dal massimo, mesi migliore e peggiore (ultimi ``anni``)."""
    fine = posizioni.data_valida(p, alla_data)
    r = rendimenti_giornalieri(p).loc[:fine]
    r = r.loc[r.index > fine - pd.DateOffset(years=anni)]
    dd = drawdown(rendimenti_giornalieri(p).loc[:fine])
    if r.empty:
        return dict.fromkeys(["Volatilità annua", "Massima perdita dal picco", "Perdita attuale dal massimo",
                              "Mese migliore", "Mese peggiore"], float("nan"))
    mesi = (1 + r).resample("ME").prod() - 1
    return {
        "Volatilità annua": float(r.std() * np.sqrt(GIORNI_ANNO)),
        "Massima perdita dal picco": float(drawdown(r).min()),
        "Perdita attuale dal massimo": float(dd.iloc[-1]),
        "Mese migliore": float(mesi.max()),
        "Mese peggiore": float(mesi.min()),
    }


def rendimenti_mensili(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> pd.DataFrame:
    """Tabella anno × mese dei rendimenti TWR, con il totale dell'anno."""
    fine = posizioni.data_valida(p, alla_data)
    r = rendimenti_giornalieri(p).loc[:fine]
    mesi = (1 + r).resample("ME").prod() - 1
    t = pd.DataFrame({"anno": mesi.index.year, "mese": mesi.index.month, "r": mesi.values})
    tabella = t.pivot(index="anno", columns="mese", values="r").reindex(columns=range(1, 13))
    tabella.columns = MESI
    tabella["Anno"] = (1 + r).groupby(r.index.year).prod() - 1
    return tabella


def contributi(p: Patrimonio, inizio: pd.Timestamp | None = None, fine: pd.Timestamp | None = None) -> pd.DataFrame:
    """Utile o perdita in euro di ogni strumento nel periodo (inizio, fine]: variazione di valore più incassi netti.

    La riga "Liquidità" raccoglie interessi e costi non legati a uno strumento (bollo, canoni). La somma è
    l'utile complessivo: variazione del patrimonio finanziario al netto di versamenti e prelievi.
    """
    fine = posizioni.data_valida(p, fine)
    v = posizioni.valori(p)
    inizio = v.index[0] if inizio is None else posizioni.data_valida(p, inizio)
    m = p.movimenti.assign(importo=posizioni.importi(p), giorno=posizioni._allinea(p, p.movimenti["data"]))
    m = m[(m["giorno"] > inizio) & (m["giorno"] <= fine)]
    interni = m[m["tipo"].isin(TIPI_TITOLI) | m["tipo"].isin(TIPI_PROVENTI)]
    per_strumento = interni["importo"].groupby(interni["strumento"].fillna("").replace("", LIQUIDITA)).sum()
    strumenti = list(p.strumenti.index)
    delta = v.loc[fine, strumenti] - v.loc[inizio, strumenti]
    utile = delta.add(per_strumento.reindex(strumenti).fillna(0.0))
    utile[LIQUIDITA] = per_strumento.get(LIQUIDITA, 0.0)
    nomi = p.strumenti["nome"].to_dict() | {LIQUIDITA: "Interessi e costi"}
    classi = p.strumenti["classe"].to_dict() | {LIQUIDITA: LIQUIDITA}
    t = pd.DataFrame({"nome": utile.index.map(nomi), "classe": utile.index.map(classi), "utile": utile.values},
                     index=utile.index.rename("strumento"))
    t = t[(t["utile"].abs() > 0.005) | (v.loc[fine, strumenti].reindex(t.index).fillna(0) != 0)]
    return t.sort_values("utile", ascending=False)
