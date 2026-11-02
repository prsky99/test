# 요청별 생성 결과

실제 맥미니 모델과 격리 고객 API에서 실행한 최종 결과. 수정 전 원문은 before/results.json, 최종 원문은 final/results.json에 보관했습니다.

## docs_two

Find public Python documentation using exactly two steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.581초, 모델 1회.
- step_1 · docs.search.v1 · public Python documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## docs_five

Find JavaScript documentation using exactly five steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.326초, 모델 1회.
- step_1 · docs.search.v1 · JavaScript documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1
- step_3 · docs.search.v1 · 이전 step_2의 첫 결과 title · 결과 수 1
- step_4 · docs.search.v1 · 이전 step_3의 첫 결과 title · 결과 수 1
- step_5 · docs.search.v1 · 이전 step_4의 첫 결과 title · 결과 수 1

## docs_ten

Find Rust documentation using exactly ten steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.321초, 모델 1회.
- step_1 · docs.search.v1 · Rust documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1
- step_3 · docs.search.v1 · 이전 step_2의 첫 결과 title · 결과 수 1
- step_4 · docs.search.v1 · 이전 step_3의 첫 결과 title · 결과 수 1
- step_5 · docs.search.v1 · 이전 step_4의 첫 결과 title · 결과 수 1
- step_6 · docs.search.v1 · 이전 step_5의 첫 결과 title · 결과 수 1
- step_7 · docs.search.v1 · 이전 step_6의 첫 결과 title · 결과 수 1
- step_8 · docs.search.v1 · 이전 step_7의 첫 결과 title · 결과 수 1
- step_9 · docs.search.v1 · 이전 step_8의 첫 결과 title · 결과 수 1
- step_10 · docs.search.v1 · 이전 step_9의 첫 결과 title · 결과 수 1

## news_two

Find artificial intelligence news using exactly two steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.401초, 모델 1회.
- step_1 · news.search.v1 · artificial intelligence news · 결과 수 1 · from_utc 2026-10-22T07:52:06Z
- step_2 · news.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1 · from_utc 2026-10-22T07:52:06Z

## news_then_docs

Find battery recycling news then supporting documentation using exactly two steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.366초, 모델 1회.
- step_1 · news.search.v1 · battery recycling news · 결과 수 1 · from_utc 2026-10-22T07:52:06Z
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## docs_then_news

Find Python documentation then related news using exactly two steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.318초, 모델 1회.
- step_1 · docs.search.v1 · Python documentation · 결과 수 1
- step_2 · news.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1 · from_utc 2026-10-22T07:52:07Z

## three_alternating

Find Python news then documentation then news using three steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.362초, 모델 1회.
- step_1 · news.search.v1 · Python news · 결과 수 1 · from_utc 2026-10-22T07:52:07Z
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1
- step_3 · news.search.v1 · 이전 step_2의 첫 결과 title · 결과 수 1 · from_utc 2026-10-22T07:52:07Z

## three_topics

Find documentation for 3 topics: Docker, Kubernetes and Terraform

수정 전: PASS. 최종: PASS, HTTP 200, 0.523초, 모델 1회.
- step_1 · docs.search.v1 · Docker documentation · 결과 수 1
- step_2 · docs.search.v1 · Kubernetes documentation · 결과 수 1
- step_3 · docs.search.v1 · Terraform documentation · 결과 수 1

## two_topic_then

Find Python documentation, then Rust documentation

수정 전: PASS. 최종: PASS, HTTP 200, 0.331초, 모델 1회.
- step_1 · docs.search.v1 · Python documentation · 결과 수 1
- step_2 · docs.search.v1 · Rust documentation · 결과 수 1

## two_topic_and

Find documentation for Python and Rust

수정 전: PASS. 최종: PASS, HTTP 200, 0.409초, 모델 1회.
- step_1 · docs.search.v1 · Python documentation · 결과 수 1
- step_2 · docs.search.v1 · Rust documentation · 결과 수 1

## independent_mixed

Independently find Python news and Python documentation using two steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.430초, 모델 1회.
- step_1 · news.search.v1 · Python news and Python documentation · 결과 수 1 · from_utc 2026-10-22T07:52:09Z
- step_2 · docs.search.v1 · Python news and Python documentation · 결과 수 1

