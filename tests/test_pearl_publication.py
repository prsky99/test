"""Rendering must never expose transient preview documents at the public entry."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def publication(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'new/publication.py'
    spec = importlib.util.spec_from_file_location('isolated_publication', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'en/assets').mkdir(parents=True)
    (tmp_path / 'en/index.html').write_text('Previous operating entry')
    (tmp_path / 'en/assets/ui.js').write_text('previous')
    (tmp_path / 'en-manifest.json').write_text('{"revision":1}')
    return module, tmp_path


def test_render_failure_keeps_previous_publication(publication):
    module, root = publication
    with pytest.raises(RuntimeError, match='render failed'):
        with module.staged_publication(root) as output:
            output.mkdir()
            (output / 'index.html').write_text('Design preview')
            assert (root / 'en/index.html').read_text() == 'Previous operating entry'
            raise RuntimeError('render failed')
    assert (root / 'en/index.html').read_text() == 'Previous operating entry'
    assert (root / 'en/assets/ui.js').read_text() == 'previous'
    assert (root / 'en-manifest.json').read_text() == '{"revision":1}'
    assert not list(root.glob('.publication-*'))


def test_incomplete_render_is_not_published(publication):
    module, root = publication
    with pytest.raises(ValueError, match='operating entry'):
        with module.staged_publication(root) as output:
            output.mkdir()
            (output / 'index.html').write_text('Design preview')
            (output.parent / 'en-manifest.json').write_text('{}')
    assert (root / 'en/index.html').read_text() == 'Previous operating entry'


def test_only_completed_files_are_published(publication):
    module, root = publication
    completed = '<body data-pearl-entry="overview">Completed operating entry</body>'
    with module.staged_publication(root) as output:
        (output / 'assets').mkdir(parents=True)
        (output / 'index.html').write_text('Design preview')
        assert (root / 'en/index.html').read_text() == 'Previous operating entry'
        (output / 'assets/ui.js').write_text('completed')
        (output / 'index.html').write_text(completed)
        (output.parent / 'en-manifest.json').write_text('{"revision":2}')
        assert (root / 'en/assets/ui.js').read_text() == 'previous'
    assert (root / 'en/index.html').read_text() == completed
    assert (root / 'en/assets/ui.js').read_text() == 'completed'
    assert (root / 'en-manifest.json').read_text() == '{"revision":2}'


def test_builder_uses_staging_and_restores_output_after_failure(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'new/build_en.py'
    monkeypatch.syspath_prepend(str(source.parent))
    spec = importlib.util.spec_from_file_location('isolated_english_builder', source)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    published = tmp_path / 'en'
    published.mkdir()
    (published / 'index.html').write_text('Previous operating entry')
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(builder, 'OUT', published)

    def failed_render():
        assert builder.OUT != published
        builder.OUT.mkdir()
        (builder.OUT / 'index.html').write_text('Design preview')
        assert (published / 'index.html').read_text() == 'Previous operating entry'
        raise RuntimeError('render failed')

    monkeypatch.setattr(builder, '_build', failed_render)
    with pytest.raises(RuntimeError, match='render failed'):
        builder.build()
    assert builder.OUT == published
    assert (published / 'index.html').read_text() == 'Previous operating entry'
