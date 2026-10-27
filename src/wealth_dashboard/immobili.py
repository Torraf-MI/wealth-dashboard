"""Patrimonio immobiliare: valore stimato nel tempo, debito residuo dei mutui, redditività degli immobili a reddito.

Il valore di un immobile tra due valutazioni (perizie, stime di mercato, quotazioni OMI) è interpolato linearmente;
dopo l'ultima valutazione resta costante. Il debito residuo segue il piano di ammortamento alla francese (rata
mensile costante).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import posizioni
from .dati import Patrimonio
from .performance import xirr


def rata(importo: float, tasso: float, anni: float) -> float:
    """Rata mensile costante di un mutuo alla francese."""
    n = int(round(anni * 12))
    if importo <= 0 or n <= 0:
        return 0.0
    i = tasso / 12
    return importo / n if i == 0 else importo * i / (1 - (1 + i) ** -n)


def debito_residuo(importo: float, tasso: float, anni: float, inizio: pd.Timestamp, data: pd.Timestamp) -> float:
    """Capitale ancora da rimborsare alla data, dopo le rate mensili scadute (la prima un mese dopo l'inizio)."""
    n = int(round(anni * 12))
    if importo <= 0 or n <= 0 or pd.isna(inizio) or data < inizio:
        return 0.0 if importo <= 0 or n <= 0 or pd.isna(inizio) else float(importo)
    pagate = (data.year - inizio.year) * 12 + data.month - inizio.month - (data.day < inizio.day)
    k = min(max(pagate, 0), n)
    i = tasso / 12
    if i == 0:
        return float(importo * (1 - k / n))
    r = rata(importo, tasso, anni)
    return float(max(importo * (1 + i) ** k - r * ((1 + i) ** k - 1) / i, 0.0))


def valori(p: Patrimonio, date: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Valore stimato di ogni immobile (colonne) per data; zero prima dell'acquisto."""
    date = p.date if date is None else date
    out = pd.DataFrame(index=date)
    giorni = date.to_numpy().astype("datetime64[ns]").astype("int64")
    for id_, imm in p.immobili.iterrows():
        v = p.valutazioni[p.valutazioni["immobile"] == id_][["data", "valore"]]
        if (v["data"] <= imm["data_acquisto"]).sum() == 0:
            v = pd.concat([pd.DataFrame({"data": [imm["data_acquisto"]], "valore": [imm["prezzo_acquisto"]]}), v])
        v = v.sort_values("data")
        serie = np.interp(giorni, v["data"].to_numpy().astype("datetime64[ns]").astype("int64"), v["valore"])
        out[id_] = np.where(date >= imm["data_acquisto"], serie, 0.0)
    return out


def debiti(p: Patrimonio, date: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Debito residuo dei mutui per immobile (colonne) e data; zero prima dell'acquisto."""
    date = p.date if date is None else date
    out = pd.DataFrame(index=date)
    for id_, imm in p.immobili.iterrows():
        if imm["mutuo_importo"] <= 0:
            out[id_] = 0.0
            continue
        residuo = [debito_residuo(imm["mutuo_importo"], imm["mutuo_tasso"], imm["mutuo_anni"], imm["mutuo_inizio"], d)
                   for d in date]
        out[id_] = np.where(date >= imm["data_acquisto"], residuo, 0.0)
    return out


def _flussi_immobile(p: Patrimonio, id_: str) -> pd.DataFrame:
    m = p.movimenti
    sel = m[(m["strumento"] == id_) & m["tipo"].isin(["AFFITTO", "SPESA_IMMOBILE"])]
    return sel.assign(importo=posizioni.importi(p)[sel.index])


def riepilogo(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> pd.DataFrame:
    """Una riga per immobile: valore, plusvalenza, mutuo, patrimonio netto, LTV, reddito e rendimenti."""
    data = posizioni.data_valida(p, alla_data)
    righe = []
    for id_, imm in p.immobili.iterrows():
        if imm["data_acquisto"] > data:
            continue
        valore = float(valori(p, pd.DatetimeIndex([data]))[id_].iloc[0])
        debito = debito_residuo(imm["mutuo_importo"], imm["mutuo_tasso"], imm["mutuo_anni"],
                                imm["mutuo_inizio"], data)
        costo = imm["prezzo_acquisto"] + imm["costi_acquisto"]
        f = _flussi_immobile(p, id_)
        f = f[f["data"] <= data]
        ultimi = f[f["data"] > data - pd.DateOffset(years=1)]
        canoni = ultimi.loc[ultimi["tipo"] == "AFFITTO", "importo"].sum()
        spese = -ultimi.loc[ultimi["tipo"] == "SPESA_IMMOBILE", "importo"].sum()
        # Rendimento totale annuo dell'immobile (senza leva): acquisto, redditi e spese, valore attuale
        flussi = pd.concat([pd.Series({imm["data_acquisto"]: -costo}),
                            f.set_index("data")["importo"], pd.Series({data: valore})])
        righe.append({
            "immobile": id_, "nome": imm["nome"], "citta": imm["citta"], "uso": imm["uso"],
            "data_acquisto": imm["data_acquisto"], "costo": costo, "valore": valore,
            "plusvalenza": valore - costo, "debito": debito, "netto": valore - debito,
            "ltv": debito / valore if valore else np.nan,
            "rata_mensile": rata(imm["mutuo_importo"], imm["mutuo_tasso"], imm["mutuo_anni"]) if debito > 0 else 0.0,
            "canoni_12m": canoni, "spese_12m": spese, "reddito_netto_12m": canoni - spese,
            "rendimento_netto": (canoni - spese) / valore if canoni else np.nan,
            "rendimento_totale_annuo": xirr(flussi.groupby(level=0).sum()),
        })
    return pd.DataFrame(righe).set_index("immobile") if righe else pd.DataFrame()
