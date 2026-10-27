"""Dashboard Streamlit di monitoraggio del patrimonio.

Avvio: ``wealth-dashboard`` oppure ``streamlit run streamlit_app.py``.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from wealth_dashboard import allocazione, grafici, immobili, integrazioni, performance, posizioni, ribilanciamento
from wealth_dashboard.dati import Patrimonio, carica_zip, esempio, zip_esempio

REPO = "https://github.com/Torraf-MI/wealth-dashboard"
ICONE = {"alto": "🔴", "medio": "🟠", "info": "🟢"}


# --------------------------------------------------------------------------- #
# Formattazione all'italiana
# --------------------------------------------------------------------------- #
def eur(x: float, decimali: int = 0) -> str:
    if pd.isna(x):
        return "–"
    testo = f"{x:,.{decimali}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{testo} €"


def pct(x: float, decimali: int = 1, segno: bool = False) -> str:
    if pd.isna(x):
        return "–"
    return f"{x * 100:{'+' if segno else ''}.{decimali}f}%".replace(".", ",")


def num(x: float, decimali: int = 0) -> str:
    if pd.isna(x):
        return ""
    return f"{x:,.{decimali}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tabella(df: pd.DataFrame, formati: dict, **kwargs) -> None:
    """Tabella con numeri formattati all'italiana (testo allineato a destra; celle vuote invece di "None")."""
    colonne = [k for k in formati if k in df.columns]
    testo = df.copy()
    for k in colonne:
        testo[k] = [formati[k](x) if pd.notna(x) else "" for x in df[k]]
    st.dataframe(testo.style.set_properties(subset=colonne, **{"text-align": "right"}), **kwargs)


def grafico(fig) -> None:
    st.plotly_chart(fig, config={"displaylogo": False, "locale": "it"})


# --------------------------------------------------------------------------- #
# Dati
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner="Lettura dei dati…")
def _esempio() -> Patrimonio:
    return esempio()


@st.cache_data(show_spinner="Lettura dei dati…")
def _da_zip(contenuto: bytes) -> Patrimonio:
    return carica_zip(contenuto)


def barra_laterale() -> tuple[Patrimonio, pd.Timestamp]:
    with st.sidebar:
        st.header("Dati")
        fonte = st.radio("Patrimonio da analizzare", ["Esempio: famiglia Conti", "I miei dati (file ZIP)"],
                         label_visibility="collapsed")
        p = None
        if fonte.startswith("I miei"):
            caricato = st.file_uploader("Archivio ZIP con i sei file del patrimonio", type="zip")
            st.download_button("Scarica il modello (dati di esempio)", zip_esempio(), "patrimonio_modello.zip",
                               "application/zip")
            if caricato is not None:
                try:
                    p = _da_zip(caricato.getvalue())
                except (ValueError, FileNotFoundError, KeyError) as e:
                    st.error(f"Dati non validi: {e}")
            if p is None:
                st.info("Finché non carichi un archivio valido viene mostrato l'esempio.")
        if p is None:
            p = _esempio()

        # serve almeno un mese di storia per misurare rendimenti e rischio
        inizio = p.movimenti["data"].min() + pd.DateOffset(months=1)
        primo = p.date[min(p.date.searchsorted(inizio), len(p.date) - 1)].date()
        ultimo = p.date[-1].date()
        scelta = st.date_input("Situazione al", value=ultimo, min_value=primo, max_value=ultimo, format="DD/MM/YYYY")
        data = posizioni.data_valida(p, pd.Timestamp(scelta if isinstance(scelta, date) else ultimo))

        st.divider()
        st.caption(
            f"Progetto open source in Python (Streamlit, plotly, pandas). [Codice su GitHub]({REPO}). "
            "I dati dell'esempio sono simulati e non si riferiscono a persone reali. "
            "Strumento dimostrativo: non costituisce consulenza finanziaria."
        )
    return p, data


