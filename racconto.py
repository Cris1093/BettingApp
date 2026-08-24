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
    """Sezioni Over/Under, Goal/NoGoal e 1X2. Signal = robustezza; a fianco EV/edge (value)."""
    by = {m["mercato"]: m for m in signal}

    def riga(nome):
        m = by.get(nome)
        if not m:
            return None
        stat = f"prob {_p(m['stat'])} · " if m.get("stat") is not None else ""
        if m.get("quota"):
            q = f"quota {m['quota']}"
            if m.get("market_prob_novig") is not None:
                q += f" (no-vig {_p(m['market_prob_novig'])})"
            val = ""
            if m.get("EV") is not None:
                val = f" · EV {m['EV']:+.2f}"
                if m.get("edge_novig") is not None:
                    val += f", edge {m['edge_novig']:+.0f}pt"
        else:
            q, val = "quota n/d", ""
        return f"{nome}: signal {m['score']}/100 · {stat}{q}{val}."

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
            nv = f" · no-vig {_p(q['market_prob_novig'])}" if q.get("market_prob_novig") is not None else ""
            mv = ""
            if q.get("movimento_pct") is not None:
                mv = f" · movimento {q['movimento_pct']:+.0f}%"
            righe.append(f"{lab}: quota {q['quota']} → implicita {_p(q['implicita'])}{nv}{mv}")
    if not righe:
        righe.append("Nessuna quota fornita.")
    return {"titolo": "Quote e probabilità implicite (raw + no-vig)", "righe": righe}


def _contraddizioni_rischi(ev, signal):
    righe = list(ev["contraddizioni"])
    if min(ev.get("n_eff_home", ev["n_home"]), ev.get("n_eff_away", ev["n_away"])) < 10:
        righe.append("Campione effettivo ridotto: confidenza complessiva ridotta.")
    top = signal[0] if signal else None
    if top and top["score"] < 55:
        righe.append("Nessun mercato ha un supporto statistico forte: partita difficile da leggere.")
    # allerta instabilità: componente instabilità presente in qualche mercato di testa
    for m in signal[:4]:
        for nome, val, det in m.get("componenti", []):
            if nome == "instabilità":
                righe.append(f"{m['mercato']}: {det} — segnale instabile, confidenza ridotta.")
                break
    if not righe:
        righe.append("Nessuna contraddizione rilevante tra i campioni.")
    return {"titolo": "Contraddizioni e rischi", "righe": righe}


def _migliori_mercati(signal):
    righe_top, righe_evita = [], []
    for m in signal[:6]:
        if m["score"] >= 28:
            val = ""
            if m.get("EV") is not None:
                if m["EV"] >= 0.05:
                    val = f" — value positivo (EV {m['EV']:+.2f})"
                elif m["EV"] <= -0.10:
                    val = f" — value negativo (EV {m['EV']:+.2f})"
            q = f" @ {m['quota']}" if m.get("quota") else ""
            righe_top.append(f"{_stelle(m['score'])} {m['mercato']}{q} "
                             f"(signal {m['score']}/100){val}")
    # mercati da evitare: quota compressa (no-vig alta) ma statistica bassa
    for m in signal:
        nov = m.get("market_prob_novig")
        if m.get("quota") and nov is not None and m.get("stat") is not None:
            if nov >= 55 and m["stat"] < nov - 10 and m["score"] < 45:
                righe_evita.append(f"{m['mercato']} @ {m['quota']}: quota compressa "
                                   f"(no-vig {_p(nov)}) ma statistica solo {_p(m['stat'])}.")
    sez = [{"titolo": "Migliori mercati (per robustezza)",
            "righe": righe_top or ["Nessun mercato con supporto sufficiente."]}]
    if righe_evita:
        sez.append({"titolo": "Mercati da evitare", "righe": righe_evita[:4]})
    return sez


def _risultati_esatti(home_name, away_name, ev, signal):
    """Risultati compatibili: preferisce quelli di Poisson (dai gol attesi), altrimenti
    li stima dai gol più frequenti."""
    fus = ev.get("fusione") or {}
    ris_pois = fus.get("risultati_poisson")
    if ris_pois:
        righe = [f"{home_name} {r['risultato']} {away_name}" for r in ris_pois[:4]]
        return {"titolo": "Risultati esatti compatibili", "righe": righe}
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


