# AI AD Coin v5 정책과 설계 검증 기록

2026-11-06 한국 시간. 실제 자산이나 블록체인을 조작하지 않는 설계 검증이다.

- 정책: [POL-01~24](../../docs/AD_COIN_POLICY.md)
- 기술 설계: [INV-01~06과 구성·상태·API·전환](../../docs/AD_COIN_ARCHITECTURE.md)
- 개발 순서와 예정 검수: [43개 항목](../../docs/AD_COIN_V5_IMPLEMENTATION_PLAN.md)
- 기계 판독 명세: [설계 v5](../../docs/ad_coin_v5_spec.json)
- 회계 모형·추적 검증: [validation.json](validation.json)
- Canvas 문법·모형 검사: [canvas-validation.json](canvas-validation.json)

다음 명령은 로컬 파일과 정수 회계 모형만 검사한다. 네트워크·DB·키·토큰·체인 배포를 사용하지 않는다.

```bash
python3 reports/ad-coin-design-v5-2026-11-06/validate_design.py
```

기존 v4의 제품 소스 해시가 유지되는지도 확인한다. 문서·모형 검증 통과를 스마트 계약·API·사람 노출 증명·상용 준비금·법적 적격성 검증으로 확대하지 않는다. 새로 계획한 43개 제품 검수는 실제 구현·시험 전까지 통과가 아니다. 기존 89건·219건 시험은 v4의 과거 증거로 구분한다.
