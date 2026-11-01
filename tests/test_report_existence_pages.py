"""Duplicate-report checks read every report of a protocol in pages under the native row limit."""
import pytest

KEY = b'a' * 32


@pytest.fixture(scope='module')
def store():
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, _tools, PORT
    from agent_market.storage_adapter import open_store
    with _private_cluster(_tools()) as cluster:
        connection = psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        value = open_store('postgresql', connection=connection, initialize=True, workflow_key=KEY)
        # More reports of one protocol than a single native query may return (MAX_ROWS=2000).
        # Each fixture row carries its own reservation, as the creation trigger requires.
        connection.execute("INSERT INTO test_report_subject_claims(subject_key,report_id) SELECT 'k'||i,NULL FROM generate_series(1,2101) AS i")
        connection.execute('''INSERT INTO agent_test_reports(creation_subject_key,title,slug,kind,source,agent_name,agent_url,category,
            test_method,summary,content_md,pros,cons,created_at,updated_at)
            SELECT 'k'||i,'Report '||i,'report-'||i,'mcp','fixture','Agent '||i,
              CASE WHEN i=2101 THEN 'HTTPS://Last.Example.:443/mcp' ELSE 'https://host-'||i||'.example/mcp' END,
              'web_search','manual','s','c','[]','[]',1,1 FROM generate_series(1,2101) AS i''')
        try:
            yield value
        finally:
            value.close(); connection.close()


def test_existing_report_beyond_the_first_pages_is_found(store):
    from agent_market.report_creation import find_existing, subject
    found = find_existing(store, subject(store, None, 'mcp', 'https://last.example/mcp'))  # canonical match
    assert found == store._connection.execute("SELECT id FROM agent_test_reports WHERE slug='report-2101'").fetchone()[0]


def test_absent_subject_reads_all_pages_without_a_result_limit(store):
    from agent_market.report_creation import find_existing, subject
    assert find_existing(store, subject(store, None, 'mcp', 'https://absent.example/mcp')) is None
    assert find_existing(store, subject(store, None, 'a2a', 'https://host-5.example/mcp')) is None  # other protocol


def test_admin_existence_endpoint_no_longer_rejects_large_catalogs(store):
    assert store.find_existing_test_report(kind='mcp', agent_url='https://host-1500.example/mcp') is not None
