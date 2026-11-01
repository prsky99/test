"""Explicit native full-text index for scalable PostgreSQL catalog reads."""
PROFILE='agentcon-postgres-simple-unaccent-gin-v1'
DOCUMENT='agentcon_search.lexical_document'
BODY=" SELECT to_tsvector('simple'::regconfig,public.unaccent('public.unaccent'::regdictionary,COALESCE($1,'')||' '||COALESCE($2,''))) "
QUERY="WITH ac_query AS (SELECT websearch_to_tsquery('simple'::regconfig,public.unaccent('public.unaccent'::regdictionary,%s)) AS terms) "
# Lexical relevance must stay comparable to the quality terms the callers add
# (eval_score/100 and the 0.5 trial bonus), as SQLite FTS5 bm25 did. A name
# match weighs more than description text (A vs D), cover density is divided by
# document length so catalogs listing every capability do not win, and ts_rank
# rewards covering more of the query's terms. Both are bounded to 0..1 (32).
WEIGHTED=("setweight(to_tsvector('simple'::regconfig,public.unaccent('public.unaccent'::regdictionary,COALESCE(f.name,''))),'A')"
          "||setweight(to_tsvector('simple'::regconfig,public.unaccent('public.unaccent'::regdictionary,COALESCE(f.description,''))),'D')")
MATCH_PREFIX=(QUERY+" , matches AS (SELECT f.rowid AS id,-ts_rank_cd(("+WEIGHTED+"),q.terms,2|32)*2-ts_rank(("+WEIGHTED+"),q.terms,32)*4 AS rank "
              "FROM public.resources_fts f CROSS JOIN ac_query q WHERE agentcon_search.lexical_document(f.name,f.description) @@ q.terms) ")
# A count reads no rank. Matching through the GIN index alone spares recomputing every listing's
# text vector: the report count went from a 3,852-row nested loop at 0.26 ms a row (1.06 s) to 58 ms.
COUNT_PREFIX=(QUERY+" , matches AS MATERIALIZED (SELECT f.rowid AS id FROM public.resources_fts f CROSS JOIN ac_query q "
              "WHERE agentcon_search.lexical_document(f.name,f.description) @@ q.terms) ")
LEGACY_PREFIX="WITH matches AS (SELECT (value->>0)::bigint AS id,(value->>1)::double precision AS rank FROM json_array_elements(%s::json)) "


def available(store):
    with store.tx(readonly=True):
        if store._execute("SELECT to_regclass('agentcon_search.lexical_configuration')").fetchone()[0] is None:return False
        profile=store._execute('SELECT profile FROM agentcon_search.lexical_configuration WHERE id=1').fetchone()
        function=store._execute("SELECT p.prosrc,p.provolatile,p.prosecdef FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='agentcon_search' AND p.proname='lexical_document'").fetchall()
        index=store._execute("SELECT i.indisvalid,pg_get_indexdef(i.indexrelid) FROM pg_index i WHERE i.indexrelid=to_regclass('public.resources_fts_native_gin')").fetchone()
        if (not profile or profile[0]!=PROFILE or len(function)!=1 or tuple(function[0])!=(BODY,'i',False)
                or not index or not index[0] or 'USING gin (agentcon_search.lexical_document(name, description))' not in index[1]):
            from .application_store_postgres import ApplicationStoreError
            raise ApplicationStoreError('schema_profile_mismatch')
        return True


def install(store):
    with store.tx():
        if store._execute("SELECT to_regclass('agentcon_search.lexical_configuration')").fetchone()[0] is not None:
            raise ValueError('native_lexical_already_provisioned')
        store._execute("SET LOCAL statement_timeout TO '900s'")
        store._execute("SET LOCAL maintenance_work_mem TO '512MB'")
        store._execute('CREATE EXTENSION IF NOT EXISTS unaccent')
        store._execute('CREATE SCHEMA IF NOT EXISTS agentcon_search')
        store._execute('REVOKE ALL ON SCHEMA agentcon_search FROM PUBLIC')
        store._execute('CREATE FUNCTION agentcon_search.lexical_document(text,text) RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$'+BODY+'$$')
        store._execute('CREATE INDEX resources_fts_native_gin ON public.resources_fts USING gin(agentcon_search.lexical_document(name,description))')
        store._execute('CREATE TABLE agentcon_search.lexical_configuration(id BIGINT PRIMARY KEY CHECK(id=1),profile TEXT NOT NULL)')
        store._execute('INSERT INTO agentcon_search.lexical_configuration VALUES(1,%s)',(PROFILE,))
        store._execute('ANALYZE public.resources_fts')
    store._native_lexical=available(store)
    return {'profile':PROFILE,'native_index':store._native_lexical,'whole_corpus_projection':False}


def ids(store,match,where,params,limit):
    # WHERE is built by reviewed repository code; all user values remain bound.
    sql=QUERY+'''SELECT r.id FROM public.resources_fts f JOIN public.resources r ON r.id=f.rowid
        CROSS JOIN ac_query q WHERE agentcon_search.lexical_document(f.name,f.description) @@ q.terms AND '''+where+'''
        ORDER BY ts_rank_cd(agentcon_search.lexical_document(f.name,f.description),q.terms) DESC,r.id
        LIMIT %s'''
    return [row[0] for row in store._execute(sql,[match,*params,limit]).fetchall()]
