"""
evidenze.py — Motore delle EVIDENZE (deterministico, senza LLM).

Data una partita da pronosticare + lo storico delle due squadre, calcola tutte le
evidenze statistiche che servono al ragionamento pre-partita, nello stile delle
analisi Goiás–Juventude / Morecambe–South Shields:

  - split generale / casa / trasferta / forma recente (ultime 3-5-10)
  - distribuzione esatta dei gol totali (0,1,2,3,4,5,6+) con frequenze
  - eventi rari con dimensione del campione esplicita (1/15 = 6,67%, non "0-5%")
  - Over 0.5 ... 5.5, Under 2.5, Goal/NoGoal, Clean sheet, gol per squadra
  - probabilità implicita dalle quote (1/quota, GREZZA) e movimento quota
  - CONVERGENZA: stesso segnale in più campioni indipendenti -> forte/media/debole
  - CONTRADDIZIONI: il dato generale dice X, il dato casa/trasferta dice il contrario

Tutto è puro conteggio: nessun numero è "stimato". La dimensione del campione entra
esplicitamente in ogni giudizio.

Contratto d'ingresso (una squadra):
  partite = lista di dict, ognuno con:
    {"gf": int, "gs": int, "casa": bool}   # gf/gs = gol fatti/subiti da QUESTA squadra
  ordinate dalla più recente alla meno recente.
"""

# --------------------------------------------------------------------------- util
def _pct(n, tot):
    return (n / tot * 100.0) if tot else 0.0


def _r2(x):
    return round(x + 1e-9, 2)


def frequenza_label(p, tot):
    """Etichetta di frequenza tenendo conto del campione (stile analisi richiesta)."""
    if tot == 0:
        return "dato assente"
    if p == 0:
        return "mai verificato"
    if p <= 5:
        return "estremamente raro"
    if p <= 10:
        return "raro"
    if p <= 25:
        return "poco frequente"
    if p <= 50:
        return "frequenza normale"
    if p <= 75:
        return "frequente"
    return "molto frequente"


# ------------------------------------------------------------------ split squadra
def _blocco(partite):
    """Calcola tutte le metriche su un insieme di partite di UNA squadra.
    Ogni partita può avere un 'peso' (default 1.0): il RECORD (V/N/P, gol) resta intero
    e onesto, ma le PERCENTUALI sono pesate (amichevoli e categorie inferiori contano meno)."""
    n = len(partite)
    if n == 0:
        return {"n": 0}
    W = sum(p.get("peso", 1.0) for p in partite) or 1.0
    v = d = s = 0
    gf = gs = 0
    # accumulatori PESATI (per le percentuali)
    vw = dw = sw = 0.0
    over = {ln: 0.0 for ln in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)}
    goalw = nogoalw = cleanw = nosegnaw = 0.0
    a1f = a1s = 0.0
    dist = {}                      # distribuzione gol TOTALI (pesata)
    dist_team = {}                 # distribuzione gol della squadra (pesata)
    for p in partite:
        w = p.get("peso", 1.0)
        f, a = int(p["gf"]), int(p["gs"])
        gf += f
        gs += a
        if f > a:
            v += 1; vw += w
        elif f == a:
            d += 1; dw += w
        else:
            s += 1; sw += w
        tot = f + a
        for ln in over:
            if tot > ln:
                over[ln] += w
        if f > 0 and a > 0:
            goalw += w
        else:
            nogoalw += w
        if a == 0:
            cleanw += w
        if f == 0:
            nosegnaw += w
        if f >= 1:
            a1f += w
        if a >= 1:
            a1s += w
        dist[tot] = dist.get(tot, 0.0) + w
        dist_team[f] = dist_team.get(f, 0.0) + w
    def pw(x):
        return _r2(x / W * 100.0)
    under_w = W - over[2.5]
    return {
        "n": n, "v": v, "d": d, "s": s, "gf": gf, "gs": gs,
        "media_tot": _r2((gf + gs) / n), "media_fatti": _r2(gf / n), "media_subiti": _r2(gs / n),
        "over": {ln: {"n": round(c, 1), "pct": pw(c)} for ln, c in over.items()},
        "under25": {"n": round(under_w, 1), "pct": pw(under_w)},
        "goal": {"n": round(goalw, 1), "pct": pw(goalw)},
        "nogoal": {"n": round(nogoalw, 1), "pct": pw(nogoalw)},
        "almeno1_fatto": {"n": round(a1f, 1), "pct": pw(a1f)},
        "almeno1_subito": {"n": round(a1s, 1), "pct": pw(a1s)},
        "clean": {"n": round(cleanw, 1), "pct": pw(cleanw)},
        "nosegna": {"n": round(nosegnaw, 1), "pct": pw(nosegnaw)},
        "vitt": {"n": v, "pct": pw(vw)},
        "pari": {"n": d, "pct": pw(dw)},
        "sconf": {"n": s, "pct": pw(sw)},
        "dist_tot": {k: {"n": round(c, 1), "pct": pw(c)} for k, c in sorted(dist.items())},
        "dist_team": {k: {"n": round(c, 1), "pct": pw(c)} for k, c in sorted(dist_team.items())},
    }


