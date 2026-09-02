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
def _riga_finestra(nome, partite, n):
    """Riga V/N/P + media gol su una finestra (ultime n)."""
    import evidenze
    sel = partite[:n] if n else partite
    if not sel:
        return None
    b = evidenze._blocco(sel)
    return (f"{nome} — ultime {len(sel)}: {b['v']}V {b['d']}N {b['s']}P, "
            f"media {b['media_tot']} gol.")


def _sintesi(home_name, away_name, ev):
    h, a = ev["home"], ev["away"]
    nh, na = ev["n_home"], ev["n_away"]
    ph = ev.get("partite_home") or []
    pa = ev.get("partite_away") or []
    righe = [
        f"{home_name} (casa) arriva da {nh} partite: "
        f"{h['generale']['v']}V {h['generale']['d']}N {h['generale']['s']}P, "
        f"media {h['generale']['media_tot']} gol a partita.",
        f"{away_name} (trasferta) arriva da {na} partite: "
        f"{a['generale']['v']}V {a['generale']['d']}N {a['generale']['s']}P, "
        f"media {a['generale']['media_tot']} gol a partita.",
    ]
    # finestre recenti contrapposte: ultime 10 (casa vs ospite), poi ultime 6
    for n in (10, 6):
        rh = _riga_finestra(home_name, ph, n)
        ra = _riga_finestra(away_name, pa, n)
        if rh:
            righe.append(rh)
        if ra:
            righe.append(ra)
    if min(nh, na) < 10:
        righe.append(f"⚠️ Campione limitato ({min(nh, na)} partite per una squadra): "
                     "i pattern vanno presi come indicativi, non consolidati.")
    return {"titolo": "Sintesi", "righe": righe}


def _forma_generale(home_name, away_name, ev):
    import evidenze

    def descr(nome, b):
        return (f"{nome}: Over 2.5 {_p(b['over'][2.5]['pct'])}, Under 2.5 {_p(b['under25']['pct'])}, "
                f"Goal {_p(b['goal']['pct'])}, No Goal {_p(b['nogoal']['pct'])}, "
                f"clean sheet {_p(b['clean']['pct'])}. "
                f"Gol fatti {b['gf']}, subiti {b['gs']}.")

    def descr_finestra(nome, partite, n):
        sel = partite[:n] if n else partite
        if len(sel) < 2:
            return None
        b = evidenze._blocco(sel)
        return (f"{nome} (ultime {len(sel)}): Over 2.5 {_p(b['over'][2.5]['pct'])}, "
                f"Goal {_p(b['goal']['pct'])}, No Goal {_p(b['nogoal']['pct'])}, "
                f"clean {_p(b['clean']['pct'])}.")

    ph = ev.get("partite_home") or []
    pa = ev.get("partite_away") or []
    righe = [descr(home_name, ev["home"]["generale"]),
             descr(away_name, ev["away"]["generale"])]
    # finestre contrapposte: ultime 10 (casa vs ospite), poi ultime 6
    for n in (10, 6):
        rh = descr_finestra(home_name, ph, n)
        ra = descr_finestra(away_name, pa, n)
        if rh:
            righe.append(rh)
        if ra:
            righe.append(ra)
    return {"titolo": "Forma generale", "righe": righe}


def _conta(partite, cond, n=None):
    """Conta quante partite soddisfano cond su una finestra (ultime n o tutte)."""
    sel = partite[:n] if n else partite
    tot = len(sel)
    k = sum(1 for p in sel if cond(p))
    return k, tot


def _incroci_gol(home_name, away_name, ev):
    """Incroci: gol FATTI da una squadra vs gol SUBITI dall'altra, su soglie 0.5 e 1.5,
    nelle finestre tutte / ultime 10 / ultime 5. È l'attacco di una contro la difesa
    dell'altra — il cuore della lettura Over/gol."""
    ph = ev.get("partite_home") or []
    pa = ev.get("partite_away") or []
    if not ph or not pa:
        return None
    righe = []
    for soglia in (0.5, 1.5):
        s = int(soglia)  # 0 o 1 (over 0.5 = gf>=1; over 1.5 = gf>=2)
        for etich, n in (("tutte", None), ("ultime 10", 10), ("ultime 5", 5)):
            # casa segna over soglia  vs  ospite subisce over soglia
            hk, ht = _conta(ph, lambda p: p["gf"] > soglia, n)
            ak, at = _conta(pa, lambda p: p["gs"] > soglia, n)
            # viceversa
            ak2, at2 = _conta(pa, lambda p: p["gf"] > soglia, n)
            hk2, ht2 = _conta(ph, lambda p: p["gs"] > soglia, n)
            righe.append(
                f"Over {soglia} ({etich}) — {home_name} segna: {hk}/{ht} · "
                f"{away_name} subisce: {ak}/{at}  |  "
                f"{away_name} segna: {ak2}/{at2} · {home_name} subisce: {hk2}/{ht2}")
    return {"titolo": "⚔️ Incroci gol (attacco vs difesa)", "righe": righe}


