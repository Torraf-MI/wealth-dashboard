"""Riga di comando: avvia la dashboard o stampa segnali e operazioni di ribilanciamento.

Esempi::

    wealth-dashboard                                  # apre la dashboard nel browser
    wealth-dashboard segnali                          # segnali sull'esempio dimostrativo
    wealth-dashboard segnali --dati cartella --metodo solo_acquisti --liquidita 10000
    wealth-dashboard planner --eta 52 --output piano.toml   # ipotesi per wealth-planner-montecarlo
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

from . import allocazione, integrazioni, ribilanciamento
from .dati import carica, esempio


def _formato(x: float) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="wealth-dashboard", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="comando")
    sub.add_parser("app", help="Avvia la dashboard Streamlit (comando predefinito)")
    for nome, aiuto in [("segnali", "Stampa segnali e operazioni di ribilanciamento"),
                        ("planner", "Esporta le ipotesi per wealth-planner-montecarlo")]:
        s = sub.add_parser(nome, help=aiuto)
        s.add_argument("--dati", help="Cartella con i file del patrimonio (default: esempio dimostrativo)")
        s.add_argument("--data", help="Data di valutazione AAAA-MM-GG (default: ultima disponibile)")
        if nome == "segnali":
            s.add_argument("--metodo", choices=["obiettivo", "solo_acquisti"], default="obiettivo")
            s.add_argument("--liquidita", type=float, default=0.0, help="Nuova liquidità da investire")
        else:
            s.add_argument("--eta", type=int, default=50)
            s.add_argument("--eta-pensione", type=int, default=67)
            s.add_argument("--versamento", type=float, default=0.0, help="Risparmio annuo")
            s.add_argument("--pensione", type=float, default=0.0, help="Pensione pubblica annua")
            s.add_argument("--output", default="piano.toml")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.comando in (None, "app"):
        app = Path(__file__).with_name("app.py")
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])

    p = carica(args.dati) if args.dati else esempio()
    data = pd.Timestamp(args.data) if args.data else None

    if args.comando == "planner":
        testo = integrazioni.toml_per_planner(p, data, eta=args.eta, eta_pensione=args.eta_pensione,
                                              versamento_annuo=args.versamento, pensione_pubblica=args.pensione)
        Path(args.output).write_text(testo, encoding="utf-8")
        print(f"Ipotesi salvate in {args.output}: wealth-planner --config {args.output}")
        return 0

    s = allocazione.sintesi(p, data)
    print(f"{p.strategia.cliente}: patrimonio netto {_formato(s['Patrimonio netto'])} "
          f"(finanziario {_formato(s['Patrimonio finanziario'])}, immobili {_formato(s['Immobili'])}, "
          f"mutui {_formato(s['Mutui'])})\n")
    for seg in ribilanciamento.segnali(p, data):
        print(f"[{seg.livello.upper():<5}] {seg.titolo}\n        {seg.dettaglio}")
    ops = ribilanciamento.operazioni(p, data, metodo=args.metodo, nuova_liquidita=args.liquidita)
    print(f"\nOperazioni proposte (metodo: {args.metodo})")
    if ops.empty:
        print("  nessuna")
    for r in ops.itertuples():
        print(f"  {r.operazione:<9} {r.quantita:>9,.0f} {r.nome:<34} {_formato(abs(r.importo)):>12}"
              f"   imposta stimata {_formato(r.imposta_stimata)}".replace(",", "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