def _recenti(partite, k):
    return _blocco(partite[:k]) if len(partite) >= 1 else {"n": 0}


def analizza_squadra(partite, venue):
    """venue: 'casa' se è la squadra di casa, 'trasf' se è quella in trasferta.
    Restituisce blocchi: generale, split (partite nel venue rilevante), recenti 3/5/10."""
    generale = _blocco(partite)
    rilevanti = [p for p in partite if p["casa"] == (venue == "casa")]
    split = _blocco(rilevanti)
    return {
        "generale": generale,
        "split": split,             # casa per la squadra di casa, trasferta per l'ospite
        "venue": venue,
        "recenti3": _recenti(partite, 3),
        "recenti5": _recenti(partite, 5),
        "recenti10": _recenti(partite, 10),
        "serie": _serie(partite),
    }


# ----------------------------------------------------------------------- streaks
def _serie(partite):
    """Serie in corso (dalla più recente): Over/Under, Goal/NoGoal, esito, clean."""
    def streak(cond):
        c = 0
        for p in partite:
            if cond(p):
                c += 1
            else:
                break
        return c
    return {
        "over25": streak(lambda p: p["gf"] + p["gs"] > 2.5),
        "under25": streak(lambda p: p["gf"] + p["gs"] < 2.5),
        "goal": streak(lambda p: p["gf"] > 0 and p["gs"] > 0),
        "nogoal": streak(lambda p: not (p["gf"] > 0 and p["gs"] > 0)),
        "clean": streak(lambda p: p["gs"] == 0),
        "nosegna": streak(lambda p: p["gf"] == 0),
        "vitt": streak(lambda p: p["gf"] > p["gs"]),
        "sconf": streak(lambda p: p["gf"] < p["gs"]),
    }


# ------------------------------------------------------------------- convergenza
def _grado_convergenza(valori):
    """Dato un insieme di percentuali (stesso segnale su campioni diversi), stabilisce
    quanto convergono: tutte alte o tutte basse = forte."""
    vals = [v for v in valori if v is not None]
    if len(vals) < 2:
        return None
    alte = sum(1 for v in vals if v >= 60)
    basse = sum(1 for v in vals if v <= 40)
    media = sum(vals) / len(vals)
    spread = max(vals) - min(vals)
    if (alte >= len(vals) - 1 or basse >= len(vals) - 1) and spread <= 25:
        grado = "forte"
    elif spread <= 35 and (alte >= 2 or basse >= 2):
        grado = "media"
    else:
        grado = "debole"
    return {"grado": grado, "media": _r2(media), "spread": _r2(spread),
            "valori": [_r2(v) for v in vals]}


