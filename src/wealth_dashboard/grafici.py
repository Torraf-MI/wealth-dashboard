"""Grafici interattivi (plotly) usati dalla dashboard e per le immagini del README."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from . import allocazione, immobili, performance, posizioni
from .dati import LIQUIDITA, Patrimonio

BLU, ACQUA, GIALLO, VIOLA, ARANCIO = "#2a78d6", "#1baf7a", "#eda100", "#6250d6", "#eb6834"
ROSSO, VERDE = "#e34948", "#008300"
TESTO, TESTO_SECONDARIO, GRIGLIA, NEUTRO = "#222222", "#52514e", "#e6e5e1", "#bdbcb6"

# Colore fisso per classe (ordine categorico validato per daltonismo): il colore segue la classe, non il rango
COLORI_CLASSE = {"Azionario": BLU, "Obbligazionario": ACQUA, "Oro": GIALLO, LIQUIDITA: VIOLA, "Immobili": ARANCIO}
ALTRI = [BLU, ARANCIO, ACQUA, GIALLO, "#e87ba4", VERDE, VIOLA, ROSSO]


def colore(classe: str, i: int = 0) -> str:
    return COLORI_CLASSE.get(classe, ALTRI[i % len(ALTRI)])


def _layout(fig: go.Figure, titolo: str = "", altezza: int = 400, legenda: bool = True) -> go.Figure:
    fig.update_layout(
        title={"text": titolo, "x": 0, "font": {"size": 15, "color": TESTO}} if titolo else None,
        height=altezza,
        template="plotly_white",
        font={"family": "Segoe UI, Helvetica, Arial, sans-serif", "size": 12, "color": TESTO_SECONDARIO},
        margin={"l": 60, "r": 20, "t": 50 if titolo else 20, "b": 40},
        separators=",.",
        hoverlabel={"bgcolor": "white", "font_color": TESTO},
        legend={"orientation": "h", "y": -0.15, "x": 0},
        showlegend=legenda,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(gridcolor=GRIGLIA, zeroline=False, linecolor=NEUTRO)
    fig.update_yaxes(gridcolor=GRIGLIA, zerolinecolor=NEUTRO)
    return fig


def patrimonio_netto(p: Patrimonio, alla_data: pd.Timestamp | None = None, frequenza: str = "W-FRI") -> go.Figure:
    """Composizione del patrimonio nel tempo: finanziario e immobili sopra lo zero, mutui sotto."""
    fine = posizioni.data_valida(p, alla_data)
    pn = allocazione.patrimonio_netto(p).loc[:fine].resample(frequenza).last().dropna()
    fig = go.Figure()
    for nome, col in [("Finanziario", BLU), ("Immobili", ARANCIO)]:
        fig.add_scatter(x=pn.index, y=pn[nome], name=nome, stackgroup="attivo", mode="lines",
                        line={"width": 0.5, "color": col}, hovertemplate="%{y:,.0f} €")
    fig.add_scatter(x=pn.index, y=pn["Mutui"], name="Mutui", fill="tozeroy", mode="lines",
                    line={"width": 0.5, "color": ROSSO}, fillcolor="rgba(227,73,72,0.35)", hovertemplate="%{y:,.0f} €")
    fig.add_scatter(x=pn.index, y=pn["Patrimonio netto"], name="Patrimonio netto", mode="lines",
                    line={"width": 2.5, "color": TESTO}, hovertemplate="%{y:,.0f} €")
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(tickformat=",.0f", ticksuffix=" €")
    return _layout(fig, altezza=420)


def composizione(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> go.Figure:
    """Sunburst del patrimonio netto: parte finanziaria per classe e immobili al netto dei mutui."""
    s = posizioni.situazione(p, alla_data)
    riep = immobili.riepilogo(p, alla_data)
    ids, labels, parents, values, colors = [], [], [], [], []

    def nodo(id_, label, parent, value, col):
        ids.append(id_), labels.append(label), parents.append(parent), values.append(value), colors.append(col)

    fin = s["valore"].sum()
    imm = riep["netto"].sum() if len(riep) else 0.0
    nodo("Finanziario", "Finanziario", "", fin, BLU)
    if imm > 0:
        nodo("Immobili", "Immobili", "", imm, ARANCIO)
        for id_, r in riep.iterrows():
            nodo(f"imm/{id_}", r["nome"], "Immobili", r["netto"], "#f19a77")
    per_classe = s.groupby("classe")["valore"].sum()
    for classe in [c for c in p.strategia.obiettivo if c in per_classe.index]:
        nodo(f"c/{classe}", classe, "Finanziario", per_classe[classe], colore(classe))
    fig = go.Figure(go.Sunburst(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
        marker={"colors": colors, "line": {"color": "white", "width": 2}},
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} €<br>%{percentRoot:.1%} del patrimonio netto<extra></extra>",
        texttemplate="%{label}<br>%{percentRoot:.0%}", insidetextorientation="horizontal",
    ))
    return _layout(fig, altezza=420, legenda=False).update_layout(
        margin={"l": 10, "r": 10, "t": 10, "b": 10}, uniformtext={"minsize": 11, "mode": "hide"})


def allocazione_obiettivo(alloc: pd.DataFrame) -> go.Figure:
    """Peso attuale di ogni classe rispetto all'obiettivo e alla banda di tolleranza."""
    classi = list(alloc.index)[::-1]
    a = alloc.loc[classi]
    fig = go.Figure()
    fig.add_bar(y=classi, x=a["massimo"] - a["minimo"], base=a["minimo"], orientation="h", name="Banda di tolleranza",
                marker={"color": "rgba(82,81,78,0.12)", "line": {"width": 0}}, width=0.55,
                hovertemplate="Banda: %{base:.0%} – %{x:.0%}<extra></extra>",
                customdata=a["massimo"])
    fig.data[0].hovertemplate = "Banda: %{base:.0%} – %{customdata:.0%}<extra></extra>"
    fig.add_scatter(y=classi, x=a["obiettivo"], mode="markers", name="Obiettivo",
                    marker={"symbol": "line-ns", "size": 26, "line": {"width": 3, "color": TESTO}},
                    hovertemplate="Obiettivo: %{x:.1%}<extra></extra>")
    fig.add_scatter(y=classi, x=a["peso"], mode="markers+text", name="Attuale",
                    marker={"size": 14, "color": [ROSSO if f else colore(c) for c, f in zip(classi, a["fuori_banda"])],
                            "line": {"width": 2, "color": "white"}},
                    text=[f"{v:.1%}".replace(".", ",") for v in a["peso"]], textposition="top center",
                    textfont={"color": TESTO},
                    hovertemplate="%{y}: %{x:.1%}<extra></extra>")
    fig.update_xaxes(tickformat=".0%", range=[0, max(a["massimo"].max(), a["peso"].max()) * 1.12])
    fig.update_layout(barmode="overlay")
    return _layout(fig, altezza=60 + 70 * len(classi))