def _tier(score):
    """Etichetta di affidabilità onesta calibrata sulla scala compressa attuale."""
    if score >= 55:
        return "forte"
    if score >= 40:
        return "moderato"
    if score >= 28:
        return "debole"
    return "molto debole"


def _due_selezioni(signal, ev):
    """Due selezioni finali distinte (studio, punto 18):
    - best_prediction: il segnale statisticamente più affidabile (robustezza + prob);
    - best_value_bet: la migliore opportunità per EV/edge (value TEORICO finché non calibrato).
    Diamo SEMPRE il pronostico migliore con un'etichetta di affidabilità, invece di
    rifiutarci: sarà l'affidabilità (forte/moderato/debole) a guidare la scelta."""
    if not signal:
        return {"best_prediction": None, "best_value_bet": None,
                "testo": "Dati insufficienti per un pronostico."}

    # best_prediction: signal più alto, escludendo il "12" (no pareggio, non è un titolo)
    cand_pred = [m for m in signal if m["mercato"] != "12"]
    best_pred = cand_pred[0] if cand_pred else signal[0]

    # best_value_bet: EV più alto tra i mercati con quota; deve essere positivo e
    # avere un minimo di robustezza (evita value su segnali fragili)
    con_ev = [m for m in signal if m.get("EV") is not None and m.get("quota")]
    best_val = None
    if con_ev:
        cand_val = sorted(con_ev, key=lambda m: -m["EV"])
        if cand_val and cand_val[0]["EV"] > 0.03 and cand_val[0]["score"] >= 28:
            best_val = cand_val[0]

    tier = _tier(best_pred["score"])
    qp = f" @ {best_pred['quota']}" if best_pred.get("quota") else ""
    if best_pred["score"] < 28:
        testo = (f"{_stelle(best_pred['score'])} {best_pred['mercato']}{qp} — "
                 f"segnale {tier} ({best_pred['score']}/100): partita difficile da leggere, "
                 f"prendere con prudenza.")
    else:
        testo = (f"{_stelle(best_pred['score'])} {best_pred['mercato']}{qp} — "
                 f"signal {best_pred['score']}/100 (affidabilità: {tier})")
    return {"best_prediction": best_pred, "best_value_bet": best_val, "testo": testo,
            "tier": tier}


def _sezione_selezioni(sel):
    """Sezione che mostra le due selezioni in chiaro."""
    righe = []
    bp = sel.get("best_prediction")
    bv = sel.get("best_value_bet")
    if bp:
        q = f" @ {bp['quota']}" if bp.get("quota") else ""
        ev = f" · EV {bp['EV']:+.2f}" if bp.get("EV") is not None else ""
        tier = sel.get("tier", "")
        righe.append(f"🎯 Più affidabile (best prediction): {bp['mercato']}{q} — "
                     f"signal {bp['score']}/100 [{tier}], prob {_p(bp['stat'])}{ev}.")
    if bv:
        q = f" @ {bv['quota']}" if bv.get("quota") else ""
        edge = f", edge no-vig {bv['edge_novig']:+.0f}pt" if bv.get("edge_novig") is not None else ""
        righe.append(f"💰 Miglior value (best value bet): {bv['mercato']}{q} — "
                     f"EV {bv['EV']:+.2f}{edge} "
                     f"(signal {bv['score']}/100). Value teorico: affidabile quanto la "
                     f"probabilità del modello.")
    if bp and bv and bp["mercato"] != bv["mercato"]:
        righe.append("Nota: il mercato più sicuro e quello con più valore sono diversi — "
                     "scelta secondo il tuo obiettivo (sicurezza o convenienza).")
    if not righe:
        righe.append("Nessuna selezione disponibile.")
    return {"titolo": "Selezioni finali", "righe": righe}


def _pronostico(signal, ev):
    """Compat: ritorna il best_prediction come 'pronostico' principale."""
    sel = _due_selezioni(signal, ev)
    bp = sel.get("best_prediction")
    if not bp:
        return {"testo": sel["testo"], "mercato": None, "score": 0, "selezioni": sel}
    return {"testo": sel["testo"], "mercato": bp["mercato"], "score": bp["score"],
            "selezioni": sel}


