"""
snapshot.py — costruzione degli snapshot PRE-MATCH per il futuro Learning Engine (ML).

Ogni snapshot è la "fotografia" di una partita PRIMA del calcio d'inizio: un insieme
RICCO di feature calcolate usando SOLO i dati precedenti (walk-forward), più il risultato
reale come target. Accumulati nel tempo formano un dataset di addestramento onesto.

Regola d'oro: nessuna informazione successiva alla partita entra nelle feature.
Versione RICCA: finestre multiple (3/5/10/tutte), casa/trasferta, qualità avversari,
trend temporali, serie/streak, distribuzione gol, sequenza competizioni, incroci relativi,
più le probabilità del motore attuale (meta-learning). ~60-70 feature.

Il numero di feature è volutamente alto: al momento dell'ADDESTRAMENTO se ne useranno
tante o poche a seconda di quanti dati ci sono. Qui l'obiettivo è REGISTRARE tutto il
calcolabile, così il dato storico è ricco e non va ricostruito.
"""

import math
import evidenze


# ---------------------------------------------------------------------------
# helper di base
# ---------------------------------------------------------------------------
def _pct(blocco, chiave, sub="pct", default=None):
    try:
        v = blocco.get(chiave)
        if isinstance(v, dict):
            return v.get(sub, default)
        return v if v is not None else default
    except Exception:
        return default


def _over_pct(blocco, linea):
    try:
        return blocco.get("over", {}).get(linea, {}).get("pct")
    except Exception:
        return None


def _punti(partite):
    """Punti totali (3/1/0) dal punto di vista della squadra."""
    tot = 0
    for p in partite:
        f, a = int(p["gf"]), int(p["gs"])
        tot += 3 if f > a else (1 if f == a else 0)
    return tot


def _ppg(partite):
    return round(_punti(partite) / len(partite), 3) if partite else None


def _media_tot(partite):
    return round(sum(int(p["gf"]) + int(p["gs"]) for p in partite) / len(partite), 3) if partite else None


def _media_gf(partite):
    return round(sum(int(p["gf"]) for p in partite) / len(partite), 3) if partite else None


def _media_gs(partite):
    return round(sum(int(p["gs"]) for p in partite) / len(partite), 3) if partite else None


def _stdev_tot(partite):
    """Volatilità dei gol totali (deviazione standard)."""
    if len(partite) < 2:
        return None
    tot = [int(p["gf"]) + int(p["gs"]) for p in partite]
    m = sum(tot) / len(tot)
    var = sum((x - m) ** 2 for x in tot) / (len(tot) - 1)
    return round(math.sqrt(var), 3)


def _streak(partite, cond):
    """Lunghezza della serie consecutiva (dalla più recente) in cui vale cond(p)."""
    n = 0
    for p in partite:
        if cond(p):
            n += 1
        else:
            break
    return n


def _qualita_avversari(partite, k):
    """Livello medio (divisione) degli ultimi k avversari, come proxy della loro forza.
    Numero più BASSO = avversari di categoria superiore (più forti)."""
    liv = [p.get("livello") for p in partite[:k] if p.get("livello") is not None]
    if not liv:
        return None
    return round(sum(liv) / len(liv), 2)


# ---------------------------------------------------------------------------
# blocco di feature per UNA squadra, su una finestra di partite
# ---------------------------------------------------------------------------
def _feat_finestra(partite, prefix, finestra_nome, n):
    """Feature aggregate su una finestra (ultime n) di partite. Ritorna dict con chiavi
    prefissate: es. home_u5_ppg, home_u5_gf, ..."""
    sel = partite[:n] if n else partite
    p = f"{prefix}_{finestra_nome}"
    out = {}
    if not sel:
        return out
    b = evidenze._blocco(sel)
    out[f"{p}_ppg"] = _ppg(sel)
    out[f"{p}_gf"] = _media_gf(sel)
    out[f"{p}_gs"] = _media_gs(sel)
    out[f"{p}_tot"] = _media_tot(sel)
    out[f"{p}_over15"] = _over_pct(b, 1.5)
    out[f"{p}_over25"] = _over_pct(b, 2.5)
    out[f"{p}_over35"] = _over_pct(b, 3.5)
    out[f"{p}_goal"] = _pct(b, "goal")
    out[f"{p}_nogoal"] = _pct(b, "nogoal")
    out[f"{p}_clean"] = _pct(b, "clean")
    out[f"{p}_nosegna"] = _pct(b, "nosegna")
    out[f"{p}_vitt"] = _pct(b, "vitt")
    return out


