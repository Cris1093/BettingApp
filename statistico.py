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
    """Tutte le righe evento con gli INCROCI corretti tra le due squadre.
    ph/pa = liste partite (gf,gs,casa) di casa/ospite. Regola: per ogni evento la colonna
    'casa' e la colonna 'trasf' misurano metriche INCROCIATE (attacco vs difesa, vittoria
    vs sconfitta), non la stessa metrica su entrambe."""
    ph_home = _split(ph, True)     # casa in casa
    pa_away = _split(pa, False)    # ospite in trasferta
    righe = []

    # === ESITI 1X2: incrocio vittoria/sconfitta ===
    # "1" = casa vince: quanto la casa VINCE  vs  quanto l'ospite PERDE
    righe.append(_riga("1 (casa vince / ospite perde)", "generale", ph, pa, _vinc, _perd))
    righe.append(_riga("1 (casa vince / ospite perde)", "casa/trasf", ph_home, pa_away, _vinc, _perd))
    # "2" = ospite vince: quanto la casa PERDE  vs  quanto l'ospite VINCE
    righe.append(_riga("2 (casa perde / ospite vince)", "generale", ph, pa, _perd, _vinc))
    righe.append(_riga("2 (casa perde / ospite vince)", "casa/trasf", ph_home, pa_away, _perd, _vinc))
    # "X" = pareggio: quanto pareggiano entrambe
    righe.append(_riga("X (pareggio)", "generale", ph, pa, _pari, _pari))
    righe.append(_riga("X (pareggio)", "casa/trasf", ph_home, pa_away, _pari, _pari))
    # 1X = casa non perde / ospite non vince
    righe.append(_riga("1X (casa non perde / ospite non vince)", "generale", ph, pa,
                       lambda p: not _perd(p), lambda p: not _vinc(p)))
    righe.append(_riga("1X (casa non perde / ospite non vince)", "casa/trasf", ph_home, pa_away,
                       lambda p: not _perd(p), lambda p: not _vinc(p)))
    # X2 = casa non vince / ospite non perde
    righe.append(_riga("X2 (casa non vince / ospite non perde)", "generale", ph, pa,
                       lambda p: not _vinc(p), lambda p: not _perd(p)))
    righe.append(_riga("X2 (casa non vince / ospite non perde)", "casa/trasf", ph_home, pa_away,
                       lambda p: not _vinc(p), lambda p: not _perd(p)))
    # 12 = non pareggio (entrambe)
    righe.append(_riga("12 (nessun pareggio)", "generale", ph, pa,
                       lambda p: not _pari(p), lambda p: not _pari(p)))
    righe.append(_riga("12 (nessun pareggio)", "casa/trasf", ph_home, pa_away,
                       lambda p: not _pari(p), lambda p: not _pari(p)))

    # === OVER/UNDER TOTALI: stessa metrica (evento simmetrico) ===
    for l in (0.5, 1.5, 2.5, 3.5, 4.5):
        righe.append(_riga(f"Over {l} totali", "generale", ph, pa, over_tot(l), over_tot(l)))
        righe.append(_riga(f"Under {l} totali", "generale", ph, pa, under_tot(l), under_tot(l)))
        righe.append(_riga(f"Over {l} totali", "casa/trasf", ph_home, pa_away, over_tot(l), over_tot(l)))
        righe.append(_riga(f"Under {l} totali", "casa/trasf", ph_home, pa_away, under_tot(l), under_tot(l)))

    # === GOL PER SQUADRA (incrocio attacco vs difesa, raggruppato per chi segna) ===
    # "Over X gol squadra di casa"  = attacco CASA (fa) + difesa OSPITE (subisce)
    #    -> colonna casa: quante volte la casa HA FATTO over X
    #    -> colonna trasf: quante volte l'ospite HA SUBITO over X
    # "Over X gol squadra in trasferta" = attacco OSPITE (fa) + difesa CASA (subisce)
    #    -> colonna casa: quante volte la casa HA SUBITO over X
    #    -> colonna trasf: quante volte l'ospite HA FATTO over X
    for l in (0.5, 1.5, 2.5):
        # gol della squadra di CASA: fa la casa vs subisce l'ospite
        righe.append(_riga(f"Over {l} gol squadra di casa", "generale",
                           ph, pa, fatti_over(l), subiti_over(l)))
        righe.append(_riga(f"Over {l} gol squadra di casa", "casa/trasf",
                           ph_home, pa_away, fatti_over(l), subiti_over(l)))
        # gol della squadra in TRASFERTA: subisce la casa vs fa l'ospite
        righe.append(_riga(f"Over {l} gol squadra in trasferta", "generale",
                           ph, pa, subiti_over(l), fatti_over(l)))
        righe.append(_riga(f"Over {l} gol squadra in trasferta", "casa/trasf",
                           ph_home, pa_away, subiti_over(l), fatti_over(l)))

    # === GOAL / NO GOAL ===
    righe.append(_riga("Goal", "generale", ph, pa, _goal, _goal))
    righe.append(_riga("Goal", "casa/trasf", ph_home, pa_away, _goal, _goal))
    righe.append(_riga("No Goal", "generale", ph, pa, _nogoal, _nogoal))
    righe.append(_riga("No Goal", "casa/trasf", ph_home, pa_away, _nogoal, _nogoal))

    # === BANDE DI GOL TOTALI 1-2 .. 1-6 ===
    for hi in (2, 3, 4, 5, 6):
        righe.append(_riga(f"1-{hi} gol totali", "generale", ph, pa, banda(1, hi), banda(1, hi)))

    return righe