# --------------------------------------------------------------------------- #
# Sezioni
# --------------------------------------------------------------------------- #
def intestazione(p: Patrimonio, data: pd.Timestamp, segnali: list[ribilanciamento.Segnale]) -> None:
    st.title(f"Patrimonio della {p.strategia.cliente}" if p.strategia.cliente.lower().startswith("famiglia")
             else f"Patrimonio di {p.strategia.cliente}")
    st.caption(f"Situazione al {data:%d/%m/%Y} · patrimonio mobiliare e immobiliare")

    s = allocazione.sintesi(p, data)
    pn = allocazione.patrimonio_netto(p)
    anno_prima = pn.index[max(pn.index.searchsorted(data - pd.DateOffset(years=1), side="right") - 1, 0)]
    variazione = s["Patrimonio netto"] - pn.loc[anno_prima, "Patrimonio netto"]
    periodi = performance.periodi(p, data)
    ytd = periodi.loc["Da inizio anno"] if "Da inizio anno" in periodi.index else None
    gravi = sum(x.livello in ("alto", "medio") for x in segnali)

    c = st.columns(5)
    c[0].metric("Patrimonio netto", eur(s["Patrimonio netto"]), f"{eur(variazione)} in 12 mesi", border=True)
    c[1].metric("Finanziario", eur(s["Patrimonio finanziario"]),
                f"liquidità {eur(s['Liquidità'])}", delta_color="off", delta_arrow="off", border=True)
    c[2].metric("Immobili al netto dei mutui", eur(s["Immobili"] - s["Mutui"]),
                f"mutui {eur(s['Mutui'])}", delta_color="off", delta_arrow="off", border=True)
    if ytd is None:
        c[3].metric("Rendimento da inizio anno", "n.d.", border=True)
    else:
        c[3].metric("Rendimento da inizio anno", pct(ytd["Portafoglio (TWR)"], segno=True),
                    f"{pct(ytd['Differenza'], segno=True)} sul benchmark", border=True,
                    help="Rendimento ponderato per il tempo (TWR) del patrimonio finanziario.")
    c[4].metric("Segnali da valutare", str(gravi), "tutto in linea" if gravi == 0 else "vedi Ribilanciamento",
                delta_color="off" if gravi == 0 else "inverse", delta_arrow="off", border=True)


def mostra_segnali(segnali: list[ribilanciamento.Segnale], limite: int | None = None) -> None:
    for s in segnali[:limite]:
        testo = f"**{s.titolo}** · {s.area}  \n{s.dettaglio}"
        {"alto": st.error, "medio": st.warning, "info": st.success}[s.livello](testo, icon=ICONE[s.livello])


def scheda_panoramica(p: Patrimonio, data: pd.Timestamp, segnali) -> None:
    mostra_segnali(segnali, limite=3)
    sx, dx = st.columns([3, 2])
    with sx:
        st.subheader("Patrimonio netto nel tempo")
        grafico(grafici.patrimonio_netto(p, data))
    with dx:
        st.subheader("Composizione")
        grafico(grafici.composizione(p, data))
    st.subheader("Patrimonio finanziario: valore e capitale versato")
    st.caption("La distanza tra le due linee è il guadagno accumulato. Gli affitti incassati e le spese degli "
               "immobili contano come versamenti e prelievi.")
    grafico(grafici.versato_e_valore(p, data))


def scheda_allocazione(p: Patrimonio, data: pd.Timestamp) -> None:
    alloc = allocazione.per_classe(p, data)
    st.subheader("Allocazione per classe rispetto alla strategia")
    st.caption("Il punto è il peso attuale (rosso se fuori banda), la barra grigia la banda di tolleranza, "
               "il trattino l'obiettivo.")
    grafico(grafici.allocazione_obiettivo(alloc))
    t = alloc.assign(stato=alloc["fuori_banda"].map({True: "Fuori banda", False: "In linea"}))
    t = t[["valore", "peso", "obiettivo", "minimo", "massimo", "scostamento", "scostamento_euro", "stato"]]
    t.columns = ["Valore", "Peso", "Obiettivo", "Minimo", "Massimo", "Scostamento", "Da comprare (+) / vendere (−)",
                 "Stato"]
    t.index.name = "Classe"
    tabella(t, {"Valore": eur, "Peso": pct, "Obiettivo": lambda x: pct(x, 0), "Minimo": lambda x: pct(x, 0),
                "Massimo": lambda x: pct(x, 0), "Scostamento": lambda x: pct(x, 1, True),
                "Da comprare (+) / vendere (−)": lambda x: eur(-x)})
    st.subheader("Dove si trova il patrimonio")
    grafico(grafici.per_conto(allocazione.per_conto(p, data)))


