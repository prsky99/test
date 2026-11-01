"""Renewed Admin quality panel on synthetic observations and intercepted HTTP."""
# ruff: noqa: F401
from pathlib import Path
import pytest
from playwright.sync_api import expect
from agent_market.search_quality import recorder
from tests.test_dashboard import dash
from tests.test_front_workflow_browser import browser
from tests.test_admin_next_browser import open_console,sign_in


@pytest.mark.parametrize('width',[390,1440])
def test_quality_menu_displays_private_aggregates(dash,browser,width):
    world,_=dash
    recorder(world.store).record('explore','matched',20,{'stages_ms':{'lexical':2},'counts':{'exact_shortcuts':1}})
    context,page,errors,external=open_console(dash,browser,width)
    try:
        sign_in(page)
        page.evaluate("location.hash='#/public/p07'")
        expect(page.get_by_role('heading',name='탐색·생성 품질',exact=True)).to_be_visible()
        expect(page.locator('#adm-main')).to_contain_text('API 내부 처리시간')
        expect(page.locator('#adm-main')).to_contain_text('20.0 ms')
        page.get_by_role('button',name='현재 지표 조회',exact=True).click()
        expect(page.locator('#adm-main')).to_contain_text('관측 요청')
        assert not errors and not external
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(Path('reports/discovery-quality-phase2-2026-10-26')/('admin-quality-'+str(width)+'.png')),full_page=True)
    finally:context.close()
