"""Actual native workspace dialogs retain contrast in both dashboard themes."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect
import pytest

from tests.test_front_workflow_browser import browser
from tests.test_workspace_browser import sign_in, select_space
from tests.test_workspace_execution_api import private_api

REPORT = Path('reports/advancement-finalization-2026-10-18/modal-visual')


def contrast(foreground, background):
    def luminance(color):
        channels = [float(value) / 255 for value in re.findall(r'[\d.]+', color)[:3]]
        assert len(channels) == 3
        channels = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return sum(value * weight for value, weight in zip(channels, (0.2126, 0.7152, 0.0722)))
    a, b = sorted((luminance(foreground), luminance(background)))
    return (b + 0.05) / (a + 0.05)


@pytest.mark.parametrize('theme,width,height', [
    ('light', 1280, 1000), ('dark', 1280, 1000),
], ids=['light-desktop', 'dark-desktop'])
def test_native_private_dialogs_match_current_theme_and_clear_on_session_change(private_api, browser, theme, width, height):
    w = private_api
    context = browser.new_context(offline=True, color_scheme=theme, viewport={'width': width, 'height': height})
    w.page = context.new_page(); errors = []; external = []; observations = []

    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'admin.test':
            external.append(request.url); route.abort(); return
        response = w.client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                    headers=request.headers, content=request.post_data)
        route.fulfill(status=response.status_code, body=response.content,
                      headers={name: value for name, value in response.headers.items()
                               if name not in ('content-length', 'content-encoding', 'transfer-encoding')})

    context.route('**/*', serve)
    w.page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        sign_in(w); select_space(w, w.ws)
        for module, dialog_id in [('AdvancementAdmin', 'advancementAdminDialog'),
                                  ('WorkspaceAgreementAdmin', 'workspaceAgreementDialog')]:
            w.page.evaluate('([module,ws])=>window[module].open(ws)', [module, w.ws['id']])
            dialog = w.page.locator('#' + dialog_id)
            expect(dialog).to_be_visible()
            if module == 'AdvancementAdmin':
                dialog.get_by_role('button', name='Draft support', exact=True).click()
                expect(dialog).to_contain_text('Approved local guidance')
            else:
                expect(dialog).to_contain_text('No verified endpoint claim is available.')
            value = dialog.evaluate('''element => {
              const style = node => {
                const computed = getComputedStyle(node), box = node.getBoundingClientRect();
                return {color:computed.color,background:computed.backgroundColor,
                  rect:{x:box.x,y:box.y,width:box.width,height:box.height},
                  clientWidth:node.clientWidth,scrollWidth:node.scrollWidth};
              };
              const card = element.querySelector('.card');
              return {dialog:style(element),body:style(document.body),card:style(card),
                cardHeading:style(card.querySelector('h3')),cardParagraph:style(card.querySelector('p'))};
            }''')
            value.update(module=module, theme=theme, width=width, height=height)
            value['card_heading_contrast'] = contrast(value['cardHeading']['color'], value['card']['background'])
            value['card_text_contrast'] = contrast(value['cardParagraph']['color'], value['card']['background'])
            observations.append(value)
            REPORT.mkdir(parents=True, exist_ok=True)
            w.page.screenshot(path=str(REPORT / f'{module}-{theme}-{width}.png'), full_page=True)
            (REPORT / f'computed-{theme}-{width}.json').write_text(json.dumps(observations, indent=2) + '\n')
            assert value['dialog']['color'] == value['body']['color']
            assert value['card_heading_contrast'] >= 4.5 and value['card_text_contrast'] >= 4.5
            box = value['dialog']['rect']
            assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
            assert box['y'] >= 0 and box['y'] + box['height'] <= height + 1
            assert abs(box['x'] + box['width'] / 2 - width / 2) < 2
            assert abs(box['y'] + box['height'] / 2 - height / 2) < 2
            assert value['dialog']['scrollWidth'] <= value['dialog']['clientWidth']
            # A transient synthetic session change is handled synchronously;
            # restoring the fixture variable does not restore the closed dialog.
            w.page.evaluate('module=>{const previous=token;token="";window[module].onSession();token=previous;}', module)
            expect(dialog).to_have_count(0)
        assert not errors and not external and not w.calls
    finally:
        context.close()
