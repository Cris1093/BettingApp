# -*- coding: utf-8 -*-
"""
Motore di analisi e pronostico (v2) - multi-fattore.

Idea: dati grezzi -> feature normalizzate (con recency + finestre + split casa/trasferta
+ qualita' avversario via Elo) -> Expected Goals (Poisson) -> uno score engine per ogni
mercato con "conflitto dei segnali" -> quote come consenso (non decidono) -> pronostico
con confidence e motivi/rischi.

Funzioni pure (niente Streamlit). Input: DataFrame 'partite' con almeno
  data, squadra_casa, squadra_trasferta, gol_casa, gol_trasferta
(gol None = non giocata). Opzionale: val_casa / val_trasferta (valore rose).
"""

from math import exp, factorial
from datetime import date, datetime, timedelta
import copy

# --------------------------------------------------------------------- CONFIG
# Pesi di default: TUTTI modificabili passando un dict 'config' ad analizza_partita.
PESI_DEFAULT = {
    "finestre": {5: 0.45, 10: 0.35, 15: 0.20},   # peso delle ultime 5/10/15
    "recency_decay": 45,                           # giorni: peso = exp(-giorni/decay)
    "elo_k": 20, "elo_hfa": 60, "elo_base": 1500,
    # divario di forza tra divisioni: Elo iniziale piu' basso per le leghe minori
    "elo_tier_offset": 150,
    "home_adv_goals": 1.08,                        # vantaggio campo sugli xG
    # peso per tipo di competizione (una partita ufficiale conta piu' di un'amichevole)
    "pesi_competizione": {
        "Campionato": 1.00, "Playoff": 1.00,
        "Coppa nazionale": 0.85, "Coppa internazionale": 0.85,
        "Coppa/torneo secondario": 0.75, "Altro": 0.70, "Amichevole": 0.35,
    },
    "peso_competizione_default": 1.00,   # ND / non categorizzata
    # score Over 2.5
    "over": {"recent": 0.20, "home_away": 0.25, "scoring": 0.15,
             "conceding": 0.15, "h2h": 0.10, "poisson": 0.15},
    # score Goal (BTTS)
    "btts": {"team_a": 0.18, "team_b": 0.18, "home_away": 0.20,
             "scoring": 0.14, "conceding": 0.12, "poisson": 0.10, "prodotto": 0.08},
    # confidence = mix di probabilita' e accordo dei segnali
    "conf_prob": 0.70, "conf_segnali": 0.30,
    "usa_consenso_quote": True,   # confronto col mercato (solo consenso, non value bet)
    # 1X2: fusione di piu' segnali sul lato vincente (la X resta ancorata a Poisson)
    "tilt_1x2": {"poisson": 0.40, "elo": 0.35, "forma": 0.15, "rose": 0.10},
    # con il valore rose presente: pesa molto di più (misura diretta della forza)
    "tilt_1x2_rose": {"poisson": 0.32, "elo": 0.20, "forma": 0.15, "rose": 0.33},
    # quanta parte della penalità di livello viene tolta quando ci sono le rose (0..1)
    "rose_mitiga_tier": 0.6,
    # penalizzazione esplicita quando i segnali si contraddicono (oltre il 50%)
    "conflitto_btts": 0.30, "conflitto_over": 0.20,
    # peso extra alle partite dello stesso tipo del match da pronosticare
    "boost_stessa_competizione": 1.20,
    # Dixon-Coles: correzione dei risultati bassi (rho tipicamente negativo)
    "dixon_coles_rho": -0.10,
    # shrinkage verso la media lega per campioni piccoli (pseudo-partite)
    "shrink_k": 5,
    # confidence: partite necessarie per la fiducia "piena" sul campione
    "conf_min_campione": 8,
    # confronto con le quote: NON media la probabilità (niente blending di default).
    # Le quote servono a segnalare discrepanze e a modulare la confidence.
    "blending_mercato": False, "peso_mercato": 0.0,
    # soglie dell'alert di discrepanza (differenza |stat - quota grezza|)
    "alert_soglie": {"basso": 0.06, "medio": 0.13, "alto": 0.22},
    # confidence dalla quota: premia l'accordo, penalizza le divergenze forti
    # (un mercato MOLTO più convinto delle statistiche è un allarme, non una conferma)
    "conf_quota_conferma": 0.35, "conf_quota_svaluta": 0.45, "conf_quota_discrepanza": 0.90,
    "conf_da_quota_max": 15.0,
    # confidence dalla variazione di quota (ribasso forte = soldi su quel segno)
    "conf_da_variazione": 12.0,
    # risultato esatto: adatta la griglia ai mercati (1X2/Over/Goal) senza toccarli
    "griglia_coerente": True,
    # riposo/calendario
    "rest_min_giorni": 3, "rest_max_giorni": 25, "rest_penalita": 0.05,
}


def _cfg(config):
    c = copy.deepcopy(PESI_DEFAULT)
    if config:
        for k, v in config.items():
            if isinstance(v, dict) and isinstance(c.get(k), dict):
                c[k].update(v)
            else:
                c[k] = v
    return c


# --------------------------------------------------------------------- utilita'
def _ok(v):
    return v is not None and v == v


def _to_date(x):
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return datetime.fromisoformat(str(x)).date()
    except Exception:
        return None


def _played(df):
    if df is None or len(df) == 0 or "gol_casa" not in getattr(df, "columns", []):
        return df.iloc[0:0] if hasattr(df, "iloc") else df
    return df[df["gol_casa"].apply(_ok) & df["gol_trasferta"].apply(_ok)]


def _key(s):
    import re as _re
    return _re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def peso_competizione(tipo, pesi, default):
    """Peso della competizione dato il tipo_partita (categoria)."""
    if not tipo or tipo in ("ND", "Non assegnata"):
        return default
    return pesi.get(tipo, default)


# --------------------------------------------------------------------- Elo
def calcola_elo(df, k=20, hfa=60, base=1500, team_tier=None, tier_offset=150):
    """Rating Elo finale per ogni squadra (aggiornato partita dopo partita)."""
    finale, _ = calcola_elo_timeline(df, k, hfa, base, team_tier, tier_offset)
    return finale


def _tier_di_squadra(df, livelli):
    """Deduce il livello di lega di ogni squadra dalla competizione più recente con
    livello noto (gestisce le neopromosse: la lega più recente vince)."""
    tier = {}
    if not livelli or "competizione" not in getattr(df, "columns", []):
        return tier
    d = _played(df)
    if "data" in d.columns:
        d = d.sort_values("data", ascending=False)
    for _, m in d.iterrows():
        liv = livelli.get(_key(m.get("competizione")))
        if liv is None:
            continue
        for t in (m["squadra_casa"], m["squadra_trasferta"]):
            if t not in tier:
                tier[t] = liv
    return tier


