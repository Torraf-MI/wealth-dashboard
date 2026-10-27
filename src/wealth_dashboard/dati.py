"""Dati del patrimonio: strumenti, prezzi, movimenti, immobili e strategia, letti da una cartella di file.

Formato della cartella (gli stessi file dell'esempio in ``wealth_dashboard/esempio``)::

    strumenti.csv              codice, nome, classe, aliquota, fattore, lotto
    prezzi.csv                 Data + una colonna di prezzi per ogni strumento (stesso formato di portfolio-optimizer)
    movimenti.csv              data, conto, tipo, strumento, quantita, prezzo, costi, importo
    immobili.csv               anagrafica degli immobili e dei mutui
    valutazioni_immobili.csv   data, immobile, valore
    strategia.toml             allocazione obiettivo, bande di tolleranza, limiti, benchmark
"""

from __future__ import annotations

import io
import tomllib
import zipfile
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

import pandas as pd

LIQUIDITA = "Liquidità"

# Movimenti che portano denaro dentro o fuori dal patrimonio finanziario (flussi esterni): non sono performance.
TIPI_ESTERNI = {"VERSAMENTO": 1, "PRELIEVO": -1, "AFFITTO": 1, "SPESA_IMMOBILE": -1}
# Movimenti interni: proventi e costi che fanno parte del rendimento del portafoglio.
TIPI_PROVENTI = {"CEDOLA": 1, "DIVIDENDO": 1, "INTERESSI": 1, "COSTO": -1}
TIPI_TITOLI = {"ACQUISTO": 1, "VENDITA": -1}
TIPI = set(TIPI_ESTERNI) | set(TIPI_PROVENTI) | set(TIPI_TITOLI)

FILE = ("strumenti.csv", "prezzi.csv", "movimenti.csv", "immobili.csv", "valutazioni_immobili.csv", "strategia.toml")


@dataclass(frozen=True)
class Classe:
    """Peso obiettivo di una classe di attività nel patrimonio finanziario e banda di tolleranza (in punti)."""

    peso: float
    banda: float


@dataclass(frozen=True)
class Limiti:
    peso_massimo_strumento: float = 0.30  # sul patrimonio finanziario
    quota_immobiliare_massima: float = 0.65  # immobili al netto dei mutui, sul patrimonio netto
    ltv_massimo: float = 0.50  # debito residuo / valore degli immobili
    drawdown_allerta: float = 0.10  # perdita dal massimo del portafoglio finanziario


@dataclass(frozen=True)
class Strategia:
    cliente: str
    obiettivo: dict[str, Classe]
    spesa_mensile: float = 0.0
    mesi_liquidita_minima: float = 6.0
    limiti: Limiti = field(default_factory=Limiti)
    benchmark: dict[str, float] = field(default_factory=dict)  # strumento (o "Liquidità") -> peso
    strumenti_preferiti: dict[str, str] = field(default_factory=dict)  # classe -> strumento per i nuovi acquisti

    def __post_init__(self) -> None:
        totale = sum(c.peso for c in self.obiettivo.values())
        if abs(totale - 1) > 1e-6:
            raise ValueError(f"I pesi obiettivo devono sommare a 1 (ora {totale:.4f})")
        if self.benchmark and abs(sum(self.benchmark.values()) - 1) > 1e-6:
            raise ValueError("I pesi del benchmark devono sommare a 1")

    @classmethod
    def from_dict(cls, d: dict) -> Strategia:
        obiettivo = {k: Classe(float(v["peso"]), float(v.get("banda", 0.05))) for k, v in d["obiettivo"].items()}
        return cls(
            cliente=d.get("cliente", "Cliente"),
            obiettivo=obiettivo,
            spesa_mensile=float(d.get("spesa_mensile", 0.0)),
            mesi_liquidita_minima=float(d.get("mesi_liquidita_minima", 6.0)),
            limiti=Limiti(**d.get("limiti", {})),
            benchmark={k: float(v) for k, v in d.get("benchmark", {}).items()},
            strumenti_preferiti=dict(d.get("strumenti_preferiti", {})),
        )


@dataclass
class Patrimonio:
    """Tutti i dati di un cliente, validati e pronti per l'analisi."""

    strumenti: pd.DataFrame  # indice: codice
    prezzi: pd.DataFrame  # indice: date (giorni di borsa), colonne: codici
    movimenti: pd.DataFrame
    immobili: pd.DataFrame  # indice: id
    valutazioni: pd.DataFrame
    strategia: Strategia

    def __post_init__(self) -> None:
        self._valida()

    @property
    def date(self) -> pd.DatetimeIndex:
        return self.prezzi.index

    @property
    def conti(self) -> list[str]:
        return sorted(self.movimenti["conto"].unique())

    def _valida(self) -> None:
        m, s = self.movimenti, self.strumenti
        tipi_ignoti = set(m["tipo"]) - TIPI
        if tipi_ignoti:
            raise ValueError(f"Tipi di movimento non riconosciuti: {sorted(tipi_ignoti)}")
        titoli = m[m["tipo"].isin(TIPI_TITOLI)]
        ignoti = set(titoli["strumento"]) - set(s.index)
        if ignoti:
            raise ValueError(f"Strumenti nei movimenti ma non in strumenti.csv: {sorted(ignoti)}")
        senza_prezzo = set(s.index) - set(self.prezzi.columns)
        if senza_prezzo:
            raise ValueError(f"Strumenti senza prezzi in prezzi.csv: {sorted(senza_prezzo)}")
        if (titoli["quantita"].isna() | (titoli["quantita"] <= 0)).any():
            raise ValueError("Acquisti e vendite richiedono una quantità positiva")
        classi = set(s["classe"]) | {LIQUIDITA}
        mancanti = classi - set(self.strategia.obiettivo)
        if mancanti:
            raise ValueError(f"Classi senza peso obiettivo in strategia.toml: {sorted(mancanti)}")
        if m["data"].min() < self.date[0] or m["data"].max() > self.date[-1]:
            raise ValueError("I movimenti devono cadere nel periodo coperto da prezzi.csv")
        ignoti = set(self.valutazioni["immobile"]) - set(self.immobili.index)
        if ignoti:
            raise ValueError(f"Valutazioni di immobili non presenti in immobili.csv: {sorted(ignoti)}")
        ignoti = set(self.strategia.benchmark) - set(s.index) - {LIQUIDITA}
        if ignoti:
            raise ValueError(f"Strumenti del benchmark non presenti in strumenti.csv: {sorted(ignoti)}")