def convergenze(home, away):
    """Cerca convergenze sui mercati principali usando i 4 campioni indipendenti:
    home generale, home casa, away generale, away trasferta."""
    out = {}

    def raccogli(chiave, sub=None):
        def val(blocco):
            if not blocco or blocco.get("n", 0) == 0:
                return None
            x = blocco[chiave]
            return x[sub]["pct"] if sub else x["pct"]
        return [val(home["generale"]), val(home["split"]),
                val(away["generale"]), val(away["split"])]

    mercati = {
        "under25": ("under25", None), "over25": ("over", 2.5),
        "goal": ("goal", None), "nogoal": ("nogoal", None),
    }
    for nome, (chiave, sub) in mercati.items():
        conv = _grado_convergenza(raccogli(chiave, sub))
        if conv:
            out[nome] = conv
    return out


# ----------------------------------------------------------------- contraddizioni
def contraddizioni(squadra, etichetta):
    """Segnala quando il dato generale e il dato casa/trasferta divergono molto."""
    out = []
    g, sp = squadra["generale"], squadra["split"]
    if g.get("n", 0) == 0 or sp.get("n", 0) == 0:
        return out
    coppie = [
        ("Over 2.5", g["over"][2.5]["pct"], sp["over"][2.5]["pct"]),
        ("Goal", g["goal"]["pct"], sp["goal"]["pct"]),
        ("Under 2.5", g["under25"]["pct"], sp["under25"]["pct"]),
    ]
    venue = "in casa" if squadra["venue"] == "casa" else "in trasferta"
    for mercato, pg, ps in coppie:
        if abs(pg - ps) >= 25:
            verso = "più alto" if ps > pg else "più basso"
            out.append(f"{etichetta}: {mercato} generale {pg:.0f}% ma {venue} {ps:.0f}% "
                       f"(rendimento {venue} nettamente {verso})")
    return out


# ------------------------------------------------------------------------- quote
def implicita(quota):
    try:
        q = float(quota)
        return _r2(100.0 / q) if q > 0 else None
    except (TypeError, ValueError):
        return None


def analizza_quote(odds, variazioni=None):
    """Probabilità implicite del mercato per ogni mercato:
    - market_prob_raw = 1/quota (grezza, include il margine del bookmaker)
    - market_prob_novig = depurata dal margine (normalizzata sul gruppo completo)
    Più il movimento quota. NON tocca la probabilità del modello (regola 7)."""
    odds = odds or {}
    variazioni = variazioni or {}
    # gruppi che formano un evento completo (per togliere il margine)
    gruppi = [("1", "X", "2"), ("over25", "under25"), ("goal", "nogoal")]
    raw = {}
    for k, q in odds.items():
        imp = implicita(q)
        if imp is not None:
            raw[k] = imp
    # no-vig: normalizza ogni gruppo completo a somma 100
    novig = {}
    margine = {}
    for g in gruppi:
        presenti = [k for k in g if k in raw]
        s = sum(raw[k] for k in presenti)
        if len(presenti) == len(g) and s > 0:
            for k in presenti:
                novig[k] = _r2(raw[k] / s * 100.0)
                margine[k] = _r2(s - 100.0)      # overround del gruppo (in punti %)
    out = {}
    for k, q in odds.items():
        imp = raw.get(k)
        if imp is None:
            continue
        mv = None
        var = variazioni.get(k)
        try:
            if var is not None:
                iniziale = float(q) - float(var)
                if iniziale > 0:
                    mv = _r2((float(q) - iniziale) / iniziale * 100.0)
        except (TypeError, ValueError):
            mv = None
        out[k] = {"quota": _r2(float(q)),
                  "implicita": imp,                         # retrocompatibilità (= raw)
                  "market_prob_raw": imp,
                  "market_prob_novig": novig.get(k),
                  "margine_gruppo": margine.get(k),
                  "movimento_pct": mv}
    return out