def calcola_elo_timeline(df, k=20, hfa=60, base=1500, team_tier=None, tier_offset=150):
    """Ritorna (finale, pre). L'Elo iniziale di ogni squadra tiene conto del livello di
    lega: una squadra di 2ª divisione parte più in basso di una di 1ª."""
    team_tier = team_tier or {}

    def rating_iniziale(t):
        liv = team_tier.get(t)
        return base - tier_offset * (liv - 1) if (liv and liv >= 1) else base

    d = _played(df).copy()
    if "data" in d.columns:
        d = d.sort_values("data")
    r = {}
    pre = {}
    for _, m in d.iterrows():
        h, a = m["squadra_casa"], m["squadra_trasferta"]
        gc, gt = int(m["gol_casa"]), int(m["gol_trasferta"])
        rh, ra = r.get(h, rating_iniziale(h)), r.get(a, rating_iniziale(a))
        key = (str(m["data"]) if "data" in m else None, h, a)
        pre[key] = {"home": rh, "away": ra}
        eh = 1 / (1 + 10 ** (-((rh + hfa) - ra) / 400))
        sh = 1.0 if gc > gt else (0.5 if gc == gt else 0.0)
        r[h] = rh + k * (sh - eh)
        r[a] = ra + k * ((1 - sh) - (1 - eh))
    return r, pre


# --------------------------------------------------------------------- record partite
def _records(nome, df, elo, mean_elo, oggi, decay, venue=None, pesi_comp=None,
             peso_def=1.0, elo_pre=None, tipo_target=None, boost=1.0):
    """Lista di record recenti (piu' recente prima) con metriche e peso combinato
    (recency x competizione x boost-stessa-competizione). L'Elo dell'avversario è
    quello PRE-partita quando disponibile."""
    if df is None or len(df) == 0 or "squadra_casa" not in getattr(df, "columns", []):
        return []
    d = df[((df["squadra_casa"] == nome) | (df["squadra_trasferta"] == nome))].copy()
    d = _played(d)
    if d.empty:
        return []
    if venue == "casa":
        d = d[d["squadra_casa"] == nome]
    elif venue == "trasf":
        d = d[d["squadra_trasferta"] == nome]
    # le amichevoli si giocano spesso in campo neutro: non alimentano gli split casa/trasferta
    if venue in ("casa", "trasf") and "tipo_partita" in d.columns:
        d = d[d["tipo_partita"] != "Amichevole"]
    if d.empty:
        return []
    if "data" in d.columns:
        d = d.sort_values("data", ascending=False)
    pesi_comp = pesi_comp or {}
    elo_pre = elo_pre or {}
    recs = []
    for _, m in d.iterrows():
        casa = m["squadra_casa"] == nome
        gf = int(m["gol_casa"]) if casa else int(m["gol_trasferta"])
        ga = int(m["gol_trasferta"]) if casa else int(m["gol_casa"])
        opp = m["squadra_trasferta"] if casa else m["squadra_casa"]
        md = _to_date(m["data"]) if "data" in m else None
        giorni = (oggi - md).days if (md and oggi) else 30
        tipo = m.get("tipo_partita") if hasattr(m, "get") else None
        cw = peso_competizione(tipo, pesi_comp, peso_def)
        # Elo avversario PRE-partita
        key = (str(m["data"]) if "data" in m else None, m["squadra_casa"], m["squadra_trasferta"])
        pr = elo_pre.get(key)
        if pr:
            opp_elo = pr["away"] if casa else pr["home"]
        else:
            opp_elo = elo.get(opp, mean_elo)
        # boost se la partita è dello stesso tipo del match da pronosticare
        b = boost if (tipo_target and tipo and tipo == tipo_target and tipo not in ("ND", "Non assegnata")) else 1.0
        recs.append({
            "gf": gf, "ga": ga, "opp_elo": opp_elo or mean_elo,
            "over25": 1 if gf + ga >= 3 else 0, "over15": 1 if gf + ga >= 2 else 0,
            "over35": 1 if gf + ga >= 4 else 0,
            "btts": 1 if gf > 0 and ga > 0 else 0,
            "cs": 1 if ga == 0 else 0, "fts": 1 if gf == 0 else 0,
            "segna": 1 if gf > 0 else 0, "subisce": 1 if ga > 0 else 0,
            "pts": 3 if gf > a_(gf, ga) else (1 if gf == ga else 0),
            "tipo": tipo or "ND", "giorni": max(giorni, 0),
            "peso": exp(-max(giorni, 0) / decay) * cw * b,
        })
    return recs


def a_(gf, ga):   # helper leggibile per confronto
    return ga


def _blend_finestre(recs, key, finestre):
    """Media (recency-weighted) di 'key' sulle ultime 5/10/15, combinata coi pesi finestre."""
    val, wsum = 0.0, 0.0
    for W, peso in finestre.items():
        sub = recs[:W]
        num = sum(r["peso"] * r[key] for r in sub)
        den = sum(r["peso"] for r in sub)
        if den > 0:
            val += peso * (num / den)
            wsum += peso
    return val / wsum if wsum else 0.0


def _rate(recs, key):
    """Tasso semplice (non pesato) su tutte le partite disponibili, per i conteggi mostrati."""
    if not recs:
        return 0.0
    return sum(r[key] for r in recs) / len(recs)


# --------------------------------------------------------------------- Expected Goals
def _clip(x, lo=0.2, hi=4.5):
    return max(lo, min(hi, x))


def _attacco_difesa(recs, mean_elo, finestre):
    """Forza d'attacco/difesa aggiustata per qualita' avversario (Elo)."""
    def adj_gf(r):
        return r["gf"] * (r["opp_elo"] / mean_elo)

    def adj_ga(r):
        return r["ga"] * (mean_elo / r["opp_elo"]) if r["opp_elo"] else r["ga"]

    # riuso _blend_finestre passando chiavi calcolate al volo
    for r in recs:
        r["_agf"] = r["gf"] * (r["opp_elo"] / mean_elo)
        r["_aga"] = r["ga"] * (mean_elo / r["opp_elo"]) if r["opp_elo"] else r["ga"]
    return _blend_finestre(recs, "_agf", finestre), _blend_finestre(recs, "_aga", finestre)


def _pmf(kk, lam):
    return lam ** kk * exp(-lam) / factorial(kk)


def _baseline_lega(df):
    """Medie di lega dal database, per il modello moltiplicativo e lo shrinkage."""
    d = _played(df)
    if d.empty:
        return {"gf": 1.2, "over25": 0.5, "over15": 0.75, "over35": 0.25,
                "btts": 0.5, "segna": 0.65, "subisce": 0.65}
    gc = d["gol_casa"].astype(int)
    gt = d["gol_trasferta"].astype(int)
    n = len(d)
    tot = gc + gt
    return {
        "gf": float(tot.sum()) / (2 * n),
        "over25": float((tot >= 3).mean()), "over15": float((tot >= 2).mean()),
        "over35": float((tot >= 4).mean()),
        "btts": float(((gc > 0) & (gt > 0)).mean()),
        "segna": float(((gc > 0).sum() + (gt > 0).sum()) / (2 * n)),
        "subisce": float(((gt > 0).sum() + (gc > 0).sum()) / (2 * n)),
    }


def _shrink(rate, n, prior, k):
    """Regressione verso il prior di lega: piu' il campione e' piccolo, piu' pesa il prior."""
    return (n * rate + k * prior) / (n + k) if (n + k) > 0 else prior