# --------------------------------------------------------------------------- #
# Lettura
# --------------------------------------------------------------------------- #
def _leggi_strumenti(f) -> pd.DataFrame:
    s = pd.read_csv(f, dtype={"codice": str}).set_index("codice")
    s["aliquota"] = s.get("aliquota", pd.Series(0.26, index=s.index)).fillna(0.26).astype(float)
    s["fattore"] = s.get("fattore", pd.Series(1.0, index=s.index)).fillna(1.0).astype(float)
    s["lotto"] = s.get("lotto", pd.Series(1.0, index=s.index)).fillna(1.0).astype(float)
    return s


def _leggi_prezzi(f) -> pd.DataFrame:
    p = pd.read_csv(f)
    p[p.columns[0]] = pd.to_datetime(p[p.columns[0]])
    return p.set_index(p.columns[0]).rename_axis("Data").sort_index().astype(float).ffill()


def _leggi_movimenti(f) -> pd.DataFrame:
    m = pd.read_csv(f, dtype={"strumento": str, "conto": str, "tipo": str})
    m["data"] = pd.to_datetime(m["data"])
    m["tipo"] = m["tipo"].str.strip().str.upper()
    for col in ("quantita", "prezzo", "costi", "importo"):
        if col not in m:
            m[col] = float("nan")
        m[col] = pd.to_numeric(m[col], errors="coerce")
    m["costi"] = m["costi"].fillna(0.0)
    return m.sort_values("data", kind="stable").reset_index(drop=True)


def _leggi_immobili(f) -> pd.DataFrame:
    i = pd.read_csv(f, dtype={"id": str}).set_index("id")
    for col in ("data_acquisto", "mutuo_inizio"):
        i[col] = pd.to_datetime(i[col])
    for col in ("costi_acquisto", "mutuo_importo", "mutuo_tasso", "mutuo_anni"):
        i[col] = pd.to_numeric(i.get(col), errors="coerce").fillna(0.0)
    return i


def _leggi_valutazioni(f) -> pd.DataFrame:
    v = pd.read_csv(f, dtype={"immobile": str})
    v["data"] = pd.to_datetime(v["data"])
    return v.sort_values(["immobile", "data"]).reset_index(drop=True)


def _da_aperti(apri) -> Patrimonio:
    with apri("strategia.toml") as f:
        strategia = Strategia.from_dict(tomllib.loads(f.read().decode("utf-8")))
    with apri("strumenti.csv") as a, apri("prezzi.csv") as b, apri("movimenti.csv") as c, \
            apri("immobili.csv") as d, apri("valutazioni_immobili.csv") as e:
        return Patrimonio(
            strumenti=_leggi_strumenti(a),
            prezzi=_leggi_prezzi(b),
            movimenti=_leggi_movimenti(c),
            immobili=_leggi_immobili(d),
            valutazioni=_leggi_valutazioni(e),
            strategia=strategia,
        )


def carica(cartella: str | Path) -> Patrimonio:
    """Legge i sei file del patrimonio da una cartella."""
    cartella = Path(cartella)
    mancanti = [n for n in FILE if not (cartella / n).exists()]
    if mancanti:
        raise FileNotFoundError(f"File mancanti in {cartella}: {', '.join(mancanti)}")
    return _da_aperti(lambda nome: open(cartella / nome, "rb"))


def carica_zip(dati: bytes) -> Patrimonio:
    """Legge i sei file da un archivio ZIP (anche dentro una sottocartella), come quello caricato nella dashboard."""
    z = zipfile.ZipFile(io.BytesIO(dati))
    nomi = {Path(n).name: n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n}
    mancanti = [n for n in FILE if n not in nomi]
    if mancanti:
        raise FileNotFoundError(f"File mancanti nell'archivio: {', '.join(mancanti)}")
    return _da_aperti(lambda nome: z.open(nomi[nome]))


def cartella_esempio() -> Path:
    return Path(str(files("wealth_dashboard") / "esempio"))


def esempio() -> Patrimonio:
    """Patrimonio dimostrativo della famiglia Conti: dati simulati, non riferiti a persone reali."""
    return carica(cartella_esempio())


def zip_esempio() -> bytes:
    """I file dell'esempio in un archivio ZIP, da usare come modello per i propri dati."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in FILE:
            z.write(cartella_esempio() / nome, f"patrimonio/{nome}")
    return buffer.getvalue()