def calcola_value(prob, quote):
    """Value ECONOMICO per ogni mercato, tenuto SEPARATO dalla probabilità del modello.
    Usa la probabilità del modello (prob) e il mercato (quote). Espone:
    fair_odds, edge_raw, edge_novig, EV. Il metro principale è edge_novig / EV.
    NB: affidabile solo quanto è accurata la probabilità del modello (value TEORICO
    finché non calibrato su dati reali)."""
    mappa = {"Over 2.5": "over25", "Under 2.5": "under25", "Goal": "goal", "No Goal": "nogoal",
             "Over 1.5": "over15", "Under 1.5": "under15", "Over 3.5": "over35", "Under 3.5": "under35",
             "1": "1", "X": "X", "2": "2"}   # doppie chance: di norma senza quota
    out = {}
    for mercato, p in (prob or {}).items():
        qk = mappa.get(mercato, mercato)
        q = quote.get(qk) if quote else None
        if not q:
            continue
        quota = q.get("quota")
        raw = q.get("market_prob_raw")
        nov = q.get("market_prob_novig")
        pf = p / 100.0
        fair = _r2(100.0 / p) if p > 0 else None
        ev = _r2(pf * float(quota) - 1.0) if quota else None
        out[mercato] = {
            "prob_modello": p,
            "fair_odds": fair,
            "quota": quota,
            "market_prob_raw": raw,
            "market_prob_novig": nov,
            "edge_raw": _r2(p - raw) if raw is not None else None,
            "edge_novig": _r2(p - nov) if nov is not None else None,
            "EV": ev,
        }
    return out


# ------------------------------------------------------------------------- entry
def _dist_fatti_subiti(partite):
    """Distribuzione di quante volte la squadra ha FATTO esattamente N gol e
    SUBITO esattamente N gol (punto 1 delle annotazioni)."""
    n = len(partite)
    fatti, subiti = {}, {}
    for p in partite:
        f, s = int(p["gf"]), int(p["gs"])
        fatti[f] = fatti.get(f, 0) + 1
        subiti[s] = subiti.get(s, 0) + 1
    return {
        "fatti": {k: {"n": c, "pct": _r2(_pct(c, n))} for k, c in sorted(fatti.items())},
        "subiti": {k: {"n": c, "pct": _r2(_pct(c, n))} for k, c in sorted(subiti.items())},
    }


def _prob_pesata(home, away, chiave, sub=None):
    """Probabilità di un mercato-gol combinando i 4 campioni con pesi (casa/trasferta
    pesa più del generale). Ritorna una % coerente e leggibile."""
    def v(blocco):
        if not blocco or blocco.get("n", 0) == 0:
            return None
        x = blocco.get(chiave)
        return (x[sub]["pct"] if sub else x["pct"]) if x else None
    # pesi: split (casa/trasf) 0.40, generale 0.30, recenti5 0.30 — mediati fra le due squadre
    comp = []
    for sq in (home, away):
        parti = [(v(sq["split"]), 0.40), (v(sq["generale"]), 0.30), (v(sq["recenti5"]), 0.30)]
        num = sum(w * val for val, w in parti if val is not None)
        den = sum(w for val, w in parti if val is not None)
        if den:
            comp.append(num / den)
    return _r2(sum(comp) / len(comp)) if comp else None