def scheda_performance(p: Patrimonio, data: pd.Timestamp) -> None:
    periodi = performance.periodi(p, data)
    st.subheader("Rendimenti per periodo")
    tabella(periodi, {c: (lambda x: pct(x, 2, True)) for c in periodi.columns})
    st.caption("**TWR**: rendimento delle scelte d'investimento, indipendente da versamenti e prelievi; si confronta "
               "con il benchmark. **MWR**: rendimento effettivo del cliente, che dipende anche da quando ha investito.")

    rischio = performance.rischio(p, data)
    c = st.columns(len(rischio))
    for col, (nome, valore) in zip(c, rischio.items()):
        col.metric(nome, pct(valore), border=True)
    st.caption("Indicatori di rischio sugli ultimi 3 anni; perdita attuale rispetto al massimo storico.")

    scelte = {"Dall'inizio": None, "Ultimi 3 anni": data - pd.DateOffset(years=3),
              "Ultimi 12 mesi": data - pd.DateOffset(years=1),
              "Da inizio anno": pd.Timestamp(year=data.year, month=1, day=1) - pd.Timedelta(days=1)}
    periodo = st.segmented_control("Periodo", list(scelte), default="Dall'inizio", label_visibility="collapsed")
    inizio = scelte.get(periodo or "Dall'inizio")
    st.subheader("Crescita di 100 € investiti")
    grafico(grafici.performance_cumulata(p, data, inizio))
    st.subheader("Perdita dal massimo")
    grafico(grafici.drawdown(p, data))
    st.subheader("Rendimenti mensili (%)")
    grafico(grafici.rendimenti_mensili(performance.rendimenti_mensili(p, data)))
    st.subheader("Contributo di ogni strumento · " + (periodo or "Dall'inizio").lower())
    contributi = performance.contributi(p, inizio, data)
    st.caption(f"Utile complessivo nel periodo: **{eur(contributi['utile'].sum())}**, al netto di versamenti e "
               "prelievi. Comprende plusvalenze, cedole, interessi, commissioni e imposta di bollo.")
    grafico(grafici.contributi(contributi))


def scheda_immobili(p: Patrimonio, data: pd.Timestamp) -> None:
    r = immobili.riepilogo(p, data)
    if r.empty:
        st.info("Nessun immobile alla data selezionata.")
        return
    c = st.columns(4)
    c[0].metric("Valore stimato", eur(r["valore"].sum()), border=True)
    c[1].metric("Mutui residui", eur(r["debito"].sum()), border=True)
    c[2].metric("Rapporto mutuo/valore (LTV)", pct(r["debito"].sum() / r["valore"].sum()), border=True)
    c[3].metric("Reddito netto da affitti (12 mesi)", eur(r["reddito_netto_12m"].sum()), border=True)
    sx, dx = st.columns(2)
    with sx:
        st.subheader("Proprietà netta e mutuo")
        grafico(grafici.immobili_valore(p, data))
    with dx:
        st.subheader("Valore e debito nel tempo")
        grafico(grafici.immobili_storico(p, data))
    t = r[["nome", "citta", "uso", "costo", "valore", "plusvalenza", "debito", "ltv", "rata_mensile",
           "reddito_netto_12m", "rendimento_netto", "rendimento_totale_annuo"]]
    t.columns = ["Immobile", "Città", "Uso", "Costo d'acquisto", "Valore stimato", "Plusvalenza", "Mutuo residuo",
                 "LTV", "Rata mensile", "Reddito netto 12 mesi", "Rendimento netto", "Rendimento totale annuo"]
    tabella(t.reset_index(drop=True), {
        **{k: eur for k in ["Costo d'acquisto", "Valore stimato", "Plusvalenza", "Mutuo residuo", "Rata mensile",
                            "Reddito netto 12 mesi"]},
        "LTV": lambda x: pct(x, 0), "Rendimento netto": pct, "Rendimento totale annuo": pct,
    }, hide_index=True)
    st.caption("Il costo comprende le spese d'acquisto. Il rendimento totale annuo è il TIR dell'immobile senza "
               "considerare il mutuo: prezzo pagato, affitti netti, spese e valore stimato di oggi. "
               "Per valutare un nuovo acquisto: [real-estate-analyzer](https://github.com/Torraf-MI/real-estate-analyzer).")


