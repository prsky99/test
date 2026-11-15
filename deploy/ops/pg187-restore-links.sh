#!/bin/bash
# PostgreSQL 18.7 업그레이드 되돌리기: brew 링크를 기록해 둔 18.6_1 상태로 복원한다(운영·SRE, PM 11-15 12:46 지시).
#   bash deploy/ops/pg187-restore-links.sh --dry-run    # 무엇을 바꿀지 보기만 함
#   bash deploy/ops/pg187-restore-links.sh              # 복원(세 서버 모두 정지된 상태에서만)
# 기록: logs/ops/pg187-20261117/links-18.6_1.tsv (링크 경로<TAB>링크 내용, 11-15 12:4x 기록, 1966개)
# 하는 일:
#   1) 18.7을 가리키는 링크 중 기록에 없는 것(18.7에서 새로 생긴 파일)은 지운다.
#   2) 기록에 있는 링크는 모두 기록된 내용(../Cellar/postgresql@18/18.6_1/...)으로 되돌린다.
#   3) 하나씩 다시 읽어 기록과 같은지 확인한다. pgvector 등 다른 패키지의 링크는 건드리지 않는다.
# 데이터 폴더는 건드리지 않는다. 18.x 소수점 버전 사이는 데이터 형식이 같다(18.7 릴리스 노트 "dump/restore is not required").
# 시험용 바꿔치기: PG_PREFIX(기본 /opt/homebrew), PG_LINKS(기록 파일), PG_RUNNING(실행 중 서버 확인 명령)
set -uo pipefail
cd "$(dirname "$0")/../.."
PREFIX=${PG_PREFIX:-/opt/homebrew}
LIST=${PG_LINKS:-logs/ops/pg187-20261117/links-18.6_1.tsv}
RECORDED_PREFIX=/opt/homebrew          # 기록 파일의 경로 앞부분
OLD=18.6_1
NEW=${PG_NEW_VERSION:-18.7}
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

say() { echo "$*"; }
[ "$DRY" = 1 ] && say "== 미리 보기(--dry-run): 아무것도 바꾸지 않습니다 =="

# 0) 미리 확인
if [ ! -s "$LIST" ]; then say "멈춤: 링크 기록이 없습니다: $LIST"; exit 1; fi
if [ ! -x "$PREFIX/Cellar/postgresql@18/$OLD/bin/postgres" ]; then
  say "멈춤: $PREFIX/Cellar/postgresql@18/$OLD 가 없습니다(업그레이드 때 정리로 지워졌으면 이 방법으로는 되돌릴 수 없음)"; exit 1
fi
running=$(${PG_RUNNING:-pgrep -lf "postgres -D"} 2>/dev/null | grep -v pgrep || true)
if [ -n "$running" ]; then
  say "멈춤: PostgreSQL 서버가 아직 돌고 있습니다(세 서버 모두 정지한 뒤 실행):"; echo "$running" | sed 's/^/  /'
  [ "$DRY" = 1 ] || exit 3
fi

total=$(wc -l < "$LIST" | tr -d ' ')
say "기록: ${total}개 (${LIST})"

# 1) 18.7을 가리키는 링크 중 기록에 없는 것
extra=0
while IFS= read -r link; do
  rel=${link#"$PREFIX"}
  if ! grep -qF "${RECORDED_PREFIX}${rel}	" "$LIST"; then
    extra=$((extra + 1))
    if [ "$DRY" = 1 ]; then say "  지울 것(18.7에만 있음): $link"; else rm -f "$link" || { say "멈춤: 지우기 실패: $link"; exit 1; }; fi
  fi
done < <(for d in opt bin lib share include; do
           [ -e "$PREFIX/$d" ] && find "$PREFIX/$d" -type l -lname "*postgresql@18/$NEW*" 2>/dev/null
         done | sort)
say "18.7에만 있는 링크: ${extra}개 $([ "$DRY" = 1 ] && echo "(지울 예정)" || echo "지움")"

# 2) 기록대로 되돌리기
changed=0
while IFS=$'\t' read -r link target; do
  path=$PREFIX${link#"$RECORDED_PREFIX"}
  [ "$(readlink "$path" 2>/dev/null)" = "$target" ] && continue
  changed=$((changed + 1))
  if [ "$DRY" = 1 ]; then
    [ "$changed" -le 5 ] && say "  되돌릴 것: $path -> $target"
    continue
  fi
  mkdir -p "$(dirname "$path")" && ln -sfn "$target" "$path" || { say "멈춤: 링크 실패: $path"; exit 1; }
done < "$LIST"
say "되돌릴 링크: ${changed}개 $([ "$DRY" = 1 ] && echo "(예정)" || echo "되돌림")"

# 3) 확인
if [ "$DRY" = 0 ]; then
  bad=0
  while IFS=$'\t' read -r link target; do
    path=$PREFIX${link#"$RECORDED_PREFIX"}
    [ "$(readlink "$path" 2>/dev/null)" = "$target" ] || { bad=$((bad + 1)); [ "$bad" -le 5 ] && say "  다름: $path"; }
  done < "$LIST"
  if [ "$bad" -gt 0 ]; then say "멈춤: 기록과 다른 링크 ${bad}개"; exit 1; fi
  say "확인: ${total}개 모두 기록과 같음. pkglibdir: $("$PREFIX/opt/postgresql@18/bin/pg_config" --pkglibdir 2>/dev/null || echo '?')"
  say "다음: launchctl kickstart gui/\$(id -u)/biz.agentconcierge.postgres18 뒤 SELECT version()이 18.6인지 확인"
else
  say "미리 보기 끝."
fi
exit 0