def _tau_dc(i, j, lh, la, rho):
    """Correzione Dixon-Coles sui risultati bassi (0-0, 1-0, 0-1, 1-1)."""
    if i == 0 and j == 0:
        return 1 - lh * la * rho
    if i == 0 and j == 1:
        return 1 + lh * rho
    if i == 1 and j == 0:
        return 1 + la * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def probabilita(lh, la, rho=-0.10, maxg=8):
    ph = pd = pa = po = pb = 0.0
    po15 = po35 = 0.0
    griglia = []
    tot = 0.0
    for i in range(maxg + 1):
        for j in range(maxg + 1):
            p = _pmf(i, lh) * _pmf(j, la) * max(0.0, _tau_dc(i, j, lh, la, rho))
            tot += p
            griglia.append((p, i, j))
    if tot <= 0:
        tot = 1.0
    ph = pd = pa = po = pb = po15 = po35 = 0.0
    grid2 = []
    for p, i, j in griglia:
        p = p / tot   # rinormalizza dopo la correzione
        grid2.append((p, i, j))
        if i > j:
            ph += p
        elif i == j:
            pd += p
        else:
            pa += p
        if i + j >= 2:
            po15 += p
        if i + j >= 3:
            po += p
        if i + j >= 4:
            po35 += p
        if i >= 1 and j >= 1:
            pb += p
    grid2.sort(reverse=True)
    top = [{"risultato": f"{i}-{j}", "p": p} for p, i, j in grid2[:6]]
    return {"1": ph, "X": pd, "2": pa, "over25": po, "under25": 1 - po,
            "over15": po15, "under15": 1 - po15, "over35": po35, "under35": 1 - po35,
            "goal": pb, "nogoal": 1 - pb, "lambda_home": lh, "lambda_away": la,
            "risultati": top}


def griglia_ipf(lh, la, rho, over_p, btts_p, p1, px, p2, maxg=8, iters=25):
    """Griglia dei risultati esatti (Poisson+Dixon-Coles) 'piegata' finché non rispetta
    i totali dei mercati (1X2, Over 2.5, Goal) SENZA toccarli. Iterative Proportional
    Fitting. Ritorna lista ordinata [(i, j, prob), ...]."""
    cells = {}
    for i in range(maxg + 1):
        for j in range(maxg + 1):
            cells[(i, j)] = _pmf(i, lh) * _pmf(j, la) * max(0.0, _tau_dc(i, j, lh, la, rho))
    s = sum(cells.values()) or 1.0
    for k in cells:
        cells[k] /= s

    def scala(pred, t_true):
        s_true = sum(cells[k] for k in cells if pred(*k))
        s_false = 1 - s_true
        ft = (t_true / s_true) if s_true > 1e-9 else 1.0
        ff = ((1 - t_true) / s_false) if s_false > 1e-9 else 1.0
        for k in cells:
            cells[k] *= ft if pred(*k) else ff

    for _ in range(iters):
        scala(lambda i, j: i + j >= 3, over_p)             # Over/Under 2.5
        scala(lambda i, j: i >= 1 and j >= 1, btts_p)      # Goal/NoGoal
        sh = sum(cells[k] for k in cells if k[0] > k[1]) or 1e-9
        sd = sum(cells[k] for k in cells if k[0] == k[1]) or 1e-9
        sa = sum(cells[k] for k in cells if k[0] < k[1]) or 1e-9
        for k in cells:
            if k[0] > k[1]:
                cells[k] *= p1 / sh
            elif k[0] == k[1]:
                cells[k] *= px / sd
            else:
                cells[k] *= p2 / sa
        tot = sum(cells.values()) or 1.0
        for k in cells:
            cells[k] /= tot
    return sorted(((i, j, p) for (i, j), p in cells.items()), key=lambda t: -t[2])


# --------------------------------------------------------------------- Poisson totale (per derivare le linee gol)
def _pois_tot_over(lam, soglia_gol):
    """P(gol totali >= soglia_gol) con totale ~ Poisson(lam)."""
    cum = 0.0
    for k in range(soglia_gol):
        cum += _pmf(k, lam)
    return 1 - cum


def _inverti_lambda(p_over25, lo=0.05, hi=7.0):
    """Trova il lambda dei gol totali tale che P(tot>=3)=p_over25 (ricerca binaria)."""
    if p_over25 <= 0:
        return lo
    if p_over25 >= 1:
        return hi
    for _ in range(40):
        mid = (lo + hi) / 2
        if _pois_tot_over(mid, 3) < p_over25:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def quote_derivate(odds):
    """Ricava le quote non fornite:
       - doppia chance (1X, 12, X2) esatta da 1/X/2
       - Over/Under 1.5 e 3.5 stimate dalla linea O/U 2.5 (via lambda gol totali).
    Ritorna (prob_mercato, quote) dove prob_mercato sono probabilita' e quote sono
    quote decimali stimate."""
    prob, quote = {}, {}
    o1, ox, o2 = odds.get("1"), odds.get("X"), odds.get("2")
    if _ok(o1) and _ok(ox) and _ok(o2) and min(o1, ox, o2) > 0:
        q1x = 1 / (1 / o1 + 1 / ox)
        q12 = 1 / (1 / o1 + 1 / o2)
        qx2 = 1 / (1 / ox + 1 / o2)
        quote["1X"], quote["12"], quote["X2"] = round(q1x, 2), round(q12, 2), round(qx2, 2)
        # prob normalizzate (tolto il margine) coerenti col mercato 1X2
        s = 1 / o1 + 1 / ox + 1 / o2
        p1, px, p2 = (1 / o1) / s, (1 / ox) / s, (1 / o2) / s
        prob["1X"], prob["12"], prob["X2"] = p1 + px, p1 + p2, px + p2

    oo, ou = odds.get("over25"), odds.get("under25")
    if _ok(oo) and _ok(ou) and min(oo, ou) > 0:
        p_over25 = (1 / oo) / (1 / oo + 1 / ou)   # normalizzata
        lam = _inverti_lambda(p_over25)
        p15 = _pois_tot_over(lam, 2)
        p35 = _pois_tot_over(lam, 4)
        prob["over15"], prob["under15"] = p15, 1 - p15
        prob["over35"], prob["under35"] = p35, 1 - p35
        for k, pk in [("over15", p15), ("under15", 1 - p15),
                      ("over35", p35), ("under35", 1 - p35)]:
            quote[k] = round(1 / pk, 2) if pk > 0 else None
    return prob, quote


# --------------------------------------------------------------------- quote -> prob
def prob_implicite(odds):
    """Probabilita' implicite normalizzate (tolto il margine) per ogni mercato."""
    out = {}

    def norm(keys):
        vals = {k: 1 / float(odds[k]) for k in keys if _ok(odds.get(k)) and float(odds[k]) > 0}
        s = sum(vals.values())
        if s > 0:
            for k in vals:
                out[k] = vals[k] / s

    norm(["1", "X", "2"])
    norm(["over25", "under25"])
    norm(["goal", "nogoal"])
    return out


def implicite_grezze(odds):
    """Probabilita' implicite GREZZE (1/quota, senza togliere il margine).
    È il confronto 'in purezza' con le quote richiesto per rilevare le discrepanze."""
    out = {}
    for k, q in (odds or {}).items():
        if _ok(q) and float(q) > 0:
            out[k] = 1 / float(q)
    return out