## reverse_after

Find Python documentation after finding Python news using two steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Write the searches in execution order, separated by then.

## negated_news_count

Find Python documentation without news using 3 steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.395초, 모델 1회.
- step_1 · docs.search.v1 · Python documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1
- step_3 · docs.search.v1 · 이전 step_2의 첫 결과 title · 결과 수 1

## negated_send

Find Python documentation using two steps. Do not send emails.

수정 전: FAIL. 최종: PASS, HTTP 200, 0.376초, 모델 1회.
- step_1 · docs.search.v1 · Python official documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## three_results

Find Python documentation using two steps. Return 3 results per step.

수정 전: FAIL. 최종: PASS, HTTP 200, 0.335초, 모델 1회.
- step_1 · docs.search.v1 · Python documentation · 결과 수 3
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 3

## top_five

Find Python documentation using two steps with top 5 results per step

수정 전: FAIL. 최종: PASS, HTTP 200, 0.329초, 모델 1회.
- step_1 · docs.search.v1 · Python documentation · 결과 수 5
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 5

## last_week

Find battery news from the last 7 days using two steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.522초, 모델 1회.
- step_1 · news.search.v1 · battery news last 7 days · 결과 수 1 · from_utc 2026-10-16T07:52:11Z
- step_2 · news.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1 · from_utc 2026-10-16T07:52:11Z

## last_twelve_hours

Find battery news from the last 12 hours using two steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.524초, 모델 1회.
- step_1 · news.search.v1 · battery news last 12 hours · 결과 수 1 · from_utc 2026-10-22T19:52:11Z
- step_2 · news.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1 · from_utc 2026-10-22T19:52:11Z

## one_step

Find Python documentation using one step

수정 전: PASS. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Choose one consistent count between two and ten steps.

## eleven_steps

Find Python documentation using 11 steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Choose one consistent count between two and ten steps.

## eleven_word

Find Python documentation using eleven steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Choose one consistent count between two and ten steps.

## zero_steps

Find Python documentation using 0 steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Choose one consistent count between two and ten steps.

## conflicting_counts

Find Python documentation using exactly two steps and three tasks

수정 전: PASS. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Choose one consistent count between two and ten steps.

## too_many_topics

Find documentation for 11 topics: Alpha, Bravo, Charlie, Delta, Echo, Foxtrot, Golf, Hotel, India, Juliet and Kilo

수정 전: FAIL. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: List at most ten distinct subjects and make the stated subject count match the list.

## topics_count_conflict

Find documentation for 3 topics: Docker, Kubernetes and Terraform using exactly two steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Use the same number of steps and listed subjects.

## unknown_weather

Find a weather forecast using two steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: An explicit supported public news or documentation search objective

## unsupported_summary

Find battery news then summarize the results using two steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Written synthesis or translation (supported search steps return sources only)

## unsupported_send

Find battery news then send an email using two steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Sending messages or publishing

## private_url

Find documentation at https://private.example/internal using two steps

수정 전: PASS. 최종: PASS, HTTP 400, 0.001초, 모델 0회.
입력 차단: Review the supported workspace fields.

## private_token

Find documentation using Bearer synthetic-private-token

수정 전: PASS. 최종: PASS, HTTP 400, 0.001초, 모델 0회.
입력 차단: Review the supported workspace fields.

## empty



수정 전: PASS. 최종: PASS, HTTP 400, 0.001초, 모델 0회.
입력 차단: Review the supported workspace fields.

## oversized

Find documentation xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

수정 전: PASS. 최종: PASS, HTTP 400, 0.001초, 모델 0회.
입력 차단: Review the supported workspace fields.

## ko_three

파이썬 문서를 3단계로 검색해줘

수정 전: FAIL. 최종: PASS, HTTP 200, 0.332초, 모델 1회.
- step_1 · docs.search.v1 · Python documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1
- step_3 · docs.search.v1 · 이전 step_2의 첫 결과 title · 결과 수 1

## ko_mixed

AI 뉴스를 찾은 다음 관련 문서를 검색하는 2단계 워크플로우

수정 전: FAIL. 최종: PASS, HTTP 200, 0.321초, 모델 1회.
- step_1 · news.search.v1 · AI news · 결과 수 1 · from_utc 2026-10-22T07:52:12Z
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## ko_exclude_news

