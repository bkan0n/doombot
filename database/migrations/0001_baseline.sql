-- name: migrate-0001-up
-- Baseline: prod schema as of 2026-07-05. Idempotent — a no-op on databases
-- that already have the schema. No down migration: reverting the baseline
-- would drop the database.

CREATE SCHEMA IF NOT EXISTS doom3;

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

CREATE TABLE IF NOT EXISTS map_contest (
    user_id bigint NOT NULL,
    map_code character varying(6) NOT NULL,
    tournament_id integer NOT NULL,
    CONSTRAINT map_contest_pk PRIMARY KEY (tournament_id, user_id),
    CONSTRAINT map_contest_tournament_id_fk FOREIGN KEY (tournament_id) REFERENCES tournament(id)
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

CREATE TABLE IF NOT EXISTS gym_prs (
    user_id bigint,
    exercise text,
    weight numeric(7,2),
    CONSTRAINT gym_prs_user_id_exercise_key UNIQUE (user_id, exercise)
);

COMMENT ON TABLE gym_prs IS 'Weight is saved in kilograms';

CREATE TABLE IF NOT EXISTS gym_records (
    user_id bigint NOT NULL,
    exercise text NOT NULL,
    value numeric(7,2),
    CONSTRAINT gym_records_pk PRIMARY KEY (user_id, exercise)
);

-- Misc

CREATE TABLE IF NOT EXISTS auto_join_thread (
    thread_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    CONSTRAINT auto_join_thread_pk PRIMARY KEY (thread_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS auto_join_thread_thread_id_uindex ON auto_join_thread USING btree (thread_id);

CREATE TABLE IF NOT EXISTS colors (
    emoji text,
    label text,
    role_id bigint,
    sort_order integer
);

CREATE TABLE IF NOT EXISTS insults (
    value text
);

CREATE TABLE IF NOT EXISTS keep_alives (
    thread_id bigint
);

CREATE TABLE IF NOT EXISTS quotes (
    id integer NOT NULL GENERATED ALWAYS AS IDENTITY,
    content text,
    username text,
    CONSTRAINT quotes_pk PRIMARY KEY (id)
);

-- Legacy Django admin

CREATE TABLE IF NOT EXISTS django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL,
    CONSTRAINT django_session_pkey PRIMARY KEY (session_key)
);

CREATE INDEX IF NOT EXISTS django_session_expire_date_a5c62663 ON django_session USING btree (expire_date);
CREATE INDEX IF NOT EXISTS django_session_session_key_c0390e0f_like ON django_session USING btree (session_key varchar_pattern_ops);

CREATE SEQUENCE IF NOT EXISTS django_migrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS django_migrations (
    id integer DEFAULT nextval('django_migrations_id_seq'::regclass) NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL,
    CONSTRAINT django_migrations_pkey PRIMARY KEY (id)
);

ALTER SEQUENCE django_migrations_id_seq OWNED BY django_migrations.id;

CREATE SEQUENCE IF NOT EXISTS django_content_type_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS django_content_type (
    id integer DEFAULT nextval('django_content_type_id_seq'::regclass) NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL,
    CONSTRAINT django_content_type_pkey PRIMARY KEY (id),
    CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model)
);

ALTER SEQUENCE django_content_type_id_seq OWNED BY django_content_type.id;

CREATE SEQUENCE IF NOT EXISTS auth_user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS auth_user (
    id integer DEFAULT nextval('auth_user_id_seq'::regclass) NOT NULL,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean NOT NULL,
    username character varying(150) NOT NULL,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    email character varying(254) NOT NULL,
    is_staff boolean NOT NULL,
    is_active boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL,
    CONSTRAINT auth_user_pkey PRIMARY KEY (id),
    CONSTRAINT auth_user_username_key UNIQUE (username)
);

ALTER SEQUENCE auth_user_id_seq OWNED BY auth_user.id;

CREATE INDEX IF NOT EXISTS auth_user_username_6821ab7c_like ON auth_user USING btree (username varchar_pattern_ops);

CREATE SEQUENCE IF NOT EXISTS auth_group_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS auth_group (
    id integer DEFAULT nextval('auth_group_id_seq'::regclass) NOT NULL,
    name character varying(150) NOT NULL,
    CONSTRAINT auth_group_pkey PRIMARY KEY (id),
    CONSTRAINT auth_group_name_key UNIQUE (name)
);

ALTER SEQUENCE auth_group_id_seq OWNED BY auth_group.id;

CREATE INDEX IF NOT EXISTS auth_group_name_a6ea08ec_like ON auth_group USING btree (name varchar_pattern_ops);

CREATE SEQUENCE IF NOT EXISTS auth_permission_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS auth_permission (
    id integer DEFAULT nextval('auth_permission_id_seq'::regclass) NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL,
    CONSTRAINT auth_permission_pkey PRIMARY KEY (id),
    CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename),
    CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES django_content_type(id) DEFERRABLE INITIALLY DEFERRED
);

