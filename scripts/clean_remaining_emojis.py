"""
Python script to clean the remaining 14 emojis and crude symbols in dashboard.html.
"""

def clean_remaining():
    with open('agent_market/gateway/dashboard.html', 'r', encoding='utf-8') as f:
        c = f.read()

    # 1. optgroup
    c = c.replace('opts += `<optgroup label="📂 내 워크플로우 (${myWorkflows.length}개)">` +',
                  'opts += `<optgroup label="내 워크플로우 (${myWorkflows.length}개)">` +')

    # 2. btn test text
    c = c.replace('btn.textContent = "⏳ 실행 중…";',
                  'btn.textContent = "실행 중…";')

    # 3. crude arrow
    c = c.replace('<span><strong>${esc(s.name)}</strong> 실행 완료 ➔ 전체 파이프라인 산출물이 최종 종합 결과 보고서로 합성되었습니다.</span>',
                  '<span><strong>${esc(s.name)}</strong> 실행 완료: 전체 파이프라인 산출물이 최종 종합 결과 보고서로 합성되었습니다.</span>')

    # 4. ratingStars in renderTemplates
    c = c.replace('const ratingStars = "★".repeat(Math.round(t.rating_avg || 5.0)) + "☆".repeat(5 - Math.round(t.rating_avg || 5.0));\n    const authorLabel = t.author || "Community Contributor";',
                  'const authorLabel = t.author || "Community Contributor";')

    # 5. outEl in webapp
    c = c.replace('outEl.textContent = "⚠️ 에이전트 원격 서비스가 중지되어 정상 응답을 수신하지 못했습니다.\\n💡 Agent Concierge 워크플로우 스튜디오(https://agentconcierge.biz)에서 동일 또는 유사 대체 에이전트로 원클릭 교체하여 파이프라인을 복구할 수 있습니다.";',
                  'outEl.textContent = "에이전트 원격 서비스가 중지되어 정상 응답을 수신하지 못했습니다.\\nAgent Concierge 워크플로우 스튜디오(https://agentconcierge.biz)에서 동일 또는 유사 대체 에이전트로 원클릭 교체하여 파이프라인을 복구할 수 있습니다.";')

    # 6. stEl in webapp
    c = c.replace('stEl.textContent = `✔ 완료 (${stepLat}ms)`;',
                  'stEl.textContent = `완료 (${stepLat}ms)`;')

    # 7. reportMd headers in webapp
    c = c.replace('let reportMd = `# 📋 ${WF.name} — 최종 실행 결과 종합 보고서\\n\\n`;',
                  'let reportMd = `# ${WF.name} — 최종 실행 결과 종합 보고서\\n\\n`;')

    c = c.replace('### 📌 1. 핵심 요약 (Executive Summary)',
                  '### 1. 핵심 요약 (Executive Summary)')

    c = c.replace('### 📊 2. 단계별 데이터 수집 및 처리 결과 (Pipeline Aggregated Data)',
                  '### 2. 단계별 데이터 수집 및 처리 결과 (Pipeline Aggregated Data)')

    c = c.replace('### 🚀 3. 다음 자동화 조치 및 채널 발송 증명 (Next Actions & Dispatch Status)',
                  '### 3. 다음 자동화 조치 및 채널 발송 증명 (Next Actions & Dispatch Status)')

    # 8. ratingStars in renderTemplateGalleryCards
    c = c.replace('const ratingStars = "★".repeat(Math.round(t.rating_avg || 5.0)) + "☆".repeat(5 - Math.round(t.rating_avg || 5.0));\n\n    const stepsChips',
                  'const stepsChips')

    # 9. email toast
    c = c.replace('toast("📧 team@agentconcierge.biz 및 Slack #general 채널로 최종 보고서가 성공적으로 발송되었습니다.");',
                  'toast("team@agentconcierge.biz 및 Slack #general 채널로 최종 보고서가 성공적으로 발송되었습니다.");')

    # 10. alt briefing desc
    c = c.replace('? "💡 95,000+개의 실시간 검증된 에이전트 중 연결할 에이전트를 검색하고 선택하세요. 선택 즉시 노드에 기능과 도구 인자가 자동 반영됩니다."',
                  '? "95,000+개의 실시간 검증된 에이전트 중 연결할 에이전트를 검색하고 선택하세요. 선택 즉시 노드에 기능과 도구 인자가 자동 반영됩니다."')
    c = c.replace(': "💡 서비스가 중단되었거나 대체가 필요한 에이전트를 상위 호환 에이전트로 1-클릭 교체합니다. 기존 DAG 파이프라인의 연결선은 그대로 유지됩니다.";',
                  ': "서비스가 중단되었거나 대체가 필요한 에이전트를 상위 호환 에이전트로 1-클릭 교체합니다. 기존 DAG 파이프라인의 연결선은 그대로 유지됩니다.";')

    with open('agent_market/gateway/dashboard.html', 'w', encoding='utf-8') as f:
        f.write(c)

    print("Remaining items cleaned successfully!")

if __name__ == '__main__':
    clean_remaining()