def probabilita_coerenti(home, away, hcap_home=1.0, hcap_away=1.0):
    """Probabilità COERENTI dei mercati: Over+Under=100, Goal+NoGoal=100, 1+X+2=100.
    hcap_home/away: handicap di livello (una squadra da categoria inferiore parte sotto)."""
    over = _prob_pesata(home, away, "over", 2.5)
    goal = _prob_pesata(home, away, "goal")
    out = {}
    if over is not None:
        out["Over 2.5"] = over
        out["Under 2.5"] = _r2(100 - over)
    # linee aggiuntive 1.5 e 3.5 (stessa logica a frequenze; poi fuse con Poisson)
    for ln in (1.5, 3.5):
        ov = _prob_pesata(home, away, "over", ln)
        if ov is not None:
            out[f"Over {ln}"] = ov
            out[f"Under {ln}"] = _r2(100 - ov)
    if goal is not None:
        out["Goal"] = goal
        out["No Goal"] = _r2(100 - goal)
    p1, px, p2 = _prob_1x2(home, away, hcap_home, hcap_away)
    out["1"], out["X"], out["2"] = p1, px, p2
    out["1X"] = _r2(min(100, p1 + px))
    out["X2"] = _r2(min(100, px + p2))
    out["12"] = _r2(min(100, p1 + p2))
    return out


def _forza(blocco_gen, blocco_split, blocco_rec):
    """Indice di rendimento 0..1 di una squadra (vittorie + mezzo pareggio), pesato."""
    def wr(b):
        if not b or b.get("n", 0) == 0:
            return None
        return (b["v"] + 0.4 * b["d"]) / b["n"]
    parti = [(wr(blocco_split), 0.45), (wr(blocco_gen), 0.30), (wr(blocco_rec), 0.25)]
    num = sum(w * v for v, w in parti if v is not None)
    den = sum(w for v, w in parti if v is not None)
    return (num / den) if den else 0.5


def _prob_1x2(home, away, hcap_home=1.0, hcap_away=1.0):
    """Probabilità 1/X/2 COERENTI (sommano a 100), con la logica richiesta:
    - se la CASA non perde quasi mai in casa -> la X e il 2 si comprimono (1X sicuro)
    - se l'OSPITE perde molto in trasferta -> l'1 sale davvero
    - se l'ospite è forte fuori -> l'1 resta prudente (non gonfiato)
    - handicap di livello: una squadra da categoria inferiore parte svantaggiata."""
    fh = _forza(home["generale"], home["split"], home["recenti5"]) * hcap_home
    fa = _forza(away["generale"], away["split"], away["recenti5"]) * hcap_away
    sh = fh + 0.12          # vantaggio campo
    sa = fa
    # attenuazione base verso la media, per non gonfiare il favorito
    m = (sh + sa) / 2
    sh = m + (sh - m) * 0.65
    sa = m + (sa - m) * 0.65

    hs, aw = home["split"], away["split"]
    # tasso sconfitte casa dell'ospite (in trasferta) e della casa (in casa)
    perde_casa = (hs["sconf"]["pct"] / 100.0) if hs.get("n", 0) >= 4 else 0.5
    perde_osp = (aw["sconf"]["pct"] / 100.0) if aw.get("n", 0) >= 4 else 0.5

    # 1) la casa non perde quasi mai in casa -> comprime il 2 (rete di sicurezza 1X)
    if hs.get("n", 0) >= 4 and perde_casa <= 0.15:
        sa *= 0.75          # l'ospite fatica a vincere qui
    # 2) l'ospite perde molto in trasferta -> spinge l'1
    if aw.get("n", 0) >= 4 and perde_osp >= 0.45:
        sh *= 1.18
    # 3) l'ospite è forte fuori (poche sconfitte) -> l'1 resta prudente
    elif aw.get("n", 0) >= 4 and perde_osp <= 0.25:
        sh *= 0.92

    diff = abs(sh - sa)
    x = max(0.14, 0.34 - 0.9 * diff)
    resto = 1 - x
    tot = sh + sa if (sh + sa) > 0 else 1
    p1 = resto * (sh / tot)
    p2 = resto * (sa / tot)
    s = p1 + x + p2
    return _r2(p1 / s * 100), _r2(x / s * 100), _r2(p2 / s * 100)