def prima_dopo(t: pd.DataFrame) -> go.Figure:
    """Pesi per classe prima e dopo il ribilanciamento proposto, con l'obiettivo."""
    fig = go.Figure()
    fig.add_bar(x=t.index, y=t["prima"], name="Oggi", marker_color=NEUTRO, hovertemplate="%{y:.1%}")
    fig.add_bar(x=t.index, y=t["dopo"], name="Dopo le operazioni", marker_color=BLU, hovertemplate="%{y:.1%}")
    fig.add_scatter(x=t.index, y=t["obiettivo"], mode="markers", name="Obiettivo",
                    marker={"symbol": "line-ew", "size": 34, "line": {"width": 3, "color": TESTO}},
                    hovertemplate="Obiettivo %{y:.0%}<extra></extra>")
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    return _layout(fig, altezza=360)


def per_conto(t: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for i, classe in enumerate(t.columns):
        fig.add_bar(y=t.index, x=t[classe], name=classe, orientation="h", marker_color=colore(classe, i),
                    marker_line={"color": "white", "width": 2},
                    hovertemplate=f"{classe}: " + "%{x:,.0f} €<extra></extra>")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(tickformat=",.0f", ticksuffix=" €")
    return _layout(fig, altezza=110 + 60 * len(t)).update_layout(legend={"traceorder": "normal"})


def performance_cumulata(p: Patrimonio, alla_data: pd.Timestamp | None = None,
                         inizio: pd.Timestamp | None = None) -> go.Figure:
    """Crescita di 100 € investiti: portafoglio (TWR) e benchmark."""
    fine = posizioni.data_valida(p, alla_data)
    r = performance.rendimenti_giornalieri(p).loc[:fine]
    if inizio is not None:
        r = r.loc[r.index > inizio]
    fig = go.Figure()
    fig.add_scatter(x=r.index, y=performance.indice(r), name="Portafoglio", line={"width": 2, "color": BLU},
                    hovertemplate="%{y:.1f}")
    b = performance.rendimenti_benchmark(p)
    if b is not None:
        fig.add_scatter(x=r.index, y=performance.indice(b.loc[r.index]), name="Benchmark",
                        line={"width": 2, "color": TESTO_SECONDARIO, "dash": "dot"}, hovertemplate="%{y:.1f}")
    fig.add_hline(y=100, line={"color": NEUTRO, "width": 1})
    fig.update_layout(hovermode="x unified")
    return _layout(fig, altezza=380)


def drawdown(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> go.Figure:
    fine = posizioni.data_valida(p, alla_data)
    dd = performance.drawdown(performance.rendimenti_giornalieri(p).loc[:fine])
    fig = go.Figure(go.Scatter(x=dd.index, y=dd, fill="tozeroy", mode="lines", name="Perdita dal massimo",
                               line={"width": 1.5, "color": ROSSO}, fillcolor="rgba(227,73,72,0.25)",
                               hovertemplate="%{y:.1%}<extra></extra>"))
    fig.update_yaxes(tickformat=".0%")
    return _layout(fig, altezza=260, legenda=False)


def rendimenti_mensili(tabella: pd.DataFrame) -> go.Figure:
    """Mappa di calore dei rendimenti mensili: scala divergente centrata sullo zero."""
    z = tabella.to_numpy(dtype=float)
    limite = np.nanmax(np.abs(z[:, :-1])) if np.isfinite(z[:, :-1]).any() else 0.05
    testo = [[("" if np.isnan(v) else f"{v * 100:.1f}".replace(".", ",")) for v in riga] for riga in z]
    fig = go.Figure(go.Heatmap(
        z=np.clip(z, -limite, limite), x=list(tabella.columns), y=[str(a) for a in tabella.index], text=testo,
        texttemplate="%{text}", zmid=0, zmin=-limite, zmax=limite, xgap=2, ygap=2,
        colorscale=[[0, ROSSO], [0.5, "#f0efec"], [1, BLU]], showscale=False,
        customdata=z, hovertemplate="%{x} %{y}: %{customdata:.2%}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False, side="top")
    return _layout(fig, altezza=70 + 38 * len(tabella), legenda=False)


def contributi(c: pd.DataFrame) -> go.Figure:
    """Utile o perdita in euro di ogni strumento nel periodo."""
    c = c.sort_values("utile")
    fig = go.Figure(go.Bar(
        y=c["nome"], x=c["utile"], orientation="h",
        marker={"color": [colore(k) for k in c["classe"]], "line": {"color": "white", "width": 1}},
        text=[f"{v:,.0f} €".replace(",", ".") for v in c["utile"]], textposition="outside",
        textfont={"color": TESTO}, cliponaxis=False, hovertemplate="%{y}: %{x:,.0f} €<extra></extra>",
    ))
    span = max(c["utile"].max(), 0) - min(c["utile"].min(), 0)
    fig.update_xaxes(tickformat=",.0f", ticksuffix=" €",
                     range=[min(c["utile"].min(), 0) - 0.15 * span, max(c["utile"].max(), 0) + 0.15 * span])
    return _layout(fig, altezza=80 + 42 * len(c), legenda=False).update_layout(margin={"l": 230, "r": 80})


def versato_e_valore(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> go.Figure:
    """Valore del patrimonio finanziario rispetto al capitale netto versato: la distanza è il guadagno."""
    fine = posizioni.data_valida(p, alla_data)
    v = performance.valore_totale(p).loc[:fine].resample("W-FRI").last()
    versato = posizioni.flussi_esterni(p).loc[:fine].cumsum().resample("W-FRI").last()
    fig = go.Figure()
    fig.add_scatter(x=versato.index, y=versato, name="Capitale netto versato", mode="lines",
                    line={"width": 2, "color": TESTO_SECONDARIO, "shape": "hv", "dash": "dot"},
                    hovertemplate="%{y:,.0f} €")
    fig.add_scatter(x=v.index, y=v, name="Valore di mercato", mode="lines", line={"width": 2, "color": BLU},
                    hovertemplate="%{y:,.0f} €")
    fig.update_yaxes(tickformat=",.0f", ticksuffix=" €")
    fig.update_layout(hovermode="x unified")
    return _layout(fig, altezza=360)


def immobili_valore(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> go.Figure:
    """Per ogni immobile: quota di proprietà netta e debito residuo, che sommati danno il valore stimato."""
    r = immobili.riepilogo(p, alla_data)
    fig = go.Figure()
    fig.add_bar(y=r["nome"], x=r["netto"], name="Patrimonio netto", orientation="h", marker_color=ARANCIO,
                marker_line={"color": "white", "width": 2}, hovertemplate="Netto: %{x:,.0f} €<extra></extra>")
    fig.add_bar(y=r["nome"], x=r["debito"], name="Mutuo residuo", orientation="h", marker_color=ROSSO,
                marker_line={"color": "white", "width": 2}, hovertemplate="Mutuo: %{x:,.0f} €<extra></extra>")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(tickformat=",.0f", ticksuffix=" €")
    return _layout(fig, altezza=130 + 60 * len(r))


def immobili_storico(p: Patrimonio, alla_data: pd.Timestamp | None = None) -> go.Figure:
    fine = posizioni.data_valida(p, alla_data)
    v = immobili.valori(p).loc[:fine].resample("ME").last()
    d = immobili.debiti(p).loc[:fine].resample("ME").last()
    fig = go.Figure()
    for i, id_ in enumerate(v.columns):
        nome = p.immobili.at[id_, "nome"]
        col = [ARANCIO, BLU, ACQUA, VIOLA][i % 4]
        fig.add_scatter(x=v.index, y=v[id_].where(v[id_] > 0), name=f"{nome}: valore", mode="lines",
                        line={"width": 2, "color": col}, hovertemplate="%{y:,.0f} €")
        if d[id_].any():
            fig.add_scatter(x=d.index, y=d[id_].where(d[id_] > 0), name=f"{nome}: mutuo", mode="lines",
                            line={"width": 2, "color": col, "dash": "dot"}, hovertemplate="%{y:,.0f} €")
    fig.update_yaxes(tickformat=",.0f", ticksuffix=" €", rangemode="tozero")
    fig.update_layout(hovermode="x unified")
    return _layout(fig, altezza=360)