def _tassi_ou(home_name, away_name, ev):
    """Confronto Over/Under TOTALI tra le due squadre (quante loro partite sono finite
    over/under quella soglia), su finestre tutte/10/5. Due blocchi:
    - GENERALE: tutte le partite di ciascuna squadra;
    - CASA/TRASF: la casa solo in casa, l'ospite solo in trasferta.
    Linee: Over 1.5, Over/Under 2.5, Over/Under 3.5."""
    ph = ev.get("partite_home") or []
    pa = ev.get("partite_away") or []
    if not ph or not pa:
        return None

    ph_venue = [p for p in ph if p["casa"] is True]     # casa in casa
    pa_venue = [p for p in pa if p["casa"] is False]    # ospite in trasferta

    def tot_over(partite, soglia, n):
        sel = partite[:n] if n else partite
        tot = len(sel)
        k = sum(1 for p in sel if (p["gf"] + p["gs"]) > soglia)
        return k, tot

    # (etichetta mercato, soglia, is_over)
    linee = [("Over 1.5", 1.5, True),
             ("Over 2.5", 2.5, True), ("Under 2.5", 2.5, False),
             ("Over 3.5", 3.5, True), ("Under 3.5", 3.5, False)]
    finestre = [("tutte", None), ("ultime 10", 10), ("ultime 5", 5)]

    def riga(merc, soglia, is_over, etich, n, lh, la, nome_extra=""):
        hk, ht = tot_over(lh, soglia, n)
        ak, at = tot_over(la, soglia, n)
        if not is_over:  # Under = totale - over
            hk, ak = ht - hk, at - ak
        return (f"{merc} ({etich}{nome_extra}) — {home_name}: {hk}/{ht} · "
                f"{away_name}: {ak}/{at}")

    righe = ["— Confronto sul TOTALE partite —"]
    for merc, soglia, is_over in linee:
        for etich, n in finestre:
            righe.append(riga(merc, soglia, is_over, etich, n, ph, pa))
    righe.append("— Solo casa (per la casa) e trasferta (per l'ospite) —")
    for merc, soglia, is_over in linee:
        for etich, n in finestre:
            righe.append(riga(merc, soglia, is_over, etich, n, ph_venue, pa_venue, " casa/trasf"))
    return {"titolo": "📊 Over/Under a confronto (casa vs trasferta)", "righe": righe}


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