# ------------------------------------------------------------------------ entry
def _distribuzione_gol(home_name, away_name, ev):
    """Mostra quante VOLTE (n/totale) ciascuna squadra ha fatto/subito esattamente N gol."""
    def riga(nome, sq):
        dfs = sq.get("dist_fs", {})
        if not dfs:
            return None
        tot = sq.get("generale", {}).get("n", 0)
        if not tot:
            return None
        fatti = dfs.get("fatti", {})
        subiti = dfs.get("subiti", {})
        ff = ", ".join(f"{g} gol {v['n']}/{tot}" for g, v in sorted(fatti.items()))
        ss = ", ".join(f"{g} gol {v['n']}/{tot}" for g, v in sorted(subiti.items()))
        return f"{nome} — fatti: {ff or 'n/d'}; subiti: {ss or 'n/d'}."
    righe = [r for r in (riga(home_name, ev["home"]), riga(away_name, ev["away"])) if r]
    return {"titolo": "Distribuzione gol (fatti / subiti)", "righe": righe} if righe else None


def _ragionamento_gol(home_name, away_name, ev):
    """Ragionamento CONCATENATO che porta a una banda di gol attesa."""
    h, a = ev["home"]["generale"], ev["away"]["generale"]
    prob = ev["prob"]
    passi = []
    hf = h.get("almeno1_fatto", {}).get("pct", 0)
    hs = h.get("almeno1_subito", {}).get("pct", 0)
    if hf >= 90 or hs >= 90:
        verbo = "segnato" if hf >= 90 else "subito"
        passi.append(f"{home_name} ha {verbo} almeno 1 gol in quasi tutte le partite "
                     f"({max(hf, hs):.0f}%): l'Over 0.5 è quasi scontato.")
    dom_h = max(h["dist_tot"].items(), key=lambda x: x[1]["pct"]) if h.get("dist_tot") else None
    dom_a = max(a["dist_tot"].items(), key=lambda x: x[1]["pct"]) if a.get("dist_tot") else None
    if dom_h and dom_a:
        passi.append(f"Il risultato-somma più frequente è {dom_h[0]} gol per {home_name} "
                     f"({dom_h[1]['pct']:.0f}%) e {dom_a[0]} gol per {away_name} ({dom_a[1]['pct']:.0f}%).")
    under = prob.get("Under 2.5")
    nogoal = prob.get("No Goal")
    tende_chiuso = (under is not None and under >= 55) or (nogoal is not None and nogoal >= 55)
    if dom_h and dom_a:
        base, alto = min(dom_h[0], dom_a[0]), max(dom_h[0], dom_a[0])
        if tende_chiuso:
            base_b = max(1, base)
            alto_b = min(2, base_b + 1) if base_b <= 1 else max(base_b, alto)
            passi.append(f"Poiché la partita tende al chiuso (Under {under:.0f}% / No Goal "
                         f"{nogoal:.0f}%), la banda più probabile è di {base_b}–{alto_b} "
                         "gol totali.")
        else:
            passi.append(f"Con tendenza aperta (Over prevalente), è probabile superare i "
                         f"{base} gol totali.")
    return {"titolo": "Ragionamento sui gol", "righe": passi} if passi else None


def _contesto_coppa(competizione):
    """Nota di cautela per coppe internazionali: forte in patria ≠ forte in Europa."""
    if not competizione:
        return None
    c = str(competizione).lower()
    internaz = any(k in c for k in ("champions", "europa", "conference", "coppa",
                                    "libertadores", "sudamericana", "cup", "uefa", "europe"))
    if not internaz:
        return None
    return {"titolo": "⚠️ Contesto competizione",
            "righe": ["Competizione internazionale/coppa: una squadra può dominare nel proprio "
                      "campionato ma essere modesta contro leghe più forti. I dati casa/trasferta "
                      "vanno letti con prudenza: gli avversari possono avere un livello molto "
                      "diverso dal solito."]}


def _peso_dati(home_name, away_name, ev):
    """Trasparenza: quali partite sono state pesate meno e l'handicap di livello."""
    info = ev.get("peso_info")
    if not info:
        return None
    righe = []
    for nome, chiave in ((home_name, "home"), (away_name, "away")):
        d = info.get(chiave, {})
        motivi = d.get("motivi", {})
        hc = d.get("handicap", 1.0)
        parti = []
        if motivi:
            parti.append("pesate meno: " + ", ".join(f"{n} {m}" for m, n in motivi.items()))
        if hc < 0.98:
            parti.append(f"handicap forza {hc:.2f} (categoria giocata inferiore alla partita)")
        if parti:
            righe.append(f"{nome}: " + "; ".join(parti) + ".")
    if not righe:
        return None
    righe.append("Le percentuali tengono conto di questi pesi; il record V/N/P resta quello reale.")
    return {"titolo": "Peso dei dati (contesto)", "righe": righe}


