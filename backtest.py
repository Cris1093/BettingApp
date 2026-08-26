"""
backtest.py — metriche per la validazione walk-forward del motore.

Filosofia (studio, punti 20-24): il motore deve prevedere bene INDIPENDENTEMENTE dalle
quote. Quindi le metriche protagoniste misurano la QUALITÀ DELLE PROBABILITÀ:
  - Brier Score  (0=perfetto, più basso è meglio)
  - Log Loss     (più basso è meglio)
  - Calibration  (quando dici 70%, succede il 70%?)
ROI/yield sono secondarie e calcolabili solo dove ci sono quote storiche.

Il loop walk-forward (per ogni partita, solo dati precedenti) vive in app.py perché usa
le funzioni-ponte; qui stanno solo le metriche pure (facili da testare).
"""

import math


def esito_over(gc, gt):     return 1 if (gc + gt) >= 3 else 0
def esito_over15(gc, gt):   return 1 if (gc + gt) >= 2 else 0
def esito_over35(gc, gt):   return 1 if (gc + gt) >= 4 else 0
def esito_goal(gc, gt):     return 1 if (gc >= 1 and gt >= 1) else 0
def esito_1(gc, gt):        return 1 if gc > gt else 0
def esito_x(gc, gt):        return 1 if gc == gt else 0
def esito_2(gc, gt):        return 1 if gc < gt else 0


# mercati binari valutati (nome -> chiave prob nel dict del motore, funzione esito)
MERCATI_BINARI = {
    "Over 1.5": ("Over 1.5", esito_over15),
    "Over 2.5": ("Over 2.5", esito_over),
    "Over 3.5": ("Over 3.5", esito_over35),
    "Goal": ("Goal", esito_goal),
    "1": ("1", esito_1),
    "X": ("X", esito_x),
    "2": ("2", esito_2),
}


def _clip(p, eps=1e-6):
    return max(eps, min(1 - eps, p))


def brier(coppie):
    """coppie: lista di (prob 0..1, esito 0/1). Ritorna il Brier score medio."""
    if not coppie:
        return None
    return sum((p - y) ** 2 for p, y in coppie) / len(coppie)


def log_loss(coppie):
    if not coppie:
        return None
    s = 0.0
    for p, y in coppie:
        p = _clip(p)
        s += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return s / len(coppie)


def baseline_brier(coppie):
    """Brier di riferimento: predire sempre la frequenza base dell'evento.
    Serve a capire se il modello batte il 'lancio della moneta informato'."""
    if not coppie:
        return None
    base = sum(y for _, y in coppie) / len(coppie)
    return sum((base - y) ** 2 for _, y in coppie) / len(coppie)


def calibration(coppie, n_bin=5):
    """Raggruppa per fascia di probabilità e confronta prob media vs frequenza reale."""
    bins = [[] for _ in range(n_bin)]
    for p, y in coppie:
        idx = min(n_bin - 1, int(p * n_bin))
        bins[idx].append((p, y))
    righe = []
    for i, b in enumerate(bins):
        if not b:
            continue
        pm = sum(p for p, _ in b) / len(b)
        fr = sum(y for _, y in b) / len(b)
        righe.append({"fascia": f"{i*100//n_bin}-{(i+1)*100//n_bin}%",
                      "n": len(b), "prob_media": round(pm * 100, 1),
                      "reale": round(fr * 100, 1), "scarto": round((pm - fr) * 100, 1)})
    return righe


def calibration_error(coppie, n_bin=5):
    """Errore di calibrazione medio pesato (|prob_media - reale|). 0 = perfetto."""
    cal = calibration(coppie, n_bin)
    if not cal:
        return None
    tot = sum(r["n"] for r in cal)
    return round(sum(abs(r["scarto"]) * r["n"] for r in cal) / tot, 1) if tot else None


def roi_yield(scommesse):
    """scommesse: lista di (esito 0/1, quota). Simula 1 unità per giocata.
    Ritorna ROI%, yield%, n, profitto, max_drawdown."""
    if not scommesse:
        return None
    profitto = 0.0
    picco = 0.0
    max_dd = 0.0
    curva = 0.0
    for y, q in scommesse:
        curva += (q - 1) if y else -1
        picco = max(picco, curva)
        max_dd = min(max_dd, curva - picco)
    profitto = curva
    n = len(scommesse)
    return {"n": n, "profitto": round(profitto, 2),
            "roi": round(profitto / n * 100, 1),
            "yield": round(profitto / n * 100, 1),
            "max_drawdown": round(max_dd, 2)}
