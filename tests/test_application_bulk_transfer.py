"""Bulk transfer keeps native ownership, signatures and typed equality checks."""
from agent_market.application_store_migration import _RowHashes, bulk_catalog_transfer, _limit


def test_bulk_digest_is_bounded_order_independent_and_preserves_multiplicity():
    with bulk_catalog_transfer():
        a,b,c=_RowHashes(),_RowHashes(),_RowHashes()
        for item in (b'a'*32,b'b'*32,b'a'*32):a.append(item)
        for item in (b'b'*32,b'a'*32,b'a'*32):b.append(item)
        for item in (b'a'*32,b'b'*32):c.append(item)
        assert a.values is None and a.digest()==b.digest()!=c.digest()
        assert _limit('MAX_TABLE_ROWS')==20000000
    assert _limit('MAX_TABLE_ROWS')==200000


def test_bulk_copy_real_postgres_full_migration_security_contracts():
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster,_tools,PORT
    from scripts.rehearse_application_migration_postgres import _contracts
    with _private_cluster(_tools()) as cluster:
        def connect():
            return psycopg.connect(host=cluster['socket'],port=PORT,dbname='postgres',user='postgres',
                autocommit=True,sslmode='disable',gssencmode='disable')
        with bulk_catalog_transfer():
            result=_contracts(connect)
        assert all(result['checks'].values()) and result['target_quarantined']