def valida_incrociato(signal, stat):
    """Confronto MOTORE vs STATISTICO mercato per mercato.
    - tabella (idea A+C): per ogni mercato prob motore, % statistico e SEMAFORO
      (🟢 validato / 🟡 debole / 🔴 discordante);
    - top5 (idea B): i 5 pronostici più sicuri con confidence 'boostata' dall'accordo.
    """
    if not signal or not stat:
        return {"tabella": [], "top5": []}
    sig_by = {m["mercato"]: m for m in signal}
    # mercato motore -> nome evento statistico (variante generale)
    stat_gen = {}
    for r in stat.get("tabella", []):
        if r["tipologia"] != "generale":
            continue
        nome_mot = _MAP_STAT_MOTORE.get(r["pronostico"])
        if nome_mot and nome_mot not in stat_gen:
            stat_gen[nome_mot] = r["somma"][2]   # % somma

    ordine = ["1", "X", "2", "1X", "X2", "12", "Over 1.5", "Under 1.5",
              "Over 2.5", "Under 2.5", "Over 3.5", "Under 3.5", "Goal", "No Goal"]
    tabella, valutati = [], []
    for merc in ordine:
        m = sig_by.get(merc)
        if not m:
            continue
        prob = m.get("stat")           # prob del motore
        signalscore = m.get("score", 0)
        statpct = stat_gen.get(merc)   # % statistico
        # semaforo: solo se il motore considera probabile il mercato (prob>=50)
        semaforo = "—"
        giudizio = "—"
        if prob is not None and prob >= 50 and statpct is not None:
            if statpct >= 65:
                semaforo, giudizio = "🟢", "validato"
            elif statpct >= 50:
                semaforo, giudizio = "🟡", "debole"
            else:
                semaforo, giudizio = "🔴", "discordante"
        tabella.append({"mercato": merc, "prob_motore": prob, "signal": signalscore,
                        "stat_pct": statpct, "semaforo": semaforo, "giudizio": giudizio,
                        "quota": m.get("quota"), "EV": m.get("EV")})
        # confidence boostata (idea B): solo mercati che il motore considera (prob>=50)
        if prob is not None and prob >= 50 and statpct is not None:
            combined = 0.5 * signalscore + 0.5 * statpct
            if giudizio == "validato":
                combined += 10
            elif giudizio == "discordante":
                combined -= 20
            combined = max(0, min(100, round(combined)))
            valutati.append({"mercato": merc, "confidence": combined,
                             "prob_motore": prob, "signal": signalscore,
                             "stat_pct": statpct, "semaforo": semaforo,
                             "quota": m.get("quota"), "EV": m.get("EV")})
    valutati.sort(key=lambda x: -x["confidence"])
    return {"tabella": tabella, "top5": valutati[:5]}


def _sezione_validazione(signal, stat):
    """Tabella A+C: motore vs statistico con semaforo."""
    vi = valida_incrociato(signal, stat)
    if not vi["tabella"]:
        return None, vi
    righe = []
    for r in vi["tabella"]:
        pm = f"{r['prob_motore']:.0f}%" if r["prob_motore"] is not None else "n/d"
        sp = f"{r['stat_pct']:.0f}%" if r["stat_pct"] is not None else "n/d"
        righe.append(f"{r['semaforo']} {r['mercato']}: motore {pm} (signal {r['signal']}) "
                     f"· statistico {sp} — {r['giudizio']}")
    return {"titolo": "🔀 Motore vs Statistico (validazione)", "righe": righe}, vi


def _sezione_top5(vi):
    """Idea B: i 5 pronostici più sicuri con confidence boostata dall'accordo."""
    if not vi or not vi.get("top5"):
        return None
    righe = []
    for i, x in enumerate(vi["top5"], 1):
        q = f" @ {x['quota']}" if x.get("quota") else ""
        ev = f" · EV {x['EV']:+.2f}" if x.get("EV") is not None else ""
        righe.append(f"{i}. {x['semaforo']} {x['mercato']}{q} — confidence {x['confidence']}/100 "
                     f"(motore {x['prob_motore']:.0f}%, statistico {x['stat_pct']:.0f}%){ev}")
    righe.append("Confidence potenziata quando motore e statistico concordano, ridotta quando "
                 "discordano. Sono i pronostici più sicuri secondo entrambi.")
    return {"titolo": "⭐ Top 5 pronostici più sicuri (confidence combinata)", "righe": righe}


def _sezione_classifica(stat):
    """Classifica degli eventi ordinati per % (somma), dal più alto."""
    if not stat or not stat.get("classifica"):
        return None
    righe = []
    for i, r in enumerate(stat["classifica"], 1):
        righe.append(f"{i} - {r['pronostico']} ({r['tipologia']}) - "
                     f"{r['n']}/{r['tot']} {r['pct']:.0f}%")
    return {"titolo": "🏅 Classifica statistica (per %)", "righe": righe}


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
    "Over 1.5 totali": "Over 1.5",
    "Under 1.5 totali": "Under 1.5",
    "Over 3.5 totali": "Over 3.5",
    "Under 3.5 totali": "Under 3.5",
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


def _classe_valore(ev_frac, edge):
    """Classifica una giocata secondo la regola dell'utente (EV prima, edge conferma)."""
    if ev_frac is None:
        return None
    ev_pct = ev_frac * 100
    if ev_pct <= 0:
        col, etich = "🔴", "non giocare"
    elif ev_pct < 3:
        col, etich = "🔴", "quasi sempre scarta"
    elif ev_pct < 10:
        col, etich = "🟡", "secondaria (valuta)"
    else:
        col, etich = "🟢", "principale (candidata)"
    anomalia = ev_pct >= 20
    if edge is None:
        edge_txt = ""
    elif edge >= 10:
        edge_txt = "edge ottimo"
    elif edge >= 5:
        edge_txt = "edge interessante"
    else:
        edge_txt = "edge debole"
    return {"col": col, "etichetta": etich, "ev_pct": ev_pct,
            "anomalia": anomalia, "edge_txt": edge_txt}


