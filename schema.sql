-- =====================================================================
--  Schema Supabase per "Estrattore Partite"
--  Esegui questo file nel SQL Editor di Supabase.
-- =====================================================================

-- Utenti dell'app
create table if not exists utenti (
    id            uuid primary key default gen_random_uuid(),
    username      text unique not null,
    password_hash text not null,
    ruolo         text not null default 'user',   -- 'admin' | 'user'
    creato_il     timestamptz default now()
);

-- Partite (il "DB" per il futuro algoritmo)
create table if not exists partite (
    id               uuid primary key default gen_random_uuid(),
    data             date not null,
    competizione     text,
    squadra_casa     text not null,
    squadra_trasferta text not null,
    gol_casa         int,
    gol_trasferta    int,
    qualificatore    text,          -- es. 'Dopo Rigori', 'Dopo Suppl.'
    tipo_partita     text,          -- categoria derivata dalla competizione ('ND' se non determinabile)
    ora              text,          -- orario di inizio (pianificazione), es. '18:00'
    da_compilare     boolean default false,  -- partita pianificata in attesa di risultato/quote

    -- quote e valori rose: valorizzati solo per la partita da pronosticare
    -- per ogni mercato: quota iniziale (dallo scraper) + variazione di quota (manuale)
    quota_iniziale_1 numeric, quota_iniziale_x numeric, quota_iniziale_2 numeric,
    variazione_quota_1 numeric, variazione_quota_x numeric, variazione_quota_2 numeric,
    quota_iniziale_over numeric, quota_iniziale_under numeric,
    variazione_quota_over numeric, variazione_quota_under numeric,
    quota_iniziale_goal numeric, quota_iniziale_nogoal numeric,
    variazione_quota_goal numeric, variazione_quota_nogoal numeric,
    forma_casa numeric, forma_trasferta numeric,
    val_casa  numeric, val_trasferta numeric,
    is_target boolean default false,

    inserito_da   text,
    creato_il     timestamptz default now(),
    aggiornato_il timestamptz default now(),

    -- la stessa partita compare nella storia di entrambe le squadre: dedup
    unique (data, squadra_casa, squadra_trasferta)
);

create index if not exists idx_partite_data on partite (data desc);

-- Pronostici salvati prima della partita (per la calibrazione)
create table if not exists pronostici (
    id           uuid primary key default gen_random_uuid(),
    partita_id   uuid,
    data         date,
    squadra_casa text, squadra_trasferta text,
    mercato      text,           -- miglior pronostico (es. 'Under 2.5')
    prob         numeric, confidence numeric, quota numeric,
    prob_over25  numeric, prob_goal numeric,
    prob_1 numeric, prob_x numeric, prob_2 numeric,
    gol_casa     int, gol_trasferta int,   -- risultato reale (riempito dopo)
    creato_il    timestamptz default now()
);

-- Calibratori salvati (isotonic) per mercato
create table if not exists calibrazione (
    mercato       text primary key,   -- 'over25' | 'goal'
    xs            text, ys text,       -- punti dell'isotonica (JSON)
    n             int,
    brier_pre     numeric, brier_post numeric,
    aggiornato_il timestamptz default now()
);

-- Competizioni: anagrafica per categorizzare le partite
create table if not exists competizioni (
    id          uuid primary key default gen_random_uuid(),
    nome_lungo  text,          -- es. 'Torneo Promocional Amateur' (dall'estrattore risultati)
    nazione     text,          -- es. 'ARGENTINA'
    nome_corto  text,          -- es. 'TPA' (codice usato nell'estrattore ultimi risultati e quote)
    categoria   text default 'Non assegnata',  -- Amichevole | Coppa nazionale | Coppa internazionale | Campionato | Altro
    livello     int,           -- livello di lega: 1 = prima divisione, 2 = seconda, 3 = terza...
    creato_il   timestamptz default now()
);

-- =====================================================================
-- MIGRAZIONE da una versione precedente della tabella.
--
-- 1) Se mancano del tutto le colonne forma:
--    alter table partite add column if not exists forma_casa numeric;
--    alter table partite add column if not exists forma_trasferta numeric;
--
-- 1b) Categoria partita + tabella competizioni + pianificazione:
--    alter table partite add column if not exists tipo_partita text;
--    alter table partite add column if not exists ora text;
--    alter table partite add column if not exists da_compilare boolean default false;
--    alter table competizioni add column if not exists livello int;
--    (le tabelle competizioni, pronostici e calibrazione vengono create dai blocchi
--     'create table if not exists' qui sopra: rilancia lo schema per crearle)
--
-- 2) Se hai le colonne quote con i vecchi nomi (q1, q1_mod, ...), rinominale:
--    alter table partite rename column q1 to quota_iniziale_1;
--    alter table partite rename column qx to quota_iniziale_x;
--    alter table partite rename column q2 to quota_iniziale_2;
--    alter table partite rename column q1_mod to variazione_quota_1;
--    alter table partite rename column qx_mod to variazione_quota_x;
--    alter table partite rename column q2_mod to variazione_quota_2;
--    alter table partite rename column q_over25 to quota_iniziale_over;
--    alter table partite rename column q_under25 to quota_iniziale_under;
--    alter table partite rename column q_over25_mod to variazione_quota_over;
--    alter table partite rename column q_under25_mod to variazione_quota_under;
--    alter table partite rename column q_goal to quota_iniziale_goal;
--    alter table partite rename column q_nogoal to quota_iniziale_nogoal;
--    alter table partite rename column q_goal_mod to variazione_quota_goal;
--    alter table partite rename column q_nogoal_mod to variazione_quota_nogoal;
-- =====================================================================

-- =====================================================================
-- NOTA SICUREZZA:
-- Per un'app privata puoi lasciare RLS disattivata (default) e usare la
-- chiave anon, oppure — meglio — usare la SERVICE ROLE key nei secrets di
-- Streamlit (lato server, non esposta al browser).
-- =====================================================================