def scheda_ribilanciamento(p: Patrimonio, data: pd.Timestamp, segnali) -> None:
    st.subheader("Segnali")
    mostra_segnali(segnali)

    st.subheader("Proposta di ribilanciamento")
    c = st.columns([2, 1])
    metodi = {"Ritorno all'obiettivo (anche vendite)": "obiettivo", "Solo acquisti, senza vendite": "solo_acquisti"}
    scelta = c[0].radio(
        "Metodo", list(metodi), horizontal=True,
        help="Il secondo metodo usa la liquidità in eccesso e i nuovi versamenti: non realizza plusvalenze e "
             "quindi non genera imposte, ma riallinea più lentamente.",
    )
    nuova = c[1].number_input("Nuova liquidità da investire (€)", min_value=0.0, value=0.0, step=1_000.0,
                            format="%.0f")
    metodo = metodi[scelta]
    ops = ribilanciamento.operazioni(p, data, metodo=metodo, nuova_liquidita=nuova)
    if ops.empty:
        st.success("Nessuna operazione necessaria con il metodo scelto.")
        return
    vendite, acquisti = -ops.loc[ops["importo"] < 0, "importo"].sum(), ops.loc[ops["importo"] > 0, "importo"].sum()
    m = st.columns(4)
    m[0].metric("Vendite", eur(vendite), border=True)
    m[1].metric("Acquisti", eur(acquisti), border=True)
    m[2].metric("Plusvalenze realizzate", eur(ops["plusvalenza_realizzata"].sum()), border=True)
    m[3].metric("Imposte stimate", eur(ops["imposta_stimata"].sum()), border=True)
    t = ops[["operazione", "nome", "conto", "quantita", "prezzo", "importo", "imposta_stimata"]]
    t.columns = ["Operazione", "Strumento", "Conto", "Quantità", "Prezzo", "Controvalore", "Imposta stimata"]
    tabella(t.assign(Controvalore=t["Controvalore"].abs()), {
        "Quantità": num, "Prezzo": lambda x: num(x, 2), "Controvalore": eur, "Imposta stimata": eur,
    }, hide_index=True)
    st.download_button("Scarica le operazioni (CSV)", ops.to_csv(index=False).encode("utf-8"),
                       f"ribilanciamento_{data:%Y%m%d}.csv", "text/csv")
    st.subheader("Allocazione prima e dopo")
    grafico(grafici.prima_dopo(ribilanciamento.allocazione_dopo(p, ops, data, nuova)))
    st.caption("Quantità arrotondate al lotto minimo, operazioni sotto 500 € tralasciate. Imposte stimate con il "
               "costo medio di carico (26%, 12,5% sui titoli di Stato), senza compensare minusvalenze pregresse.")


