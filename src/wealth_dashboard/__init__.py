"""Dashboard di monitoraggio del patrimonio mobiliare e immobiliare: allocazione, performance, ribilanciamento."""

from .dati import Patrimonio, Strategia, carica, carica_zip, esempio, zip_esempio
from .ribilanciamento import Segnale, operazioni, segnali

__all__ = ["Patrimonio", "Segnale", "Strategia", "carica", "carica_zip", "esempio", "operazioni", "segnali",
           "zip_esempio"]

__version__ = "0.1.0"
