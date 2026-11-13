"""Every ISO 3166-1 country, by name, mapped to a region code of gateway/constraints.REGIONS (PM 11-14 04:0x).

Adding one country at a time kept leaking (11-14: "Cambio Uruguay" was not seen as limited to one country, so it
led a worldwide geocoding task). Each row is: ISO alpha-2 code, the REGIONS code it belongs to, and the names a
listing uses for it (short name, official or older names, common aliases), lower case, "|" between them.

- A country inside an existing group (EU member, Latin America, Africa, South-East Asia, Middle East) maps to
  that group; smaller European countries outside the EU join "eu" too, whose display name is "EU·유럽".
- A country without a group gets its own code; OWN_REGIONS gives its display name.
- Names only, never demonyms or language adjectives ("Spanish translation", "Russian text" are not places).
- A name that is also a common word or a US state needs a qualifier (AMBIGUOUS): "georgia" (the state),
  "jordan" (a person), "chad", "guinea" (guinea pig), "jersey", "turkey" (the bird), "niger", "man", "wales" (New South Wales).
"""

COUNTRIES = (
    # existing own codes
    ('us', 'us', 'united states of america|united states'),
    ('gb', 'gb', 'united kingdom|great britain|england|scotland|northern ireland|isle of man'),
    ('br', 'br', 'brazil|brasil'),
    ('in', 'in', 'india'),
    ('jp', 'jp', 'japan'),
    ('kr', 'kr', 'south korea|republic of korea'),
    ('cn', 'cn', 'china|people\'s republic of china'),
    ('de', 'de', 'germany|deutschland'),
    ('fr', 'fr', 'france'),
    ('ch', 'ch', 'switzerland'),
    ('ca', 'ca', 'canada'),
    ('au', 'au', 'australia'),
    ('no', 'no', 'norway'),
    ('tr', 'tr', 'türkiye|turkiye|republic of turkey|republic of türkiye'),
    ('il', 'il', 'israel'),
    ('nz', 'nz', 'new zealand|aotearoa'),
    # EU members and the rest of Europe ("EU·유럽")
    ('at', 'eu', 'austria'), ('be', 'eu', 'belgium'), ('bg', 'eu', 'bulgaria'), ('hr', 'eu', 'croatia|hrvatska'),
    ('cy', 'eu', 'cyprus'), ('cz', 'eu', 'czechia|czech republic'), ('dk', 'eu', 'denmark'),
    ('ee', 'eu', 'estonia'), ('fi', 'eu', 'finland'), ('gr', 'eu', 'greece|hellenic republic'),
    ('hu', 'eu', 'hungary'), ('ie', 'eu', 'ireland|republic of ireland|éire'), ('it', 'eu', 'italy|italia'),
    ('lv', 'eu', 'latvia'), ('lt', 'eu', 'lithuania'), ('lu', 'eu', 'luxembourg'), ('mt', 'eu', 'malta'),
    ('nl', 'eu', 'netherlands|the netherlands|holland'), ('pl', 'eu', 'poland|polska'),
    ('pt', 'eu', 'portugal'), ('ro', 'eu', 'romania'), ('sk', 'eu', 'slovakia|slovak republic'),
    ('si', 'eu', 'slovenia'), ('es', 'eu', 'spain|españa|espana'), ('se', 'eu', 'sweden|sverige'),
    ('al', 'eu', 'albania'), ('ad', 'eu', 'andorra'), ('ba', 'eu', 'bosnia and herzegovina|bosnia & herzegovina|bosnia'),
    ('xk', 'eu', 'kosovo'), ('li', 'eu', 'liechtenstein'), ('mk', 'eu', 'north macedonia|macedonia'),
    ('md', 'eu', 'moldova|republic of moldova'), ('mc', 'eu', 'monaco'), ('me', 'eu', 'montenegro'),
    ('sm', 'eu', 'san marino'), ('rs', 'eu', 'serbia'), ('va', 'eu', 'vatican city|holy see'),
    ('fo', 'eu', 'faroe islands'), ('gi', 'eu', 'gibraltar'),
    # Latin America and the Caribbean
    ('mx', 'latam', 'mexico|méxico|united mexican states'), ('gt', 'latam', 'guatemala'), ('bz', 'latam', 'belize'),
    ('sv', 'latam', 'el salvador'), ('hn', 'latam', 'honduras'), ('ni', 'latam', 'nicaragua'),
    ('cr', 'latam', 'costa rica'), ('pa', 'latam', 'panama|panamá'), ('cu', 'latam', 'cuba'),
    ('do', 'latam', 'dominican republic|república dominicana'), ('ht', 'latam', 'haiti'), ('jm', 'latam', 'jamaica'),
    ('tt', 'latam', 'trinidad and tobago|trinidad & tobago'), ('bb', 'latam', 'barbados'), ('bs', 'latam', 'bahamas'),
    ('ag', 'latam', 'antigua and barbuda'), ('dm', 'latam', 'dominica'), ('gd', 'latam', 'grenada'),
    ('kn', 'latam', 'saint kitts and nevis|st kitts'), ('lc', 'latam', 'saint lucia|st lucia'),
    ('vc', 'latam', 'saint vincent and the grenadines'), ('aw', 'latam', 'aruba'), ('cw', 'latam', 'curaçao|curacao'),
    ('pr', 'latam', 'puerto rico'), ('ky', 'latam', 'cayman islands'), ('ar', 'latam', 'argentina'),
    ('bo', 'latam', 'bolivia'), ('cl', 'latam', 'chile'), ('co', 'latam', 'colombia'), ('ec', 'latam', 'ecuador'),
    ('gy', 'latam', 'guyana'), ('py', 'latam', 'paraguay'), ('pe', 'latam', 'peru|perú'), ('sr', 'latam', 'suriname'),
    ('uy', 'latam', 'uruguay'), ('ve', 'latam', 'venezuela'),
    # Africa
    ('dz', 'africa', 'algeria'), ('ao', 'africa', 'angola'), ('bj', 'africa', 'benin'), ('bw', 'africa', 'botswana'),
    ('bf', 'africa', 'burkina faso'), ('bi', 'africa', 'burundi'), ('cv', 'africa', 'cabo verde|cape verde'),
    ('cm', 'africa', 'cameroon'), ('cf', 'africa', 'central african republic'), ('td', 'africa', 'republic of chad'),
    ('km', 'africa', 'comoros'), ('cg', 'africa', 'republic of the congo|congo-brazzaville|congo'),
    ('cd', 'africa', 'democratic republic of the congo|dr congo|drc congo|congo-kinshasa'),
    ('ci', 'africa', 'côte d\'ivoire|cote d\'ivoire|ivory coast'), ('dj', 'africa', 'djibouti'), ('eg', 'africa', 'egypt'),
    ('gq', 'africa', 'equatorial guinea'), ('er', 'africa', 'eritrea'), ('sz', 'africa', 'eswatini|swaziland'),
    ('et', 'africa', 'ethiopia'), ('ga', 'africa', 'gabon'), ('gm', 'africa', 'the gambia|gambia'),
    ('gh', 'africa', 'ghana'), ('gn', 'africa', 'republic of guinea|guinea-conakry'), ('gw', 'africa', 'guinea-bissau'),
    ('ke', 'africa', 'kenya'), ('ls', 'africa', 'lesotho'), ('lr', 'africa', 'liberia'), ('ly', 'africa', 'libya'),
    ('mg', 'africa', 'madagascar'), ('mw', 'africa', 'malawi'), ('ml', 'africa', 'mali'), ('mr', 'africa', 'mauritania'),
    ('mu', 'africa', 'mauritius'), ('ma', 'africa', 'morocco'), ('mz', 'africa', 'mozambique'),
    ('na', 'africa', 'namibia'), ('ne', 'africa', 'republic of niger'), ('ng', 'africa', 'nigeria'),
    ('rw', 'africa', 'rwanda'), ('st', 'africa', 'são tomé and príncipe|sao tome and principe'),
    ('sn', 'africa', 'senegal'), ('sc', 'africa', 'seychelles'), ('sl', 'africa', 'sierra leone'),
    ('so', 'africa', 'somalia'), ('za', 'africa', 'south africa'), ('ss', 'africa', 'south sudan'),
    ('sd', 'africa', 'sudan'), ('tz', 'africa', 'tanzania'), ('tg', 'africa', 'togo'), ('tn', 'africa', 'tunisia'),
    ('ug', 'africa', 'uganda'), ('zm', 'africa', 'zambia'), ('zw', 'africa', 'zimbabwe'),
    # South-East Asia
    ('sg', 'sea', 'singapore'), ('id', 'sea', 'indonesia'), ('vn', 'sea', 'vietnam|viet nam'),
    ('th', 'sea', 'thailand'), ('ph', 'sea', 'philippines'), ('my', 'sea', 'malaysia'),
    ('mm', 'sea', 'myanmar|burma'), ('kh', 'sea', 'cambodia'), ('la', 'sea', 'laos|lao pdr'),
    ('bn', 'sea', 'brunei|brunei darussalam'), ('tl', 'sea', 'timor-leste|east timor'),
    # Middle East
    ('ae', 'me', 'united arab emirates'), ('sa', 'me', 'saudi arabia'), ('qa', 'me', 'qatar'), ('kw', 'me', 'kuwait'),
    ('bh', 'me', 'bahrain'), ('om', 'me', 'oman'), ('ye', 'me', 'yemen'),
    ('jo', 'me', 'kingdom of jordan|hashemite kingdom of jordan'), ('lb', 'me', 'lebanon'), ('sy', 'me', 'syria'),
    ('iq', 'me', 'iraq'), ('ir', 'me', 'iran|islamic republic of iran'), ('ps', 'me', 'palestine|west bank|gaza'),
    # countries with their own code (display names in OWN_REGIONS)
    ('ru', 'ru', 'russia|russian federation'), ('ua', 'ua', 'ukraine'), ('by', 'by', 'belarus'),
    ('is', 'is', 'iceland'), ('ge', 'ge', 'republic of georgia|sakartvelo'), ('am', 'am', 'armenia'),
    ('az', 'az', 'azerbaijan'), ('kz', 'kz', 'kazakhstan'), ('uz', 'uz', 'uzbekistan'), ('kg', 'kg', 'kyrgyzstan'),
    ('tj', 'tj', 'tajikistan'), ('tm', 'tm', 'turkmenistan'), ('mn', 'mn', 'mongolia'),
    ('tw', 'tw', 'taiwan'), ('hk', 'hk', 'hong kong'), ('mo', 'mo', 'macau|macao'),
    ('kp', 'kp', 'north korea|democratic people\'s republic of korea'), ('pk', 'pk', 'pakistan'),
    ('bd', 'bd', 'bangladesh'), ('lk', 'lk', 'sri lanka'), ('np', 'np', 'nepal'), ('bt', 'bt', 'bhutan'),
    ('mv', 'mv', 'maldives'), ('af', 'af', 'afghanistan'), ('pg', 'pg', 'papua new guinea'), ('fj', 'fj', 'fiji'),
    ('ws', 'ws', 'samoa'), ('to', 'to', 'tonga'), ('vu', 'vu', 'vanuatu'), ('sb', 'sb', 'solomon islands'),
    ('ki', 'ki', 'kiribati'), ('fm', 'fm', 'micronesia'), ('mh', 'mh', 'marshall islands'), ('pw', 'pw', 'palau'),
    ('nr', 'nr', 'nauru'), ('tv', 'tv', 'tuvalu'),
)

