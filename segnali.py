"""
segnali.py — SIGNAL SCORE = SOLO robustezza/affidabilità statistica del segnale.

Ristrutturato secondo lo studio:
  - Il signal NON è probabilità e NON è value. È "quanto è solido/stabile il segnale
    nei dati". Probabilità (modello) e value (mercato) vivono altrove (evidenze.py).
  - NIENTE contributo di quota/movimento nel signal (il value è separato).
  - NIENTE double-counting: la convergenza non è "evidenza in più" ma un MODULATORE
    di stabilità (i campioni generale/split/recenti sono viste sovrapposte, non
    indipendenti).
  - Allerta se il RECENTE diverge dallo STORICO (instabilità -> abbassa il signal).
  - Serie CONCORDANTI casa+trasferta premiate; serie singola = contributo minore.
  - Penalità campione piccolo su n_effective (dopo i pesi), non su n_raw.
  - COMPRESSIONE MORBIDA finale: nessun troncamento brusco a 100 (le combinazioni
    restano distinguibili in alto).

NB: i PESI restano quelli attuali; non si ottimizzano "a occhio" prima del backtest.
"""

# Contributi alla ROBUSTEZZA (non alla probabilità). Base = quanto l'evidenza è netta.
PESO_BASE = 55          # quanto il segnale è "marcato" nei dati (probabilità coerente alta)
PESO_STABILITA = 18     # convergenza/uniformità dei campioni (modulatore, non evidenza nuova)
PESO_SERIE = 6          # serie in corso, concordanti (informazione SECONDARIA)
PEN_CAMPIONE = -12      # campione effettivo piccolo
PEN_INSTABILITA = -14   # il recente contraddice lo storico
PEN_PAREGGIO_ANOMALO = -12   # X forte ma la casa non pareggia quasi mai (da validare a backtest)

CONV_KEY = {"Under 2.5": "under25", "Over 2.5": "over25", "Goal": "goal", "No Goal": "nogoal"}


def _val(blocco, chiave, sub=None):
    if not blocco or blocco.get("n", 0) == 0:
        return None
    x = blocco.get(chiave)
    if x is None:
        return None
    return x[sub]["pct"] if sub else x["pct"]


def _campioni_mercato(ev, nome, blocco="storico"):
    """Le % del mercato viste da generale e split (viste sovrapposte dello stesso storico).
    blocco='recente' usa le ultime 5."""
    key = {"Under 2.5": ("under25", None), "Over 2.5": ("over", 2.5),
           "Goal": ("goal", None), "No Goal": ("nogoal", None)}.get(nome)
    if not key:
        return []
    chiave, sub = key
    h, a = ev["home"], ev["away"]
    if blocco == "recente":
        return [_val(h["recenti5"], chiave, sub), _val(a["recenti5"], chiave, sub)]
    return [_val(h["generale"], chiave, sub), _val(h["split"], chiave, sub),
            _val(a["generale"], chiave, sub), _val(a["split"], chiave, sub)]


def _stabilita(valori):
    """Quanto i campioni concordano: 1 = molto compatti e nella stessa direzione, 0 = sparsi.
    Misura la STABILITÀ dell'evidenza, non aggiunge evidenza."""
    v = [x for x in valori if x is not None]
    if len(v) < 2:
        return 0.0
    spread = max(v) - min(v)
    return max(0.0, 1.0 - spread / 45.0)      # spread 0 -> 1 ; spread>=45 -> 0


def _direzione(p):
    """Robustezza di GIOCARE questo mercato: sale solo se il mercato è PROBABILE
    (p sopra 50). Sotto il 50% il segnale non c'è (giocheresti il complementare)."""
    if p is None:
        return 0.0
    return max(0.0, min(1.0, (p - 50.0) / 35.0))     # 50%->0 ; 85%+ ->1 ; <50% ->0