def livello_alert(p_stat, p_odds, soglie):
    """Alert di discrepanza statistiche vs quota grezza: None/basso/medio/alto."""
    if p_odds is None:
        return None
    d = abs(p_stat - p_odds)
    if d < soglie["basso"]:
        liv = None
    elif d < soglie["medio"]:
        liv = "basso"
    elif d < soglie["alto"]:
        liv = "medio"
    else:
        liv = "alto"
    # se cambia il favorito (una sopra e una sotto il 50%) l'attenzione sale
    if (p_stat - 0.5) * (p_odds - 0.5) < 0:
        liv = {"None": "basso", None: "basso", "basso": "medio",
               "medio": "alto", "alto": "alto"}[liv]
    return liv


# --------------------------------------------------------------------- score engine
def _pct(x):
    return f"{x*100:.0f}%"


def _frazione(recs, key):
    return sum(r[key] for r in recs), len(recs)


def analizza_partita(home, away, df, odds=None, data_partita=None, config=None,
                     calibratori=None, rose=None, tipo_partita_target=None, livelli=None,
                     variazioni=None):
    c = _cfg(config)
    odds = odds or {}
    fin = c["finestre"]
    decay = c["recency_decay"]

    team_tier = _tier_di_squadra(df, livelli)
    elo, elo_pre = calcola_elo_timeline(df, c["elo_k"], c["elo_hfa"], c["elo_base"],
                                        team_tier, c["elo_tier_offset"])
    mean_elo = (sum(elo.values()) / len(elo)) if elo else c["elo_base"]

    if data_partita:
        oggi = _to_date(data_partita)
    elif "data" in df.columns and not _played(df).empty:
        oggi = max(_to_date(x) for x in _played(df)["data"]) + timedelta(days=3)
    else:
        oggi = date.today()

    pcomp = c["pesi_competizione"]
    pdef = c["peso_competizione_default"]
    boost = c["boost_stessa_competizione"]
    tt = tipo_partita_target

    def rec(nome, venue=None):
        return _records(nome, df, elo, mean_elo, oggi, decay, venue, pcomp, pdef,
                        elo_pre=elo_pre, tipo_target=tt, boost=boost)
    rh = rec(home)
    ra = rec(away)
    rh_c = rec(home, "casa")
    ra_t = rec(away, "trasf")

    if not rh or not ra:
        return {"errore": "storico insufficiente", "home": home, "away": away,
                "n_home": len(rh), "n_away": len(ra)}

    lega = _baseline_lega(df)
    Lg = max(0.3, lega["gf"])
    K = c["shrink_k"]

    # ---- Expected Goals: modello moltiplicativo con baseline di lega + shrinkage ----
    h_att_all, h_dif_all = _attacco_difesa(rh, mean_elo, fin)
    a_att_all, a_dif_all = _attacco_difesa(ra, mean_elo, fin)
    h_att_c, h_dif_c = _attacco_difesa(rh_c, mean_elo, fin) if rh_c else (h_att_all, h_dif_all)
    a_att_t, a_dif_t = _attacco_difesa(ra_t, mean_elo, fin) if ra_t else (a_att_all, a_dif_all)

    def wv(v_c, v_all, n):
        return (0.6 * v_c + 0.4 * v_all) if n >= 4 else (0.4 * v_c + 0.6 * v_all if n >= 1 else v_all)

    home_att = wv(h_att_c, h_att_all, len(rh_c))
    home_dif = wv(h_dif_c, h_dif_all, len(rh_c))
    away_att = wv(a_att_t, a_att_all, len(ra_t))
    away_dif = wv(a_dif_t, a_dif_all, len(ra_t))

    # forze relative alla media lega, con shrinkage verso 1.0 (prior neutro)
    def forza(x, n):
        return _shrink(x / Lg, n, 1.0, K)
    att_h = forza(home_att, len(rh)); dif_h = forza(home_dif, len(rh))
    att_a = forza(away_att, len(ra)); dif_a = forza(away_dif, len(ra))

    # fattore campo: neutro per le amichevoli (spesso campo neutro)
    hf = 1.0 if (tt == "Amichevole") else c["home_adv_goals"] ** 0.5
    lh = _clip(Lg * att_h * dif_a * hf)
    la = _clip(Lg * att_a * dif_h / hf)

    # ---- riposo/calendario ----
    def _giorni_riposo(recs):
        return recs[0]["giorni"] if recs and "giorni" in recs[0] else None
    rest_h, rest_a = _giorni_riposo(rh), _giorni_riposo(ra)
    note_rest = []
    for nome_s, rst, lam_ref in [(home, rest_h, "lh"), (away, rest_a, "la")]:
        if rst is None:
            continue
        if rst <= c["rest_min_giorni"]:
            note_rest.append(f"{nome_s}: poco riposo ({rst}g)")
            if lam_ref == "lh":
                lh *= (1 - c["rest_penalita"])
            else:
                la *= (1 - c["rest_penalita"])
        elif rst >= c["rest_max_giorni"]:
            note_rest.append(f"{nome_s}: lunga sosta ({rst}g)")

    prob = probabilita(lh, la, c["dixon_coles_rho"])

    # ---- 1X2 multi-segnale: la X resta da Poisson (Dixon-Coles), il lato vincente
    #      fonde Poisson + Elo + forma casa/trasferta + valore rose ----
    ha_rose = bool(rose and _ok(rose[0]) and _ok(rose[1]) and (float(rose[0]) + float(rose[1])) > 0)
    Rh, Ra = elo.get(home, mean_elo), elo.get(away, mean_elo)
    # se ho il valore rose, la forza reale è nelle rose: restituisco parte della
    # penalità di livello alle due squadre (una 3ª di un campionato top può valere
    # più di una 1ª di un campionato minore -> il livello non deve pesare troppo)
    if ha_rose:
        mit = c["rose_mitiga_tier"]
        for t, side in ((home, "h"), (away, "a")):
            liv = team_tier.get(t)
            if liv and liv > 1:
                add = c["elo_tier_offset"] * (liv - 1) * mit
                if side == "h":
                    Rh += add
                else:
                    Ra += add
    e_home = 1 / (1 + 10 ** (-((Rh + c["elo_hfa"]) - Ra) / 400))
    tw_pois = prob["1"] / (prob["1"] + prob["2"]) if (prob["1"] + prob["2"]) > 0 else 0.5
    tw_elo = e_home
    hppg, appg = _rate(rh_c, "pts"), _rate(ra_t, "pts")
    tw_form = hppg / (hppg + appg) if (hppg + appg) > 0 else 0.5
    # pesi del tilt: con le rose presenti, le rose contano molto di più (misura diretta)
    tw = c["tilt_1x2_rose"] if ha_rose else c["tilt_1x2"]
    comp = [("poisson", tw_pois, tw["poisson"]), ("elo", tw_elo, tw["elo"]),
            ("forma", tw_form, tw["forma"])]
    if ha_rose:
        tw_rose = float(rose[0]) / (float(rose[0]) + float(rose[1]))
        comp.append(("rose", tw_rose, tw["rose"]))
    wsum = sum(pw for _, _, pw in comp)
    tilt = sum(val * pw for _, val, pw in comp) / wsum if wsum else 0.5
    resto = 1 - prob["X"]
    prob["1"] = resto * tilt
    prob["2"] = resto * (1 - tilt)

    # ---- metriche per gli score (recency+finestre, con shrinkage verso la lega) ----
    def M(recs, venue_recs):
        n = len(recs)
        nv = len(venue_recs) if venue_recs else n

        def sh(key, prior, recs_, nn):
            return _shrink(_blend_finestre(recs_, key, fin), nn, prior, K)
        return {
            "over25": sh("over25", lega["over25"], recs, n),
            "over15": sh("over15", lega["over15"], recs, n),
            "over35": sh("over35", lega["over35"], recs, n),
            "btts": sh("btts", lega["btts"], recs, n),
            "segna": sh("segna", lega["segna"], recs, n),
            "subisce": sh("subisce", lega["subisce"], recs, n),
            "cs": sh("cs", 1 - lega["subisce"], recs, n),
            "fts": sh("fts", 1 - lega["segna"], recs, n),
            "ha_over25": sh("over25", lega["over25"], venue_recs or recs, nv),
            "ha_btts": sh("btts", lega["btts"], venue_recs or recs, nv),
        }
    mh = M(rh, rh_c)
    ma = M(ra, ra_t)
    hh = h2h(home, away, df)

    # ---- OVER 2.5 ----
    w = c["over"]
    over_p = (
        w["recent"] * ((mh["over25"] + ma["over25"]) / 2) +
        w["home_away"] * ((mh["ha_over25"] + ma["ha_over25"]) / 2) +
        w["scoring"] * ((mh["segna"] + ma["segna"]) / 2) +
        w["conceding"] * ((mh["subisce"] + ma["subisce"]) / 2) +
        w["h2h"] * (hh["over"] / hh["n"] if hh["n"] else prob["over25"]) +
        w["poisson"] * prob["over25"]
    )
    over_p = min(1.0, max(0.0, over_p))
    # conflitto Over: se entrambe difendono molto o segnano poco, oltre il 50%, penalizza
    over_conflict = max((mh["cs"] + ma["cs"]) / 2, 1 - (mh["segna"] + ma["segna"]) / 2)
    over_p *= (1 - c["conflitto_over"] * max(0.0, over_conflict - 0.5) * 2)

    # ---- GOAL (BTTS) con conflitto dei segnali ----
    w = c["btts"]
    p_prodotto = mh["segna"] * ma["segna"]  # entrambe segnano (stima indipendente)
    btts_p = (
        w["team_a"] * mh["btts"] + w["team_b"] * ma["btts"] +
        w["home_away"] * ((mh["ha_btts"] + ma["ha_btts"]) / 2) +
        w["scoring"] * ((mh["segna"] + ma["segna"]) / 2) +
        w["conceding"] * ((mh["subisce"] + ma["subisce"]) / 2) +
        w["poisson"] * prob["goal"] +
        w["prodotto"] * p_prodotto
    )
    btts_p = min(1.0, max(0.0, btts_p))
    # conflitto BTTS: una difesa che tiene molti clean sheet o un attacco che spesso
    # non segna sono segnali forti CONTRO il Goal -> penalizza oltre il 50%
    btts_conflict = max(mh["cs"], ma["cs"], mh["fts"], ma["fts"])
    btts_p *= (1 - c["conflitto_btts"] * max(0.0, btts_conflict - 0.5) * 2)
    btts_p = min(1.0, max(0.0, btts_p))

    # ---- calibrazione (se disponibile) ----
    over_p_raw, btts_p_raw = over_p, btts_p
    if calibratori:
        if calibratori.get("over25"):
            over_p = applica_iso(over_p, calibratori["over25"])
        if calibratori.get("goal"):
            btts_p = applica_iso(btts_p, calibratori["goal"])

    # ---- Over/Under 1.5 e 3.5 (modello: Poisson + tassi empirici) ----
    over15_p = min(1.0, max(0.0, 0.5 * prob["over15"] + 0.25 * mh["over15"] + 0.25 * ma["over15"]))
    over35_p = min(1.0, max(0.0, 0.5 * prob["over35"] + 0.25 * mh["over35"] + 0.25 * ma["over35"]))

    # ---- mercato: quote derivate (DC, O/U 1.5/3.5) + IMPLICITE GREZZE (1/quota) ----
    quote_der = {}
    if c["usa_consenso_quote"]:
        _, quote_der = quote_derivate(odds)
    odds_est = dict(odds)
    odds_est.update(quote_der)   # quote fornite + quote derivate
    # confronto in purezza: probabilità implicite grezze (senza togliere il margine)
    mkt = implicite_grezze(odds_est)

    # ---- blending (DISATTIVATO di default): le quote NON mediano la probabilità ----
    alpha = c["peso_mercato"] if (c["usa_consenso_quote"] and c["blending_mercato"]) else 0.0
    blended = False
    if alpha > 0 and mkt:
        mktn = prob_implicite(odds)   # se riattivato, il blending usa le normalizzate
        if "over25" in mktn:
            over_p = (1 - alpha) * over_p + alpha * mktn["over25"]; blended = True
        if "goal" in mktn:
            btts_p = (1 - alpha) * btts_p + alpha * mktn["goal"]; blended = True
        if all(k in mktn for k in ("1", "X", "2")):
            b1 = (1 - alpha) * prob["1"] + alpha * mktn["1"]
            bx = (1 - alpha) * prob["X"] + alpha * mktn["X"]
            b2 = (1 - alpha) * prob["2"] + alpha * mktn["2"]
            s = b1 + bx + b2
            if s > 0:
                prob["1"], prob["X"], prob["2"] = b1 / s, bx / s, b2 / s
            blended = True

    # ---- coerenza delle linee gol: Over1.5 >= Over2.5 >= Over3.5 ----
    over15_p = max(over15_p, over_p)
    over35_p = min(over35_p, over_p)

    # ---- costruzione candidati con segnali ----
    def seg_over():
        s, o = [], []
        for nome_s, val, lab in [
            (home, mh["over25"], "Over"), (away, ma["over25"], "Over")]:
            (s if val >= 0.55 else o if val <= 0.45 else s).append(
                f"{nome_s}: Over {_pct(val)}")
        (s if (mh["ha_over25"] + ma["ha_over25"]) / 2 >= 0.5 else o).append(
            f"campo: Over {_pct((mh['ha_over25']+ma['ha_over25'])/2)}")
        if hh["n"]:
            (s if hh["over"] / hh["n"] >= 0.5 else o).append(f"H2H Over {hh['over']}/{hh['n']}")
        return s, o

    def seg_btts():
        s, o = [], []
        (s if mh["btts"] >= 0.5 else o).append(f"{home}: Goal {_pct(mh['btts'])}")
        (s if ma["btts"] >= 0.5 else o).append(f"{away}: Goal {_pct(ma['btts'])}")
        if mh["fts"] >= 0.35:
            o.append(f"{home} non segna nel {_pct(mh['fts'])}")
        if ma["fts"] >= 0.35:
            o.append(f"{away} non segna nel {_pct(ma['fts'])}")
        if mh["cs"] >= 0.35:
            o.append(f"{home} clean sheet {_pct(mh['cs'])}")
        if ma["cs"] >= 0.35:
            o.append(f"{away} clean sheet {_pct(ma['cs'])}")
        if hh["n"]:
            (s if hh["goal"] / hh["n"] >= 0.5 else o).append(f"H2H Goal {hh['goal']}/{hh['n']}")
        return s, o

    def seg_1x2(pick):
        s, o = [], []
        eh = 1 / (1 + 10 ** (-((elo.get(home, mean_elo) + c["elo_hfa"]) - elo.get(away, mean_elo)) / 400))
        forza = f"Elo {home} {elo.get(home, mean_elo):.0f} vs {away} {elo.get(away, mean_elo):.0f}"
        if pick in ("1", "1X", "12"):
            (s if eh >= 0.5 else o).append(forza)
            (s if _rate(rh_c, "pts") >= 1.5 else o).append(
                f"{home} casa {_rate(rh_c,'pts'):.2f} punti/gara")
        if pick in ("2", "X2", "12"):
            (s if eh <= 0.5 else o).append(forza)
            (s if _rate(ra_t, "pts") >= 1.3 else o).append(
                f"{away} trasferta {_rate(ra_t,'pts'):.2f} punti/gara")
        return s, o

    def seg_linea(keyrate, etichetta):
        s, o = [], []
        (s if mh[keyrate] >= 0.5 else o).append(f"{home}: {etichetta} {_pct(mh[keyrate])}")
        (s if ma[keyrate] >= 0.5 else o).append(f"{away}: {etichetta} {_pct(ma[keyrate])}")
        return s, o

    candidati = []
    # fattore campione: meno partite -> meno fiducia (a parità di probabilità)
    sample_factor = min(1.0, min(len(rh), len(ra)) / max(1, c["conf_min_campione"]))
    variazioni = variazioni or {}
    alert_presenti = []

    def aggiungi(mercato, p, gruppo, segnali):
        supp, opp = segnali
        ratio = len(supp) / (len(supp) + len(opp)) if (supp or opp) else 0.5
        conf = c["conf_prob"] * (p * 100) + c["conf_segnali"] * (ratio * 100)
        conf *= (0.75 + 0.25 * sample_factor)   # penalità per campioni piccoli
        key_map = {"Over 2.5": "over25", "Under 2.5": "under25", "Goal": "goal",
                   "No Goal": "nogoal", "1": "1", "X": "X", "2": "2",
                   "1X": "1X", "X2": "X2", "12": "12",
                   "Over 1.5": "over15", "Under 1.5": "under15",
                   "Over 3.5": "over35", "Under 3.5": "under35"}
        kk = key_map.get(mercato)
        # implicita GREZZA (1/quota) per il confronto in purezza
        p_odds = mkt.get(kk) if kk else None
        alert = None
        delta = None
        if p_odds is not None:
            delta = p_odds - p          # >0: mercato più convinto delle statistiche
            alert = livello_alert(p, p_odds, c["alert_soglie"])
            # forma "a tenda": accordo lieve = conferma (premia); divario forte in
            # una delle due direzioni = discrepanza/svalutazione (penalizza)
            s_conf = c["alert_soglie"]["medio"]
            if delta < 0:                                    # mercato meno convinto -> svaluta
                adj = c["conf_quota_svaluta"] * delta * 100
            elif delta <= s_conf:                            # accordo -> conferma
                adj = c["conf_quota_conferma"] * delta * 100
            else:                                            # mercato troppo più convinto -> allarme
                adj = -c["conf_quota_discrepanza"] * (delta - s_conf) * 100
            adj = max(-c["conf_da_quota_max"], min(c["conf_da_quota_max"], adj))
            conf += adj
            if alert:
                alert_presenti.append((mercato, alert))
        # variazione di quota: un ribasso forte (soldi sul segno) spinge la confidence
        var = variazioni.get(kk) if kk else None
        var_rel = None
        if var is not None and kk and _ok(odds_est.get(kk)) and float(odds_est.get(kk)) > 0:
            q_now = float(odds_est[kk])
            q_prima = q_now - float(var)          # variazione = attuale - iniziale
            if q_prima > 0:
                var_rel = (q_prima - q_now) / q_prima   # >0 se la quota è scesa
                conf += c["conf_da_variazione"] * var_rel
        candidati.append({
            "mercato": mercato, "gruppo": gruppo, "prob": p,
            "confidence": round(min(100, max(0, conf)), 0),
            "supporting": supp, "opposing": opp, "signal_ratio": ratio,
            "market_prob": p_odds, "delta_quota": delta, "alert": alert,
            "var_quota": var_rel,
            "quota": odds_est.get(kk) if kk else None,
        })

    aggiungi("Over 2.5", over_p, "O/U", seg_over())
    aggiungi("Under 2.5", 1 - over_p, "O/U",
             ([x.replace("Over", "Under") for x in seg_over()[1]],
              [x.replace("Over", "Under") for x in seg_over()[0]]))
    aggiungi("Goal", btts_p, "BTTS", seg_btts())
    aggiungi("No Goal", 1 - btts_p, "BTTS", (seg_btts()[1], seg_btts()[0]))
    aggiungi("1", prob["1"], "1X2", seg_1x2("1"))
    aggiungi("X", prob["X"], "1X2", ([], []))
    aggiungi("2", prob["2"], "1X2", seg_1x2("2"))
    aggiungi("1X", prob["1"] + prob["X"], "DC", seg_1x2("1X"))
    aggiungi("X2", prob["X"] + prob["2"], "DC", seg_1x2("X2"))
    aggiungi("12", prob["1"] + prob["2"], "DC", seg_1x2("12"))
    aggiungi("Over 1.5", over15_p, "O/U1.5", seg_linea("over15", "Over 1.5"))
    aggiungi("Under 1.5", 1 - over15_p, "O/U1.5",
             (seg_linea("over15", "Over 1.5")[1], seg_linea("over15", "Over 1.5")[0]))
    aggiungi("Over 3.5", over35_p, "O/U3.5", seg_linea("over35", "Over 3.5"))
    aggiungi("Under 3.5", 1 - over35_p, "O/U3.5",
             (seg_linea("over35", "Over 3.5")[1], seg_linea("over35", "Over 3.5")[0]))

    # miglior pronostico: massima confidence tra 1X2, O/U, Goal e doppia chance
    primari = [x for x in candidati if x["gruppo"] in ("O/U", "BTTS", "1X2", "DC")]
    best = max(primari, key=lambda x: x["confidence"])

    # ---- risultato esatto: griglia coerente coi mercati (i mercati NON cambiano) ----
    risultati_esatti = prob["risultati"]
    ris_per_esito = {}
    if c["griglia_coerente"]:
        g = griglia_ipf(lh, la, c["dixon_coles_rho"], over_p, btts_p,
                        prob["1"], prob["X"], prob["2"])
        risultati_esatti = [{"risultato": f"{i}-{j}", "p": p} for i, j, p in g[:6]]
        # raggruppa i più probabili per esito 1 / X / 2
        for lab, pred in [("1", lambda i, j: i > j), ("X", lambda i, j: i == j),
                          ("2", lambda i, j: i < j)]:
            sub = [(i, j, p) for i, j, p in g if pred(i, j)][:3]
            ris_per_esito[lab] = [{"risultato": f"{i}-{j}", "p": p} for i, j, p in sub]
        prob["risultati"] = risultati_esatti

    # rischi strutturali
    rischi = list(best["opposing"])
    if prob["X"] >= 0.30:
        rischi.append(f"alta frequenza di pareggi (X {_pct(prob['X'])})")
    if min(len(rh_c), len(ra_t)) < 4:
        rischi.append("campione casa/trasferta limitato")
    if sample_factor < 1.0:
        rischi.append(f"pochi dati ({min(len(rh), len(ra))} partite): fiducia ridotta")
    rischi.extend(note_rest)
    # alert quota sul miglior pronostico
    if best.get("alert"):
        seg = "più bassa" if (best.get("delta_quota") or 0) < 0 else "più alta"
        rischi.append(f"⚠️ alert quota {best['alert']}: la quota è {seg} delle statistiche "
                      f"(stat {_pct(best['prob'])} vs quota {_pct(best['market_prob'])})")
        if best["alert"] in ("medio", "alto"):
            rischi.append("giocata da prendere con prudenza: statistiche e quote divergono molto")
    if best["prob"] < 0.55 and best["gruppo"] in ("1X2", "O/U", "BTTS"):
        rischi.append(f"conviction statistica non alta ({_pct(best['prob'])}): partita incerta")

    # riepilogo alert (ordinati per gravità) sui mercati principali
    ordine = {"alto": 0, "medio": 1, "basso": 2}
    alerts = sorted(
        [{"mercato": m["mercato"], "livello": m["alert"], "prob": m["prob"],
          "market_prob": m["market_prob"], "delta": m["delta_quota"]}
         for m in candidati if m.get("alert") and m["gruppo"] in ("O/U", "BTTS", "1X2", "DC")],
        key=lambda x: (ordine.get(x["livello"], 9), -abs(x["delta"] or 0)))

    return {
        "home": home, "away": away, "data": str(oggi),
        "elo": {"home": elo.get(home, mean_elo), "away": elo.get(away, mean_elo)},
        "prob": prob, "over_prob": over_p, "btts_prob": btts_p,
        "over_prob_raw": over_p_raw, "btts_prob_raw": btts_p_raw,
        "calibrato": bool(calibratori and (calibratori.get("over25") or calibratori.get("goal"))),
        "blended_mercato": blended, "peso_mercato": alpha if blended else 0.0,
        "mercati": candidati, "best": best, "alerts": alerts,
        "reasons": best["supporting"], "risks": rischi,
        "market": mkt,
        "motivazioni": _motivazioni(home, away, rh, ra, rh_c, ra_t, hh),
        "forme_tipo_home": _forma_per_tipo(rh), "forme_tipo_away": _forma_per_tipo(ra),
        "risultati_per_esito": ris_per_esito, "griglia_coerente": c["griglia_coerente"],
        "n_home": len(rh), "n_away": len(ra),
    }


