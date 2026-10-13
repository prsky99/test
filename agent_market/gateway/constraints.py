"""에이전트 제약 정보 추출: 지원 언어, 대상 지역, 통화, 인증 필요 여부.

MCP·x402에는 언어·지역을 적는 표준 필드가 없어서 여러 신호를 모은다 (2026-10 조사 결과):
- 설명문: 쓰인 언어(문자·흔한 단어), 다루는 나라·지역 (예: 브라질 법원, EU 규제, 미국 SEC)
- 레지스트리: 원격 서버가 요구하는 인증 헤더 (Authorization, X-API-Key 등)
- 헬스체크: MCP initialize 응답 401/403 → 인증 필요, 200 → 인증 없이 사용 가능
- 도구 목록(tools/list): language/locale·country/region·currency 파라미터와 그 선택지(enum)·기본값
"""

import re

# 지역 코드 → (표시 이름, 대소문자 구분 패턴, 소문자 패턴)
# "US"/"EU"처럼 짧은 코드는 "contact us" 같은 오탐을 피하려고 대문자로만 인식한다.
REGIONS = {
    "us": ("미국", r"\b(US|USA|U\.S\.A?\.?)\b", r"\b(united states|american|sec filings?|edgar|irs|fda|nasdaq|nyse|us-only)\b"),
    "eu": ("EU·유럽", r"\bEU\b", r"\b(european union|european|europe|esma|gdpr|eur-lex|eurostat|mifid)\b"),
    "gb": ("영국", r"\b(UK|GB)\b", r"\b(united kingdom|british|hmrc|companies house|england|scotland)\b"),
    "br": ("브라질", r"\b(CNPJ|CPF|SEFAZ|INPI|TRT\d*|PIX)\b", r"\b(brazil|brasil|brazilian|receita federal)\b"),
    "in": ("인도", r"\b(GST|NSE|BSE|UPI)\b", r"\b(india|indian|aadhaar)\b"),
    "jp": ("일본", r"\bJP\b", r"\b(japan|japanese)\b|日本"),
    "kr": ("한국", r"\b(KR|DART|KOSPI|KOSDAQ)\b", r"\b(korea|korean)\b|한국|국내"),
    "cn": ("중국", r"\bCN\b", r"\b(china|chinese)\b|中国"),
    "de": ("독일", r"\bDE\b", r"\b(germany|german|deutschland)\b"),
    "fr": ("프랑스", r"\bFR\b", r"\b(france|french)\b"),
    "ch": ("스위스", r"\bCH\b", r"\b(switzerland|swiss)\b"),
    "ca": ("캐나다", r"\bCA\b(?!\s*\d)", r"\b(canada|canadian)\b"),
    "au": ("호주", r"\b(AU|ASX)\b", r"\b(australia|australian)\b"),
    "latam": ("중남미", r"\b(MX|AR|CL|CO|PE)\b", r"\b(mexico|mexican|latam|latin america|argentina|chile|colombia|peru)\b"),
    "africa": ("아프리카", r"\b(NG|KE|ZA)\b", r"\b(nigeria|kenya|south africa|africa|african)\b"),
    "sea": ("동남아", r"\b(SG|ID|VN|TH|PH|MY)\b(?=[\s,).]|$)", r"\b(singapore|indonesia|vietnam|thailand|philippines|malaysia)\b"),
    "me": ("중동", r"\b(UAE|KSA)\b", r"\b(dubai|saudi|qatar|abu dhabi|emirates)\b"),
}
_REGION_PATTERNS = {code: (re.compile(cs), re.compile(ci, re.I)) for code, (_, cs, ci) in REGIONS.items()}
# 도구 파라미터 값(ISO 국가 코드 등) → 지역 코드
_COUNTRY_TO_REGION = {
    "us": "us", "usa": "us", "gb": "gb", "uk": "gb", "br": "br", "in": "in", "jp": "jp", "kr": "kr", "cn": "cn",
    "de": "de", "fr": "fr", "ch": "ch", "ca": "ca", "au": "au", "eu": "eu", "mx": "latam", "ar": "latam",
    "cl": "latam", "co": "latam", "pe": "latam", "ng": "africa", "ke": "africa", "za": "africa", "sg": "sea",
    "id": "sea", "vn": "sea", "th": "sea", "ph": "sea", "my": "sea", "ae": "me", "sa": "me",
    "es": "eu", "it": "eu", "nl": "eu", "pl": "eu", "pt": "eu", "se": "eu", "at": "eu", "be": "eu", "ie": "eu",
}

LANGUAGES = {"en": "영어", "ko": "한국어", "ja": "일본어", "zh": "중국어", "es": "스페인어", "pt": "포르투갈어", "fr": "프랑스어",
             "de": "독일어", "it": "이탈리아어", "ru": "러시아어", "ar": "아랍어", "hi": "힌디어", "th": "태국어", "pl": "폴란드어",
             "nl": "네덜란드어", "tr": "터키어", "vi": "베트남어", "id": "인도네시아어"}
_LANG_NAMES = {"english": "en", "eng": "en", "korean": "ko", "kor": "ko", "japanese": "ja", "jpn": "ja", "chinese": "zh",
               "zho": "zh", "spanish": "es", "spa": "es", "portuguese": "pt", "por": "pt", "french": "fr", "fra": "fr",
               "german": "de", "deu": "de", "italian": "it", "ita": "it", "russian": "ru", "rus": "ru", "arabic": "ar",
               "hindi": "hi", "thai": "th", "polish": "pl", "dutch": "nl", "turkish": "tr", "vietnamese": "vi"}
