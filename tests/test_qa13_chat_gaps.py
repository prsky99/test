"""Improvement check round 13: requested languages limit translation listings."""
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_qa12_chat_gaps import tool_guide


def add_translators(add, now):
    add('Bhasini Indic Languages', report_at=now - 1, category='language_translation',
        description='Indic MCP: transliterate into all 22 Indian languages, convert scripts, keymaps.',
        usage_guide=tool_guide('translate', 'Translates the meaning of text between English and the 22 scheduled languages of India.', 'text', 'target'))
    add('Faceabot Translate', report_at=now - 50, category='language_translation',
        description='Translate text or a document into about 100 languages.',
        usage_guide=tool_guide('translate_text', 'Translates text into another language. About 100 languages.', 'text', 'target'))


def names_for(client, message):
    body = client.post('/chat', json={'message': message}).json()
    return [item['name'] for item in body['data']['recommendations']], body['reply']


def test_regional_translator_does_not_serve_other_languages(catalog):
    _, _, client, add, now = catalog
    add_translators(add, now)
    for message in ('translate an English document into Korean', 'translate a Korean contract', 'translate to Spanish',
                    '\uc2a4\ud398\uc778\uc5b4\ub85c \ubc88\uc5ed\ud574\uc918'):
        names, reply = names_for(client, message)
        assert names and names[0] == 'Faceabot Translate', (message, reply)
        assert 'Bhasini Indic Languages' not in names, message


def test_regional_translator_still_serves_its_languages():
    from agent_market.concierge.selection import _regional_languages_cover
    indic = 'transliterate into all 22 indian languages'
    assert _regional_languages_cover({'translate', 'hindi'}, indic)
    assert _regional_languages_cover({'translate', 'english'}, indic)
    assert _regional_languages_cover({'translate'}, indic)
    assert not _regional_languages_cover({'translate', 'korean'}, indic)
    assert _regional_languages_cover({'translate', 'korean'}, 'translate text into about 100 languages')