SIGNAL_MIN_VALORE = 20   # sotto questo il segnale è troppo fragile: EV non affidabile


def selezione_valore(signal):
    """Regola pratica di valore (EV → edge → signal). Ritorna (candidati ordinati, schedina).
    Il signal NON è il criterio principale, ma fa da GUARDIA: un EV alto con signal nullo o
    troppo basso è una falsa opportunità (probabilità fragile), quindi va escluso/declassato."""
    cand = []
    scartati_fragili = []
    for m in signal:
        if m.get("mercato") == "12":     # "12" (nessun pareggio): mai come giocata
            continue
        ev = m.get("EV")
        if ev is None or not m.get("quota"):
            continue
        cl = _classe_valore(ev, m.get("edge_novig"))
        if not cl:
            continue
        riga = {**m, "_cl": cl}
        # guardia signal: EV positivo ma segnale fragile -> non è una vera giocata
        if ev > 0 and m["score"] < SIGNAL_MIN_VALORE:
            riga["_fragile"] = True
            scartati_fragili.append(riga)
        else:
            cand.append(riga)
    cand.sort(key=lambda x: (-(x["EV"] or 0), -(x.get("edge_novig") or -999), -x["score"]))
    scartati_fragili.sort(key=lambda x: -(x["EV"] or 0))
    # schedina: EV>=10% E signal affidabile
    schedina = [c for c in cand if c["EV"] is not None and c["EV"] * 100 >= 10][:3]
    return cand, schedina, scartati_fragili


def _sezione_valore(signal):
    """Sezione IN CIMA: le giocate di valore secondo la regola EV → edge → signal.
    Il signal fa da guardia: EV alto con segnale fragile = falsa opportunità (esclusa)."""
    cand, schedina, fragili = selezione_valore(signal)
    if not cand and not fragili:
        return {"titolo": "💎 Giocate di valore (EV → edge → signal)",
                "righe": ["Nessuna quota inserita: senza quote non è possibile calcolare "
                          "EV/edge. Inserisci le quote per attivare la selezione di valore.",
                          _nota_calibrazione()]}
    righe = []
    if cand:
        best = cand[0]
        clb = best["_cl"]
        q = f" @ {best['quota']}" if best.get("quota") else ""
        edge_b = f"{best['edge_novig']:+.0f}pt" if best.get("edge_novig") is not None else "n/d"
        riga_best = (f"{clb['col']} MIGLIORE VALORE: {best['mercato']}{q} — "
                     f"EV {clb['ev_pct']:+.0f}%, edge {edge_b}, signal {best['score']}")
        if clb["anomalia"]:
            riga_best += " ⚠️ EV molto alto: verifica che non sia un'anomalia del modello."
        righe.append(riga_best)
        righe.append("")
        righe.append("Giocate per valore, con signal affidabile (dalla migliore):")
        for c in cand:
            cl = c["_cl"]
            q = f" @ {c['quota']}" if c.get("quota") else ""
            edge_c = f"{c['edge_novig']:+.0f}pt" if c.get("edge_novig") is not None else "n/d"
            extra = " ⚠️ verifica anomalia" if cl["anomalia"] else ""
            righe.append(f"  {cl['col']} {c['mercato']}{q}: EV {cl['ev_pct']:+.0f}% · "
                         f"edge {edge_c} · signal {c['score']} — {cl['etichetta']}, {cl['edge_txt']}{extra}")
    else:
        righe.append("Nessuna giocata di valore con signal affidabile.")

    # giocate fragili: EV positivo ma signal troppo basso -> NON giocare (falsa opportunità)
    if fragili:
        righe.append("")
        righe.append(f"⛔ Escluse — valore apparente ma signal < {SIGNAL_MIN_VALORE} "
                     "(probabilità fragile, EV inaffidabile):")
        for c in fragili[:5]:
            cl = c["_cl"]
            q = f" @ {c['quota']}" if c.get("quota") else ""
            righe.append(f"  ⛔ {c['mercato']}{q}: EV {cl['ev_pct']:+.0f}% ma signal {c['score']} "
                         "— NON giocare: il modello non è affidabile su questo mercato.")

    righe.append("")
    if schedina:
        nomi = ", ".join(f"{c['mercato']} @ {c['quota']}" for c in schedina)
        righe.append(f"🎯 Schedina di valore (EV ≥ +10% e signal affidabile): {nomi}")
        righe.append("Ricorda: probabilità = quanto pensi succeda; quota = quanto ti pagano; "
                     "EV = se il prezzo vale il rischio. Il valore guida la scelta, ma il signal "
                     "deve confermare che la probabilità è solida.")
    else:
        righe.append("🎯 Nessuna giocata con EV ≥ +10% e signal affidabile: niente candidate forti.")
    righe.append(_nota_calibrazione())
    return {"titolo": "💎 Giocate di valore (EV → edge → signal)", "righe": righe}


