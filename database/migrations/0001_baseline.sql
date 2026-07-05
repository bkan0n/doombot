-- name: migrate-0001-up
-- Baseline: prod schema as of 2026-07-05. Idempotent — a no-op on databases
-- that already have the schema. No down migration: reverting the baseline
-- would drop the database.

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

CREATE OR REPLACE FUNCTION natsort(s text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$
  select string_agg(r[1] || E'\x01' || lpad(r[2], 20, '0'), '')
  from regexp_matches(s, '(\D*)(\d*)', 'g') r;
$$;

CREATE OR REPLACE FUNCTION primary_id_sequences_from_all_tables() RETURNS TABLE(table_name text, column_name text, data_type text, max bigint, next bigint)
    LANGUAGE plpgsql
    AS $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT tc.table_name, kcu.column_name, c.data_type
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.columns AS c
            ON kcu.table_name = c.table_name
            AND kcu.column_name = c.column_name
            AND c.data_type IN ('smallint', 'integer', 'bigint', 'decimal', 'numeric', 'real', 'double precision')
        WHERE tc.constraint_type = 'PRIMARY KEY'
    LOOP
        RETURN QUERY EXECUTE 'SELECT ' || quote_nullable(rec.table_name) || ', ' || quote_nullable(rec.column_name) || ', ' || quote_nullable(rec.data_type) || ', (SELECT COALESCE(MAX(' || rec.column_name || '), 0)::BIGINT FROM ' || rec.table_name || '), (SELECT nextval(pg_get_serial_sequence(' || quote_nullable(rec.table_name) || ', ' || quote_nullable(rec.column_name) || ')))';
    END LOOP;
END;
$$;

-- Users

CREATE TABLE IF NOT EXISTS users (
    user_id bigint NOT NULL,
    nickname character varying(25) NOT NULL,
    alertable boolean DEFAULT true NOT NULL,
    flags integer,
    CONSTRAINT users_pk PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS alias (
    user_id bigint NOT NULL,
    alias text NOT NULL,
    "primary" boolean DEFAULT false NOT NULL,
    CONSTRAINT alias_users_user_id_fk FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS user_ranks (
    user_id bigint NOT NULL,
    category text NOT NULL,
    value text NOT NULL,
    CONSTRAINT user_ranks_pk PRIMARY KEY (user_id, category),
    CONSTRAINT user_ranks_users_user_id_fk FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_xp (
    user_id bigint NOT NULL,
    xp bigint DEFAULT 0,
    season integer NOT NULL,
    CONSTRAINT user_xp_pk PRIMARY KEY (user_id, season),
    CONSTRAINT user_xp_users_user_id_fk FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
);

-- Maps

CREATE TABLE IF NOT EXISTS maps (
    map_name text NOT NULL,
    map_type text[] NOT NULL,
    map_code character varying(6) NOT NULL,
    "desc" text,
    official boolean DEFAULT false NOT NULL,
    image text,
    CONSTRAINT maps_pk PRIMARY KEY (map_code)
);

CREATE TABLE IF NOT EXISTS map_levels (
    map_code character varying(6) NOT NULL,
    level text NOT NULL,
    CONSTRAINT map_levels_pk PRIMARY KEY (map_code, level),
    CONSTRAINT map_levels_maps_map_code_fk FOREIGN KEY (map_code) REFERENCES maps(map_code) ON UPDATE CASCADE ON DELETE CASCADE
);

-- Redundant with the primary key, but prod has it; postgres silently skips an
-- inline UNIQUE that duplicates the PK, so it needs an explicit guarded ALTER.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_constraint WHERE conname = 'map_levels_pk_2') THEN
        ALTER TABLE map_levels ADD CONSTRAINT map_levels_pk_2 UNIQUE (map_code, level);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS map_creators (
    map_code character varying(6) NOT NULL,
    user_id bigint NOT NULL,
    CONSTRAINT map_creators_pk PRIMARY KEY (map_code, user_id),
    CONSTRAINT map_creators_maps_map_code_fk FOREIGN KEY (map_code) REFERENCES maps(map_code) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT map_creators_users_user_id_fk FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS map_level_ratings (
    map_code character varying(6) NOT NULL,
    level text NOT NULL,
    rating integer NOT NULL,
    user_id bigint NOT NULL,
    CONSTRAINT table_name_pk PRIMARY KEY (map_code, level, user_id),
    CONSTRAINT table_name_map_levels_map_code_level_fk FOREIGN KEY (map_code, level) REFERENCES map_levels(map_code, level) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS guides (
    map_code character varying(6) NOT NULL,
    url text NOT NULL,
    CONSTRAINT guides_maps_map_code_fk FOREIGN KEY (map_code) REFERENCES maps(map_code) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS guides_url_uindex ON guides USING btree (url);

CREATE TABLE IF NOT EXISTS all_map_names (
    name text,
    color text
);

CREATE TABLE IF NOT EXISTS all_map_types (
    name text
);

-- Records

CREATE TABLE IF NOT EXISTS records (
    map_code character varying(6) NOT NULL,
    user_id bigint NOT NULL,
    level_name text NOT NULL,
    record numeric(10,2) NOT NULL,
    screenshot text NOT NULL,
    video text,
    verified boolean DEFAULT false NOT NULL,
    message_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    hidden_id bigint,
    CONSTRAINT records_pk PRIMARY KEY (map_code, user_id, level_name, inserted_at),
    CONSTRAINT records_map_levels_map_code_level_fk FOREIGN KEY (map_code, level_name) REFERENCES map_levels(map_code, level) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT records_users_user_id_fk FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS records_message_id_uindex ON records USING btree (message_id);

CREATE TABLE IF NOT EXISTS top_records (
    user_id bigint NOT NULL,
    original_message_id bigint NOT NULL,
    top_record_id bigint,
    channel_id bigint NOT NULL,
    CONSTRAINT top_records_pk PRIMARY KEY (user_id, original_message_id, channel_id)
);

COMMENT ON COLUMN top_records.user_id IS 'User that upvoted record (not the record holder)';

CREATE TABLE IF NOT EXISTS verification_counts (
    user_id bigint,
    amount integer DEFAULT 0,
    CONSTRAINT verification_counts_users_user_id_fk FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS verification_counts_user_id_uindex ON verification_counts USING btree (user_id);

-- Tournament

CREATE TABLE IF NOT EXISTS tournament (
    title text DEFAULT 'Doomfist Parkour Tournament'::text,
    start timestamp with time zone NOT NULL,
    "end" timestamp with time zone NOT NULL,
    active boolean NOT NULL,
    bracket boolean NOT NULL,
    roles bigint[],
    id integer NOT NULL GENERATED BY DEFAULT AS IDENTITY (START WITH 0 MINVALUE 0),
    CONSTRAINT tournament_pk PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS tournament_maps (
    id integer NOT NULL,
    code character varying(6) NOT NULL,
    level text NOT NULL,
    category text NOT NULL,
    creator text,
    CONSTRAINT tournament_maps_pk PRIMARY KEY (id, category),
    CONSTRAINT tournament_maps_tournament_id_fk FOREIGN KEY (id) REFERENCES tournament(id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tournament_missions (
    id integer NOT NULL,
    type text NOT NULL,
    target numeric(10,2) NOT NULL,
    difficulty text NOT NULL,
    category text NOT NULL,
    extra_target text,
    CONSTRAINT tournament_missions_pk PRIMARY KEY (id, difficulty, category),
    CONSTRAINT tournament_missions_tournament_id_fk FOREIGN KEY (id) REFERENCES tournament(id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tournament_ranks (
    value text NOT NULL,
    CONSTRAINT tournament_ranks_pk PRIMARY KEY (value)
);

CREATE TABLE IF NOT EXISTS tournament_records (
    user_id bigint NOT NULL,
    category text NOT NULL,
    record numeric(10,2) NOT NULL,
    tournament_id integer NOT NULL,
    screenshot text,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tournament_records_pk PRIMARY KEY (tournament_id, user_id, category, inserted_at),
    CONSTRAINT tournament_records_tournament_id_fk FOREIGN KEY (tournament_id) REFERENCES tournament(id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT tournament_records_users_user_id_fk FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tournament_seasons (
    number integer NOT NULL GENERATED ALWAYS AS IDENTITY (START WITH 1 MINVALUE 0),
    name text NOT NULL,
    active boolean DEFAULT false NOT NULL,
    CONSTRAINT tournament_seasons_pk PRIMARY KEY (number),
    CONSTRAINT tournament_seasons_pk_2 UNIQUE (name)
);

-- Duels

CREATE TABLE IF NOT EXISTS duels (
    id integer NOT NULL GENERATED ALWAYS AS IDENTITY,
    thread_id bigint NOT NULL,
    message_id bigint NOT NULL,
    map_code text NOT NULL,
    level text NOT NULL,
    wager integer NOT NULL,
    season integer NOT NULL,
    duration interval NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    ready_deadline timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    ends_at timestamp with time zone,
    CONSTRAINT duels_wager_check CHECK ((wager > 0)),
    CONSTRAINT duels_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS duel_players (
    duel_id integer NOT NULL,
    user_id bigint NOT NULL,
    num integer NOT NULL,
    ready boolean DEFAULT false NOT NULL,
    record numeric(10,2),
    screenshot text,
    result integer DEFAULT 0 NOT NULL,
    CONSTRAINT duel_players_num_check CHECK ((num = ANY (ARRAY[1, 2]))),
    CONSTRAINT duel_players_pkey PRIMARY KEY (duel_id, user_id),
    CONSTRAINT duel_players_duel_id_num_key UNIQUE (duel_id, num),
    CONSTRAINT duel_players_duel_id_fkey FOREIGN KEY (duel_id) REFERENCES duels(id) ON DELETE CASCADE,
    CONSTRAINT duel_players_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
);

-- Tags

CREATE TABLE IF NOT EXISTS tags (
    name text NOT NULL,
    value text,
    CONSTRAINT tags_pk PRIMARY KEY (name)
);

CREATE SEQUENCE IF NOT EXISTS tags2_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS tags2 (
    id integer DEFAULT nextval('tags2_id_seq'::regclass) NOT NULL,
    name text,
    content text,
    owner_id bigint,
    uses integer DEFAULT 0,
    location_id bigint,
    created_at timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    CONSTRAINT tags2_pkey PRIMARY KEY (id)
);

ALTER SEQUENCE tags2_id_seq OWNED BY tags2.id;

CREATE INDEX IF NOT EXISTS tags2_location_id_idx ON tags2 USING btree (location_id);
CREATE INDEX IF NOT EXISTS tags2_name_idx ON tags2 USING btree (name);
CREATE INDEX IF NOT EXISTS tags2_name_lower_idx ON tags2 USING btree (lower(name));
CREATE INDEX IF NOT EXISTS tags2_name_trgm_idx ON tags2 USING gin (name gin_trgm_ops);
CREATE UNIQUE INDEX IF NOT EXISTS tags2_uniq_idx ON tags2 USING btree (lower(name), location_id);

CREATE SEQUENCE IF NOT EXISTS tag_lookup_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS tag_lookup (
    id integer DEFAULT nextval('tag_lookup_id_seq'::regclass) NOT NULL,
    name text,
    location_id bigint,
    owner_id bigint,
    created_at timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    tag_id integer,
    CONSTRAINT tag_lookup_pkey PRIMARY KEY (id),
    CONSTRAINT tag_lookup_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES tags2(id) ON DELETE CASCADE
);

ALTER SEQUENCE tag_lookup_id_seq OWNED BY tag_lookup.id;

CREATE INDEX IF NOT EXISTS tag_lookup_location_id_idx ON tag_lookup USING btree (location_id);
CREATE INDEX IF NOT EXISTS tag_lookup_name_idx ON tag_lookup USING btree (name);
CREATE INDEX IF NOT EXISTS tag_lookup_name_lower_idx ON tag_lookup USING btree (lower(name));
CREATE INDEX IF NOT EXISTS tag_lookup_name_trgm_idx ON tag_lookup USING gin (name gin_trgm_ops);
CREATE UNIQUE INDEX IF NOT EXISTS tag_lookup_uniq_idx ON tag_lookup USING btree (lower(name), location_id);

-- Gym

CREATE TABLE IF NOT EXISTS all_exercises (
    name text NOT NULL,
    type text,
    CONSTRAINT all_exercises_pk PRIMARY KEY (name)
);

CREATE UNIQUE INDEX IF NOT EXISTS all_exercises_name_uindex ON all_exercises USING btree (name);

CREATE TABLE IF NOT EXISTS exercises (
    equipment text,
    name text,
    target text,
    location text,
    url text,
    id integer NOT NULL GENERATED BY DEFAULT AS IDENTITY
);

CREATE TABLE IF NOT EXISTS gym_records (
    user_id bigint NOT NULL,
    exercise text NOT NULL,
    value numeric(7,2),
    CONSTRAINT gym_records_pk PRIMARY KEY (user_id, exercise)
);

-- Misc

CREATE TABLE IF NOT EXISTS colors (
    emoji text,
    label text,
    role_id bigint,
    sort_order integer
);

CREATE TABLE IF NOT EXISTS insults (
    value text
);

CREATE TABLE IF NOT EXISTS quotes (
    id integer NOT NULL GENERATED ALWAYS AS IDENTITY,
    content text,
    username text,
    CONSTRAINT quotes_pk PRIMARY KEY (id)
);