def _fusione_sezione(ev):
    """Trasparenza: gol attesi e le due sotto-stime (frequenze vs Poisson) prima della fusione."""
    fus = ev.get("fusione")
    if not fus:
        return None
    righe = [f"Gol attesi (λ): casa {fus['lambda_home']:.2f} · trasferta {fus['lambda_away']:.2f}."]
    pf = ev.get("prob_freq") or {}
    pp = ev.get("prob_poisson") or {}
    prob = ev.get("prob") or {}
    for m in ("1", "X", "2", "Over 2.5", "Goal"):
        if m in pf and m in pp:
            righe.append(f"{m}: frequenze {pf[m]:.0f}% + Poisson {pp[m]:.0f}% → fusa {prob.get(m,0):.0f}%.")
    w = f"{fus.get('w_freq',0.5):.2f}/{fus.get('w_pois',0.5):.2f}"
    righe.append(f"Peso di fusione frequenze/Poisson: {w} (provvisorio, da ottimizzare col backtest).")
    return {"titolo": "Fusione dei due motori (λ e sotto-stime)", "righe": righe}


def _sezione_statistico(stat):
    """Output del MOTORE STATISTICO: eventi forti con confidence (conteggi grezzi)."""
    if not stat or not stat.get("forti"):
        return {"titolo": "📊 Motore statistico (eventi più frequenti)",
                "righe": ["Nessun evento statisticamente forte e stabile trovato."]}
    righe = []
    for f in stat["forti"][:8]:
        ph_ = f["casa"][2]
        pa_ = f["trasf"][2]
        righe.append(f"[{f['confidence']}] {f['pronostico']} ({f['tipologia']}): "
                     f"casa {f['casa'][0]}/{f['casa'][1]} ({ph_:.0f}%) · "
                     f"trasf {f['trasf'][0]}/{f['trasf'][1]} ({pa_:.0f}%) · "
                     f"somma {f['somma'][0]}/{f['somma'][1]} ({f['somma_pct']:.0f}%).")
    return {"titolo": "📊 Motore statistico (eventi più frequenti)", "righe": righe}


def _tabella_statistica(stat):
    """Tabella completa degli eventi (per chi vuole vedere tutto)."""
    if not stat or not stat.get("tabella"):
        return None
    righe = []
    for r in stat["tabella"]:
        c, t, s = r["casa"], r["trasf"], r["somma"]
        cp = f"{c[2]:.0f}%" if c[2] is not None else "n/d"
        tp = f"{t[2]:.0f}%" if t[2] is not None else "n/d"
        sp = f"{s[2]:.0f}%" if s[2] is not None else "n/d"
        righe.append(f"{r['pronostico']} ({r['tipologia']}): "
                     f"casa {c[0]}/{c[1]} {cp} · trasf {t[0]}/{t[1]} {tp} · somma {s[0]}/{s[1]} {sp}.")
    return {"titolo": "📋 Tabella statistica completa", "righe": righe}


# mercati che i due motori hanno in comune (per la fusione): nome_statistico -> nome_motore
_MAP_STAT_MOTORE = {
    "1 (casa vince / ospite perde)": "1",
    "2 (casa perde / ospite vince)": "2",
    "X (pareggio)": "X",
    "1X (casa non perde / ospite non vince)": "1X",
    "X2 (casa non vince / ospite non perde)": "X2",
    "12 (nessun pareggio)": "12",
    "Over 2.5 totali": "Over 2.5",
    "Under 2.5 totali": "Under 2.5",
    "Goal": "Goal",
    "No Goal": "No Goal",
}


