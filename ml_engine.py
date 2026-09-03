"""
ml_engine.py — Learning Engine (Passo 1: modello esploratore).

Legge gli snapshot pre-match (feature calcolate walk-forward + risultato reale), addestra
un gradient boosting (HistGradientBoostingClassifier di scikit-learn) e lo VALIDA in modo
onesto con split temporale (allena sul passato, testa sul futuro). Non tocca i motori
esistenti: serve a (1) scoprire quali feature contano e (2) vedere se batte il motore attuale.

Prudenza con ~600 esempi: modello regolarizzato, poche foglie, e validazione temporale
(mai testare su dati usati per allenare). I risultati sono INDICATIVI, non definitivi.
"""

import json
import numpy as np
import pandas as pd


# target binari che vogliamo modellare (nome_target -> descrizione)
TARGET_BINARI = {
    "over15": "Over 1.5", "over25": "Over 2.5", "over35": "Over 3.5",
    "goal": "Goal", "home_scored": "Casa segna", "away_scored": "Ospite segna",
}


def carica_dataset(client):
    """Legge tutti gli snapshot da Supabase e li trasforma in:
    - X: DataFrame delle feature NUMERICHE (una riga per partita)
    - targets: dict {nome_target: Series di 0/1}
    - date: Series di date (per lo split temporale)
    Ritorna (X, targets, date, note)."""
    righe = []
    step = 1000
    start = 0
    while True:
        res = (client.table("snapshot_prematch")
               .select("data,features_json,target_json")
               .order("data", desc=False)
               .range(start, start + step - 1).execute())
        batch = res.data or []
        righe.extend(batch)
        if len(batch) < step:
            break
        start += step
    if not righe:
        return None, None, None, "Nessuno snapshot trovato."

    feats = []
    targs = []
    date = []
    for r in righe:
        try:
            f = json.loads(r["features_json"]) if r.get("features_json") else {}
            t = json.loads(r["target_json"]) if r.get("target_json") else {}
        except Exception:
            continue
        if not f or not t:
            continue
        feats.append(f)
        targs.append(t)
        date.append(r.get("data"))

    if not feats:
        return None, None, None, "Snapshot presenti ma vuoti."

    Xraw = pd.DataFrame(feats)
    # tieni SOLO le feature numeriche (scarta stringhe tipo 'mot_best_mercato')
    num_cols = [c for c in Xraw.columns if pd.api.types.is_numeric_dtype(Xraw[c])]
    # riprova a convertire le colonne "object" che sono in realtà numeri
    for c in Xraw.columns:
        if c not in num_cols:
            conv = pd.to_numeric(Xraw[c], errors="coerce")
            if conv.notna().sum() > len(conv) * 0.5:   # se >50% convertibili, tienila
                Xraw[c] = conv
                num_cols.append(c)
    X = Xraw[num_cols].astype(float)

    Traw = pd.DataFrame(targs)
    targets = {}
    for name in TARGET_BINARI:
        if name in Traw.columns:
            targets[name] = pd.to_numeric(Traw[name], errors="coerce")
    # target 1X2 (multiclasse) a parte
    if "risultato_1x2" in Traw.columns:
        targets["risultato_1x2"] = Traw["risultato_1x2"].astype(str)

    date = pd.to_datetime(pd.Series(date), errors="coerce")
    nota = f"{len(X)} snapshot · {X.shape[1]} feature numeriche."
    return X, targets, date, nota


def _baseline_binario(y_train, y_test):
    """Baseline: prevede sempre la classe più frequente nel train. Ritorna accuratezza test."""
    if len(y_train) == 0:
        return 0.0
    maggioranza = int(round(y_train.mean()))
    return float((y_test == maggioranza).mean())


def addestra_valida_binario(X, y, date, min_train=300, quota_test=0.3):
    """Addestra e valida un target BINARIO con split TEMPORALE (train sul passato, test sul
    futuro). Ritorna dict con accuratezza modello, baseline, Brier, e importanza feature."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import brier_score_loss, log_loss

    # allinea e pulisci
    mask = y.notna()
    X2, y2, d2 = X[mask].reset_index(drop=True), y[mask].astype(int).reset_index(drop=True), date[mask].reset_index(drop=True)
    ordine = d2.sort_values(kind="stable").index
    X2, y2 = X2.loc[ordine].reset_index(drop=True), y2.loc[ordine].reset_index(drop=True)

    n = len(X2)
    if n < min_train + 30:
        return {"errore": f"pochi dati validi ({n}); servono almeno {min_train + 30}."}

    n_test = max(30, int(n * quota_test))
    n_train = n - n_test
    Xtr, Xte = X2.iloc[:n_train], X2.iloc[n_train:]
    ytr, yte = y2.iloc[:n_train], y2.iloc[n_train:]

    if ytr.nunique() < 2 or yte.nunique() < 2:
        return {"errore": "una classe assente nel train o test (target troppo sbilanciato)."}

    # modello regolarizzato: prudente per ~600 esempi
    modello = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
        min_samples_leaf=25, l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.15, random_state=42)
    modello.fit(Xtr, ytr)

    prob = modello.predict_proba(Xte)[:, 1]
    pred = (prob >= 0.5).astype(int)
    acc = float((pred == yte.values).mean())
    base = _baseline_binario(ytr, yte)
    brier = float(brier_score_loss(yte, prob))
    try:
        ll = float(log_loss(yte, prob, labels=[0, 1]))
    except Exception:
        ll = None

    # importanza feature via permutation (più onesta della "gain")
    from sklearn.inspection import permutation_importance
    imp = permutation_importance(modello, Xte, yte, n_repeats=5, random_state=42,
                                 scoring="accuracy")
    importanze = sorted(zip(X2.columns, imp.importances_mean),
                        key=lambda t: t[1], reverse=True)[:12]

    return {
        "n_train": n_train, "n_test": n_test,
        "acc_modello": round(acc * 100, 1), "acc_baseline": round(base * 100, 1),
        "batte_baseline": acc > base, "brier": round(brier, 4), "log_loss": round(ll, 4) if ll else None,
        "top_feature": [(f, round(v, 4)) for f, v in importanze if v > 0],
    }


def addestra_valida_1x2(X, y, date, min_train=300, quota_test=0.3):
    """Come sopra ma per il target 1X2 (multiclasse: 1/X/2)."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    mask = y.notna() & (y != "nan")
    X2 = X[mask].reset_index(drop=True)
    y2 = y[mask].reset_index(drop=True)
    d2 = date[mask].reset_index(drop=True)
    ordine = d2.sort_values(kind="stable").index
    X2, y2 = X2.loc[ordine].reset_index(drop=True), y2.loc[ordine].reset_index(drop=True)

    n = len(X2)
    if n < min_train + 30:
        return {"errore": f"pochi dati validi ({n})."}

    n_test = max(30, int(n * quota_test))
    n_train = n - n_test
    Xtr, Xte = X2.iloc[:n_train], X2.iloc[n_train:]
    ytr, yte = y2.iloc[:n_train], y2.iloc[n_train:]

    modello = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
        min_samples_leaf=25, l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.15, random_state=42)
    modello.fit(Xtr, ytr)
    pred = modello.predict(Xte)
    acc = float((pred == yte.values).mean())
    # baseline: sempre la classe più frequente (di solito "1")
    maggioranza = ytr.value_counts().idxmax()
    base = float((yte == maggioranza).mean())

    return {
        "n_train": n_train, "n_test": n_test,
        "acc_modello": round(acc * 100, 1), "acc_baseline": round(base * 100, 1),
        "batte_baseline": acc > base, "classe_baseline": maggioranza,
    }
