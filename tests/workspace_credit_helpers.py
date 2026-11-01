"""Confirm the credit dialog that precedes every credit-using workspace save."""
import re


def save_with_credit(page):
    from playwright.sync_api import expect
    if page.locator('#human-save').count():
        page.locator('#human-save').click()
        expect(page.locator('#human-confirm')).to_be_visible()
        expect(page.locator('#human-confirm-check')).not_to_be_checked()
        page.locator('#human-confirm-check').check()
        page.locator('#human-confirm-yes').click()
        return
    free = re.search(r'uses 0 credit', page.locator('#credit-quote').text_content() or '')
    page.locator('#save').click()
    if free:
        expect(page.locator('#credit-dialog')).to_be_hidden()
        return
    expect(page.locator('#credit-dialog')).to_be_visible()
    expect(page.locator('#credit-dialog-copy')).to_contain_text('Your balance changes from')
    page.locator('#credit-dialog-confirm').click()