def _nota_calibrazione():
    return ("ℹ️ Le probabilità dei mercati gol (Over/Under, Goal/No Goal) sono CALIBRATE: "
            "il backtest ha mostrato che il modello le sovrastimava, quindi sono state "
            "abbassate ai valori realistici. L'1X2 è già affidabile e resta invariato.")


def _opposto_accaduto(mercato, partita):
    """Dato un mercato e UNA partita giocata (dict gf/gs/casa), dice se in quella partita
    è uscito l'esito OPPOSTO al mercato. None se non applicabile."""
    gf, gs = int(partita["gf"]), int(partita["gs"])
    tot = gf + gs
    m = mercato.strip()
    # gol totali
    if m == "Over 1.5":  return tot < 2
    if m == "Under 1.5": return tot >= 2
    if m == "Over 2.5":  return tot < 3
    if m == "Under 2.5": return tot >= 3
    if m == "Over 3.5":  return tot < 4
    if m == "Under 3.5": return tot >= 4
    if m == "Goal":      return not (gf >= 1 and gs >= 1)
    if m == "No Goal":   return (gf >= 1 and gs >= 1)
    # segni: opposto = la squadra (dal suo punto di vista, gf=suoi gol) ha PERSO
    if m in ("1", "1X"):  return gf < gs      # casa/non-perde -> opposto: ha perso
    if m in ("2", "X2"):  return gf < gs      # ospite/non-perde -> opposto: ha perso
    if m == "X":          return gf != gs     # opposto del pari: c'è un vincitore
    return None


def _veto_contro_tendenza(mercato, partite_home, partite_away):
    """Applica i blocchi di veto. Ritorna (vietato: bool, motivo: str|None).
    1) opposto nell'ULTIMA partita di una delle due squadre (qualsiasi sede);
    2) opposto >=3 volte nelle ULTIME 5 di una delle due (qualsiasi sede);
    3) per i SEGNI: sconfitta nell'ultima gara nella sede specifica;
    4) opposto nell'ULTIMA partita nella SEDE specifica (casa in casa / ospite in trasferta),
       valido per TUTTI i mercati;
    5) opposto >=3 volte nelle ULTIME 5 nella SEDE specifica, per TUTTI i mercati."""
    ph = partite_home or []
    pa = partite_away or []
    # sotto-insiemi per sede: casa quando gioca in casa, ospite quando gioca in trasferta
    ph_casa = [p for p in ph if p.get("casa") is True]
    pa_trasf = [p for p in pa if p.get("casa") is False]

    # blocco 1: ultima partita (qualsiasi sede)
    for part, nome in ((ph, "casa"), (pa, "ospite")):
        if part and _opposto_accaduto(mercato, part[0]):
            return True, f"opposto nell'ultima partita ({nome})"

    # blocco 2: >=3 volte nelle ultime 5 (qualsiasi sede)
    for part, nome in ((ph, "casa"), (pa, "ospite")):
        cnt = sum(1 for p in part[:5] if _opposto_accaduto(mercato, p))
        if cnt >= 3:
            return True, f"opposto {cnt}/5 volte nelle ultime 5 ({nome})"

    # blocco 3: sede specifica per i segni (sconfitta)
    m = mercato.strip()
    if m in ("1", "1X") and ph_casa and _opposto_accaduto(m, ph_casa[0]):
        return True, "sconfitta nell'ultima gara in casa"
    if m in ("2", "X2") and pa_trasf and _opposto_accaduto(m, pa_trasf[0]):
        return True, "sconfitta nell'ultima gara in trasferta"

    # blocco 4: opposto nell'ULTIMA partita nella SEDE specifica (tutti i mercati)
    if ph_casa and _opposto_accaduto(mercato, ph_casa[0]):
        return True, "opposto nell'ultima gara in casa (casa)"
    if pa_trasf and _opposto_accaduto(mercato, pa_trasf[0]):
        return True, "opposto nell'ultima gara in trasferta (ospite)"

    # blocco 5: opposto >=3 volte nelle ULTIME 5 nella SEDE specifica (tutti i mercati)
    cnt_casa = sum(1 for p in ph_casa[:5] if _opposto_accaduto(mercato, p))
    if cnt_casa >= 3:
        return True, f"opposto {cnt_casa}/5 nelle ultime in casa (casa)"
    cnt_trasf = sum(1 for p in pa_trasf[:5] if _opposto_accaduto(mercato, p))
    if cnt_trasf >= 3:
        return True, f"opposto {cnt_trasf}/5 nelle ultime in trasferta (ospite)"

    return False, None


