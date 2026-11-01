"""Regeneration retains the reviewed template finder and stable refresh behavior."""
from pathlib import Path
import importlib.util
import shutil
import pytest


def test_library_survives_isolated_rebuild(tmp_path,monkeypatch):
    project=Path(__file__).resolve().parents[1];source=project/'new'
    isolated=tmp_path/'project';copy=isolated/'new';copy.mkdir(parents=True)
    # Read fixtures from the repository; build only into a disposable project.
    for name in ('html','live-assets'):
        shutil.copytree(source/name,copy/name)
    shutil.copy2(source/'shared-ui.js',copy/'shared-ui.js')
    (isolated/'agent_market/concierge').mkdir(parents=True)
    shutil.copy2(project/'agent_market/concierge/front.py',isolated/'agent_market/concierge/front.py')
    monkeypatch.syspath_prepend(str(source))
    spec=importlib.util.spec_from_file_location('isolated_library_builder',source/'build_en.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'ROOT',copy);monkeypatch.setattr(module,'OUT',copy/'en');module.build()
    for name in ('index.html','workflows.html'):
        html=(copy/'en'/name).read_text();assert 'assets/workflow-library.js?v=template-discovery-20261025-r3' in html
    compiled=(copy/'en/assets/pearl-ui.js').read_text();runtime=(copy/'en/assets/operating.js').read_text()
    assert 'pearlWorkflowFind' in compiled and 'pearlWorkflowSelect' not in compiled
    assert 'window.selectFrontTemplatePage' in runtime
    assert 'if (templatesChanged) renderFrontTemplates()' in runtime
    assert (copy/'en/assets/workflow-library.js').read_bytes()==(source/'live-assets/workflow-library.js').read_bytes()
