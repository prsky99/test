# 운영 적용

검증 후보만 적용합니다. 운영 프로세스 교체에 대한 사용자 승인 후 실행하세요.

```bash
./agentcon deploy frontend protocol-disclosures-frontend-20261029-r1
./agentcon deploy admin protocol-disclosures-admin-20261029-r1
./agentcon status
```

현재 기준은 experience-search-frontend/admin-20261029-r2입니다. 적용 직전 기준 릴리스가 달라졌다면 후보를 그대로 덮어쓰지 말고 변경 내용을 재검토해야 합니다.

반영 후 /mcp tools/list와 /.well-known/mcp.json에서 search·find_agents·whats_new의 readOnlyHint=true 및 chat=false를 확인합니다. 조회 응답의 visitor=null은 의도된 변경이며, 대화 저장에는 chat을 사용합니다. x402 실제 제공자가 이용 불가한 경우 격리 검증을 운영 성공으로 표시하지 않습니다.
