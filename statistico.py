"""
statistico.py — MOTORE STATISTICO / FREQUENZIALE (conteggi grezzi).

Affianca il motore probabilistico: qui niente pesi, niente Poisson. Solo "quante volte
su quante partite" (es. Over 1.5: 13/15 = 87%), per casa, trasferta e somma.

Regole (dettate dall'utente):
  - ogni evento ha: stat squadra CASA · stat squadra TRASFERTA · stat SOMMATE;
  - un evento è "forte" se è alto per almeno una squadra e le due NON sono in forte
    contrasto (differenza >= 30 punti % -> scartato);
  - non segnalare un evento se non si è verificato in TUTTE le 5 partite più recenti
    (di entrambe le squadre): filtro di stabilità recente;
  - confidence = quanto la squadra OPPOSTA conferma l'evento (guidata dalla % più bassa
    tra le due): entrambe alte -> alta; una bassa -> bassa.
"""

CONTRASTO = 30          # punti % di differenza oltre i quali le due squadre sono "opposte"
SOGLIA_FORTE = 70       # una squadra deve avere l'evento almeno a questa % per candidarlo
CONF_ALTA = 80
CONF_MEDIA = 65


def _conta(partite, pred):
    """(n eventi, totale, pct) grezzi su una lista di partite."""
    n = len(partite)
    if n == 0:
        return (0, 0, None)
    k = sum(1 for p in partite if pred(p))
    return (k, n, round(k / n * 100, 1))


def _split(partite, casa):
    """Partite in casa (casa=True) o in trasferta (casa=False)."""
    return [p for p in partite if bool(p.get("casa")) == casa]


# ---- predicati -------------------------------------------------------------
def _tot(p): return p["gf"] + p["gs"]
def over_tot(l): return lambda p: _tot(p) > l
def under_tot(l): return lambda p: _tot(p) < l
def fatti_over(l): return lambda p: p["gf"] > l
def fatti_under(l): return lambda p: p["gf"] < l
def subiti_over(l): return lambda p: p["gs"] > l
def subiti_under(l): return lambda p: p["gs"] < l
def banda(lo, hi): return lambda p: lo <= _tot(p) <= hi
def _vinc(p): return p["gf"] > p["gs"]
def _pari(p): return p["gf"] == p["gs"]
def _perd(p): return p["gf"] < p["gs"]
def _goal(p): return p["gf"] > 0 and p["gs"] > 0
def _nogoal(p): return not _goal(p)


def _riga(nome, tipologia, ph, pa, pred_home, pred_away):
    """Costruisce una riga evento con stat casa/trasferta/somma (conteggi grezzi)."""
    kh, nh, ph_pct = _conta(ph, pred_home)
    ka, na, pa_pct = _conta(pa, pred_away)
    ks, ns = kh + ka, nh + na
    somma_pct = round(ks / ns * 100, 1) if ns else None
    return {"pronostico": nome, "tipologia": tipologia,
            "casa": (kh, nh, ph_pct), "trasf": (ka, na, pa_pct),
            "somma": (ks, ns, somma_pct)}


def tabella_eventi(ph, pa):
    """Tutte le righe evento richieste. ph/pa = liste partite (gf,gs,casa) di casa/ospite."""
    ph_home = _split(ph, True)     # casa in casa
    pa_away = _split(pa, False)    # ospite in trasferta
    righe = []

    # --- esiti 1X2 e doppie chance (casa vince / ospite perde, ecc.) ---
    # "1" = vittoria casa: home vince, away perde
    righe.append(_riga("1", "generale", ph, pa, _vinc, _perd))
    righe.append(_riga("1", "casa/trasf", ph_home, pa_away, _vinc, _perd))
    righe.append(_riga("X", "generale", ph, pa, _pari, _pari))
    righe.append(_riga("X", "casa/trasf", ph_home, pa_away, _pari, _pari))
    righe.append(_riga("2", "generale", ph, pa, _perd, _vinc))
    righe.append(_riga("2", "casa/trasf", ph_home, pa_away, _perd, _vinc))
    # 1X = casa non perde / ospite non vince
    righe.append(_riga("1X", "generale", ph, pa, lambda p: not _perd(p), lambda p: not _vinc(p)))
    righe.append(_riga("1X", "casa/trasf", ph_home, pa_away, lambda p: not _perd(p), lambda p: not _vinc(p)))
    # X2 = casa non vince / ospite non perde
    righe.append(_riga("X2", "generale", ph, pa, lambda p: not _vinc(p), lambda p: not _perd(p)))
    righe.append(_riga("X2", "casa/trasf", ph_home, pa_away, lambda p: not _vinc(p), lambda p: not _perd(p)))
    # 12 = non pareggio (entrambe)
    righe.append(_riga("12", "generale", ph, pa, lambda p: not _pari(p), lambda p: not _pari(p)))
    righe.append(_riga("12", "casa/trasf", ph_home, pa_away, lambda p: not _pari(p), lambda p: not _pari(p)))

    # --- vittorie/pareggi/sconfitte casa-trasferta espliciti ---
    righe.append(_riga("Vittoria", "casa/trasf", ph_home, pa_away, _vinc, _vinc))
    righe.append(_riga("Pareggio", "casa/trasf", ph_home, pa_away, _pari, _pari))
    righe.append(_riga("Sconfitta", "casa/trasf", ph_home, pa_away, _perd, _perd))

    # --- Over/Under totali 0.5..4.5 (generale e casa/trasf) ---
    for l in (0.5, 1.5, 2.5, 3.5, 4.5):
        righe.append(_riga(f"Over {l}", "generale", ph, pa, over_tot(l), over_tot(l)))
        righe.append(_riga(f"Under {l}", "generale", ph, pa, under_tot(l), under_tot(l)))
        righe.append(_riga(f"Over {l}", "casa/trasf", ph_home, pa_away, over_tot(l), over_tot(l)))
        righe.append(_riga(f"Under {l}", "casa/trasf", ph_home, pa_away, under_tot(l), under_tot(l)))

    # --- Over/Under gol FATTI e SUBITI per squadra (0.5,1.5,2.5) ---
    for l in (0.5, 1.5, 2.5):
        righe.append(_riga(f"Gol fatti Over {l}", "generale", ph, pa, fatti_over(l), fatti_over(l)))
        righe.append(_riga(f"Gol fatti Over {l}", "casa/trasf", ph_home, pa_away, fatti_over(l), fatti_over(l)))
        righe.append(_riga(f"Gol subiti Over {l}", "generale", ph, pa, subiti_over(l), subiti_over(l)))
        righe.append(_riga(f"Gol subiti Over {l}", "casa/trasf", ph_home, pa_away, subiti_over(l), subiti_over(l)))

    # --- Goal / No Goal ---
    righe.append(_riga("Goal", "generale", ph, pa, _goal, _goal))
    righe.append(_riga("Goal", "casa/trasf", ph_home, pa_away, _goal, _goal))
    righe.append(_riga("No Goal", "generale", ph, pa, _nogoal, _nogoal))
    righe.append(_riga("No Goal", "casa/trasf", ph_home, pa_away, _nogoal, _nogoal))

    # --- bande di gol totali 1-2 .. 1-6 ---
    for hi in (2, 3, 4, 5, 6):
        righe.append(_riga(f"1-{hi} gol totali", "generale", ph, pa, banda(1, hi), banda(1, hi)))

    return righe


