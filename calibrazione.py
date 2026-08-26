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
# Fonte Over 2.5 (tabella calibrazione a 128 partite):
#   35->33, 50->39, 67->46, 82->60
# Over 2.5 (e 3.5): il modello SOVRASTIMAVA -> la curva abbassa. Tarata sul backtest.
_PUNTI_OVER = [(0, 0), (35, 33), (50, 39), (67, 46), (82, 60), (100, 75)]
# Over 1.5: il modello GREZZO sovrastima LEGGERMENTE (raw ~72 -> reale ~67; raw ~88 -> reale
# ~73). La vecchia curva _PUNTI_OVER abbassava TROPPO. Qui una correzione GENTILE che abbassa
# di poco, coerente coi dati del backtest (144 partite). Da raffinare con più dati.
_PUNTI_OVER15 = [(0, 0), (50, 48), (72, 67), (88, 73), (100, 80)]
# Goal/NoGoal: lieve sovrastima.
_PUNTI_GOAL = [(0, 0), (40, 36), (55, 46), (65, 50), (80, 63), (100, 80)]

# quali mercati calibrare e con quale curva (il "lato positivo" del gruppo)
_GRUPPI = {
    "Over 2.5": ("_PUNTI_OVER", "Under 2.5"),
    "Over 1.5": ("_PUNTI_OVER15", "Under 1.5"),
    "Over 3.5": ("_PUNTI_OVER", "Under 3.5"),
    "Goal": ("_PUNTI_GOAL", "No Goal"),
}
_CURVE = {"_PUNTI_OVER": _PUNTI_OVER, "_PUNTI_OVER15": _PUNTI_OVER15, "_PUNTI_GOAL": _PUNTI_GOAL}

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
    con le probabilità dei mercati gol corrette e i complementari ricoerenziati.
    L'1X2 resta invariato. Idempotente sui mercati non gestiti."""
    if not prob:
        return prob
    out = dict(prob)
    for pos, (curva_key, neg) in _GRUPPI.items():
        if pos in out and out[pos] is not None:
            grezza = out[pos]
            cal = _interp(grezza, _CURVE[curva_key])
            out[pos] = round(cal, 2)
            if neg in out:
                out[neg] = round(100.0 - cal, 2)
    return out


def info_calibrazione(mercato):
    """Piccola nota di trasparenza per il racconto: dice se un mercato è calibrato."""
    if mercato in _GRUPPI or any(mercato == neg for _, neg in _GRUPPI.values()):
        return "calibrato (il modello sovrastimava questo mercato)"
    if mercato in _NON_CALIBRARE:
        return "non calibrato (già affidabile)"
    return None