def _feat_squadra(partite, venue, prefix):
    """Tutte le feature di UNA squadra: finestre multiple, split casa/trasferta, qualità
    avversari, trend, serie, distribuzione, volatilità."""
    out = {}
    out[f"{prefix}_n"] = len(partite)

    # finestre multiple (ultime 3 / 5 / 10 / tutte)
    out.update(_feat_finestra(partite, prefix, "u3", 3))
    out.update(_feat_finestra(partite, prefix, "u5", 5))
    out.update(_feat_finestra(partite, prefix, "u10", 10))
    out.update(_feat_finestra(partite, prefix, "all", None))

    # split casa/trasferta rilevante
    rilev = [p for p in partite if p["casa"] == (venue == "casa")]
    out.update(_feat_finestra(rilev, prefix, "venue", None))
    out[f"{prefix}_venue_n"] = len(rilev)

    # qualità avversari (proxy: livello divisione)
    out[f"{prefix}_qavv_u5"] = _qualita_avversari(partite, 5)
    out[f"{prefix}_qavv_u10"] = _qualita_avversari(partite, 10)

    # trend temporali: ultime 5 vs precedenti 5
    u5 = partite[:5]
    prev5 = partite[5:10]
    if u5 and prev5:
        out[f"{prefix}_trend_gf"] = round((_media_gf(u5) or 0) - (_media_gf(prev5) or 0), 3)
        out[f"{prefix}_trend_gs"] = round((_media_gs(u5) or 0) - (_media_gs(prev5) or 0), 3)
        out[f"{prefix}_trend_tot"] = round((_media_tot(u5) or 0) - (_media_tot(prev5) or 0), 3)
        out[f"{prefix}_trend_ppg"] = round((_ppg(u5) or 0) - (_ppg(prev5) or 0), 3)

    # serie / streak (dalla più recente)
    out[f"{prefix}_streak_vitt"] = _streak(partite, lambda p: p["gf"] > p["gs"])
    out[f"{prefix}_streak_nosconf"] = _streak(partite, lambda p: p["gf"] >= p["gs"])
    out[f"{prefix}_streak_over25"] = _streak(partite, lambda p: p["gf"] + p["gs"] >= 3)
    out[f"{prefix}_streak_goal"] = _streak(partite, lambda p: p["gf"] >= 1 and p["gs"] >= 1)
    out[f"{prefix}_streak_clean"] = _streak(partite, lambda p: p["gs"] == 0)
    out[f"{prefix}_streak_segna"] = _streak(partite, lambda p: p["gf"] >= 1)

    # distribuzione gol della squadra (% di 0,1,2,3+ gol fatti)
    n = len(partite)
    if n:
        seg = [int(p["gf"]) for p in partite]
        out[f"{prefix}_gf0_pct"] = round(sum(1 for x in seg if x == 0) / n * 100, 1)
        out[f"{prefix}_gf1_pct"] = round(sum(1 for x in seg if x == 1) / n * 100, 1)
        out[f"{prefix}_gf2_pct"] = round(sum(1 for x in seg if x == 2) / n * 100, 1)
        out[f"{prefix}_gf3p_pct"] = round(sum(1 for x in seg if x >= 3) / n * 100, 1)

    # volatilità gol totali
    out[f"{prefix}_volat_tot"] = _stdev_tot(partite)

    return out


