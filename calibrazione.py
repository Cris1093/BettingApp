"""
calibrazione.py — correzione della miscalibrazione delle probabilità del modello.

Motivazione (dal backtest su 128 partite, 25/08/2026):
  I mercati GOL (Over/Under, Goal/NoGoal) sovrastimano sistematicamente:
    Over 2.5: dice 50% -> reale 39% ; dice 67% -> reale 46% ; dice 82% -> reale 60%.
  L'1X2 (1/X/2) è invece ben calibrato (scarti 3-6 punti) -> NON si tocca.

Metodo: calibrazione lineare per gruppo di mercati, ricavata dai punti (prob_dichiarata,
prob_reale) misurati nel backtest. È una PRIMA correzione, volutamente semplice e
trasparente; si aggiorna quando ci saranno più dati (isotonic/Platt col tempo).

La correzione si applica alla probabilità del mercato "positivo" (es. Over, Goal) e il
complementare si ricava per coerenza (Under = 100 - Over calibrato).
"""

# punti di calibrazione osservati (prob dichiarata % -> prob reale %), dal backtest.
# ============================================================================
# CALIBRAZIONE GOL — ritarata sul backtest a 454 partite (fasce da 200-350 casi, solide).
# Scoperta: su campione grande il modello SOTTOSTIMA i gol in modo sistematico. Le vecchie
# curve (tarate su ~150 partite) abbassavano troppo. Queste ALZANO, puntando ai valori reali
# osservati. Curve separate per ogni linea (scarti diversi). raw = prob grezza -> calibrata.
# ============================================================================
# Over 2.5: dice 35->reale 45, dice 45->reale 63. Invertito: raw 41->45, raw 65->63.
_PUNTI_OVER25 = [(0, 0), (41, 45), (65, 63), (85, 82), (100, 92)]
# Over 3.5: dice 15->20, 31->36, 42->65. Invertito: raw 16->20, raw 32->36, raw 58->65.
_PUNTI_OVER35 = [(0, 0), (16, 20), (32, 36), (58, 65), (80, 82), (100, 92)]
# Over 1.5: dice 55->61, 69->78. Invertito: raw 58->61, raw 78->79 (quasi identità in alto).
_PUNTI_OVER15 = [(0, 0), (58, 61), (78, 79), (90, 88), (100, 95)]
# Goal: dice 35->41, 47->61. Invertito: raw 39->41, raw 57->61.
_PUNTI_GOAL = [(0, 0), (39, 41), (57, 61), (75, 78), (100, 90)]
# (compat: alcune parti del codice referenziano ancora _PUNTI_OVER)
_PUNTI_OVER = _PUNTI_OVER25

# "2" (vittoria ospite): su 454 partite dice ~25 -> reale ~32 (fascia 20-40, N=374):
# ora SOTTOSTIMA leggermente. Curva che alza un po' in quella fascia. Differenza ridistribuita.
_PUNTI_2 = [(0, 0), (18, 15), (25, 32), (48, 50), (100, 100)]

# quali mercati calibrare e con quale curva (il "lato positivo" del gruppo)
_GRUPPI = {
    "Over 2.5": ("_PUNTI_OVER25", "Under 2.5"),
    "Over 1.5": ("_PUNTI_OVER15", "Under 1.5"),
    "Over 3.5": ("_PUNTI_OVER35", "Under 3.5"),
    "Goal": ("_PUNTI_GOAL", "No Goal"),
}
_CURVE = {"_PUNTI_OVER25": _PUNTI_OVER25, "_PUNTI_OVER35": _PUNTI_OVER35,
          "_PUNTI_OVER15": _PUNTI_OVER15, "_PUNTI_GOAL": _PUNTI_GOAL}

# mercati 1X2: ben calibrati, nessuna correzione
_NON_CALIBRARE = {"1", "X", "2", "1X", "X2", "12"}


def _interp(x, punti):
    """Interpolazione lineare a tratti su una lista di punti (x crescente)."""
    if x <= punti[0][0]:
        return punti[0][1]
    if x >= punti[-1][0]:
        return punti[-1][1]
    for (x0, y0), (x1, y1) in zip(punti, punti[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return x


def calibra_prob(prob):
    """Applica la calibrazione a un dizionario {mercato: prob%}. Ritorna un NUOVO dizionario
    con le probabilità corrette e i complementari ricoerenziati.
    - mercati gol (Over/Under, Goal): calibrati a coppie.
    - "2" (1X2): calibrato e la differenza ridistribuita su 1 e X (somma 1+X+2 = 100).
    L'1 e la X non vengono toccati direttamente (erano ben calibrati)."""
    if not prob:
        return prob
    out = dict(prob)
    # gruppi a coppie (gol)
    for pos, (curva_key, neg) in _GRUPPI.items():
        if pos in out and out[pos] is not None:
            grezza = out[pos]
            cal = _interp(grezza, _CURVE[curva_key])
            out[pos] = round(cal, 2)
            if neg in out:
                out[neg] = round(100.0 - cal, 2)
    # "2" nel gruppo 1X2: abbassa e ridistribuisci su 1 e X proporzionalmente
    if all(k in out and out[k] is not None for k in ("1", "X", "2")):
        due_grezzo = out["2"]
        due_cal = _interp(due_grezzo, _PUNTI_2)
        delta = due_grezzo - due_cal          # quanto tolgo al 2 (positivo se abbasso)
        uno, ics = out["1"], out["X"]
        base = uno + ics
        if base > 0 and abs(delta) > 1e-9:
            out["2"] = round(due_cal, 2)
            out["1"] = round(uno + delta * (uno / base), 2)
            out["X"] = round(ics + delta * (ics / base), 2)
            # normalizzazione di sicurezza (somma esatta a 100)
            s = out["1"] + out["X"] + out["2"]
            if s > 0:
                out["1"] = round(out["1"] * 100.0 / s, 2)
                out["X"] = round(out["X"] * 100.0 / s, 2)
                out["2"] = round(out["2"] * 100.0 / s, 2)
    return out


def info_calibrazione(mercato):
    """Piccola nota di trasparenza per il racconto: dice se un mercato è calibrato."""
    if mercato in _GRUPPI or any(mercato == neg for _, neg in _GRUPPI.values()):
        return "calibrato (il modello sovrastimava questo mercato)"
    if mercato in _NON_CALIBRARE:
        return "non calibrato (già affidabile)"
    return None