def _forma_per_tipo(recs, min_n=3, top=4):
    """Forma separata per tipo di competizione (Campionato, Coppa, Amichevole, ...)."""
    from collections import defaultdict
    grp = defaultdict(list)
    for r in recs:
        grp[r.get("tipo", "ND")].append(r)
    out = []
    for tipo, rs in grp.items():
        if len(rs) < min_n:
            continue
        out.append({
            "tipo": tipo, "n": len(rs),
            "V": sum(1 for r in rs if r["gf"] > r["ga"]),
            "N": sum(1 for r in rs if r["gf"] == r["ga"]),
            "P": sum(1 for r in rs if r["gf"] < r["ga"]),
            "gf": sum(r["gf"] for r in rs), "ga": sum(r["ga"] for r in rs),
            "goal": sum(r["btts"] for r in rs), "over25": sum(r["over25"] for r in rs),
        })
    out.sort(key=lambda x: -x["n"])
    return out[:top]


def h2h(a, b, df, n=6):
    d = df[(((df["squadra_casa"] == a) & (df["squadra_trasferta"] == b)) |
            ((df["squadra_casa"] == b) & (df["squadra_trasferta"] == a)))].copy()
    d = _played(d)
    if "data" in d.columns:
        d = d.sort_values("data", ascending=False)
    d = d.head(n)
    va = vb = pari = over = goal = 0
    dettaglio = []
    for _, m in d.iterrows():
        gc, gt = int(m["gol_casa"]), int(m["gol_trasferta"])
        casa = m["squadra_casa"]
        gA = gc if casa == a else gt
        gB = gt if casa == a else gc
        if gA > gB:
            va += 1
        elif gB > gA:
            vb += 1
        else:
            pari += 1
        if gc + gt >= 3:
            over += 1
        if gc > 0 and gt > 0:
            goal += 1
        dettaglio.append({"casa": casa, "trasferta": m["squadra_trasferta"],
                          "gc": gc, "gt": gt, "data": str(m["data"]) if "data" in m else ""})
    return {"n": len(d), "vitt_a": va, "vitt_b": vb, "pari": pari,
            "over": over, "goal": goal, "dettaglio": dettaglio}


