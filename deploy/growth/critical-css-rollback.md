# 첫 화면 CSS 되돌리기 (11-11, 성장·유통, PM 결정 B)

첫 화면 CSS는 `new/en/assets/critical/<화면>.css` 파일이 있을 때만 켜집니다. 환경 변수는 없습니다(agentcon.env가 새 키를 거부함).

## 언제 되돌리나
- 배포 뒤 공개 주소에서 다음 중 하나가 보일 때
  - 화면 모양이 어긋남
  - 콘솔 CSP 오류
  - CLS가 늘어남
  - 화면 감사(ui_audit)에서 0이 아닌 값
- 한 화면만 문제면 그 화면 파일만 빼도 됩니다.

## 가장 빠른 방법: 직전 버전으로 되돌리기 (코드 변경 없음)
```bash
./agentcon status        # 활성 칸과 직전 버전 확인
./agentcon deploy frontend <직전 버전 이름> --lock-owner 성장·유통
```
- 현황판 "배포 잠금" 칸이 비어 있어야 합니다.
- 직전 버전은 첫 화면 CSS가 없는 버전이므로, 바뀌는 것은 이 기능뿐입니다(그 묶음의 다른 변경도 함께 되돌아감).

## 이 기능만 끄기 (다른 변경은 유지)
```bash
git rm -r -q new/en/assets/critical
git commit -m "Turn off first-screen CSS: drop new/en/assets/critical"
./agentcon package <새 버전> --base <활성 버전> --commit HEAD
.venv-tests/bin/python -m scripts.release_gate <새 버전>
./agentcon deploy frontend <새 버전> --lock-owner 성장·유통
```
- 파일이 없으면 화면은 예전처럼 묶음 CSS 하나를 막고 받습니다.
- `tests/test_critical_css_browser.py`는 파일이 없으면 건너뜁니다.

## 다시 켜기
```bash
.venv-tests/bin/python -m scripts.build_critical_css --local
```
- 작업본 화면과 공개 주소의 실제 데이터로 9개 화면 × 1280·375 × 밝은·어두운을 엽니다.
- 그다음 `tests/test_critical_css.py`와 `tests/test_critical_css_browser.py`를 통과시킨 뒤 커밋합니다.
- 스타일 파일을 고치면 꼭 다시 만들어야 합니다. 원본 해시가 다르면 시험이 실패합니다.
