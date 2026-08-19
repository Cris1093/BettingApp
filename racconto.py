"""
racconto.py — NARRATORE (deterministico, senza LLM).

Trasforma evidenze + signal score in un'analisi PRE-MATCH discorsiva e strutturata,
nello stile dei ragionamenti richiesti (Goiás–Juventude / Morecambe–South Shields):

  1. Sintesi
  2. Forma generale
  3. Casa / trasferta
  4. Pattern principali e convergenze
  5. Eventi rari (con dimensione del campione)
  6. Over / Under
  7. Goal / No Goal
  8. 1X2
  9. Quote (implicite + movimento)
 10. Contraddizioni / rischi
 11. Migliori mercati (con stelline) e mercati da evitare
 12. Risultati esatti compatibili
 13. Pronostico principale (o "nessun mercato con valore")

Output: dict con 'sezioni' (lista di {titolo, righe}) + 'pronostico' + 'stelle'.
La app poi rende questo in HTML/Word. Nessun numero è inventato.
"""

import evidenze as EV


def _stelle(score):
    if score >= 80:
        return "★★★★★"
    if score >= 68:
        return "★★★★"
    if score >= 55:
        return "★★★"
    if score >= 45:
        return "★★"
    return "★"


def _p(x):
    return f"{x:.0f}%" if x is not None else "n/d"


# --------------------------------------------------------------------- sezioni
def _sintesi(home_name, away_name, ev):
    h, a = ev["home"], ev["away"]
    nh, na = ev["n_home"], ev["n_away"]
    righe = [
        f"{home_name} (casa) arriva da {nh} partite: "
        f"{h['generale']['v']}V {h['generale']['d']}N {h['generale']['s']}P, "
        f"media {h['generale']['media_tot']} gol a partita.",
        f"{away_name} (trasferta) arriva da {na} partite: "
        f"{a['generale']['v']}V {a['generale']['d']}N {a['generale']['s']}P, "
        f"media {a['generale']['media_tot']} gol a partita.",
    ]
    if min(nh, na) < 10:
        righe.append(f"⚠️ Campione limitato ({min(nh, na)} partite per una squadra): "
                     "i pattern vanno presi come indicativi, non consolidati.")
    return {"titolo": "Sintesi", "righe": righe}


def _forma_generale(home_name, away_name, ev):
    def descr(nome, b):
        return (f"{nome}: Over 2.5 {_p(b['over'][2.5]['pct'])}, Under 2.5 {_p(b['under25']['pct'])}, "
                f"Goal {_p(b['goal']['pct'])}, No Goal {_p(b['nogoal']['pct'])}, "
                f"clean sheet {_p(b['clean']['pct'])}. "
                f"Gol fatti {b['gf']}, subiti {b['gs']}.")
    return {"titolo": "Forma generale",
            "righe": [descr(home_name, ev["home"]["generale"]),
                      descr(away_name, ev["away"]["generale"])]}


def _casa_trasferta(home_name, away_name, ev):
    h, a = ev["home"]["split"], ev["away"]["split"]
    righe = []
    if h.get("n"):
        righe.append(f"{home_name} in casa ({h['n']}): {h['v']}V {h['d']}N {h['s']}P · "
                     f"Under 2.5 {_p(h['under25']['pct'])}, Goal {_p(h['goal']['pct'])}, "
                     f"No Goal {_p(h['nogoal']['pct'])}, clean sheet {_p(h['clean']['pct'])}.")
    if a.get("n"):
        righe.append(f"{away_name} in trasferta ({a['n']}): {a['v']}V {a['d']}N {a['s']}P · "
                     f"Under 2.5 {_p(a['under25']['pct'])}, Goal {_p(a['goal']['pct'])}, "
                     f"No Goal {_p(a['nogoal']['pct'])}, clean sheet {_p(a['clean']['pct'])}.")
    # confronto forza esito
    if h.get("n") and a.get("n"):
        vc = h["vitt"]["pct"]
        va = a["vitt"]["pct"]
        if vc <= 25 and va >= 50:
            righe.append(f"🔴 Contrasto forte: {home_name} vince poco in casa "
                         f"({_p(vc)}) mentre {away_name} rende molto in trasferta ({_p(va)}).")
        elif vc >= 50 and va <= 25:
            righe.append(f"🟢 {home_name} molto solido in casa ({_p(vc)} vittorie) "
                         f"contro un {away_name} debole fuori ({_p(va)}).")
    righe.append("Nota: il rendimento casa/trasferta pesa più del dato generale.")
    return {"titolo": "Casa / Trasferta", "righe": righe}