def statistiche_squadra(nome, df, n=15, venue=None):
    """Compat: conteggi semplici (non pesati) sulle ultime n, per la vista 'ragionamento'."""
    elo = {}
    recs = _records(nome, df, elo, 1500, date.today(), 45, venue)[:n]
    tot = len(recs)
    def s(k):
        return sum(r[k] for r in recs)
    return {"n": tot, "over25": s("over25"), "goal": s("btts"), "segna": s("segna"),
            "subisce": s("subisce"), "cs": s("cs"), "fts": s("fts"),
            "gf": s("gf"), "ga": s("ga"),
            "V": sum(1 for r in recs if r["gf"] > r["ga"]),
            "N": sum(1 for r in recs if r["gf"] == r["ga"]),
            "P": sum(1 for r in recs if r["gf"] < r["ga"]),
            "avg_gf": s("gf") / tot if tot else 0, "avg_ga": s("ga") / tot if tot else 0,
            "tasso_over": s("over25") / tot if tot else 0,
            "tasso_goal": s("btts") / tot if tot else 0}


def _motivazioni(home, away, rh, ra, rh_c, ra_t, hh):
    def cnt(recs, k):
        return sum(r[k] for r in recs), len(recs)
    b = []
    o, n = cnt(rh, "over25"); g, _ = cnt(rh, "btts"); se, _ = cnt(rh, "segna")
    b.append(f"{home} (ultime {n}): Goal {g}/{n} · Over {o}/{n} · segna {se}/{n}")
    o, n = cnt(ra, "over25"); g, _ = cnt(ra, "btts"); se, _ = cnt(ra, "segna")
    b.append(f"{away} (ultime {n}): Goal {g}/{n} · Over {o}/{n} · segna {se}/{n}")
    if rh_c:
        o, n = cnt(rh_c, "over25"); g, _ = cnt(rh_c, "btts")
        b.append(f"{home} in casa: Over {o}/{n} · Goal {g}/{n}")
    if ra_t:
        o, n = cnt(ra_t, "over25"); g, _ = cnt(ra_t, "btts")
        b.append(f"{away} in trasferta: Over {o}/{n} · Goal {g}/{n}")
    if hh["n"]:
        b.append(f"H2H ({hh['n']}): Goal {hh['goal']}/{hh['n']} · Over {hh['over']}/{hh['n']} · "
                 f"{home} {hh['vitt_a']}-{hh['pari']}-{hh['vitt_b']} {away}")
    return b