def fondi_due_motori(signal, stat):
    """FUSIONE FINALE: eventi su cui MOTORE (signal) e STATISTICO (frequenze) concordano.
    Sono i pronostici più sicuri, perché confermati da due metodi indipendenti."""
    if not signal or not stat:
        return []
    sig_by = {m["mercato"]: m for m in signal}
    # eventi forti dello statistico, ridotti ai mercati comuni col motore
    stat_forti = {}
    for f in stat.get("forti", []):
        nome = _MAP_STAT_MOTORE.get(f["pronostico"])
        if nome and nome not in stat_forti:
            stat_forti[nome] = f
    fusi = []
    for nome, f in stat_forti.items():
        m = sig_by.get(nome)
        if not m:
            continue
        # il motore deve dare un minimo di supporto (signal) e prob dalla parte giusta
        if m["score"] < 28 or (m.get("stat") is not None and m["stat"] < 50):
            continue
        # confidence combinata: media tra confidence statistica e signal normalizzato
        conf_stat = {"alta": 90, "media": 70, "bassa": 50}.get(f["confidence"], 50)
        conf_mot = m["score"]
        conf_fusa = round((conf_stat + conf_mot) / 2)
        fusi.append({"mercato": nome, "signal": m["score"], "prob": m.get("stat"),
                     "stat_somma": f["somma_pct"], "conf_stat": f["confidence"],
                     "confidence": conf_fusa, "quota": m.get("quota"), "EV": m.get("EV")})
    fusi.sort(key=lambda x: -x["confidence"])
    return fusi


def _sezione_fusione_finale(signal, stat):
    """I pronostici più sicuri: dove motore e statistico concordano."""
    fusi = fondi_due_motori(signal, stat)
    if not fusi:
        return {"titolo": "🏆 Pronostici fusi (motore + statistico)",
                "righe": ["Nessun evento confermato da entrambi i motori: partita incerta, "
                          "meglio astenersi o puntare solo sul singolo motore più forte."]}
    righe = []
    for x in fusi[:4]:
        q = f" @ {x['quota']}" if x.get("quota") else ""
        ev = f" · EV {x['EV']:+.2f}" if x.get("EV") is not None else ""
        righe.append(f"⭐ {x['mercato']}{q} — confidence {x['confidence']}/100 "
                     f"(motore signal {x['signal']}, statistico {x['stat_somma']:.0f}% "
                     f"[{x['conf_stat']}]){ev}.")
    righe.append("Questi sono i pronostici più sicuri: confermati sia dal motore "
                 "probabilistico sia da quello statistico (due metodi indipendenti).")
    return {"titolo": "🏆 Pronostici fusi (motore + statistico)", "righe": righe}


def racconta(home_name, away_name, ev, signal, competizione=None, statistico=None):
    sezioni = []
    coppa = _contesto_coppa(competizione)
    if coppa:
        sezioni.append(coppa)
    peso = _peso_dati(home_name, away_name, ev)
    if peso:
        sezioni.append(peso)
    sezioni.extend([
        _sintesi(home_name, away_name, ev),
        _forma_generale(home_name, away_name, ev),
    ])
    dist = _distribuzione_gol(home_name, away_name, ev)
    if dist:
        sezioni.append(dist)
    sezioni.extend([
        _casa_trasferta(home_name, away_name, ev),
        _convergenze(ev),
        _eventi_rari(home_name, away_name, ev),
    ])
    fus = _fusione_sezione(ev)
    if fus:
        sezioni.append(fus)
    rag = _ragionamento_gol(home_name, away_name, ev)
    if rag:
        sezioni.append(rag)
    serie = _serie_attive(home_name, away_name, ev)
    if serie:
        sezioni.append(serie)
    sezioni.extend(_mercati_sezione(signal, ev))
    sezioni.append(_quote_sezione(ev))
    sezioni.append(_contraddizioni_rischi(ev, signal))
    sezioni.extend(_migliori_mercati(signal))
    sezioni.append(_risultati_esatti(home_name, away_name, ev, signal))
    pron = _pronostico(signal, ev)
    sezioni.append(_sezione_selezioni(pron.get("selezioni", {})))
    # === TERZO OUTPUT: motore statistico + fusione dei due motori ===
    if statistico:
        sezioni.append(_sezione_statistico(statistico))
        sezioni.append(_sezione_fusione_finale(signal, statistico))
        tab = _tabella_statistica(statistico)
        if tab:
            sezioni.append(tab)
    fusi = fondi_due_motori(signal, statistico) if statistico else []
    return {"home": home_name, "away": away_name, "sezioni": sezioni,
            "pronostico": pron, "signal": signal,
            "statistico": statistico,
            "pronostico_statistico": (statistico.get("best") if statistico else None),
            "pronostici_fusi": fusi}