# ---------------------------------------------------------------------------
# costruzione completa
# ---------------------------------------------------------------------------
def costruisci_snapshot(partite_home, partite_away, ev=None, sig=None):
    """Snapshot RICCO pre-match. Input: liste walk-forward (partite precedenti), dalla più
    recente. ev/sig opzionali per le probabilità/segnale del motore attuale."""
    feat = {}
    feat.update(_feat_squadra(partite_home, "casa", "home"))
    feat.update(_feat_squadra(partite_away, "trasf", "away"))

    # ---- incroci attacco/difesa (i più informativi per i gol) ----
    hgf = _media_gf(partite_home); hgs = _media_gs(partite_home)
    agf = _media_gf(partite_away); ags = _media_gs(partite_away)
    if hgf is not None and ags is not None:
        feat["x_att_casa_vs_dif_osp"] = round((hgf + ags) / 2, 3)
    if agf is not None and hgs is not None:
        feat["x_att_osp_vs_dif_casa"] = round((agf + hgs) / 2, 3)
    # somma gol attesi grezza (proxy Over)
    if hgf is not None and ags is not None and agf is not None and hgs is not None:
        feat["x_gol_attesi"] = round((hgf + ags) / 2 + (agf + hgs) / 2, 3)

    # ---- differenze relative (spesso più informative dei valori assoluti) ----
    def _d(a, b):
        return round(a - b, 3) if (a is not None and b is not None) else None
    feat["d_ppg_all"] = _d(_ppg(partite_home), _ppg(partite_away))
    feat["d_gf_all"] = _d(hgf, agf)
    feat["d_gs_all"] = _d(hgs, ags)
    feat["d_ppg_u5"] = _d(_ppg(partite_home[:5]), _ppg(partite_away[:5]))
    feat["d_forma_u5"] = _d(_punti(partite_home[:5]), _punti(partite_away[:5]))
    feat["d_qavv_u5"] = _d(_qualita_avversari(partite_home, 5), _qualita_avversari(partite_away, 5))

    # ---- probabilità del MOTORE attuale (meta-learning) ----
    if ev and ev.get("prob"):
        p = ev["prob"]
        for k_src, k_dst in (("1", "mot_1"), ("X", "mot_X"), ("2", "mot_2"),
                             ("Over 1.5", "mot_over15"), ("Over 2.5", "mot_over25"),
                             ("Over 3.5", "mot_over35"), ("Goal", "mot_goal"),
                             ("No Goal", "mot_nogoal")):
            if k_src in p and p[k_src] is not None:
                feat[k_dst] = round(p[k_src], 1)
        # anche la versione grezza (pre-calibrazione) dell'Over/Goal, se disponibile
        pg = ev.get("prob_grezza") or {}
        for k_src, k_dst in (("Over 2.5", "mot_over25_grezza"), ("Goal", "mot_goal_grezza")):
            if k_src in pg and pg[k_src] is not None:
                feat[k_dst] = round(pg[k_src], 1)

    # ---- signal del pronostico di punta ----
    if sig:
        best = max(sig, key=lambda m: m.get("score", 0), default=None)
        if best:
            feat["mot_best_mercato"] = best.get("mercato")
            feat["mot_best_signal"] = best.get("score")

    return feat


def costruisci_target(gc, gt):
    """Target (esiti reali) da un risultato gc-gt."""
    gc, gt = int(gc), int(gt)
    tot = gc + gt
    return {
        "home_goals": gc, "away_goals": gt, "tot_goals": tot,
        "risultato_1x2": "1" if gc > gt else ("X" if gc == gt else "2"),
        "over05": 1 if tot >= 1 else 0,
        "over15": 1 if tot >= 2 else 0,
        "over25": 1 if tot >= 3 else 0,
        "over35": 1 if tot >= 4 else 0,
        "goal": 1 if (gc >= 1 and gt >= 1) else 0,
        "home_scored": 1 if gc >= 1 else 0,
        "away_scored": 1 if gt >= 1 else 0,
        "clean_home": 1 if gt == 0 else 0,
        "clean_away": 1 if gc == 0 else 0,
    }
