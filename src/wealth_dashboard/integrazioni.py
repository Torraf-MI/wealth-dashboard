"""Collegamenti con gli altri progetti della serie: i dati della dashboard diventano input per analisi più profonde.

- `portfolio-optimizer <https://github.com/Torraf-MI/portfolio-optimizer>`_: legge i prezzi nello stesso
  formato CSV (``--csv``);
- `wealth-planner-montecarlo <https://github.com/Torraf-MI/wealth-planner-montecarlo>`_: riceve patrimonio e
  allocazione attuali in un file TOML di ipotesi;
- `real-estate-analyzer <https://github.com/Torraf-MI/real-estate-analyzer>`_: valuta un nuovo acquisto immobiliare
  prima che entri nel patrimonio.
"""

from __future__ import annotations

import pandas as pd

from . import allocazione, posizioni
from .dati import LIQUIDITA, Patrimonio

PROGETTI = {
    "portfolio-optimizer": (
        "https://github.com/Torraf-MI/portfolio-optimizer",
        "Ottimizzazione del portafoglio (Markowitz, risk parity) e backtest: per ridefinire l'allocazione obiettivo.",
    ),
    "real-estate-analyzer": (
        "https://github.com/Torraf-MI/real-estate-analyzer",
        "Valutazione di un investimento immobiliare con mutuo e fiscalità italiana: prima di un nuovo acquisto.",
    ),
    "wealth-planner-montecarlo": (
        "https://github.com/Torraf-MI/wealth-planner-montecarlo",
        "Pianificazione Monte Carlo: il patrimonio attuale basta per gli obiettivi e la pensione?",
    ),
}

# Classi della dashboard -> classi del wealth planner. L'oro, attività rischiosa e volatile, va con le azioni.
MAPPA_PLANNER = {"Azionario": "azioni", "Oro": "azioni", "Obbligazionario": "obbligazioni", LIQUIDITA: "liquidita"}


def prezzi_per_optimizer(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> str:
    """CSV dei prezzi degli strumenti in portafoglio, nel formato letto da ``portfolio-optimizer --csv``."""
    s = posizioni.situazione(p, alla_data)
    codici = [c for c in p.strumenti.index if c in set(s["strumento"])]
    fine = posizioni.data_valida(p, alla_data)
    prezzi = p.prezzi.loc[:fine, codici].rename(columns=p.strumenti["nome"])
    return prezzi.to_csv(date_format="%Y-%m-%d", float_format="%.4f")


def toml_per_planner(
    p: Patrimonio,
    alla_data: pd.Timestamp | None = None,
    eta: int = 50,
    eta_pensione: int = 67,
    versamento_annuo: float = 0.0,
    spesa_annua: float | None = None,
    pensione_pubblica: float = 0.0,
) -> str:
    """File di ipotesi per ``wealth-planner --config``: patrimonio finanziario e allocazione di oggi."""
    alloc = allocazione.per_classe(p, alla_data)
    pesi: dict[str, float] = {"azioni": 0.0, "obbligazioni": 0.0, "liquidita": 0.0}
    for classe, peso in alloc["peso"].items():
        pesi[MAPPA_PLANNER.get(classe, "obbligazioni")] += float(peso)
    pesi = {k: round(v, 3) for k, v in pesi.items()}
    pesi["liquidita"] = round(1 - pesi["azioni"] - pesi["obbligazioni"], 3)
    spesa = spesa_annua if spesa_annua is not None else p.strategia.spesa_mensile * 12
    data = posizioni.data_valida(p, alla_data)
    pesi_testo = ", ".join(f"{k} = {v}" for k, v in pesi.items())
    return f"""# Ipotesi generate da wealth-dashboard il {data:%d/%m/%Y} per wealth-planner-montecarlo
# Le età e i flussi vanno verificati con il cliente. L'oro è incluso nella quota azionaria.
nome = "{p.strategia.cliente}, verifica del piano"

[cliente]
eta = {eta}
eta_pensione = {eta_pensione}

[flussi]
patrimonio_iniziale = {alloc['valore'].sum():.0f}
versamento_annuo = {versamento_annuo:.0f}
spesa_annua = {spesa:.0f}
pensione_pubblica = {pensione_pubblica:.0f}

[portafoglio]
pesi = {{ {pesi_testo} }}
"""
