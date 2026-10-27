"""Allocazione del patrimonio: per classe di attività rispetto all'obiettivo, per conto, patrimonio netto nel tempo."""

from __future__ import annotations

import pandas as pd

from . import immobili, posizioni
from .dati import LIQUIDITA, Patrimonio


def per_classe(p: Patrimonio, alla_data: pd.Timestamp | None = None, nuova_liquidita: float = 0.0) -> pd.DataFrame:
    """Peso attuale e obiettivo di ogni classe nel patrimonio finanziario, con banda di tolleranza.

    ``scostamento`` è in punti (0,03 = 3 punti percentuali), ``scostamento_euro`` è l'importo da vendere (se
    positivo) o da comprare (se negativo) per tornare all'obiettivo.
    """
    s = posizioni.situazione(p, alla_data)
    valore = s.groupby("classe")["valore"].sum()
    valore.loc[LIQUIDITA] = valore.get(LIQUIDITA, 0.0) + nuova_liquidita
    obiettivo = pd.DataFrame({k: {"obiettivo": c.peso, "banda": c.banda} for k, c in p.strategia.obiettivo.items()}).T
    t = obiettivo.join(valore.rename("valore"), how="outer").fillna({"valore": 0.0, "obiettivo": 0.0, "banda": 0.0})
    totale = t["valore"].sum()
    t["peso"] = t["valore"] / totale
    t["scostamento"] = t["peso"] - t["obiettivo"]
    t["minimo"] = (t["obiettivo"] - t["banda"]).clip(lower=0)
    t["massimo"] = t["obiettivo"] + t["banda"]
    t["fuori_banda"] = t["scostamento"].abs() > t["banda"] + 1e-12
    t["scostamento_euro"] = t["valore"] - t["obiettivo"] * totale
    ordine = list(p.strategia.obiettivo) + [c for c in t.index if c not in p.strategia.obiettivo]
    return t.loc[ordine, ["valore", "peso", "obiettivo", "banda", "minimo", "massimo", "scostamento",
                          "scostamento_euro", "fuori_banda"]].rename_axis("classe")


def per_conto(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> pd.DataFrame:
    """Valore per conto (righe) e classe (colonne)."""
    s = posizioni.situazione(p, alla_data)
    t = s.pivot_table(index="conto", columns="classe", values="valore", aggfunc="sum", fill_value=0.0)
    return t.reindex(columns=[c for c in p.strategia.obiettivo if c in t.columns])


def patrimonio_netto(p: Patrimonio) -> pd.DataFrame:
    """Serie giornaliera di patrimonio finanziario, immobili, mutui (negativi) e patrimonio netto."""
    fin = posizioni.valori(p).sum(axis=1)
    imm = immobili.valori(p).sum(axis=1)
    deb = immobili.debiti(p).sum(axis=1)
    return pd.DataFrame({"Finanziario": fin, "Immobili": imm, "Mutui": -deb, "Patrimonio netto": fin + imm - deb})


def sintesi(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> dict[str, float]:
    """Cifre chiave a una data."""
    data = posizioni.data_valida(p, alla_data)
    s = posizioni.situazione(p, data)
    imm = immobili.valori(p, pd.DatetimeIndex([data])).iloc[0].sum()
    deb = immobili.debiti(p, pd.DatetimeIndex([data])).iloc[0].sum()
    fin = s["valore"].sum()
    netto = fin + imm - deb
    return {
        "Patrimonio netto": netto,
        "Patrimonio finanziario": fin,
        "Immobili": imm,
        "Mutui": deb,
        "Liquidità": s.loc[s["classe"] == LIQUIDITA, "valore"].sum(),
        "Quota immobiliare netta": (imm - deb) / netto if netto else 0.0,
        "Plusvalenze latenti": s["plusvalenza"].sum(),
        "Imposte latenti": s["imposta_latente"].sum(),
    }