OWN_REGIONS = {
    'ru': '러시아', 'ua': '우크라이나', 'by': '벨라루스', 'is': '아이슬란드', 'ge': '조지아', 'am': '아르메니아',
    'az': '아제르바이잔', 'kz': '카자흐스탄', 'uz': '우즈베키스탄', 'kg': '키르기스스탄', 'tj': '타지키스탄',
    'tm': '투르크메니스탄', 'mn': '몽골', 'tw': '대만', 'hk': '홍콩', 'mo': '마카오', 'kp': '북한', 'pk': '파키스탄',
    'bd': '방글라데시', 'lk': '스리랑카', 'np': '네팔', 'bt': '부탄', 'mv': '몰디브', 'af': '아프가니스탄',
    'pg': '파푸아뉴기니', 'fj': '피지', 'ws': '사모아', 'to': '통가', 'vu': '바누아투', 'sb': '솔로몬 제도',
    'ki': '키리바시', 'fm': '미크로네시아', 'mh': '마셜 제도', 'pw': '팔라우', 'nr': '나우루', 'tv': '투발루',
}

# Bare names left out on purpose; the row lists a qualified form instead.
AMBIGUOUS = frozenset('georgia jordan chad guinea niger jersey guernsey turkey man wales'.split())

# Places whose name contains a country but are not that country: removed from the text before matching.
# Only these phrases: "new" before a country is usually an adjective ("a new French customer", "new Swiss permits").
NOT_COUNTRY = r'\bnew\s+(?:mexico|england|south\s+wales|caledonia)\b'
