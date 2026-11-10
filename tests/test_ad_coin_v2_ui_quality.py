"""AD Coin public and operator screens meet the quality bar (PM 11-11): measured in Chromium at 1280 and 375,
light and dark, for every screen state. Any regression fails. Parts sized by the shared design system
(header brand, theme toggle, checkbox label) are counted apart and reported to the design system owners."""
import pytest

pytest.importorskip("playwright.sync_api")

from scripts.ui_quality_audit import COUNTED, STATES, local_audit, summary  # noqa: E402


def test_every_ad_coin_screen_state_has_zero_errors_and_layout_faults():
    results = local_audit()
    assert len(results) == len(STATES) * 4
    total = summary(results)
    faults = {key: total[key] for key in COUNTED if key != "design_system_small" and total[key]}
    examples = {r["label"] + "/" + r["viewport"] + "/" + r["scheme"]: {k: r[k] for k in r if k.endswith("examples") and r[k]}
                for r in results if any(r[k] for k in COUNTED if k != "design_system_small")}
    assert not faults, (faults, examples)
