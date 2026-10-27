import numpy as np
import pandas as pd
import pytest

from wealth_dashboard.dati import Patrimonio, Strategia

DATE = pd.bdate_range("2024-01-01", "2024-12-31")


def strategia(**kwargs) -> Strategia:
    d = {
        "cliente": "Test",
        "obiettivo": {"Azionario": {"peso": 0.6, "banda": 0.05}, "Obbligazionario": {"peso": 0.3, "banda": 0.05},
                      "Liquidità": {"peso": 0.1, "banda": 0.05}},
        "benchmark": {"AZ": 0.6, "OBB": 0.4},
    }
    d.update(kwargs)
    return Strategia.from_dict(d)


def patrimonio(movimenti: list[tuple], prezzi: pd.DataFrame | None = None, immobili=None, valutazioni=None,
               **kwargs) -> Patrimonio:
    """Patrimonio di prova: AZ cresce linearmente da 100 a 120, OBB resta a 100, BTP (fattore 0,01) a 100."""
    if prezzi is None:
        prezzi = pd.DataFrame({"AZ": np.linspace(100, 120, len(DATE)), "OBB": 100.0, "BTP": 100.0}, index=DATE)
    strumenti = pd.DataFrame(
        {"nome": ["Azioni", "Obbligazioni", "BTP"], "classe": ["Azionario", "Obbligazionario", "Obbligazionario"],
         "aliquota": [0.26, 0.26, 0.125], "fattore": [1.0, 1.0, 0.01], "lotto": [1.0, 1.0, 1000.0]},
        index=pd.Index(["AZ", "OBB", "BTP"], name="codice"))
    m = pd.DataFrame(movimenti, columns=["data", "conto", "tipo", "strumento", "quantita", "prezzo", "costi",
                                         "importo"])
    m["data"] = pd.to_datetime(m["data"])
    m["costi"] = m["costi"].fillna(0.0)
    for col in ("quantita", "prezzo", "importo"):
        m[col] = m[col].astype(float)
    if immobili is None:
        immobili = pd.DataFrame(columns=["nome", "citta", "uso", "data_acquisto", "prezzo_acquisto", "costi_acquisto",
                                         "mutuo_importo", "mutuo_tasso", "mutuo_anni", "mutuo_inizio"],
                                index=pd.Index([], name="id"))
    if valutazioni is None:
        valutazioni = pd.DataFrame({"data": pd.to_datetime([]), "immobile": [], "valore": []})
    return Patrimonio(strumenti=strumenti, prezzi=prezzi.rename_axis("Data"), movimenti=m.sort_values("data"),
                      immobili=immobili, valutazioni=valutazioni, strategia=kwargs.pop("strategia", strategia()))


def mov(data, tipo, strumento=None, quantita=None, prezzo=None, costi=0.0, importo=None, conto="Banca"):
    return (data, conto, tipo, strumento, quantita, prezzo, costi, importo)


@pytest.fixture
def semplice() -> Patrimonio:
    """10.000 € versati il 1° gennaio: 60 AZ e 30 OBB a 100, 1.000 € di liquidità."""
    return patrimonio([
        mov("2024-01-01", "VERSAMENTO", importo=10_000),
        mov("2024-01-01", "ACQUISTO", "AZ", 60, 100),
        mov("2024-01-01", "ACQUISTO", "OBB", 30, 100),
    ])
