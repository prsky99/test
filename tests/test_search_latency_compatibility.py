"""Latest task gates preserve domain-specific searches during optimization."""
import pytest
from agent_market.concierge.task_capability import matches


@pytest.mark.parametrize('task,allowed', [
    ('weather forecast', False),
    ('weather forecast for construction roofing in Seattle', True),
    ('weather forecast for skiing', False),
])
def test_specialized_forecast_needs_its_actual_domain(task, allowed):
    tool={'name':'get_weather_window','description':
          'Checks 14-day Seattle weather forecast for suitability of exterior construction projects (painting, roofing).'}
    assert matches(task,tool,'a2a') is allowed