_LATIN_STOPWORDS = {
    "pt": {"de", "para", "consulta", "não", "dados", "com", "uma", "dos", "das", "processual", "empresa", "busca"},
    "es": {"para", "del", "los", "las", "con", "una", "consulta", "búsqueda", "datos", "empresa"},
    "de": {"und", "der", "die", "das", "mit", "für", "von", "ist", "eine"},
    "fr": {"les", "des", "pour", "avec", "une", "données", "recherche", "est"},
    "it": {"della", "degli", "per", "con", "una", "dati", "ricerca"},
    "en": {"the", "and", "for", "with", "your", "from", "to", "of", "get", "search", "data", "api"},
}
AUTH_HEADERS = {"authorization", "x-api-key", "x-api-token", "x-authorization-token", "api-key", "x-auth-token"}


def detect_language(text: str) -> str | None:
    """설명문이 쓰인 언어 (2글자 코드). 판단이 어려우면 None."""
    if re.search(r"[가-힣]", text):
        return "ko"
    if re.search(r"[぀-ヿ]", text):
        return "ja"
    if re.search(r"[一-鿿]", text):
        return "zh"
    if re.search(r"[Ѐ-ӿ]", text):
        return "ru"
    if re.search(r"[؀-ۿ]", text):
        return "ar"
    if re.search(r"[฀-๿]", text):
        return "th"
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    words = set(re.findall(r"[a-zà-ÿ]+", text.lower()))
    scores = {lang: len(words & sw) for lang, sw in _LATIN_STOPWORDS.items()}
    best = max(scores, key=scores.get)
    if best != "en" and scores[best] >= 2 and scores[best] >= scores["en"]:
        return best
    return "en" if scores["en"] else None


def regions_in_text(text: str) -> list[str]:
    """설명문에 나오는 나라·지역 (데이터 대상 지역). 특정 지역이 없으면 빈 목록 = 전 세계 공통."""
    return sorted(code for code, (cs, ci) in _REGION_PATTERNS.items() if cs.search(text) or ci.search(text))


def normalize_language(value) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lower().replace("_", "-")
    if v in _LANG_NAMES:
        return _LANG_NAMES[v]
    base = v.split("-")[0]
    return base if base in LANGUAGES else None


def normalize_region(value) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in REGIONS:
        return v
    return _COUNTRY_TO_REGION.get(v)


def declared_auth(remotes: list[dict] | None) -> bool | None:
    """레지스트리에 선언된 원격 서버 헤더로 본 인증 필요 여부. 정보가 없으면 None."""
    if not remotes:
        return None
    for r in remotes:
        for h in r.get("headers") or []:
            name = str(h.get("name", "")).lower()
            if h.get("isRequired") and (h.get("isSecret") or name in AUTH_HEADERS):
                return True
    return False if any("headers" in r for r in remotes) else None


_PARAM_LANG = re.compile(r"^(language|lang|locale|hl|target_?lang(uage)?|source_?lang(uage)?|output_?language|response_?language|languages?)$")
_PARAM_REGION = re.compile(r"^(country|country_?code|countrycode|region|market|gl|jurisdiction|country_?iso)$")
_PARAM_CURRENCY = re.compile(r"^(currency|currency_?code|vs_?currency|fiat)$")
_PARAM_TZ = re.compile(r"^(timezone|tz|time_?zone)$")


def from_tools(tools: list[dict]) -> dict:
    """tools/list 결과에서 지원 언어·지역·통화를 뽑는다. 선택지(enum)가 있으면 그 목록, 없으면 기본값만."""
    langs, regions, currencies, has_tz, has_lang_param, has_region_param = set(), set(), set(), False, False, False
    for tool in tools or []:
        props = ((tool.get("inputSchema") or {}).get("properties") or {}) if isinstance(tool, dict) else {}
        for name, schema in props.items():
            if not isinstance(schema, dict):
                continue
            key = name.lower()
            values = list(schema.get("enum") or []) + ([schema["default"]] if schema.get("default") else [])
            if _PARAM_LANG.match(key):
                has_lang_param = True
                langs.update(filter(None, (normalize_language(v) for v in values)))
            elif _PARAM_REGION.match(key):
                has_region_param = True
                regions.update(filter(None, (normalize_region(v) for v in values)))
            elif _PARAM_CURRENCY.match(key):
                currencies.update(str(v).upper() for v in values if isinstance(v, str) and 2 < len(v) <= 5)
            elif _PARAM_TZ.match(key):
                has_tz = True
    return {
        "languages": sorted(langs), "regions": sorted(regions), "currencies": sorted(currencies)[:20],
        "language_param": has_lang_param, "region_param": has_region_param, "timezone_param": has_tz,
        "tool_count": len(tools or []),
        "tool_names": [t.get("name") for t in (tools or [])[:40] if isinstance(t, dict) and t.get("name")],
    }


def pack(codes) -> str | None:
    """DB 저장 형식: ',ko,en,' (LIKE '%,ko,%'로 검색). 없으면 None."""
    codes = [c for c in dict.fromkeys(codes) if c]
    return "," + ",".join(codes) + "," if codes else None


def unpack(value: str | None) -> list[str]:
    return [c for c in (value or "").strip(",").split(",") if c]