def _convergenze(ev):
    nomi = {"under25": "Under 2.5", "over25": "Over 2.5", "goal": "Goal", "nogoal": "No Goal"}
    righe = []
    for k, conv in sorted(ev["convergenze"].items(), key=lambda x: -x[1]["media"]):
        if conv["grado"] in ("forte", "media") and conv["media"] >= 55:
            vals = " / ".join(f"{v:.0f}%" for v in conv["valori"])
            righe.append(f"Convergenza {conv['grado'].upper()} su {nomi[k]}: {vals} "
                         f"(media {conv['media']:.0f}%) sui campioni generali e casa/trasferta.")
    if not righe:
        righe.append("Nessuna convergenza forte tra i campioni: partita più incerta nella lettura.")
    return {"titolo": "Pattern principali e convergenze", "righe": righe}


def _eventi_rari(home_name, away_name, ev):
    righe = []
    for nome, sq in ((home_name, ev["home"]), (away_name, ev["away"])):
        b = sq["generale"]
        n = b.get("n", 0)
        if not n:
            continue
        rari = []
        # 0-0 mai visto
        if 0 not in b["dist_tot"]:
            rari.append("0 gol totali mai verificato (0%)")
        # goleade rare
        o55 = b["over"][5.5]["pct"]
        if o55 <= 10:
            rari.append(f"Over 5.5 {EV.frequenza_label(o55, n)} ({_p(o55)})")
        # pattern dominante nella distribuzione
        dom = max(b["dist_tot"].items(), key=lambda x: x[1]["pct"])
        rari.append(f"risultato con {dom[0]} gol totali è il più frequente ({_p(dom[1]['pct'])})")
        righe.append(f"{nome}: " + "; ".join(rari) + f". [campione {n}: 1 caso = {100/n:.2f}%]")
    return {"titolo": "Eventi rari", "righe": righe}


def _serie_attive(home_name, away_name, ev):
    etich = {"under25": "Under 2.5", "over25": "Over 2.5", "goal": "Goal",
             "nogoal": "No Goal", "clean": "clean sheet", "nosegna": "senza segnare",
             "vitt": "vittorie", "sconf": "sconfitte"}
    righe = []
    for nome, sq in ((home_name, ev["home"]), (away_name, ev["away"])):
        attive = [f"{n} {etich[k]} di fila" for k, n in sq["serie"].items() if n >= 3]
        if attive:
            righe.append(f"{nome}: " + ", ".join(attive) + ".")
    return {"titolo": "Serie in corso", "righe": righe} if righe else None


def _mercati_sezione(signal, ev):
    """Sezioni Over/Under, Goal/NoGoal e 1X2 con i dati chiave."""
    by = {m["mercato"]: m for m in signal}

    def riga(nome):
        m = by.get(nome)
        if not m:
            return None
        q = f"quota {m['quota']} (implicita {_p(m['implicita'])})" if m.get("quota") else "quota n/d"
        mv = ""
        if m.get("movimento") is not None:
            verso = "in calo" if m["movimento"] < 0 else "in rialzo"
            mv = f", quota {verso} {m['movimento']:+.0f}%"
        stat = f"statistica {_p(m['stat'])} · " if m.get("stat") is not None else ""
        return f"{nome}: signal {m['score']}/100 · {stat}{q}{mv}."

    ou = [r for r in (riga("Over 2.5"), riga("Under 2.5")) if r]
    gg = [r for r in (riga("Goal"), riga("No Goal")) if r]
    x12 = [r for r in (riga("1"), riga("X"), riga("2")) if r]
    sezioni = []
    if ou:
        sezioni.append({"titolo": "Over / Under", "righe": ou})
    if gg:
        sezioni.append({"titolo": "Goal / No Goal", "righe": gg})
    if x12:
        sezioni.append({"titolo": "1X2", "righe": x12})
    return sezioni


def _quote_sezione(ev):
    righe = []
    etich = {"1": "1", "X": "X", "2": "2", "over25": "Over 2.5", "under25": "Under 2.5",
             "goal": "Goal", "nogoal": "No Goal"}
    for k, lab in etich.items():
        if k in ev["quote"]:
            q = ev["quote"][k]
            mv = ""
            if q.get("movimento_pct") is not None:
                mv = f" · movimento {q['movimento_pct']:+.0f}%"
            righe.append(f"{lab}: quota {q['quota']} → implicita {_p(q['implicita'])}{mv}")
    if not righe:
        righe.append("Nessuna quota fornita.")
    return {"titolo": "Quote e probabilità implicite", "righe": righe}


def _contraddizioni_rischi(ev, signal):
    righe = list(ev["contraddizioni"])
    if min(ev["n_home"], ev["n_away"]) < 10:
        righe.append("Campione ridotto: confidenza complessiva ridotta.")
    top = signal[0] if signal else None
    if top and top["score"] < 55:
        righe.append("Nessun mercato ha un supporto statistico forte: partita difficile da leggere.")
    if not righe:
        righe.append("Nessuna contraddizione rilevante tra i campioni.")
    return {"titolo": "Contraddizioni e rischi", "righe": righe}