def _evento_recente_stabile(partite, pred, k=5):
    """True se l'evento si è verificato in TUTTE le ultime k partite (stabilità recente)."""
    rec = partite[:k]
    if len(rec) < k:
        return True   # troppo pochi dati recenti: non blocco
    return all(pred(p) for p in rec)


# per il filtro di stabilità recente serve rimappare il nome evento -> predicato
def _pred_da_nome(nome):
    m = {"Goal": _goal, "No Goal": _nogoal, "Vittoria": _vinc, "Pareggio": _pari,
         "Sconfitta": _perd, "1": _vinc, "X": _pari, "2": _perd,
         "1X": lambda p: not _perd(p), "X2": lambda p: not _vinc(p), "12": lambda p: not _pari(p)}
    if nome in m:
        return m[nome]
    if nome.startswith("Over ") and "gol" not in nome:
        return over_tot(float(nome.split()[1]))
    if nome.startswith("Under "):
        return under_tot(float(nome.split()[1]))
    if nome.startswith("Gol fatti Over "):
        return fatti_over(float(nome.split()[-1]))
    if nome.startswith("Gol subiti Over "):
        return subiti_over(float(nome.split()[-1]))
    if nome.startswith("1-") and "totali" in nome:
        return banda(1, int(nome.split("-")[1].split()[0]))
    return None


def _confidence(ph_pct, pa_pct):
    if ph_pct is None or pa_pct is None:
        return None
    basso = min(ph_pct, pa_pct)
    if basso >= CONF_ALTA:
        return "alta"
    if basso >= CONF_MEDIA:
        return "media"
    return "bassa"


def eventi_forti(righe, ph, pa):
    """Filtra gli eventi statisticamente forti secondo le regole dell'utente:
    - alto per almeno una squadra; NON in contrasto (>=30pt); stabile nelle ultime 5.
    Ordina per confidence e % somma."""
    forti = []
    for r in righe:
        ph_pct = r["casa"][2]
        pa_pct = r["trasf"][2]
        if ph_pct is None or pa_pct is None:
            continue
        # almeno una squadra sopra soglia
        if max(ph_pct, pa_pct) < SOGLIA_FORTE:
            continue
        # non in forte contrasto
        if abs(ph_pct - pa_pct) >= CONTRASTO:
            continue
        # stabilità nelle ultime 5 di ENTRAMBE
        pred = _pred_da_nome(r["pronostico"])
        if pred is not None:
            if not _evento_recente_stabile(ph, pred) or not _evento_recente_stabile(pa, pred):
                continue
        conf = _confidence(ph_pct, pa_pct)
        forti.append({**r, "confidence": conf, "somma_pct": r["somma"][2]})
    # ordina: confidence (alta>media>bassa) poi % somma
    ordine = {"alta": 0, "media": 1, "bassa": 2, None: 3}
    forti.sort(key=lambda x: (ordine.get(x["confidence"], 3), -(x["somma_pct"] or 0)))
    return forti


def analizza(ph, pa):
    """Punto d'ingresso: tabella completa + eventi forti con confidence."""
    righe = tabella_eventi(ph, pa)
    forti = eventi_forti(righe, ph, pa)
    # miglior evento statistico = il primo forte (se c'è)
    best = forti[0] if forti else None
    return {"tabella": righe, "forti": forti, "best": best}