def _seleziona_con_veto(candidati_ordinati, partite_home, partite_away, conf_min=32):
    """Data una lista di (mercato, confidence) ordinata dal migliore, applica il veto e
    ritorna il PRIMO che passa tutti i blocchi con confidence >= conf_min.
    Ritorna (mercato, confidence, vietati) dove vietati è la lista dei bloccati (per nota).
    Se nessuno passa: (None, None, vietati)."""
    vietati = []
    for merc, conf in candidati_ordinati:
        if conf is None or conf < conf_min:
            continue
        vietato, motivo = _veto_contro_tendenza(merc, partite_home, partite_away)
        if vietato:
            vietati.append((merc, motivo))
            continue
        return merc, conf, vietati
    return None, None, vietati


def fusione_media(signal, stat, partite_home=None, partite_away=None):
    """Fusione a MEDIA: per i mercati candidati (doppie chance, Goal/NoGoal, Over/Under
    1.5/2.5/3.5) calcola (prob_motore + %_statistico)/2. Ordina e applica il VETO
    contro-tendenza (ripiego al successivo, conf>=32). Ritorna (mercato, confidence) o
    (None, None)."""
    if not signal or not stat:
        return None, None
    sig_by = {m["mercato"]: m.get("stat") for m in signal}   # prob del motore
    stat_pct = {}
    for r in stat.get("tabella", []):
        if r["tipologia"] != "generale":
            continue
        nome_mot = _MAP_STAT_MOTORE.get(r["pronostico"])
        if nome_mot and nome_mot not in stat_pct:
            stat_pct[nome_mot] = r["somma"][2]
    candidati = ["1X", "X2", "Goal", "No Goal",
                 "Over 1.5", "Under 1.5", "Over 2.5", "Under 2.5", "Over 3.5", "Under 3.5"]
    scored = []
    for merc in candidati:
        pm = sig_by.get(merc)
        ps = stat_pct.get(merc)
        if pm is None or ps is None:
            continue
        scored.append((merc, round((pm + ps) / 2.0)))
    scored.sort(key=lambda t: t[1], reverse=True)
    if partite_home is not None:
        merc, conf, _ = _seleziona_con_veto(scored, partite_home, partite_away)
        return (merc, conf) if merc else (None, None)
    return (scored[0][0], scored[0][1]) if scored else (None, None)


def solo_statistico(stat, partite_home=None, partite_away=None):
    """Miglior pronostico basato SOLO sui dati statistici, tra gli stessi mercati della
    fusione a media. Ordina per % e applica il VETO contro-tendenza (ripiego, conf>=32).
    Ritorna (mercato, percentuale) o (None, None)."""
    if not stat:
        return None, None
    stat_pct = {}
    for r in stat.get("tabella", []):
        if r["tipologia"] != "generale":
            continue
        nome_mot = _MAP_STAT_MOTORE.get(r["pronostico"])
        if nome_mot and nome_mot not in stat_pct:
            stat_pct[nome_mot] = r["somma"][2]
    candidati = ["1X", "X2", "Goal", "No Goal",
                 "Over 1.5", "Under 1.5", "Over 2.5", "Under 2.5", "Over 3.5", "Under 3.5"]
    scored = [(merc, round(stat_pct[merc])) for merc in candidati if stat_pct.get(merc) is not None]
    scored.sort(key=lambda t: t[1], reverse=True)
    if partite_home is not None:
        merc, conf, _ = _seleziona_con_veto(scored, partite_home, partite_away)
        return (merc, conf) if merc else (None, None)
    return (scored[0][0], scored[0][1]) if scored else (None, None)


