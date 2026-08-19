"""
segnali.py — SIGNAL SCORE (deterministico, tracciato, backtestabile).

RICOSTRUITO su due livelli distinti (come richiesto dalle annotazioni):

  LIVELLO 1 — PROBABILITÀ COERENTI (da evidenze.probabilita_coerenti):
     1+X+2 = 100 · Over+Under = 100 · Goal+NoGoal = 100.
     Sono la base: niente più signal complementari incoerenti (Under 0 con Over 48).

  LIVELLO 2 — QUALITÀ DELLA GIOCATA (Signal 0-100):
     costruito SOPRA la probabilità coerente, aggiungendo:
       + convergenza dei campioni
       + uniformità del segnale casa/trasferta
       + valore rispetto alla quota (statistica vs implicita grezza)
       + serie in corso a favore
       - penalità di coerenza (pareggio anomalo, campione piccolo)

Ogni contributo è tracciato in "componenti" per spiegare "perché N/100".
"""

PESO_PROB = 0.80          # SICUREZZA: la probabilità domina (100% -> 80 punti)
PESO_VALORE = 8           # valore = bonus leggero, non guida la scelta
PESO_CONVERGENZA = 14
PESO_UNIFORMITA = 8
PESO_SERIE = 6
PEN_CAMPIONE = -10
PEN_PAREGGIO_ANOMALO = -12

MERCATO_QUOTA = {
    "Under 2.5": "under25", "Over 2.5": "over25", "Goal": "goal", "No Goal": "nogoal",
    "1": "1", "X": "X", "2": "2", "1X": "1X", "X2": "X2", "12": "12",
}
CONV_KEY = {"Under 2.5": "under25", "Over 2.5": "over25", "Goal": "goal", "No Goal": "nogoal"}


def _val(blocco, chiave, sub=None):
    if not blocco or blocco.get("n", 0) == 0:
        return None
    x = blocco.get(chiave)
    if x is None:
        return None
    return x[sub]["pct"] if sub else x["pct"]


def _campioni_mercato(ev, nome):
    key = {"Under 2.5": ("under25", None), "Over 2.5": ("over", 2.5),
           "Goal": ("goal", None), "No Goal": ("nogoal", None)}.get(nome)
    if not key:
        return []
    chiave, sub = key
    h, a = ev["home"], ev["away"]
    return [_val(h["generale"], chiave, sub), _val(h["split"], chiave, sub),
            _val(a["generale"], chiave, sub), _val(a["split"], chiave, sub)]


def _uniformita(valori):
    v = [x for x in valori if x is not None]
    if len(v) < 2:
        return 0.0
    spread = max(v) - min(v)
    media = sum(v) / len(v)
    if media < 50:
        return 0.0
    return max(0.0, 1.0 - spread / 40.0)


def _score_mercato(nome, ev, prob):
    comp = []
    p = prob.get(nome)
    if p is None:
        return None
    base = PESO_PROB * p
    comp.append(("probabilità", round(base, 1), f"{p:.0f}% coerente"))
    score = base

    qk = MERCATO_QUOTA.get(nome)
    implicita = ev["quote"].get(qk, {}).get("implicita") if qk else None
    quota = ev["quote"].get(qk, {}).get("quota") if qk else None
    movimento = ev["quote"].get(qk, {}).get("movimento_pct") if qk else None

    if implicita is not None:
        diff = p - implicita
        c = max(-PESO_VALORE, min(PESO_VALORE, PESO_VALORE * diff / 20.0))
        score += c
        seg = "a favore" if diff >= 0 else "contro"
        comp.append(("valore quota", round(c, 1),
                     f"stat {p:.0f}% vs quota {implicita:.0f}% ({seg})"))

    if nome in CONV_KEY:
        conv = ev["convergenze"].get(CONV_KEY[nome])
        if conv and conv["media"] >= 55:
            fatt = {"forte": 1.0, "media": 0.55, "debole": 0.15}[conv["grado"]]
            c = PESO_CONVERGENZA * fatt
            score += c
            comp.append(("convergenza", round(c, 1), f"{conv['grado']} ({conv['media']:.0f}%)"))
        u = _uniformita(_campioni_mercato(ev, nome))
        if u > 0:
            c = PESO_UNIFORMITA * u
            score += c
            comp.append(("uniformità", round(c, 1), "campioni concordi"))
        ks = CONV_KEY[nome]
        s = max(ev["home"]["serie"].get(ks, 0), ev["away"]["serie"].get(ks, 0))
        if s >= 3:
            c = PESO_SERIE * min(1.0, (s - 2) / 3)
            score += c
            comp.append(("serie", round(c, 1), f"{s} di fila"))

    if nome == "X":
        hs = ev["home"]["split"]
        if hs.get("n", 0) >= 4 and hs["pari"]["pct"] <= 20:
            score += PEN_PAREGGIO_ANOMALO
            comp.append(("pareggio raro in casa", PEN_PAREGGIO_ANOMALO,
                         f"la casa pareggia solo {hs['pari']['pct']:.0f}%"))

    nmin = min(ev["n_home"], ev["n_away"])
    if nmin < 10:
        c = PEN_CAMPIONE * (10 - nmin) / 10.0
        score += c
        comp.append(("campione piccolo", round(c, 1), f"solo {nmin} partite"))

    return {"mercato": nome, "score": int(max(0, min(100, round(score)))),
            "prob": p, "componenti": comp, "stat": p,
            "quota": quota, "implicita": implicita, "movimento": movimento}


def calcola_signal(ev):
    prob = ev.get("prob", {})
    mercati = []
    for nome in ("Over 2.5", "Under 2.5", "Goal", "No Goal",
                 "1", "X", "2", "1X", "X2", "12"):
        m = _score_mercato(nome, ev, prob)
        if m:
            mercati.append(m)
    mercati.sort(key=lambda m: -m["score"])
    return mercati
