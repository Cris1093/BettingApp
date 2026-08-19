"""
segnali.py — SIGNAL SCORE (deterministico, tracciato, backtestabile).

Per ogni mercato calcola un punteggio 0-100 sommando contributi ESPLICITI:
  - dato generale delle due squadre
  - dato casa (squadra di casa) / trasferta (squadra ospite)  <-- peso maggiore
  - forma recente (ultime 5)
  - convergenza (stesso segnale su più campioni)
  - eventi rari / serie in corso
  - valore rispetto alla quota (statistica vs implicita grezza)
  - penalità per contraddizioni e per campione piccolo

Ogni contributo è registrato in "componenti" così l'analisi può spiegare
"perché 78/100". Nessun numero è stimato: tutto viene dalle evidenze.

Mercati valutati: 1, X, 2, 1X, X2, 12, Over 2.5, Under 2.5, Goal, No Goal.
"""

PESI = {
    "generale": 18,      # media dei due dati generali rilevanti
    "split": 26,         # casa (per la casa) / trasferta (per l'ospite): pesa di più
    "forma": 12,         # ultime 5
    "convergenza": 16,   # forte/media/debole
    "serie": 6,          # serie in corso a favore
    "valore": 10,        # statistica vs quota implicita
    "campione": -8,      # penalità se poche partite
    "contraddizione": -6,
}


def _lerp(pct, lo=40.0, hi=80.0):
    """Mappa una percentuale (di frequenza storica) in 0..1 tra due soglie."""
    if pct <= lo:
        return 0.0
    if pct >= hi:
        return 1.0
    return (pct - lo) / (hi - lo)


def _bidir(pct):
    """Per mercati simmetrici: 0..1 quanto il dato spinge verso l'evento (sopra 50)."""
    return max(0.0, min(1.0, (pct - 50.0) / 30.0))


# ---- estrattori di percentuale per ciascun mercato dai blocchi evidenze --------
def _val(blocco, chiave, sub=None):
    if not blocco or blocco.get("n", 0) == 0:
        return None
    x = blocco.get(chiave)
    if x is None:
        return None
    return x[sub]["pct"] if sub else x["pct"]


def _mercati_percentuali(home, away):
    """Ritorna, per ogni mercato 'gol', le 6 percentuali chiave (generali+split+recenti)."""
    def pack(chiave, sub=None):
        return {
            "home_gen": _val(home["generale"], chiave, sub),
            "home_split": _val(home["split"], chiave, sub),
            "away_gen": _val(away["generale"], chiave, sub),
            "away_split": _val(away["split"], chiave, sub),
            "home_rec": _val(home["recenti5"], chiave, sub),
            "away_rec": _val(away["recenti5"], chiave, sub),
        }
    return {
        "Under 2.5": pack("under25"),
        "Over 2.5": pack("over", 2.5),
        "Goal": pack("goal"),
        "No Goal": pack("nogoal"),
    }