def scheda_posizioni(p: Patrimonio, data: pd.Timestamp) -> None:
    s = posizioni.situazione(p, data)
    st.subheader("Posizioni")
    t = s[["conto", "nome", "classe", "quantita", "prezzo", "valore", "costo", "plusvalenza", "plusvalenza_pct",
           "imposta_latente", "peso"]]
    t.columns = ["Conto", "Strumento", "Classe", "Quantità", "Prezzo", "Valore", "Costo medio di carico",
                 "Plus/minus", "Plus/minus %", "Imposta latente", "Peso"]
    tabella(t, {"Quantità": num, "Prezzo": lambda x: num(x, 2), "Valore": eur, "Costo medio di carico": eur,
                "Plus/minus": eur, "Plus/minus %": lambda x: pct(x, 1, True),
                "Imposta latente": eur, "Peso": pct}, hide_index=True)
    st.subheader("Movimenti")
    m = p.movimenti[p.movimenti["data"] <= data].assign(importo=posizioni.importi(p))
    c = st.columns(2)
    conti = c[0].multiselect("Conti", p.conti, default=p.conti)
    tipi = c[1].multiselect("Tipi", sorted(m["tipo"].unique()), default=sorted(m["tipo"].unique()))
    m = m[m["conto"].isin(conti) & m["tipo"].isin(tipi)].sort_values("data", ascending=False)
    m = m.assign(strumento=m["strumento"].map(p.strumenti["nome"]).fillna(m["strumento"].map(p.immobili["nome"]))
                 .fillna(""))
    m = m[["data", "conto", "tipo", "strumento", "quantita", "prezzo", "importo"]]
    m.columns = ["Data", "Conto", "Tipo", "Strumento o immobile", "Quantità", "Prezzo", "Importo"]
    tabella(m, {"Data": lambda d: f"{d:%d/%m/%Y}", "Quantità": num, "Prezzo": lambda x: num(x, 2), "Importo": eur},
            hide_index=True)


def scheda_strumenti(p: Patrimonio, data: pd.Timestamp) -> None:
    st.subheader("Approfondimenti con gli altri progetti della serie")
    st.write("La dashboard è il punto di raccolta; le analisi più profonde usano gli strumenti dedicati, che "
             "leggono direttamente i dati esportati da qui.")
    for nome, (url, descrizione) in integrazioni.PROGETTI.items():
        st.markdown(f"- **[{nome}]({url})**: {descrizione}")

    c = st.columns(2)
    with c[0]:
        st.markdown("**Prezzi per portfolio-optimizer**")
        st.caption("Serie storiche degli strumenti in portafoglio: `portfolio-optimizer --csv prezzi.csv`.")
        st.download_button("Scarica prezzi.csv", integrazioni.prezzi_per_optimizer(p, data).encode("utf-8"),
                           "prezzi.csv", "text/csv")
    with c[1]:
        st.markdown("**Ipotesi per wealth-planner-montecarlo**")
        st.caption("Patrimonio finanziario e allocazione di oggi: `wealth-planner --config piano.toml`.")
        a, b = st.columns(2)
        eta = a.number_input("Età", 18, 90, 52)
        eta_pensione = b.number_input("Età di pensione", 40, 80, 67)
        versamento = a.number_input("Risparmio annuo (€)", 0, 500_000, 18_000, step=1_000)
        pensione = b.number_input("Pensione pubblica annua (€)", 0, 200_000, 30_000, step=1_000)
        toml = integrazioni.toml_per_planner(p, data, eta=int(eta), eta_pensione=int(eta_pensione),
                                             versamento_annuo=versamento, pensione_pubblica=pensione)
        st.download_button("Scarica piano.toml", toml.encode("utf-8"), "piano.toml", "application/toml")
        with st.expander("Anteprima"):
            st.code(toml, language="toml")


def main() -> None:
    st.set_page_config(page_title="Monitoraggio del patrimonio", page_icon="📊", layout="wide")
    st.markdown("<style>[data-testid='stMetricValue'] {font-size: 1.75rem;}</style>", unsafe_allow_html=True)
    p, data = barra_laterale()
    segnali = ribilanciamento.segnali(p, data)
    intestazione(p, data, segnali)
    schede = st.tabs(["Panoramica", "Allocazione", "Performance", "Immobili", "Ribilanciamento",
                      "Posizioni e movimenti", "Altri strumenti"])
    with schede[0]:
        scheda_panoramica(p, data, segnali)
    with schede[1]:
        scheda_allocazione(p, data)
    with schede[2]:
        scheda_performance(p, data)
    with schede[3]:
        scheda_immobili(p, data)
    with schede[4]:
        scheda_ribilanciamento(p, data, segnali)
    with schede[5]:
        scheda_posizioni(p, data)
    with schede[6]:
        scheda_strumenti(p, data)


if __name__ == "__main__":
    main()
