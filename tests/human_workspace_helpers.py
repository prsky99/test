"""Shared actual-user navigation for the guided Workspace regression suites."""
from playwright.sync_api import expect


def library(page):
    page.locator('#human-nav-library').click()


def load_first(page):
    library(page)
    page.locator('#workflow-cards .workflow-card').first.click()
    page.wait_for_function("()=>!document.getElementById('human-builder').hidden||document.getElementById('discard-dialog').open")
    if not page.locator('#discard-dialog').is_visible():
        expect(page.locator('#human-builder')).to_be_visible()


def manual(page):
    page.locator('#human-nav-create').click()
    page.locator('#human-manual').click()
    expect(page.locator('#step-editor')).to_be_visible()


def edit_steps(page):
    page.get_by_role('button',name='View or edit steps',exact=True).click()
    expect(page.locator('#step-editor')).to_be_visible()


def confirm(page):
    expect(page.locator('#human-confirm')).to_be_visible()
    page.locator('#human-confirm-check').check()
    page.locator('#human-confirm-yes').click()


def expert(page):
    root=page.locator('.human-expert')
    if not root.evaluate('(d)=>d.open'):root.locator(':scope > summary').click()


def new_idea(page):
    page.locator('#human-nav-create').click()
    page.locator('#human-manual').click()