# --------------------------------------------------------------------- backtest
def backtest(df, min_storico=6, max_partite=250, config=None):
    d = _played(df).copy()
    if "data" not in d.columns or d.empty:
        return None
    d = d.sort_values("data")
    d = d.tail(max_partite)
    n_tot = hit_over = hit_goal = hit_1x2 = 0
    brier_over = brier_goal = 0.0
    pairs_over, pairs_goal = [], []
    for _, m in d.iterrows():
        passato = df[df["data"] < m["data"]] if "data" in df else df
        home, away = m["squadra_casa"], m["squadra_trasferta"]
        res = analizza_partita(home, away, passato, config=config, data_partita=m["data"])
        if res.get("errore"):
            continue
        if res["n_home"] < min_storico or res["n_away"] < min_storico:
            continue
        gc, gt = int(m["gol_casa"]), int(m["gol_trasferta"])
        r_over = 1 if gc + gt >= 3 else 0
        r_goal = 1 if gc > 0 and gt > 0 else 0
        r_1x2 = "1" if gc > gt else ("X" if gc == gt else "2")
        p_over = res["over_prob"]
        p_goal = res["btts_prob"]
        pred_1x2 = max(("1", "X", "2"), key=lambda kk: res["prob"][kk])
        hit_over += (round(p_over) == r_over)
        hit_goal += (round(p_goal) == r_goal)
        hit_1x2 += (pred_1x2 == r_1x2)
        brier_over += (p_over - r_over) ** 2
        brier_goal += (p_goal - r_goal) ** 2
        pairs_over.append((p_over, r_over))
        pairs_goal.append((p_goal, r_goal))
        n_tot += 1
    if not n_tot:
        return None
    return {"n": n_tot, "acc_over": hit_over / n_tot, "acc_goal": hit_goal / n_tot,
            "acc_1x2": hit_1x2 / n_tot,
            "brier_over": brier_over / n_tot, "brier_goal": brier_goal / n_tot,
            "pairs_over": pairs_over, "pairs_goal": pairs_goal}