def _score_mercato(nome, ev, prob):
    comp = []
    p = prob.get(nome)
    if p is None:
        return None

    # 1) BASE: quanto il segnale è netto nei dati (probabilità marcata)
    base = PESO_BASE * _direzione(p)
    comp.append(("evidenza", round(base, 1), f"prob {p:.0f}% (nettezza)"))
    score = base

    # 2) STABILITÀ: convergenza/uniformità dei campioni (modulatore, no double count)
    #    Si applica solo se il mercato è un candidato reale (probabile, p>=50).
    if nome in CONV_KEY and p >= 50:
        st = _stabilita(_campioni_mercato(ev, nome, "storico"))
        c = PESO_STABILITA * st
        score += c
        comp.append(("stabilità storica", round(c, 1),
                     "campioni concordi" if st > 0.5 else "campioni sparsi"))

        # 3) ALLERTA recente vs storico: se il recente contraddice, instabilità
        rec = _campioni_mercato(ev, nome, "recente")
        rec_media = sum(x for x in rec if x is not None) / max(1, len([x for x in rec if x is not None])) \
            if any(x is not None for x in rec) else None
        if rec_media is not None:
            # se lo storico dice "alto" (>55) ma il recente dice "basso" (<45) o viceversa
            if (p >= 55 and rec_media <= 40) or (p <= 45 and rec_media >= 60):
                score += PEN_INSTABILITA
                comp.append(("instabilità", PEN_INSTABILITA,
                             f"recente {rec_media:.0f}% diverge dallo storico"))

        # 4) SERIE concordanti (secondaria): premia solo se casa E trasferta concordano
        ks = CONV_KEY[nome]
        sh = ev["home"]["serie"].get(ks, 0)
        sa = ev["away"]["serie"].get(ks, 0)
        if sh >= 3 and sa >= 3:
            score += PESO_SERIE
            comp.append(("serie concordi", PESO_SERIE, f"casa {sh} e trasf {sa} di fila"))
        elif max(sh, sa) >= 4:
            score += PESO_SERIE * 0.4
            comp.append(("serie singola", round(PESO_SERIE * 0.4, 1),
                         f"solo una squadra ({max(sh, sa)} di fila)"))

    # 5) penalità pareggio anomalo (da validare a backtest)
    if nome == "X":
        hs = ev["home"]["split"]
        if hs.get("n", 0) >= 4 and hs["pari"]["pct"] <= 20:
            score += PEN_PAREGGIO_ANOMALO
            comp.append(("pareggio raro in casa", PEN_PAREGGIO_ANOMALO,
                         f"la casa pareggia solo {hs['pari']['pct']:.0f}%"))

    # 6) penalità campione piccolo su n_EFFECTIVE
    n_eff = min(ev.get("n_eff_home", ev["n_home"]), ev.get("n_eff_away", ev["n_away"]))
    if n_eff < 10:
        c = PEN_CAMPIONE * (10 - n_eff) / 10.0
        score += c
        comp.append(("campione effettivo piccolo", round(c, 1), f"n_eff {n_eff:.1f}"))

    score_finale = _comprimi(score)
    return {"mercato": nome, "score": score_finale,
            "prob": p, "stat": p, "componenti": comp,
            # campi mercato/value replicati per comodità del narratore (restano separati)
            "quota": ev["value"].get(nome, {}).get("quota") if ev.get("value") else None,
            "market_prob_novig": ev["value"].get(nome, {}).get("market_prob_novig") if ev.get("value") else None,
            "edge_novig": ev["value"].get(nome, {}).get("edge_novig") if ev.get("value") else None,
            "EV": ev["value"].get(nome, {}).get("EV") if ev.get("value") else None,
            "fair_odds": ev["value"].get(nome, {}).get("fair_odds") if ev.get("value") else None}


def _comprimi(x):
    """Compressione morbida in 0..100: nessun troncamento brusco. Valori alti restano
    distinguibili (una curva satura dolcemente verso 100 invece di tagliare)."""
    if x <= 0:
        return 0
    # mappa [0, +inf) -> [0,100) con saturazione morbida; ~ lineare fino a 70, poi curva
    import math
    return int(round(100.0 * (1.0 - math.exp(-x / 70.0))))


def calcola_signal(ev):
    """Tutti i mercati con Signal Score = SOLO robustezza statistica. Le probabilità
    restano coerenti e separate; value/quota vivono in ev['value']."""
    prob = ev.get("prob", {})
    mercati = []
    for nome in ("Over 2.5", "Under 2.5", "Goal", "No Goal",
                 "1", "X", "2", "1X", "X2", "12"):
        m = _score_mercato(nome, ev, prob)
        if m:
            mercati.append(m)
    mercati.sort(key=lambda m: -m["score"])
    return mercati
