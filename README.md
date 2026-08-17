# ⚽ Estrattore Partite

App base (v1) per estrarre partite dai blocchi "ULTIMI INCONTRI", salvarle a
database e costruire nel tempo il DB su cui gireranno i futuri algoritmi di pronostico.

**Stack:** Python · Streamlit · Supabase · Streamlit Community Cloud · GitHub

## Cosa fa (v1)
- **Ultimi risultati e quote** — incolli i blocchi di 2 squadre, l'app riconosce tutte le
  partite (formato `Casa - Trasferta | risultato`), quote iniziali e variazione di quota,
  forma e valori rose; risultati modificabili, copia e salvataggio a DB.
- **Estrattore risultati** — incolli i risultati per competizione (senza data): l'app aggancia
  il punteggio alle partite **già presenti** confrontando i nomi squadra (togliendo il codice
  paese tipo `(Kaz)`). Per le partite non trovate esatte c'è l'**aggancio manuale per somiglianza**
  (suggerimenti ordinati). Non crea partite nuove. Le nuove competizioni finiscono in Configurazione.
- **Estrattore pianificazione** — incolli le partite in programma (con orario, senza risultato):
  vengono create come **partite da compilare**, con categoria assegnata in automatico se la
  competizione è già configurata (altrimenti `ND`). Scelgi la data del turno (modificabile per riga).
  Quando poi aggiungi risultato o quote, la partita **esce** dalla lista "da compilare".
- **Database** — elenco dalla partita più recente, modifica risultati, dettaglio grafico, export Excel.
- **Configurazione** — utenti, **competizioni** (categoria + nome corto) e backup Excel.

### Competizioni e categorie
Ogni competizione ha `nome_lungo`, `nazione`, `nome_corto` e `categoria`
(Amichevole / Coppa nazionale / Coppa internazionale / Campionato / Altro). Il **nome corto**
(es. `TPA`) collega il nome lungo dell'estrattore risultati (`Torneo Promocional Amateur | ARGENTINA`)
al codice usato nello storico. In Configurazione assegni la categoria dal menu a tendina; il
pulsante *Applica categorie alle partite* propaga `tipo_partita` su tutte le partite.
Quando la categoria non è determinabile (competizione assente o non ancora configurata) la
partita è marcata **`ND`**.

## Setup
1. **Supabase** — crea un progetto, apri *SQL Editor* ed esegui `schema.sql`.
2. **Secrets** — copia `.streamlit/secrets.toml.example` in `.streamlit/secrets.toml`
   e inserisci `url` e `key` (consigliata la *service_role* key).
3. **Locale** — `pip install -r requirements.txt` poi `streamlit run app.py`.
4. **Deploy** — push su GitHub, poi su Streamlit Community Cloud punta a `app.py` e
   incolla i secrets in *Settings → Secrets*.
5. **Primo avvio** — la prima schermata ti fa creare l'utente amministratore.

## Note sul parsing
- Le squadre si riconoscono dalla riga `ULTIMI INCONTRI: <squadra>` (gestita anche
  con `INCONTRI:` o `ULTIMI` troncato).
- I punteggi dei rigori tra parentesi `1(4)` vengono ignorati (resta `1`).
- Virgole al posto del punto nelle quote/valori vengono normalizzate.
- Ordine del blocco di coda (ogni riga può mancare): 1X2 · O/U 2.5 · Goal/NoGoal ·
  **forma** (casa, trasferta) · **valore rose** (casa, trasferta). La forma è sempre in
  formato decimale (X.XX o X.X, anche con virgola, es. `7.21 8.9`); il valore rose è
  sempre intero (es. `287 325`, può stare anche sotto i 10). Da questo il parser le
  distingue in modo affidabile anche quando ne compare una sola.
- La stessa partita presente nella storia di entrambe le squadre viene salvata una
  sola volta (chiave `data + casa + trasferta`).
- L'esito `V/N/P` è relativo alla squadra di quel blocco: non viene salvato perché
  ambiguo dopo la deduplica — il risultato si ricava dai gol.

## Analisi & Pronostico (motore in `analisi.py`)
Pagina **🔮 Analisi & Pronostico**: seleziona una partita in attesa e il motore multi-fattore
calcola tutto dal database.

Cosa fa il motore (`analisi.py`, funzioni pure e testabili):
- **Forma pesata** su ultime 5/10/15 (pesi 45/35/20) con **recency weighting** esponenziale
  (`peso = exp(-giorni/decay)`): le gare recenti contano di più.
- **Split casa/trasferta** con priorità sulla forma generale.
- **Rigori**: le partite decise ai rigori usano il risultato dei 90/120' (es. `1(3)-1(4)` → 1-1,
  quindi un pareggio per 1X2/OU/Goal); la nota "Dopo Rigori" resta come info supplementare.
- **Gerarchia competizioni**: ogni partita è pesata per tipo (Campionato/Playoff 1.00, Coppe 0.85,
  Torneo secondario 0.75, Amichevole 0.35 — tutti regolabili). Una goleada in amichevole conta
  molto meno di una gara ufficiale. Il peso si attiva quando la competizione è categorizzata.
- **Forma separata per competizione**: oltre a ultime 5/10/15, mostra la forma per tipo
  (es. "in campionato 6V, in amichevole 4V") quando ci sono abbastanza dati.
- **Qualità avversari** via **Elo pre-partita** (aggiornato partita dopo partita): battere una
  squadra forte pesa più che batterne una debole, e l'aggiustamento usa il rating dell'avversario
  *al momento* di quella partita.