# --------------------------------------------------------------------- CALIBRAZIONE
# Isotonic regression (Pool Adjacent Violators) senza dipendenze esterne.
def _pava(y, w):
    """Regressione isotona non decrescente sui valori y con pesi w."""
    vals, wts, cnt = [], [], []
    for yi, wi in zip(y, w):
        vals.append(float(yi)); wts.append(float(wi)); cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v2, w2, c2 = vals.pop(), wts.pop(), cnt.pop()
            v1, w1, c1 = vals.pop(), wts.pop(), cnt.pop()
            nv = (v1 * w1 + v2 * w2) / (w1 + w2)
            vals.append(nv); wts.append(w1 + w2); cnt.append(c1 + c2)
    out = []
    for v, c in zip(vals, cnt):
        out.extend([v] * c)
    return out


def fit_isotonic(pairs, min_n=40):
    """pairs = [(prob_grezza, esito 0/1), ...]. Ritorna {'xs':[...], 'ys':[...]}."""
    if not pairs or len(pairs) < min_n:
        return None
    pts = sorted(pairs, key=lambda t: t[0])
    xs = [p for p, _ in pts]
    ys_raw = [float(y) for _, y in pts]
    ys_fit = _pava(ys_raw, [1.0] * len(ys_raw))
    # riduce a punti di rottura (x, y) per l'interpolazione
    bx, by = [], []
    for x, y in zip(xs, ys_fit):
        if bx and abs(by[-1] - y) < 1e-9 and abs(bx[-1] - x) < 1e-9:
            continue
        bx.append(x); by.append(y)
    # dedup di x uguali tenendo l'ultimo y
    dx, dy = [], []
    for x, y in zip(bx, by):
        if dx and dx[-1] == x:
            dy[-1] = y
        else:
            dx.append(x); dy.append(y)
    if len(dx) < 2:
        return None
    return {"xs": dx, "ys": dy}


def applica_iso(p, iso):
    """Interpola la probabilita' calibrata; fuori range usa gli estremi."""
    if not iso or not iso.get("xs"):
        return p
    xs, ys = iso["xs"], iso["ys"]
    if p <= xs[0]:
        return ys[0]
    if p >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if p <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (p - x0) / (x1 - x0)
    return ys[-1]


def reliability(pairs, n_bin=10):
    """Raggruppa in bin di probabilita' e confronta previsto vs reale."""
    bins = []
    for b in range(n_bin):
        lo, hi = b / n_bin, (b + 1) / n_bin
        sel = [(p, y) for p, y in pairs if (p >= lo and (p < hi or (b == n_bin - 1 and p <= hi)))]
        if not sel:
            continue
        pm = sum(p for p, _ in sel) / len(sel)
        rr = sum(y for _, y in sel) / len(sel)
        bins.append({"bin": f"{int(lo*100)}-{int(hi*100)}%", "previsto": pm,
                     "reale": rr, "n": len(sel)})
    return bins


def brier(pairs):
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def brier_calibrato(pairs, iso):
    if not pairs or not iso:
        return None
    return sum((applica_iso(p, iso) - y) ** 2 for p, y in pairs) / len(pairs)


# --------------------------------------------------------------------- OTTIMIZZAZIONE PARAMETRI
def ottimizza_parametri(df, griglia_rho=None, griglia_mercato=None, min_partite=80):
    """Cerca (via backtest) i valori di rho Dixon-Coles e peso_mercato che minimizzano
    il Brier score sulle partite già giocate. Richiede un database corposo, altrimenti
    rischia overfitting: ritorna None se ci sono troppe poche partite."""
    giocate = _played(df)
    if len(giocate) < min_partite:
        return {"errore": "dati insufficienti", "n": len(giocate), "min": min_partite}
    griglia_rho = griglia_rho or [-0.18, -0.14, -0.10, -0.06, -0.02, 0.0]
    griglia_mercato = griglia_mercato or [0.0, 0.2, 0.35, 0.5]
    risultati = []
    for rho in griglia_rho:
        for pm in griglia_mercato:
            bt = backtest(df, config={"dixon_coles_rho": rho, "peso_mercato": pm,
                                      "blending_mercato": pm > 0})
            if not bt:
                continue
            score = (bt["brier_over"] + bt["brier_goal"]) / 2
            risultati.append({"rho": rho, "peso_mercato": pm, "brier": score, "n": bt["n"]})
    if not risultati:
        return None
    risultati.sort(key=lambda x: x["brier"])
    return {"migliore": risultati[0], "tutti": risultati[:8]}