def _media(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


# ---- Signal Score per un mercato "gol" (Over/Under/Goal/NoGoal) -----------------
def _score_gol(nome, ev, mercato_quota):
    home, away = ev["home"], ev["away"]
    perc = _mercati_percentuali(home, away)[nome]
    comp = []
    score = 0.0

    gen = _media([perc["home_gen"], perc["away_gen"]])
    if gen is not None:
        c = PESI["generale"] * _lerp(gen)
        score += c
        comp.append(("generale", round(c, 1), f"media generale {gen:.0f}%"))

    split = _media([perc["home_split"], perc["away_split"]])
    if split is not None:
        c = PESI["split"] * _lerp(split)
        score += c
        comp.append(("casa/trasferta", round(c, 1), f"media casa/trasf {split:.0f}%"))

    rec = _media([perc["home_rec"], perc["away_rec"]])
    if rec is not None:
        c = PESI["forma"] * _lerp(rec)
        score += c
        comp.append(("forma recente", round(c, 1), f"ultime 5: {rec:.0f}%"))

    conv = ev["convergenze"].get({"Under 2.5": "under25", "Over 2.5": "over25",
                                  "Goal": "goal", "No Goal": "nogoal"}[nome])
    if conv:
        fatt = {"forte": 1.0, "media": 0.55, "debole": 0.15}[conv["grado"]]
        # conta solo se la convergenza è verso l'evento (media alta)
        if conv["media"] >= 55:
            c = PESI["convergenza"] * fatt
            score += c
            comp.append(("convergenza", round(c, 1), f"{conv['grado']} ({conv['media']:.0f}%)"))

    # serie in corso a favore (una delle due squadre)
    key_serie = {"Under 2.5": "under25", "Over 2.5": "over25",
                 "Goal": "goal", "No Goal": "nogoal"}[nome]
    s = max(home["serie"].get(key_serie, 0), away["serie"].get(key_serie, 0))
    if s >= 3:
        c = PESI["serie"] * min(1.0, (s - 2) / 3)
        score += c
        comp.append(("serie in corso", round(c, 1), f"{s} di fila"))

    # valore vs quota
    qk = mercato_quota.get(nome)
    if qk and qk in ev["quote"]:
        implicita = ev["quote"][qk]["implicita"]
        stat = split if split is not None else gen
        if stat is not None and implicita is not None:
            diff = stat - implicita
            c = max(-PESI["valore"], min(PESI["valore"], PESI["valore"] * diff / 20.0))
            score += c
            seg = "a favore" if diff >= 0 else "contro"
            comp.append(("valore quota", round(c, 1),
                         f"stat {stat:.0f}% vs quota {implicita:.0f}% ({seg})"))

    # penalità campione piccolo
    nmin = min(ev["n_home"], ev["n_away"])
    if nmin < 10:
        c = PESI["campione"] * (10 - nmin) / 10.0
        score += c
        comp.append(("campione piccolo", round(c, 1), f"solo {nmin} partite"))

    # penalità contraddizioni sul mercato
    contrad = [x for x in ev["contraddizioni"] if nome.split()[0].lower() in x.lower()]
    if contrad:
        c = PESI["contraddizione"]
        score += c
        comp.append(("contraddizione", round(c, 1), "generale vs casa/trasf discordi"))

    return {"mercato": nome, "score": int(max(0, min(100, round(score)))),
            "componenti": comp,
            "stat": round(split if split is not None else (gen or 0), 1),
            "quota": ev["quote"].get(qk, {}).get("quota") if qk else None,
            "implicita": ev["quote"].get(qk, {}).get("implicita") if qk else None,
            "movimento": ev["quote"].get(qk, {}).get("movimento_pct") if qk else None}


# ---- Signal Score per il 1X2 e le doppie chance --------------------------------
def _forza_squadra(blocco_gen, blocco_split, blocco_rec):
    """Punti-forza 0..1 di una squadra dal suo rendimento (vittorie pesate)."""
    def wr(b):
        if not b or b.get("n", 0) == 0:
            return None
        return (b["v"] + 0.4 * b["d"]) / b["n"]
    parts = [(wr(blocco_split), 0.5), (wr(blocco_gen), 0.3), (wr(blocco_rec), 0.2)]
    num = sum(w * p for w, (v, p) in [(v, (v, p)) for v, p in parts] if v is not None for w in [v])
    den = sum(p for v, p in parts if v is not None)
    return (num / den) if den else 0.5


def _score_1x2(ev, mercato_quota):
    home, away = ev["home"], ev["away"]
    fh = _forza_squadra(home["generale"], home["split"], home["recenti5"])
    fa = _forza_squadra(away["generale"], away["split"], away["recenti5"])
    # vantaggio casa incluso nello split della squadra di casa
    out = {}
    scenari = {
        "1": fh - fa + 0.10,
        "2": fa - fh - 0.05,
        "X": 0.18 - abs(fh - fa),      # più è equilibrata, più X è probabile
    }
    for seg, raw in scenari.items():
        base = max(0.0, min(1.0, 0.5 + raw))
        comp = [("forza casa/trasf", round(45 * base, 1),
                 f"rendimento casa {fh*100:.0f}% vs trasferta {fa*100:.0f}%")]
        score = 45 * base
        # valore quota
        qk = mercato_quota.get(seg)
        stat_pct = base * 100
        if qk and qk in ev["quote"]:
            implicita = ev["quote"][qk]["implicita"]
            if implicita is not None:
                diff = stat_pct - implicita
                c = max(-10, min(10, diff / 3.0))
                score += c
                comp.append(("valore quota", round(c, 1),
                             f"stat ~{stat_pct:.0f}% vs quota {implicita:.0f}%"))
        # movimento quota a favore (quota scesa)
        mv = ev["quote"].get(qk, {}).get("movimento_pct") if qk else None
        if mv is not None and mv <= -5:
            score += 6
            comp.append(("quota in calo", 6.0, f"movimento {mv:.0f}% (soldi sul segno)"))
        nmin = min(ev["n_home"], ev["n_away"])
        if nmin < 10:
            pen = -8 * (10 - nmin) / 10.0
            score += pen
            comp.append(("campione piccolo", round(pen, 1), f"solo {nmin} partite"))
        out[seg] = {"mercato": seg, "score": int(max(0, min(100, round(score * 1.15)))),
                    "componenti": comp, "stat": round(stat_pct, 1),
                    "quota": ev["quote"].get(qk, {}).get("quota") if qk else None,
                    "implicita": ev["quote"].get(qk, {}).get("implicita") if qk else None,
                    "movimento": mv}
    # doppie chance derivate dai singoli
    def dc(a, b, nome, qk):
        sc = int(max(out[a]["score"], out[b]["score"]) * 0.6 + min(out[a]["score"], out[b]["score"]) * 0.6)
        sc = min(100, sc)
        imp = ev["quote"].get(qk, {}).get("implicita") if qk else None
        return {"mercato": nome, "score": sc, "componenti": [("somma esiti", sc, f"{a}+{b}")],
                "stat": None,   # proxy dei singoli esiti: non è una vera frequenza storica
                "quota": ev["quote"].get(qk, {}).get("quota") if qk else None,
                "implicita": imp,
                "movimento": ev["quote"].get(qk, {}).get("movimento_pct") if qk else None}
    out["1X"] = dc("1", "X", "1X", mercato_quota.get("1X"))
    out["X2"] = dc("X", "2", "X2", mercato_quota.get("X2"))
    out["12"] = dc("1", "2", "12", mercato_quota.get("12"))
    return out


MERCATO_QUOTA = {
    "Under 2.5": "under25", "Over 2.5": "over25", "Goal": "goal", "No Goal": "nogoal",
    "1": "1", "X": "X", "2": "2", "1X": "1X", "X2": "X2", "12": "12",
}


def calcola_signal(ev):
    """Ritorna tutti i mercati con Signal Score, ordinati per punteggio decrescente."""
    mercati = []
    for nome in ("Under 2.5", "Over 2.5", "Goal", "No Goal"):
        mercati.append(_score_gol(nome, ev, MERCATO_QUOTA))
    mercati.extend(_score_1x2(ev, MERCATO_QUOTA).values())
    mercati.sort(key=lambda m: -m["score"])
    return mercati
