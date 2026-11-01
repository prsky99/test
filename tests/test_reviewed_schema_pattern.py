"""One reviewed bounded lexical pattern, never arbitrary provider regex code."""
import pytest
from agent_market.concierge.execution_policy import supported_schema,validate_arguments,ExecutionDenied

PATTERN=r'^[a-z][a-z-]*(\.[A-Za-z-]+)?$'


def spec(pattern=PATTERN,maximum=30):
    return {'inputSchema':{'type':'object','properties':{'category':{
        'type':'string','pattern':pattern,'maxLength':maximum}},'additionalProperties':False}}


@pytest.mark.parametrize('value',['cs','cs.CL','stat.ML','math.PR','a','a-b.X'])
def test_reviewed_short_categories_are_actually_validated(value):
    validate_arguments(spec(),{'category':value})


@pytest.mark.parametrize('value',['','123','CS.CL','cs/CL','cs.','a'*31,'cs.X1'])
def test_invalid_or_oversized_categories_are_not_accepted(value):
    with pytest.raises(ExecutionDenied):validate_arguments(spec(),{'category':value})


@pytest.mark.parametrize('pattern',['^(a+)+$','(a|aa)+$','.*',r'^(\w+)\1$',None,[],{}])
def test_other_regex_profiles_stay_refused(pattern):
    with pytest.raises(ExecutionDenied):supported_schema(spec(pattern))


@pytest.mark.parametrize('maximum',[31,100000,True,None,0,-1])
def test_known_pattern_needs_an_explicit_bounded_integer_limit(maximum):
    with pytest.raises(ExecutionDenied):supported_schema(spec(maximum=maximum))


def test_omitting_optional_category_does_not_strip_its_original_schema():
    supported_schema(spec());validate_arguments(spec(),{})
    assert spec()['inputSchema']['properties']['category']['pattern']==PATTERN