- **1X2 multi-segnale**: il pareggio resta ancorato al Poisson, mentre il lato vincente fonde
  Poisson + Elo + forma casa/trasferta + **valore rose**.
- **Livello di lega**: assegnando un livello alle competizioni (1ª, 2ª, 3ª divisione…) l'Elo
  parte più basso per le leghe minori. Così una squadra che domina in 2ª non viene sovrastimata
  contro una di 1ª (utile per neopromosse, coppe cross-divisione, amichevoli). Si auto-corregge
  coi risultati reali quando le divisioni si incrociano.
- **Rose che mitigano il livello**: se inserisci il valore delle rose, questo diventa il segnale
  guida di forza e *riduce* la penalità di livello — una 3ª di un campionato forte può valere più
  di una 1ª di un campionato minore. Senza il valore rose, il livello resta il proxy.
- **Expected Goals** con modello **moltiplicativo**: `λ = media_gol_lega × forza_attacco ×
  debolezza_difesa_avversario × fattore_campo`, con **correzione Dixon-Coles** sui risultati
  bassi (0-0, 1-1) e attacco/difesa aggiustati per qualità avversario (Elo pre-partita).
- **Shrinkage**: le statistiche di squadre con pochi dati vengono regredite verso la media di
  lega — meno falsi "90%" su campioni piccoli.
- **Le quote NON mediano la probabilità** (niente blending): la probabilità resta pura
  statistica. Le quote servono a due cose:
  - **Alert di discrepanza** (basso/medio/alto): confronto in purezza tra statistiche e quota
    *grezza* (1/quota, senza togliere il margine). Segnala solo i mercati dove statistiche e
    bookmaker divergono — "come mai le statistiche dicono una cosa e le quote un'altra?".
  - **Confidence**: un accordo lieve (mercato un po' più convinto) *premia* la giocata; un
    divario forte in una delle due direzioni la *penalizza* (un mercato molto più convinto delle
    statistiche è un allarme, non una conferma; se il mercato svaluta, la giocata perde valore).
  - **Variazione di quota**: un ribasso forte (soldi entrati su quel segno) spinge la confidence.
- Questa logica è una **tesi da validare col backtest** sui dati storici (potrebbe rivelarsi da
  correggere): l'idea è capire come le discrepanze quote/statistiche incidono sul risultato.
- **Risultato esatto coerente**: la griglia dei risultati esatti (Poisson+Dixon-Coles) viene
  "piegata" finché non rispetta i totali dei mercati (1X2/Over/Goal) **senza toccarli** — così
  i risultati esatti tornano con gli altri mercati. Mostrati anche raggruppati per esito.
- **Studio quote bookmaker**, **analisi discrepanze** (tasso di successo per scarto quota↔statistica
  e per livello di alert, per validare o smentire la tesi della confidence) e **ottimizzazione
  parametri** dal backtest, da usare col database pieno.
- **Auto-riempimento risultati** nei pronostici salvati: quando il risultato entra nel database,
  viene copiato nel pronostico corrispondente (base per la calibrazione prospettica).
- **Confidence consapevole del campione** (meno dati → meno fiducia), **coerenza delle linee
  gol** (Over 1.5 ≥ Over 2.5 ≥ Over 3.5) e nota su **riposo/calendario** (poco riposo o lunga
  sosta).
- **Score per mercato con conflitto dei segnali**: per Over e Goal combina forma, split, H2H e
  Poisson, e applica una **penalizzazione esplicita** quando un segnale forte contraddice il
  mercato (es. una difesa che tiene molti clean sheet abbatte il Goal; due squadre chiuse e poco
  prolifiche abbattono l'Over).
- **Quote come consenso, non per decidere**: le trasforma in probabilità implicite normalizzate
  (tolto il margine) e segnala solo se modello e mercato sono concordi o divergono.
- **Output ricco**: miglior pronostico con **confidence /100**, barra forza-segnali, motivi ✓,
  rischi ⚠, probabilità per mercato, risultati esatti probabili.
- **Pesi configurabili** dall'interfaccia (recency decay, vantaggio campo, peso H2H).
- **Backtest**: valuta il modello sulle partite già giocate (accuratezza 1X2/Over/Goal + Brier)
  usando solo i dati precedenti a ciascuna gara.

### Calibrazione (nella pagina Analisi)
Il modello si **auto-valuta e si corregge** sui tuoi dati:
- **Backtest**: rigioca le partite già chiuse usando solo i dati precedenti a ciascuna e misura
  accuratezza (1X2/Over/Goal) e Brier score.
- **Affidabilità**: raggruppa le previsioni in fasce (0-10%, ... 90-100%) e confronta *previsto*
  vs *reale* — così vedi se una confidence dell'80% vale davvero ~80%.
- **Isotonic regression**: fitta una correzione monotona che trasforma le probabilità grezze in
  probabilità realistiche; la attivi solo se **migliora il Brier**.
- Una volta attivata, le probabilità Over/Goal nelle analisi sono **calibrate** (con badge e
  valore grezzo a confronto).
- **Salva pronostico**: ogni analisi pre-partita può essere salvata (tabella `pronostici`) per
  accumulare uno storico di previsioni e calibrare in modo prospettico nel tempo.

## Prossimi passi
- Calibrazione anche su 1X2 (multiclasse) e sul punteggio esatto.
- Riempimento automatico del risultato reale nei `pronostici` quando la partita si chiude, e
  report ROI/hit-rate per fascia di confidence.
- Confronto con modelli ML (Logistic, Random Forest, Gradient Boosting, Dixon-Coles) ed ensemble.