def _migliori_mercati(signal):
    righe_top, righe_evita = [], []
    for m in signal[:6]:
        if m["score"] >= 45:
            val = ""
            if m.get("implicita") is not None and m.get("stat") is not None:
                d = m["stat"] - m["implicita"]
                if d >= 6:
                    val = " — potenziale valore"
                elif d <= -8:
                    val = " — quota che svaluta"
            q = f" @ {m['quota']}" if m.get("quota") else ""
            righe_top.append(f"{_stelle(m['score'])} {m['mercato']}{q} "
                             f"(signal {m['score']}/100){val}")
    # mercati da evitare: quota bassa ma poco supporto, o statistica contro
    for m in signal:
        if m.get("quota") and m.get("implicita") is not None and m.get("stat") is not None:
            if m["implicita"] >= 55 and m["stat"] < m["implicita"] - 8 and m["score"] < 45:
                righe_evita.append(f"{m['mercato']} @ {m['quota']}: quota compressa "
                                   f"(implica {_p(m['implicita'])}) ma statistica solo {_p(m['stat'])}.")
    sez = [{"titolo": "Migliori mercati", "righe": righe_top or ["Nessun mercato con supporto sufficiente."]}]
    if righe_evita:
        sez.append({"titolo": "Mercati da evitare", "righe": righe_evita[:4]})
    return sez


def _risultati_esatti(home_name, away_name, ev, signal):
    """Risultati compatibili con i pattern (gol più frequenti per squadra + tendenza gol)."""
    h, a = ev["home"], ev["away"]
    # gol più probabili per la squadra di casa (dallo split casa) e ospite (split trasf)
    def top_gol(blocco, fallback):
        b = blocco if blocco.get("n") else fallback
        if not b.get("n"):
            return [1, 0]
        ordina = sorted(b["dist_team"].items(), key=lambda x: -x[1]["pct"])
        return [g for g, _ in ordina[:2]] or [1, 0]
    gh = top_gol(h["split"], h["generale"])
    ga = top_gol(a["split"], a["generale"])
    combos = []
    for x in gh:
        for y in ga:
            combos.append((x, y))
    # ordina per "plausibilità": somma bassa se il mercato forte è Under/NoGoal
    by = {m["mercato"]: m for m in signal}
    under_forte = by.get("Under 2.5", {}).get("score", 0) >= 55 or \
        by.get("No Goal", {}).get("score", 0) >= 55
    combos = sorted(set(combos), key=lambda r: (r[0] + r[1]) if under_forte else -(r[0] + r[1]))
    righe = [f"{home_name} {x}-{y} {away_name}" for x, y in combos[:4]]
    return {"titolo": "Risultati esatti compatibili", "righe": righe}


def _pronostico(signal, ev):
    if not signal:
        return {"testo": "Dati insufficienti per un pronostico.", "mercato": None, "score": 0}
    # il "12" (no pareggio) è sicuro ma non è un titolo sensato: non lo si headline
    candidati = [m for m in signal if m["mercato"] != "12"]
    top = candidati[0] if candidati else signal[0]
    # regola d'oro: se nessun mercato è forte, dillo
    if top["score"] < 45:
        return {"testo": "Nessun mercato presenta un supporto statistico sufficiente: "
                "partita da evitare o da seguire solo con estrema prudenza.",
                "mercato": None, "score": top["score"]}
    q = f" @ {top['quota']}" if top.get("quota") else ""
    nota = ""
    if top.get("implicita") is not None and top.get("stat") is not None:
        d = top["stat"] - top["implicita"]
        if top.get("quota") and float(top["quota"]) <= 1.45 and d < 6:
            nota = " (molto probabile ma quota compressa: poco valore)"
        elif d >= 6:
            nota = " (con potenziale valore rispetto alla quota)"
    return {"testo": f"{_stelle(top['score'])} {top['mercato']}{q} — signal {top['score']}/100{nota}",
            "mercato": top["mercato"], "score": top["score"]}


# ------------------------------------------------------------------------ entry
def racconta(home_name, away_name, ev, signal):
    sezioni = [
        _sintesi(home_name, away_name, ev),
        _forma_generale(home_name, away_name, ev),
        _casa_trasferta(home_name, away_name, ev),
        _convergenze(ev),
        _eventi_rari(home_name, away_name, ev),
    ]
    serie = _serie_attive(home_name, away_name, ev)
    if serie:
        sezioni.append(serie)
    sezioni.extend(_mercati_sezione(signal, ev))
    sezioni.append(_quote_sezione(ev))
    sezioni.append(_contraddizioni_rischi(ev, signal))
    sezioni.extend(_migliori_mercati(signal))
    sezioni.append(_risultati_esatti(home_name, away_name, ev, signal))
    pron = _pronostico(signal, ev)
    return {"home": home_name, "away": away_name, "sezioni": sezioni,
            "pronostico": pron, "signal": signal}