def _n_effective(partite):
    """Dimensione EFFETTIVA del campione dopo i pesi (contesto). n_raw resta il numero
    reale di partite; n_effective è la somma dei pesi (amichevoli/categorie inferiori
    contano meno). Usata per penalizzare la qualità statistica in modo onesto."""
    if not partite:
        return 0.0
    return round(sum(p.get("peso", 1.0) for p in partite), 1)


def convergenza_recente(home, away):
    """Convergenza calcolata SOLO sulle ultime 5 di ciascuna squadra: serve a rilevare
    se il recente diverge dallo storico (allerta di instabilità, non verità assoluta)."""
    def blocco_rec(sq):
        return {"generale": sq["recenti5"], "split": sq["recenti5"]}
    return convergenze(blocco_rec(home), blocco_rec(away))


def costruisci_evidenze(partite_home, partite_away, odds=None, variazioni=None,
                        hcap_home=1.0, hcap_away=1.0, w_freq=None, w_pois=None, home_adv=None):
    """Punto d'ingresso: costruisce l'intero quadro di evidenze per la partita.
    Separazione netta: 'prob' = modello (FUSO frequenze+Poisson), 'quote' = mercato
    (raw+novig), 'value' = convenienza economica (edge/EV). La probabilità NON è mai
    toccata dal mercato."""
    home = analizza_squadra(partite_home, "casa")
    away = analizza_squadra(partite_away, "trasf")
    home["dist_fs"] = _dist_fatti_subiti(partite_home)
    away["dist_fs"] = _dist_fatti_subiti(partite_away)

    # 1) probabilità a FREQUENZE (motore ragionato)
    prob_freq = probabilita_coerenti(home, away, hcap_home, hcap_away)
    # 2) FUSIONE con Poisson/Elo (motore statistico). Se fallisce, resta la frequenza.
    fus_det = None
    prob = prob_freq
    try:
        import fusione
        kw = {}
        if w_freq is not None:
            kw["w_freq"] = w_freq
        if w_pois is not None:
            kw["w_pois"] = w_pois
        if home_adv is not None:
            kw["home_adv"] = home_adv
        prob_fusa, fus_det = fusione.fondi(prob_freq, home, away, hcap_home, hcap_away, **kw)
        if prob_fusa:
            prob = prob_fusa
    except Exception:
        fus_det = None

    # CALIBRAZIONE: corregge la sovrastima dei mercati gol (Over/Under, Goal/NoGoal),
    # misurata dal backtest. L'1X2 resta invariato (già ben calibrato). Teniamo anche
    # la versione grezza (prob_grezza) per trasparenza e confronto.
    prob_grezza = dict(prob)
    try:
        import calibrazione
        prob = calibrazione.calibra_prob(prob)
    except Exception:
        pass

    quote = analizza_quote(odds, variazioni)
    return {
        "home": home,
        "away": away,
        "convergenze": convergenze(home, away),          # convergenza STORICA
        "convergenze_recenti": convergenza_recente(home, away),
        "contraddizioni": contraddizioni(home, "Casa") + contraddizioni(away, "Trasferta"),
        "quote": quote,
        "prob": prob,                                    # probabilità del MODELLO (fusa+calibrata)
        "prob_grezza": prob_grezza,                      # fusa PRIMA della calibrazione
        "prob_freq": prob_freq,                          # sotto-stima: frequenze
        "prob_poisson": (fus_det or {}).get("prob_poisson"),   # sotto-stima: Poisson
        "fusione": fus_det,                              # λ, risultati Poisson, pesi
        "value": calcola_value(prob, quote),             # convenienza vs mercato (separata)
        "hcap_home": hcap_home, "hcap_away": hcap_away,
        "n_home": home["generale"].get("n", 0),
        "n_away": away["generale"].get("n", 0),
        "n_eff_home": _n_effective(partite_home),
        "n_eff_away": _n_effective(partite_away),
        "partite_home": partite_home,   # liste grezze (per finestre e incroci nel racconto)
        "partite_away": partite_away,
    }
