"""Segnali di monitoraggio e proposta di ribilanciamento del patrimonio finanziario.

Due metodi di ribilanciamento:

- ``"obiettivo"``: riporta tutte le classi ai pesi obiettivo, vendendo ciò che è in eccesso;
- ``"solo_acquisti"``: non vende nulla e usa la liquidità in eccesso (più l'eventuale nuova liquidità) per
  comprare le classi sottopesate, in proporzione a quanto mancano. Ribilancia più lentamente ma non realizza
  plusvalenze, quindi non genera imposte.

Le imposte sulle vendite sono stimate con il costo medio di carico e l'aliquota di ogni strumento (26%, 12,5% per i
titoli di Stato), senza compensazione con eventuali minusvalenze pregresse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from . import allocazione, immobili, performance, posizioni
from .dati import LIQUIDITA, Patrimonio

LIVELLI = {"alto": 0, "medio": 1, "info": 2}


def _eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def _pct(x: float, decimali: int = 1) -> str:
    return f"{x * 100:.{decimali}f}%".replace(".", ",")


def _punti(x: float) -> str:
    return f"{abs(x) * 100:.1f} punti".replace(".", ",")


@dataclass(frozen=True)
class Segnale:
    livello: Literal["alto", "medio", "info"]
    area: str
    titolo: str
    dettaglio: str


def segnali(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> list[Segnale]:
    """Controlla allocazione, liquidità, concentrazione, mutui e andamento; restituisce i segnali per gravità."""
    data = posizioni.data_valida(p, alla_data)
    st, lim = p.strategia, p.strategia.limiti
    out: list[Segnale] = []

    alloc = allocazione.per_classe(p, data)
    for classe, r in alloc[alloc["fuori_banda"]].iterrows():
        sopra = r["scostamento"] > 0
        out.append(Segnale(
            "alto" if abs(r["scostamento"]) > 1.5 * r["banda"] else "medio", "Allocazione",
            f"{classe} {'sopra' if sopra else 'sotto'} la banda di tolleranza",
            f"Pesa il {_pct(r['peso'])} contro un obiettivo del {_pct(r['obiettivo'], 0)} "
            f"(banda ±{_punti(r['banda'])}): {'sovrappeso' if sopra else 'sottopeso'} di {_punti(r['scostamento'])}, "
            f"circa {_eur(abs(r['scostamento_euro']))} da {'ridurre' if sopra else 'integrare'}.",
        ))

    sit = posizioni.situazione(p, data)
    cassa = sit.loc[sit["classe"] == LIQUIDITA, "valore"].sum()
    if st.spesa_mensile > 0:
        mesi = cassa / st.spesa_mensile
        if mesi < st.mesi_liquidita_minima:
            out.append(Segnale(
                "alto", "Liquidità", "Riserva di liquidità sotto il minimo",
                f"{_eur(cassa)} coprono {f'{mesi:.1f}'.replace('.', ',')} mesi di spesa familiare contro i "
                f"{st.mesi_liquidita_minima:g} previsti: mancano "
                f"{_eur(st.spesa_mensile * st.mesi_liquidita_minima - cassa)}.",
            ))

    titoli = sit[sit["classe"] != LIQUIDITA].groupby(["strumento", "nome"])["peso"].sum()
    for (_, nome), peso in titoli[titoli > lim.peso_massimo_strumento].items():
        out.append(Segnale(
            "medio", "Concentrazione", f"{nome}: peso elevato",
            f"Rappresenta il {_pct(peso)} del patrimonio finanziario, oltre il limite del "
            f"{_pct(lim.peso_massimo_strumento, 0)} per singolo strumento.",
        ))

    sintesi = allocazione.sintesi(p, data)
    if sintesi["Quota immobiliare netta"] > lim.quota_immobiliare_massima:
        out.append(Segnale(
            "medio", "Immobili", "Patrimonio concentrato negli immobili",
            f"Gli immobili, al netto dei mutui, sono il {_pct(sintesi['Quota immobiliare netta'])} del patrimonio "
            f"netto (limite {_pct(lim.quota_immobiliare_massima, 0)}). Non si riequilibra in tempi brevi: conviene "
            "destinare i nuovi risparmi alla parte finanziaria.",
        ))

    for _, r in immobili.riepilogo(p, data).iterrows():
        if r["ltv"] > lim.ltv_massimo:
            out.append(Segnale(
                "alto", "Mutui", f"{r['nome']}: mutuo elevato rispetto al valore",
                f"Debito residuo di {_eur(r['debito'])} su un valore stimato di {_eur(r['valore'])} "
                f"(LTV {_pct(r['ltv'], 0)}, limite {_pct(lim.ltv_massimo, 0)}).",
            ))

    dd = performance.rischio(p, data)["Perdita attuale dal massimo"]
    if not np.isnan(dd) and dd < -lim.drawdown_allerta:
        out.append(Segnale(
            "medio", "Andamento", "Portafoglio in calo dal massimo",
            f"Il portafoglio finanziario è del {_pct(-dd)} sotto il valore massimo raggiunto (soglia di attenzione "
            f"{_pct(lim.drawdown_allerta, 0)}). Non è di per sé un motivo per vendere: è il momento di verificare che "
            "il piano resti sostenibile e, se le bande lo richiedono, di ribilanciare.",
        ))

    if not any(s.livello in ("alto", "medio") for s in out):
        out.append(Segnale("info", "Allocazione", "Patrimonio in linea con la strategia",
                           "Tutte le classi sono dentro le bande di tolleranza e i limiti sono rispettati."))
    return sorted(out, key=lambda s: LIVELLI[s.livello])


# --------------------------------------------------------------------------- #
# Proposta di operazioni
# --------------------------------------------------------------------------- #
def _ripartisci(p: Patrimonio, sit: pd.DataFrame, classe: str, importo: float) -> list[tuple[str, str, float]]:
    """Divide un importo (positivo = acquisto, negativo = vendita) tra conti e strumenti di una classe."""
    posizioni_classe = sit[sit["classe"] == classe]
    preferito = p.strategia.strumenti_preferiti.get(classe)
    if importo > 0 and preferito:
        su = posizioni_classe[posizioni_classe["strumento"] == preferito]
        conto = su.sort_values("valore")["conto"].iloc[-1] if len(su) else \
            sit[sit["classe"] == LIQUIDITA].sort_values("valore")["conto"].iloc[-1]
        return [(conto, preferito, importo)]
    if posizioni_classe.empty:
        if importo < 0:
            return []
        strumento = p.strumenti.index[p.strumenti["classe"] == classe][0]
        conto = sit[sit["classe"] == LIQUIDITA].sort_values("valore")["conto"].iloc[-1]
        return [(conto, strumento, importo)]
    quote = posizioni_classe["valore"] / posizioni_classe["valore"].sum()
    return [(r.conto, r.strumento, importo * q) for r, q in zip(posizioni_classe.itertuples(), quote)]


def operazioni(
    p: Patrimonio,
    alla_data: pd.Timestamp | None = None,
    metodo: Literal["obiettivo", "solo_acquisti"] = "obiettivo",
    nuova_liquidita: float = 0.0,
    importo_minimo: float = 500.0,
) -> pd.DataFrame:
    """Operazioni proposte per avvicinare il patrimonio finanziario all'allocazione obiettivo.

    Le quantità sono arrotondate per difetto al lotto minimo di ogni strumento; le operazioni sotto
    ``importo_minimo`` sono tralasciate.
    """
    data = posizioni.data_valida(p, alla_data)
    alloc = allocazione.per_classe(p, data, nuova_liquidita)
    sit = posizioni.situazione(p, data)
    if nuova_liquidita and not (sit["classe"] == LIQUIDITA).any():
        sit = pd.concat([sit, pd.DataFrame([{"conto": p.conti[0], "strumento": LIQUIDITA, "classe": LIQUIDITA,
                                             "valore": 0.0}])], ignore_index=True)
    rischiose = alloc.drop(index=LIQUIDITA, errors="ignore")
    totale = alloc["valore"].sum()

    if metodo == "obiettivo":
        variazioni = -rischiose["scostamento_euro"]
    elif metodo == "solo_acquisti":
        disponibile = alloc.loc[LIQUIDITA, "valore"] - alloc.loc[LIQUIDITA, "obiettivo"] * totale
        mancanze = (-rischiose["scostamento_euro"]).clip(lower=0)
        if disponibile <= 0 or mancanze.sum() <= 0:
            variazioni = mancanze * 0
        else:
            variazioni = mancanze * min(disponibile, mancanze.sum()) / mancanze.sum()
    else:
        raise ValueError("metodo deve essere 'obiettivo' o 'solo_acquisti'")

    costo = posizioni.costo_medio(p, data).set_index(["conto", "strumento"])
    prezzi = p.prezzi.loc[data]
    righe = []
    for classe, importo in variazioni.items():
        if abs(importo) < importo_minimo:
            continue
        for conto, strumento, quota in _ripartisci(p, sit, classe, importo):
            s = p.strumenti.loc[strumento]
            unitario = prezzi[strumento] * s["fattore"]
            q = np.floor(abs(quota) / unitario / s["lotto"]) * s["lotto"]
            controvalore = q * unitario
            if q <= 0 or controvalore < importo_minimo:
                continue
            plus = imposta = 0.0
            if quota < 0:
                c = costo.loc[(conto, strumento)]
                plus = controvalore - c["costo"] * q / c["quantita"]
                imposta = max(plus, 0.0) * s["aliquota"]
            righe.append({
                "classe": classe, "conto": conto, "strumento": strumento, "nome": s["nome"],
                "operazione": "Acquista" if quota > 0 else "Vendi", "quantita": q, "prezzo": prezzi[strumento],
                "importo": controvalore if quota > 0 else -controvalore,
                "plusvalenza_realizzata": plus, "imposta_stimata": imposta,
            })
    colonne = ["classe", "conto", "strumento", "nome", "operazione", "quantita", "prezzo", "importo",
               "plusvalenza_realizzata", "imposta_stimata"]
    return pd.DataFrame(righe, columns=colonne).sort_values(["operazione", "importo"], ascending=[False, True],
                                                            ignore_index=True)


def allocazione_dopo(p: Patrimonio, ops: pd.DataFrame, alla_data: pd.Timestamp | None = None,
                     nuova_liquidita: float = 0.0) -> pd.DataFrame:
    """Allocazione per classe prima e dopo le operazioni proposte (imposte pagate con la liquidità)."""
    alloc = allocazione.per_classe(p, alla_data, nuova_liquidita)
    dopo = alloc["valore"].copy()
    for classe, importo in ops.groupby("classe")["importo"].sum().items():
        dopo[classe] += importo
    dopo[LIQUIDITA] -= ops["importo"].sum() + ops["imposta_stimata"].sum()
    return pd.DataFrame({"prima": alloc["peso"], "dopo": dopo / dopo.sum(), "obiettivo": alloc["obiettivo"],
                         "minimo": alloc["minimo"], "massimo": alloc["massimo"]})