뉴스는 제외하고 Python 문서만 3단계로 검색해줘

수정 전: FAIL. 최종: PASS, HTTP 200, 0.321초, 모델 1회.
- step_1 · docs.search.v1 · Python documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1
- step_3 · docs.search.v1 · 이전 step_2의 첫 결과 title · 결과 수 1

## ko_summary

AI 뉴스를 검색한 후 결과를 요약해줘

수정 전: FAIL. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Written synthesis or translation (supported search steps return sources only)

## cpp_topic

Find C++ documentation using two steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.360초, 모델 1회.
- step_1 · docs.search.v1 · C++ documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## dotnet_topic

Find .NET documentation using two steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.333초, 모델 1회.
- step_1 · docs.search.v1 · .NET documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## version_topic

Find Python 3.12 documentation using two steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.538초, 모델 1회.
- step_1 · docs.search.v1 · Python 3.12 official documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## news_payment_topic

Find news about payment security using two steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.406초, 모델 1회.
- step_1 · news.search.v1 · news about payment security · 결과 수 1 · from_utc 2026-10-22T07:52:14Z
- step_2 · news.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1 · from_utc 2026-10-22T07:52:14Z

## docs_news_topic

Find documentation about news APIs using two steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.430초, 모델 1회.
- step_1 · docs.search.v1 · news APIs documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## unsupported_translation

Translate a Korean document into French using two steps

수정 전: FAIL. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Written synthesis or translation (supported search steps return sources only)

## conflicting_types

Find news and documentation using three steps

수정 전: PASS. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Specify a supported search type for every requested step.

## too_many_results

Find Python documentation using two steps with 100 results per step

수정 전: FAIL. 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Choose one consistent limit between one and five results per search step.

## summary_as_topic

Find documentation about summarization algorithms using two steps

수정 전: 미실시(추가 경계 사례). 최종: PASS, HTTP 200, 0.497초, 모델 1회.
- step_1 · docs.search.v1 · summarization algorithms documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## translation_as_topic

Find documentation about translation algorithms using two steps

수정 전: 미실시(추가 경계 사례). 최종: PASS, HTTP 200, 0.521초, 모델 1회.
- step_1 · docs.search.v1 · translation algorithms documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## negated_summary

Find Python documentation using two steps. Do not summarize.

수정 전: 미실시(추가 경계 사례). 최종: PASS, HTTP 200, 0.370초, 모델 1회.
- step_1 · docs.search.v1 · Python official documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1

## excessive_period

Find battery news from the last 30 days using two steps

수정 전: 미실시(추가 경계 사례). 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Choose one news window between one and 168 hours (seven days).

## conflicting_limits

Find Python documentation using two steps. Return 2 results and top 3 results per step.

수정 전: 미실시(추가 경계 사례). 최종: PASS, HTTP 200, 0.005초, 모델 0회.
보완 안내: Choose one consistent limit between one and five results per search step.

## upper_case_count

Find Python documentation using exactly THREE steps

수정 전: 미실시(추가 경계 사례). 최종: PASS, HTTP 200, 0.337초, 모델 1회.
- step_1 · docs.search.v1 · Python documentation · 결과 수 1
- step_2 · docs.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1
- step_3 · docs.search.v1 · 이전 step_2의 첫 결과 title · 결과 수 1

## research_news

Find battery research news using two steps

수정 전: 미실시(추가 경계 사례). 최종: PASS, HTTP 200, 0.370초, 모델 1회.
- step_1 · news.search.v1 · battery research news · 결과 수 1 · from_utc 2026-10-22T07:52:16Z
- step_2 · news.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1 · from_utc 2026-10-22T07:52:16Z

## news_about_docs

Find news about documentation software using two steps

수정 전: 미실시(추가 경계 사례). 최종: PASS, HTTP 200, 0.467초, 모델 1회.
- step_1 · news.search.v1 · news about documentation software · 결과 수 1 · from_utc 2026-10-22T07:52:17Z
- step_2 · news.search.v1 · 이전 step_1의 첫 결과 title · 결과 수 1 · from_utc 2026-10-22T07:52:17Z
