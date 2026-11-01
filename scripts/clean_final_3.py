with open('agent_market/gateway/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for idx, line in enumerate(lines):
    if 'outEl.textContent = "⚠️' in line:
        line = '            outEl.textContent = "에이전트 원격 서비스가 중지되어 정상 응답을 수신하지 못했습니다.\\\\nAgent Concierge 워크플로우 스튜디오(https://agentconcierge.biz)에서 동일 또는 유사 대체 에이전트로 원클릭 교체하여 파이프라인을 복구할 수 있습니다.";\n'
    elif 'stEl.textContent = `✔ 완료' in line:
        line = line.replace('✔ ', '')
    elif 'let reportMd = `# 📋' in line:
        line = line.replace('# 📋', '#')
    new_lines.append(line)

with open('agent_market/gateway/dashboard.html', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Applied final 3 cleanups via script!")
