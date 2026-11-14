"""PM 11-15: storage pointers set inside one test never reach the next one (tests/conftest.py guard)."""
import os


def test_a_test_that_sets_production_storage_directly():
    os.environ['APPLICATION_STORE_BACKEND'] = 'postgresql'
    os.environ['APPLICATION_POSTGRES_DSN_FILE'] = '/nonexistent/application.dsn'


def test_the_next_test_does_not_inherit_it():
    assert 'APPLICATION_STORE_BACKEND' not in os.environ
    assert 'APPLICATION_POSTGRES_DSN_FILE' not in os.environ