def racconta(home_name, away_name, ev, signal, competizione=None, statistico=None):
    sezioni = []
    # 💎 GIOCATE DI VALORE — in cima a tutto (regola EV → edge → signal)
    sezioni.append(_sezione_valore(signal))
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
    incr = _incroci_gol(home_name, away_name, ev)
    if incr:
        sezioni.append(incr)
    tou = _tassi_ou(home_name, away_name, ev)
    if tou:
        sezioni.append(tou)
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
        # validazione incrociata (A+C) + top 5 con confidence combinata (B)
        sez_val, vi = _sezione_validazione(signal, statistico)
        if sez_val:
            sezioni.append(sez_val)
        top5 = _sezione_top5(vi)
        if top5:
            sezioni.append(top5)
        clas = _sezione_classifica(statistico)
        if clas:
            sezioni.append(clas)
        tab = _tabella_statistica(statistico)
        if tab:
            sezioni.append(tab)
    fusi = fondi_due_motori(signal, statistico) if statistico else []
    ph = ev.get("partite_home")
    pa = ev.get("partite_away")
    fus_media_merc, fus_media_conf = (fusione_media(signal, statistico, ph, pa)
                                      if statistico else (None, None))
    stat_merc, stat_conf = (solo_statistico(statistico, ph, pa)
                            if statistico else (None, None))

    # VETO anche sul pronostico principale (Motore): se il suo mercato è bloccato dalla
    # contro-tendenza, ripiega sul miglior mercato del signal che passa (conf>=32).
    pron_out = pron
    primo_merc = pron.get("mercato") if pron else None   # primo pronostico (pre-veto)
    primo_bloccato = False
    if pron and pron.get("mercato") and ph is not None:
        vietato, motivo = _veto_contro_tendenza(pron["mercato"], ph, pa)
        if vietato:
            primo_bloccato = True
            # lista ordinata dei mercati del signal per probabilità (escluso "12")
            scored = sorted(((m["mercato"], m.get("stat")) for m in signal
                             if m.get("stat") is not None and m.get("mercato") != "12"),
                            key=lambda t: t[1], reverse=True)
            nuovo, nconf, _ = _seleziona_con_veto(scored, ph, pa)
            if nuovo:
                pron_out = dict(pron)
                pron_out["mercato"] = nuovo
                pron_out["veto_ripiego"] = f"{pron['mercato']} bloccato ({motivo})"
            else:
                pron_out = dict(pron)
                pron_out["mercato"] = None
                pron_out["veto_ripiego"] = f"nessun pronostico giocabile ({motivo})"

    # miglior pronostico per EV (solo dove ci sono quote): mercato con EV massimo positivo
    miglior_ev = {"mercato": None, "ev": None, "quota": None}
    val = ev.get("value") or {}
    _best = None
    for merc, d in val.items():
        e = d.get("EV")
        if e is None:
            continue
        if _best is None or e > _best[1]:
            _best = (merc, e, d.get("quota"))
    if _best:
        miglior_ev = {"mercato": _best[0], "ev": round(_best[1] * 100, 1), "quota": _best[2]}

    return {"home": home_name, "away": away_name, "sezioni": sezioni,
            "pronostico": pron_out, "signal": signal,
            "statistico": statistico,
            "pronostico_statistico": (statistico.get("best") if statistico else None),
            "pronostici_fusi": fusi,
            "fusione_media": {"mercato": fus_media_merc, "confidence": fus_media_conf},
            "solo_statistico": {"mercato": stat_merc, "confidence": stat_conf},
            "miglior_ev": miglior_ev,
            "primo_pronostico": primo_merc, "primo_bloccato": primo_bloccato,
            "prob_1x2": {"1": (ev.get("prob") or {}).get("1"),
                         "X": (ev.get("prob") or {}).get("X"),
                         "2": (ev.get("prob") or {}).get("2")}}
