"""
fusione.py — FUSIONE dei due motori in un'unica probabilità per mercato.

Idea (Fase 2 dello studio):
  - Il motore a FREQUENZE (evidenze.py) dà probabilità coerenti dai dati pesati.
  - Il motore POISSON/Dixon-Coles (analisi.probabilita) dà probabilità da gol attesi (λ),
    ottimo per risultati esatti e linee Over alternative.
  I due sono stime diverse dello stesso fenomeno: le fondiamo in UNA probabilità.

Punti chiave:
  - I gol attesi (λ) sono calcolati dagli STESSI dati pesati del motore a frequenze
    (quindi time-consistent per costruzione, niente info dal futuro).
  - Applica l'handicap di livello (una squadra da categoria inferiore segna meno).
  - La fusione è una media pesata per mercato; il peso di fusione (w_freq/w_pois)
    parte NEUTRO 50/50 ed è un parametro DA OTTIMIZZARE COL BACKTEST (non a occhio).
  - Restano esposte tutte e tre le stime: freq, poisson, fusa (per trasparenza/backtest).
"""

import analisi

# peso di fusione provvisorio (neutro): da ottimizzare col backtest, non a occhio.
W_FREQ = 0.5
W_POIS = 0.5


def _media_pesata_gol(partite, tipo):
    """Media pesata dei gol fatti ('gf') o subiti ('gs') su una lista di partite pesate."""
    num = den = 0.0
    for p in partite:
        w = p.get("peso", 1.0)
        num += w * p[tipo]
        den += w
    return (num / den) if den > 0 else None


def lambda_attesi(home_blocco, away_blocco, hcap_home=1.0, hcap_away=1.0):
    """Gol attesi λ per casa e trasferta, da medie pesate incrociate (attacco vs difesa),
    dando più peso al rendimento casa/trasferta specifico. Con handicap di livello."""
    def att(sq, tipo, split_key):
        # combina generale e split (casa/trasf), più peso allo split
        g = sq["generale"].get(tipo)
        s = sq["split"].get(tipo) if sq["split"].get("n") else None
        vals = [(s, 0.6), (g, 0.4)] if s is not None else [(g, 1.0)]
        num = sum(w * v for v, w in vals if v is not None)
        den = sum(w for v, w in vals if v is not None)
        return (num / den) if den else 1.2

    # λ casa = (attacco casa in casa) combinato con (difesa avversario in trasferta)
    att_home = att(home_blocco, "media_fatti", "split")
    dif_away = att(away_blocco, "media_subiti", "split")
    att_away = att(away_blocco, "media_fatti", "split")
    dif_home = att(home_blocco, "media_subiti", "split")

    lh = (att_home + dif_away) / 2.0
    la = (att_away + dif_home) / 2.0

    # vantaggio campo leggero + handicap di livello (una squadra inferiore segna meno)
    lh = lh * 1.06 * hcap_home
    la = la * 0.96 * hcap_away
    # clamp di sicurezza
    lh = max(0.15, min(5.0, lh))
    la = max(0.15, min(5.0, la))
    return round(lh, 3), round(la, 3)


def prob_poisson(home_blocco, away_blocco, hcap_home=1.0, hcap_away=1.0, rho=-0.10):
    """Probabilità (in %) dai gol attesi via Poisson/Dixon-Coles. Coerenti per costruzione."""
    lh, la = lambda_attesi(home_blocco, away_blocco, hcap_home, hcap_away)
    pr = analisi.probabilita(lh, la, rho)   # ritorna frazioni 0..1
    out = {
        "1": pr["1"] * 100, "X": pr["X"] * 100, "2": pr["2"] * 100,
        "Over 2.5": pr["over25"] * 100, "Under 2.5": pr["under25"] * 100,
        "Goal": pr["goal"] * 100, "No Goal": pr["nogoal"] * 100,
    }
    out["1X"] = out["1"] + out["X"]
    out["X2"] = out["X"] + out["2"]
    out["12"] = out["1"] + out["2"]
    return {k: round(v, 2) for k, v in out.items()}, {"lambda_home": lh, "lambda_away": la,
                                                      "risultati": pr.get("risultati", [])}


def fondi(prob_freq, home_blocco, away_blocco, hcap_home=1.0, hcap_away=1.0,
          w_freq=W_FREQ, w_pois=W_POIS):
    """Fonde le probabilità a frequenze con quelle Poisson in un'unica stima per mercato.
    Ritorna (prob_fusa, dettaglio) dove dettaglio contiene freq, poisson, λ e risultati.
    Le coppie complementari restano coerenti (rinormalizzate)."""
    p_pois, meta = prob_poisson(home_blocco, away_blocco, hcap_home, hcap_away)
    tot_w = (w_freq + w_pois) or 1.0

    def mix(m):
        a = prob_freq.get(m)
        b = p_pois.get(m)
        if a is None and b is None:
            return None
        if a is None:
            return b
        if b is None:
            return a
        return (w_freq * a + w_pois * b) / tot_w

    fusa = {}
    # gruppi complementari: fondi e rinormalizza a 100
    for grp in (("1", "X", "2"), ("Over 2.5", "Under 2.5"), ("Goal", "No Goal")):
        vals = {m: mix(m) for m in grp if mix(m) is not None}
        s = sum(vals.values())
        if s > 0:
            for m, v in vals.items():
                fusa[m] = round(v / s * 100.0, 2)
    # doppie chance come somme coerenti
    if all(k in fusa for k in ("1", "X", "2")):
        fusa["1X"] = round(fusa["1"] + fusa["X"], 2)
        fusa["X2"] = round(fusa["X"] + fusa["2"], 2)
        fusa["12"] = round(fusa["1"] + fusa["2"], 2)

    dettaglio = {
        "prob_freq": {k: prob_freq.get(k) for k in fusa},
        "prob_poisson": p_pois,
        "lambda_home": meta["lambda_home"], "lambda_away": meta["lambda_away"],
        "risultati_poisson": meta["risultati"],
        "w_freq": w_freq, "w_pois": w_pois,
    }
    return fusa, dettaglio