ALTER SEQUENCE auth_permission_id_seq OWNED BY auth_permission.id;

CREATE INDEX IF NOT EXISTS auth_permission_content_type_id_2f476e4b ON auth_permission USING btree (content_type_id);

CREATE SEQUENCE IF NOT EXISTS auth_group_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS auth_group_permissions (
    id integer DEFAULT nextval('auth_group_permissions_id_seq'::regclass) NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL,
    CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id),
    CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id),
    CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES auth_permission(id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES auth_group(id) DEFERRABLE INITIALLY DEFERRED
);

ALTER SEQUENCE auth_group_permissions_id_seq OWNED BY auth_group_permissions.id;

CREATE INDEX IF NOT EXISTS auth_group_permissions_group_id_b120cbf9 ON auth_group_permissions USING btree (group_id);
CREATE INDEX IF NOT EXISTS auth_group_permissions_permission_id_84c5c92e ON auth_group_permissions USING btree (permission_id);

CREATE SEQUENCE IF NOT EXISTS auth_user_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS auth_user_groups (
    id integer DEFAULT nextval('auth_user_groups_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    group_id integer NOT NULL,
    CONSTRAINT auth_user_groups_pkey PRIMARY KEY (id),
    CONSTRAINT auth_user_groups_user_id_group_id_94350c0c_uniq UNIQUE (user_id, group_id),
    CONSTRAINT auth_user_groups_group_id_97559544_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES auth_group(id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT auth_user_groups_user_id_6a12ed8b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED
);

ALTER SEQUENCE auth_user_groups_id_seq OWNED BY auth_user_groups.id;

CREATE INDEX IF NOT EXISTS auth_user_groups_group_id_97559544 ON auth_user_groups USING btree (group_id);
CREATE INDEX IF NOT EXISTS auth_user_groups_user_id_6a12ed8b ON auth_user_groups USING btree (user_id);

CREATE SEQUENCE IF NOT EXISTS auth_user_user_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS auth_user_user_permissions (
    id integer DEFAULT nextval('auth_user_user_permissions_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    permission_id integer NOT NULL,
    CONSTRAINT auth_user_user_permissions_pkey PRIMARY KEY (id),
    CONSTRAINT auth_user_user_permissions_user_id_permission_id_14a6b632_uniq UNIQUE (user_id, permission_id),
    CONSTRAINT auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES auth_permission(id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED
);

ALTER SEQUENCE auth_user_user_permissions_id_seq OWNED BY auth_user_user_permissions.id;

CREATE INDEX IF NOT EXISTS auth_user_user_permissions_permission_id_1fbb5f2c ON auth_user_user_permissions USING btree (permission_id);
CREATE INDEX IF NOT EXISTS auth_user_user_permissions_user_id_a95ead1b ON auth_user_user_permissions USING btree (user_id);

CREATE SEQUENCE IF NOT EXISTS django_admin_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS django_admin_log (
    id integer DEFAULT nextval('django_admin_log_id_seq'::regclass) NOT NULL,
    action_time timestamp with time zone NOT NULL,
    object_id text,
    object_repr character varying(200) NOT NULL,
    action_flag smallint NOT NULL,
    change_message text NOT NULL,
    content_type_id integer,
    user_id integer NOT NULL,
    CONSTRAINT django_admin_log_action_flag_check CHECK ((action_flag >= 0)),
    CONSTRAINT django_admin_log_pkey PRIMARY KEY (id),
    CONSTRAINT django_admin_log_content_type_id_c4bce8eb_fk_django_co FOREIGN KEY (content_type_id) REFERENCES django_content_type(id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT django_admin_log_user_id_c564eba6_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED
);

ALTER SEQUENCE django_admin_log_id_seq OWNED BY django_admin_log.id;

CREATE INDEX IF NOT EXISTS django_admin_log_content_type_id_c4bce8eb ON django_admin_log USING btree (content_type_id);
CREATE INDEX IF NOT EXISTS django_admin_log_user_id_c564eba6 ON django_admin_log USING btree (user_id);