def _evento_recente_stabile(partite, pred, k=5):
    """Stabilità recente (regola utente):
    - deve verificarsi in ENTRAMBE le 2 partite più recenti;
    - può mancare al massimo UNA volta nelle ultime k (5).
    """
    rec = partite[:k]
    if len(rec) < 2:
        return True   # troppo pochi dati recenti: non blocco
    # le 2 più recenti devono averlo entrambe
    due = partite[:2]
    if not all(pred(p) for p in due):
        return False
    # al massimo 1 assenza nelle ultime k
    assenze = sum(1 for p in rec if not pred(p))
    return assenze <= 1


# per il filtro di stabilità recente serve rimappare il nome evento -> predicato
def _pred_da_nome(nome):
    """Predicato per il filtro 'stabile nelle ultime 5'. Per gli eventi INCROCIATI usa il
    predicato della squadra di CASA (la colonna 'casa' dell'evento)."""
    if nome.startswith("1 ("):
        return _vinc
    if nome.startswith("2 ("):
        return _perd
    if nome.startswith("X ("):
        return _pari
    if nome.startswith("1X "):
        return lambda p: not _perd(p)
    if nome.startswith("X2 "):
        return lambda p: not _vinc(p)
    if nome.startswith("12 "):
        return lambda p: not _pari(p)
    if nome == "Goal":
        return _goal
    if nome == "No Goal":
        return _nogoal
    if nome.startswith("Over ") and "totali" in nome:
        return over_tot(float(nome.split()[1]))
    if nome.startswith("Under ") and "totali" in nome:
        return under_tot(float(nome.split()[1]))
    if nome.startswith("Over ") and "gol squadra di casa" in nome:
        return fatti_over(float(nome.split()[1]))
    if nome.startswith("Over ") and "gol squadra in trasferta" in nome:
        return subiti_over(float(nome.split()[1]))
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


def classifica(righe):
    """Classifica di TUTTI gli eventi ordinati per % somma (dal più alto). Ritorna una
    lista di dict pronti per la visualizzazione."""
    valide = [r for r in righe if r["somma"][2] is not None]
    valide.sort(key=lambda r: (-r["somma"][2], -(r["somma"][1] or 0)))
    out = []
    for r in valide:
        s = r["somma"]
        out.append({"pronostico": r["pronostico"], "tipologia": r["tipologia"],
                    "n": s[0], "tot": s[1], "pct": s[2]})
    return out


def analizza(ph, pa):
    """Punto d'ingresso: tabella completa + eventi forti + classifica per % somma."""
    righe = tabella_eventi(ph, pa)
    forti = eventi_forti(righe, ph, pa)
    best = forti[0] if forti else None
    return {"tabella": righe, "forti": forti, "best": best,
            "classifica": classifica(righe)}


def esito_evento(nome, gc, gt):
    """Valuta se un evento statistico (per nome) si è verificato, dato il risultato
    gc-gt (dal punto di vista casa-trasferta). Ritorna True/False, o None se ignoto."""
    if not nome:
        return None
    tot = gc + gt
    n = nome.strip()
    # esiti 1X2 e doppie chance
    if n.startswith("1 (") or n == "1":
        return gc > gt
    if n.startswith("2 (") or n == "2":
        return gc < gt
    if n.startswith("X (") or n == "X":
        return gc == gt
    if n.startswith("1X"):
        return gc >= gt
    if n.startswith("X2"):
        return gc <= gt
    if n.startswith("12"):
        return gc != gt
    # goal / no goal
    if n == "Goal":
        return gc > 0 and gt > 0
    if n == "No Goal":
        return not (gc > 0 and gt > 0)
    # over/under totali
    if n.startswith("Over ") and "totali" in n:
        return tot > float(n.split()[1])
    if n.startswith("Under ") and "totali" in n:
        return tot < float(n.split()[1])
    # over gol squadra di casa / trasferta
    if n.startswith("Over ") and "gol squadra di casa" in n:
        return gc > float(n.split()[1])
    if n.startswith("Over ") and "gol squadra in trasferta" in n:
        return gt > float(n.split()[1])
    # bande di gol totali
    if n.startswith("1-") and "totali" in n:
        hi = int(n.split("-")[1].split()[0])
        return 1 <= tot <= hi
    return None
