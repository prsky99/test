"""
Python script to modernize renderTemplates, renderMyWorkflows, generateStandaloneAppHtml,
renderTemplateGalleryCards, renderAlternativeCards, and showAgentReplacementDetail with Lucide SVG icons.
"""

def update_templates_and_modals():
    with open('agent_market/gateway/dashboard.html', 'r', encoding='utf-8') as f:
        c = f.read()

    # 1. renderTemplates
    old_render_tmpl = '''    return `
      <div class="template-card" data-tmpl-id="${t.id}">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
              <span class="chip" style="font-weight:700;font-size:11px">${esc(t.category || 'automation')}</span>
              <span class="star-rating" title="평점 ${t.rating_avg ? t.rating_avg.toFixed(1) : '5.0'}">${ratingStars} ${(t.rating_avg || 5.0).toFixed(1)}</span>
            </div>
            <span class="chip" style="font-size:11px;background:rgba(59,130,246,0.1);color:#3b82f6">⚡ ${(t.runs_count || 0)}회 실행</span>
          </div>

          <h3 style="margin:0 0 6px;font-size:15px;line-height:1.4">${esc(t.name)}</h3>
          <p class="muted" style="margin:0 0 10px;font-size:12.5px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">
            ${esc(t.description || '검증된 다중 에이전트 자율 오케스트레이션 파이프라인')}
          </p>

          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">
            ${stepsPreview || '<span class="muted" style="font-size:11px">단계 정보 없음</span>'}
          </div>
        </div>

        <div style="border-top:1px solid var(--line);padding-top:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
          <div style="font-size:11.5px;color:var(--muted)">
            작성자: <strong style="color:${isVerifiedTeam ? 'var(--ok)' : 'var(--text)'}">${esc(authorLabel)}</strong>
            · 🍴 ${t.forks_count || 0}
          </div>
          <div style="display:flex;gap:6px">
            <button class="btn sm primary btn-run-tmpl" data-id="${t.id}" type="button" title="템플릿 즉시 실행 및 결과 확인">▶ 실행</button>
            <button class="btn sm btn-load-tmpl" data-id="${t.id}" type="button" title="현재 캔버스에 불러와 수정">🚀 캔버스</button>
            <button class="btn sm btn-fork-tmpl" data-id="${t.id}" type="button" title="포크하여 내 워크플로우로 복사">🍴 포크</button>
            <button class="btn sm btn-export-tmpl" data-id="${t.id}" type="button" title="독립 웹앱 다운로드">📲 앱</button>
            <button class="btn sm btn-share-tmpl" data-id="${t.id}" type="button" title="공유">🔗</button>
            <button class="btn sm btn-review-tmpl" data-id="${t.id}" type="button" title="리뷰 작성">⭐</button>
          </div>
        </div>
      </div>
    `;'''

    new_render_tmpl = '''    return `
      <div class="template-card" data-tmpl-id="${t.id}">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
              <span class="chip" style="font-weight:700;font-size:11px">${esc(t.category || 'automation')}</span>
              <span class="star-rating" style="display:inline-flex;align-items:center;gap:3px;color:#f59e0b;font-size:11.5px;font-weight:700" title="평점 ${t.rating_avg ? t.rating_avg.toFixed(1) : '5.0'}">
                ${ico('star', 12, 12, 'fill-amber')}
                <span>${(t.rating_avg || 5.0).toFixed(1)}</span>
              </span>
            </div>
            <span class="chip" style="font-size:11px;background:rgba(59,130,246,0.1);color:#3b82f6;display:inline-flex;align-items:center;gap:3px">
              ${ico('zap', 11, 11)}
              <span>${(t.runs_count || 0)}회 실행</span>
            </span>
          </div>

          <h3 style="margin:0 0 6px;font-size:15px;line-height:1.4">${esc(t.name)}</h3>
          <p class="muted" style="margin:0 0 10px;font-size:12.5px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">
            ${esc(t.description || '검증된 다중 에이전트 자율 오케스트레이션 파이프라인')}
          </p>

          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">
            ${stepsPreview || '<span class="muted" style="font-size:11px">단계 정보 없음</span>'}
          </div>
        </div>

        <div style="border-top:1px solid var(--line);padding-top:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
          <div style="font-size:11.5px;color:var(--muted);display:flex;align-items:center;gap:4px">
            <span>작성자: <strong style="color:${isVerifiedTeam ? 'var(--ok)' : 'var(--text)'}">${esc(authorLabel)}</strong></span>
            <span>·</span>
            <span style="display:inline-flex;align-items:center;gap:3px">${ico('git-fork', 11, 11)} <span>${t.forks_count || 0}</span></span>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn sm primary btn-run-tmpl" data-id="${t.id}" type="button" title="템플릿 즉시 실행 및 결과 확인" style="display:inline-flex;align-items:center;gap:4px">
              ${ico('play', 12, 12)}
              <span>실행</span>
            </button>
            <button class="btn sm btn-load-tmpl" data-id="${t.id}" type="button" title="현재 캔버스에 불러와 수정" style="display:inline-flex;align-items:center;gap:4px">
              ${ico('workflow', 12, 12)}
              <span>캔버스</span>
            </button>
            <button class="btn sm btn-fork-tmpl" data-id="${t.id}" type="button" title="포크하여 내 워크플로우로 복사" style="display:inline-flex;align-items:center;gap:4px">
              ${ico('git-fork', 12, 12)}
              <span>포크</span>
            </button>
            <button class="btn sm btn-export-tmpl" data-id="${t.id}" type="button" title="독립 웹앱 다운로드" style="display:inline-flex;align-items:center;gap:4px">
              ${ico('smartphone', 12, 12)}
              <span>앱</span>
            </button>
            <button class="btn sm btn-share-tmpl" data-id="${t.id}" type="button" title="공유" style="display:inline-flex;align-items:center;justify-content:center;padding:4px 8px">
              ${ico('share-2', 12, 12)}
            </button>
            <button class="btn sm btn-review-tmpl" data-id="${t.id}" type="button" title="리뷰 작성" style="display:inline-flex;align-items:center;justify-content:center;padding:4px 8px">
              ${ico('star', 12, 12)}
            </button>
          </div>
        </div>
      </div>
    `;'''

    assert old_render_tmpl in c, "Could not find old_render_tmpl in dashboard.html"
    c = c.replace(old_render_tmpl, new_render_tmpl, 1)

    # 2. renderMyWorkflows
    old_my_empty = '''    list.innerHTML = `
      <div class="card muted" style="padding:36px;text-align:center">
        <p style="margin:0 0 12px;font-size:14px">아직 생성하거나 포크한 워크플로우가 없습니다.</p>
        <button class="btn primary" onclick="switchWfSubView('templates')" style="font-size:13px">📚 템플릿 허브 둘러보기</button>
      </div>
    `;'''

    new_my_empty = '''    list.innerHTML = `
      <div class="card muted" style="padding:36px;text-align:center">
        <p style="margin:0 0 12px;font-size:14px">아직 생성하거나 포크한 워크플로우가 없습니다.</p>
        <button class="btn primary" onclick="switchWfSubView('templates')" style="font-size:13px;display:inline-flex;align-items:center;gap:6px">
          ${ico('library', 14, 14)}
          <span>템플릿 허브 둘러보기</span>
        </button>
      </div>
    `;'''

    assert old_my_empty in c, "Could not find old_my_empty in dashboard.html"
    c = c.replace(old_my_empty, new_my_empty, 1)

    old_my_card = '''    return `
      <div class="card" style="padding:14px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
        <div style="flex:1;min-width:280px">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap">
            <strong style="font-size:15px">${esc(w.name)}</strong>
            <span class="chip">${esc(w.category || 'automation')}</span>
            <span class="chip" style="font-weight:600">${esc(w.trigger_type || 'manual')}</span>
            ${lineage}
            <span class="chip mono" style="color:var(--ok)">⚡ ${w.runs_count || 0}회 실행</span>
          </div>
          <p class="muted" style="margin:0;font-size:12.5px">${esc(w.description || '설명 없음')}</p>
        </div>

        <div class="row" style="gap:6px;flex-wrap:wrap">
          <button class="btn sm primary my-edit-btn" data-id="${w.id}" type="button">✏️ 캔버스 편집</button>
          <button class="btn sm my-run-btn" data-id="${w.id}" type="button">⚡ 바로 실행</button>
          <button class="btn sm my-pub-btn" data-id="${w.id}" type="button">🌟 템플릿에 공유</button>
          <button class="btn sm my-export-btn" data-id="${w.id}" type="button">📲 웹앱 받기</button>
          <button class="btn sm my-share-btn" data-id="${w.id}" type="button">🔗 공유</button>
          <button class="btn sm my-dup-btn" data-id="${w.id}" type="button">📋 복제</button>
          <button class="btn sm my-del-btn" data-id="${w.id}" type="button" style="color:var(--bad)">삭제</button>
        </div>
      </div>
    `;'''

    new_my_card = '''    return `
      <div class="card" style="padding:16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;border:1px solid rgba(59,130,246,0.18);border-radius:12px;background:rgba(15,23,42,0.65);backdrop-filter:blur(12px)">
        <div style="flex:1;min-width:280px">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">
            <strong style="font-size:15px;color:var(--text)">${esc(w.name)}</strong>
            <span class="chip" style="font-size:11px">${esc(w.category || 'automation')}</span>
            <span class="chip" style="font-weight:600;font-size:11px">${esc(w.trigger_type || 'manual')}</span>
            ${lineage}
            <span class="chip mono" style="color:var(--ok);display:inline-flex;align-items:center;gap:3px;font-size:11px">
              ${ico('zap', 11, 11)}
              <span>${w.runs_count || 0}회 실행</span>
            </span>
          </div>
          <p class="muted" style="margin:0;font-size:12.5px;line-height:1.45">${esc(w.description || '설명 없음')}</p>
        </div>

        <div class="row" style="gap:6px;flex-wrap:wrap">
          <button class="btn sm primary my-edit-btn" data-id="${w.id}" type="button" style="display:inline-flex;align-items:center;gap:4px">
            ${ico('edit-3', 12, 12)}
            <span>캔버스 편집</span>
          </button>
          <button class="btn sm my-run-btn" data-id="${w.id}" type="button" style="display:inline-flex;align-items:center;gap:4px">
            ${ico('play', 12, 12)}
            <span>바로 실행</span>
          </button>
          <button class="btn sm my-pub-btn" data-id="${w.id}" type="button" style="display:inline-flex;align-items:center;gap:4px">
            ${ico('upload-cloud', 12, 12)}
            <span>템플릿에 공유</span>
          </button>
          <button class="btn sm my-export-btn" data-id="${w.id}" type="button" style="display:inline-flex;align-items:center;gap:4px">
            ${ico('smartphone', 12, 12)}
            <span>웹앱 받기</span>
          </button>
          <button class="btn sm my-share-btn" data-id="${w.id}" type="button" style="display:inline-flex;align-items:center;gap:4px">
            ${ico('share-2', 12, 12)}
            <span>공유</span>
          </button>
          <button class="btn sm my-dup-btn" data-id="${w.id}" type="button" style="display:inline-flex;align-items:center;gap:4px">
            ${ico('copy', 12, 12)}
            <span>복제</span>
          </button>
          <button class="btn sm my-del-btn" data-id="${w.id}" type="button" style="color:var(--bad);display:inline-flex;align-items:center;gap:4px">
            ${ico('trash-2', 12, 12)}
            <span>삭제</span>
          </button>
        </div>
      </div>
    `;'''

    assert old_my_card in c, "Could not find old_my_card in dashboard.html"
    c = c.replace(old_my_card, new_my_card, 1)

    # 3. generateStandaloneAppHtml
    old_app_header = '''        <button class="btn" id="runAppBtn" style="padding:12px 26px;font-size:15px;background:linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);box-shadow:0 4px 12px rgba(99,102,241,0.35)">⚡ 파이프라인 실행</button>
      </div>

      ${config.is_paid ? `
      <div style="margin-top:14px;padding:12px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:8px;font-size:12.5px;color:#fcd34d">
        ⚡ <strong>유료 실행 과금:</strong> 실행당 <strong>${config.price_sats} sats</strong> (정산 수령지: <code>${esc(config.wallet_address)}</code>)
      </div>` : ''}

      ${config.require_google_auth ? `
      <div id="googleAuthContainer" style="margin-top:14px;padding:12px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);border-radius:8px">
        <div style="font-size:12.5px;margin-bottom:8px">🔒 구글 계정으로 로그인 후 실행할 수 있습니다.</div>'''

    new_app_header = '''        <button class="btn" id="runAppBtn" style="padding:12px 26px;font-size:15px;background:linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);box-shadow:0 4px 14px rgba(37,99,235,0.4);display:inline-flex;align-items:center;gap:6px">
          <svg class="lucide lucide-zap" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          <span>파이프라인 실행</span>
        </button>
      </div>

      ${config.is_paid ? `
      <div style="margin-top:14px;padding:12px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:8px;font-size:12.5px;color:#fcd34d;display:flex;align-items:center;gap:6px">
        <svg class="lucide lucide-zap" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        <span><strong>유료 실행 과금:</strong> 실행당 <strong>${config.price_sats} sats</strong> (정산 수령지: <code>${esc(config.wallet_address)}</code>)</span>
      </div>` : ''}

      ${config.require_google_auth ? `
      <div id="googleAuthContainer" style="margin-top:14px;padding:12px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);border-radius:8px">
        <div style="font-size:12.5px;margin-bottom:8px;display:flex;align-items:center;gap:6px">
          <svg class="lucide lucide-lock" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          <span>구글 계정으로 로그인 후 실행할 수 있습니다.</span>
        </div>'''

    assert old_app_header in c, "Could not find old_app_header in dashboard.html"
    c = c.replace(old_app_header, new_app_header, 1)

    old_app_sections = '''    <!-- 1. 파이프라인 단계별 실행 상태 -->
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <h2 style="font-size:15px">⚡ 파이프라인 단계별 실행 상태 (Step Execution)</h2>
        <span id="appExecProgressBadge" class="chip" style="font-size:11px">대기 중</span>
      </div>
      <div id="appStepsList"></div>
    </div>

    <!-- 2. 노드 간 데이터 전달 흐름 추적 (Data Flow Trace) -->
    <div class="card hidden" id="appDataFlowCard">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <h3 style="font-size:14.5px">🔄 노드 간 데이터 전달 흐름 (Data Flow Trace)</h3>
        <span class="chip primary" id="appDataFlowCount" style="font-size:10.5px">0개 전달</span>
      </div>
      <div id="appDataFlowList"></div>
    </div>

    <!-- 3. 최종 실행 결과 종합 보고서 (Executive Summary Report) -->
    <div class="card hidden" id="appDeliverableCard" style="border:1.5px solid var(--ok);background:linear-gradient(180deg, var(--card) 0%, rgba(16,185,129,0.03) 100%)">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-bottom:12px">
        <div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span class="chip ok" style="font-size:11px;font-weight:700">COMPLETED</span>
            <span class="chip" id="appScheduleBadge" style="font-size:11px">Daily 09:00 AM</span>
          </div>
          <h2 style="font-size:17px;margin:4px 0" id="appDeliverableTitle">최종 종합 완료 보고서</h2>
          <span style="font-size:12px;color:var(--muted)" id="appTotalLatencyText">총 소요 시간: 0ms</span>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn sm outline" id="btnCopyAppDeliverable" type="button">📋 보고서 복사</button>
          <button class="btn sm" id="btnDownloadAppDeliverable" type="button" style="background:var(--ok)">💾 마크다운 다운로드 (.md)</button>
        </div>
      </div>

      <!-- 핵심 요약 요점 리스트 -->
      <div style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.25);border-radius:8px;padding:12px 16px;margin-bottom:12px">
        <div style="font-size:12px;font-weight:700;color:var(--ok);margin-bottom:6px">📌 핵심 요약 (Executive Summary)</div>'''

    new_app_sections = '''    <!-- 1. 파이프라인 단계별 실행 상태 -->
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <h2 style="font-size:15px;display:flex;align-items:center;gap:6px">
          <svg class="lucide lucide-zap" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          <span>파이프라인 단계별 실행 상태 (Step Execution)</span>
        </h2>
        <span id="appExecProgressBadge" class="chip" style="font-size:11px">대기 중</span>
      </div>
      <div id="appStepsList"></div>
    </div>

    <!-- 2. 노드 간 데이터 전달 흐름 추적 (Data Flow Trace) -->
    <div class="card hidden" id="appDataFlowCard">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <h3 style="font-size:14.5px;display:flex;align-items:center;gap:6px">
          <svg class="lucide lucide-refresh-cw" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
          <span>노드 간 데이터 전달 흐름 (Data Flow Trace)</span>
        </h3>
        <span class="chip primary" id="appDataFlowCount" style="font-size:10.5px">0개 전달</span>
      </div>
      <div id="appDataFlowList"></div>
    </div>

    <!-- 3. 최종 실행 결과 종합 보고서 (Executive Summary Report) -->
    <div class="card hidden" id="appDeliverableCard" style="border:1.5px solid var(--ok);background:linear-gradient(180deg, var(--card) 0%, rgba(16,185,129,0.03) 100%)">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-bottom:12px">
        <div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span class="chip ok" style="font-size:11px;font-weight:700">COMPLETED</span>
            <span class="chip" id="appScheduleBadge" style="font-size:11px">Daily 09:00 AM</span>
          </div>
          <h2 style="font-size:17px;margin:4px 0" id="appDeliverableTitle">최종 종합 완료 보고서</h2>
          <span style="font-size:12px;color:var(--muted)" id="appTotalLatencyText">총 소요 시간: 0ms</span>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn sm outline" id="btnCopyAppDeliverable" type="button" style="display:inline-flex;align-items:center;gap:4px">
            <svg class="lucide lucide-copy" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
            <span>보고서 복사</span>
          </button>
          <button class="btn sm" id="btnDownloadAppDeliverable" type="button" style="background:var(--ok);display:inline-flex;align-items:center;gap:4px">
            <svg class="lucide lucide-download" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <span>마크다운 다운로드 (.md)</span>
          </button>
        </div>
      </div>

      <!-- 핵심 요약 요점 리스트 -->
      <div style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.25);border-radius:8px;padding:12px 16px;margin-bottom:12px">
        <div style="font-size:12px;font-weight:700;color:var(--ok);margin-bottom:6px;display:flex;align-items:center;gap:4px">
          <svg class="lucide lucide-pin" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="17" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg>
          <span>핵심 요약 (Executive Summary)</span>
        </div>'''

    assert old_app_sections in c, "Could not find old_app_sections in dashboard.html"
    c = c.replace(old_app_sections, new_app_sections, 1)

    # Clean webapp JS strings
    c = c.replace('if (box) box.innerHTML = \'<span style="color:var(--ok);font-size:12.5px">✔ 구글 로그인 인증 완료</span>\';',
                  'if (box) box.innerHTML = \'<span style="color:var(--ok);font-size:12.5px;display:inline-flex;align-items:center;gap:4px"><svg class="lucide lucide-check-circle-2" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9 12 2 2 4-4"/></svg> <span>구글 로그인 인증 완료</span></span>\';')

    c = c.replace('\\${isSusp ? \'<span style="color:#ef4444;font-size:11px;font-weight:700">⛔ 서비스 중지</span>\' : \'\'}',
                  '\\${isSusp ? \'<span style="color:#ef4444;font-size:11px;font-weight:700;display:inline-flex;align-items:center;gap:3px"><svg class="lucide lucide-alert-octagon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg> <span>서비스 중지</span></span>\' : \'\'}')

    c = c.replace('⚠️ <strong>원격 에이전트 서비스 중단:</strong> 외부 서비스가 중지되어 응답하지 않습니다.',
                  '<strong>원격 에이전트 서비스 중단:</strong> 외부 서비스가 중지되어 응답하지 않습니다.')

    c = c.replace('btn.textContent = "⏳ 파이프라인 실행 중…";',
                  'btn.innerHTML = \'<svg class="lucide lucide-refresh-cw" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg> <span>파이프라인 실행 중…</span>\';')

    c = c.replace('if (stEl) { stEl.textContent = "⛔ 서비스 중지"; stEl.style.color = "#ef4444"; }',
                  'if (stEl) { stEl.innerHTML = \'<svg class="lucide lucide-alert-octagon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:middle"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg> <span>서비스 중지</span>\'; stEl.style.color = "#ef4444"; }')

    c = c.replace('outEl.textContent = "⚠️ 에이전트 원격 서비스가 중지되어 정상 응답을 수신하지 못했습니다.\\n💡 Agent Concierge 워크플로우 스튜디오(https://agentconcierge.biz)에서 동일 또는 유사 대체 에이전트로 원클릭 교체하여 파이프라인을 복구할 수 있습니다.";',
                  'outEl.textContent = "에이전트 원격 서비스가 중지되어 정상 응답을 수신하지 못했습니다.\\nAgent Concierge 워크플로우 스튜디오(https://agentconcierge.biz)에서 동일 또는 유사 대체 에이전트로 원클릭 교체하여 파이프라인을 복구할 수 있습니다.";')

    c = c.replace('stEl.textContent = "⚡ 실행 중...";',
                  'stEl.innerHTML = \'<svg class="lucide lucide-zap" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:middle"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> <span>실행 중...</span>\';')

    c = c.replace('stEl.textContent = `✔ 완료 (${stepLat}ms)`;',
                  'stEl.innerHTML = `<svg class="lucide lucide-check-circle-2" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:middle"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9 12 2 2 4-4"/></svg> <span>완료 (${stepLat}ms)</span>`;')

    c = c.replace('<span style="color:#60a5fa">──▶</span>',
                  '<span style="color:#60a5fa;display:inline-flex;align-items:center"><svg class="lucide lucide-arrow-right" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg></span>')

    c = c.replace('let reportMd = `# 📋 ${WF.name} — 최종 실행 결과 종합 보고서\\n\\n`;',
                  'let reportMd = `# ${WF.name} — 최종 실행 결과 종합 보고서\\n\\n`;')
    c = c.replace('reportMd += `---' + '\\n\\n### 📌 1. 핵심 요약 (Executive Summary)\\n`;',
                  'reportMd += `---' + '\\n\\n### 1. 핵심 요약 (Executive Summary)\\n`;')
    c = c.replace('reportMd += `\\n---' + '\\n\\n### 📊 2. 단계별 데이터 수집 및 처리 결과 (Pipeline Aggregated Data)\\n`;',
                  'reportMd += `\\n---' + '\\n\\n### 2. 단계별 데이터 수집 및 처리 결과 (Pipeline Aggregated Data)\\n`;')
    c = c.replace('reportMd += `---' + '\\n\\n### 🚀 3. 다음 자동화 조치 및 채널 발송 증명 (Next Actions & Dispatch Status)\\n` +',
                  'reportMd += `---' + '\\n\\n### 3. 다음 자동화 조치 및 채널 발송 증명 (Next Actions & Dispatch Status)\\n` +')

    c = c.replace('progressBadge.textContent = "✔ 파이프라인 완결";',
                  'progressBadge.innerHTML = \'<svg class="lucide lucide-check-circle-2" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:middle"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9 12 2 2 4-4"/></svg> <span>파이프라인 완결</span>\';')

    c = c.replace('btn.textContent = "⚡ 파이프라인 재실행";',
                  'btn.innerHTML = \'<svg class="lucide lucide-zap" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:middle"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> <span>파이프라인 재실행</span>\';')

    c = c.replace('toast(`📲 \'${fileName}\' 독립 실행형 웹앱이 다운로드되었습니다!`);',
                  'toast(`\'${fileName}\' 독립 실행형 웹앱이 다운로드되었습니다!`);')

    # 4. renderTemplateGalleryCards
    old_gal_empty = '''    grid.innerHTML = `<div class="card muted" style="grid-column:1/-1;padding:36px;text-align:center">
      <div style="font-size:24px;margin-bottom:8px">🔍</div>
      <p style="margin:0 0 6px;font-weight:600">일치하는 워크플로우 템플릿이 없습니다.</p>
      <span class="muted" style="font-size:12px">검색어를 변경하거나 카테고리 필터를 '전체'로 선택해보세요.</span>
    </div>`;'''

    new_gal_empty = '''    grid.innerHTML = `<div class="card muted" style="grid-column:1/-1;padding:36px;text-align:center">
      <div style="margin-bottom:12px;color:var(--muted)">${ico('search', 32, 32)}</div>
      <p style="margin:0 0 6px;font-weight:600;font-size:14px">일치하는 워크플로우 템플릿이 없습니다.</p>
      <span class="muted" style="font-size:12px">검색어를 변경하거나 카테고리 필터를 '전체'로 선택해보세요.</span>
    </div>`;'''

    assert old_gal_empty in c
    c = c.replace(old_gal_empty, new_gal_empty, 1)

    old_gal_card = '''    return `
      <div class="card" style="margin-bottom:0;display:flex;flex-direction:column;justify-content:space-between;padding:14px;border:1px solid var(--line);border-radius:12px;background:var(--card, var(--panel));transition:transform 0.15s ease, box-shadow 0.15s ease">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:8px">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
              <span class="chip" style="font-weight:700;font-size:10.5px">${esc(t.category || 'automation')}</span>
              <span class="star-rating" style="font-size:11px" title="평점 ${t.rating_avg ? t.rating_avg.toFixed(1) : '5.0'}">${ratingStars} ${(t.rating_avg || 5.0).toFixed(1)}</span>
            </div>
            <span class="chip" style="font-size:10.5px;background:rgba(59,130,246,0.1);color:#3b82f6;font-weight:700">⚡ ${(t.runs_count || 0)}회</span>
          </div>

          <h4 style="margin:0 0 6px;font-size:14.5px;line-height:1.35">${esc(t.name)}</h4>
          <p class="muted" style="margin:0 0 10px;font-size:12px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">
            ${esc(t.description || '검증된 다중 에이전트 자율 오케스트레이션 파이프라인')}
          </p>

          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">
            ${stepsChips || '<span class="muted" style="font-size:11px">단계 정보 없음</span>'}
          </div>
        </div>

        <div style="border-top:1px solid var(--line);padding-top:10px;display:flex;justify-content:space-between;align-items:center;gap:8px">
          <div class="muted" style="font-size:11px">🍴 ${t.forks_count || 0} forks</div>
          <div style="display:flex;gap:6px">
            <button class="btn sm btn-gal-fork" data-id="${t.id}" type="button" style="font-size:11px">🍴 포크</button>
            <button class="btn sm primary btn-gal-load" data-id="${t.id}" type="button" style="font-size:11.5px;font-weight:700;padding:4px 12px">🚀 캔버스에 불러오기</button>
          </div>
        </div>
      </div>
    `;'''

    new_gal_card = '''    return `
      <div class="card" style="margin-bottom:0;display:flex;flex-direction:column;justify-content:space-between;padding:16px;border:1px solid rgba(59,130,246,0.2);border-radius:12px;background:rgba(15,23,42,0.7);backdrop-filter:blur(12px);transition:transform 0.15s ease, box-shadow 0.15s ease">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:8px">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
              <span class="chip" style="font-weight:700;font-size:10.5px">${esc(t.category || 'automation')}</span>
              <span class="star-rating" style="display:inline-flex;align-items:center;gap:3px;color:#f59e0b;font-size:11px;font-weight:700" title="평점 ${t.rating_avg ? t.rating_avg.toFixed(1) : '5.0'}">
                ${ico('star', 11, 11, 'fill-amber')}
                <span>${(t.rating_avg || 5.0).toFixed(1)}</span>
              </span>
            </div>
            <span class="chip" style="font-size:10.5px;background:rgba(59,130,246,0.1);color:#3b82f6;font-weight:700;display:inline-flex;align-items:center;gap:3px">
              ${ico('zap', 10, 10)}
              <span>${(t.runs_count || 0)}회</span>
            </span>
          </div>

          <h4 style="margin:0 0 6px;font-size:14.5px;line-height:1.35;color:var(--text)">${esc(t.name)}</h4>
          <p class="muted" style="margin:0 0 10px;font-size:12px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">
            ${esc(t.description || '검증된 다중 에이전트 자율 오케스트레이션 파이프라인')}
          </p>

          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">
            ${stepsChips || '<span class="muted" style="font-size:11px">단계 정보 없음</span>'}
          </div>
        </div>

        <div style="border-top:1px solid var(--line);padding-top:10px;display:flex;justify-content:space-between;align-items:center;gap:8px">
          <div class="muted" style="font-size:11px;display:inline-flex;align-items:center;gap:3px">
            ${ico('git-fork', 11, 11)}
            <span>${t.forks_count || 0} forks</span>
          </div>
          <div style="display:flex;gap:6px">
            <button class="btn sm btn-gal-fork" data-id="${t.id}" type="button" style="font-size:11px;display:inline-flex;align-items:center;gap:4px">
              ${ico('git-fork', 11, 11)}
              <span>포크</span>
            </button>
            <button class="btn sm primary btn-gal-load" data-id="${t.id}" type="button" style="font-size:11.5px;font-weight:700;padding:4px 12px;display:inline-flex;align-items:center;gap:4px">
              ${ico('workflow', 12, 12)}
              <span>캔버스 로드</span>
            </button>
          </div>
        </div>
      </div>
    `;'''

    assert old_gal_card in c
    c = c.replace(old_gal_card, new_gal_card, 1)

    # 5. SNS and review toasts
    c = c.replace('const content = `🚀 신규 자율 워크플로우 공개: [${wf.name}] (${wf.category || \'automation\'})\\n` +',
                  'const content = `신규 자율 워크플로우 공개: [${wf.name}] (${wf.category || \'automation\'})\\n` +')

    c = c.replace('toast("📢 에이전트 SNS 피드에 성공적으로 발행되었습니다!");',
                  'toast("에이전트 SNS 피드에 성공적으로 발행되었습니다!");')

    c = c.replace('toast("🌟 커뮤니티 템플릿 허브에 성공적으로 등록되었습니다!");',
                  'toast("커뮤니티 템플릿 허브에 성공적으로 등록되었습니다!");')

    c = c.replace('toast("⭐ 평점과 리뷰가 성공적으로 반영되었습니다!");',
                  'toast("평점과 리뷰가 성공적으로 반영되었습니다!");')

    # 6. Alternative agents loading & cards
    old_alt_load = '''  grid.innerHTML = `<div class="card muted" style="padding:32px;text-align:center;grid-column:1/-1">
    <div style="font-size:20px;margin-bottom:8px">🔄</div>
    <div>동일·유사 추천 에이전트를 탐색하고 상위 호환 순위를 계산하는 중입니다...</div>
  </div>`;'''

    new_alt_load = '''  grid.innerHTML = `<div class="card muted" style="padding:32px;text-align:center;grid-column:1/-1">
    <div style="margin-bottom:10px;color:#60a5fa">${ico('refresh-cw', 22, 22, 'lucide-spin')}</div>
    <div>동일·유사 추천 에이전트를 탐색하고 상위 호환 순위를 계산하는 중입니다...</div>
  </div>`;'''

    assert old_alt_load in c
    c = c.replace(old_alt_load, new_alt_load, 1)

    old_alt_cards = '''            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
              <span class="kind-badge k-${k}" style="font-size:10px">${k.toUpperCase()}</span>
              <strong style="font-size:13.5px;line-height:1.3">${esc(c.name)}</strong>
              ${c.trial_ok ? '<span title="실제 호출 검증 완료" style="color:var(--ok);font-size:12px">✔</span>' : ''}
            </div>
            <div style="display:flex;align-items:center;gap:4px">
              <span class="chip ok" style="font-size:10px;font-weight:700">🟢 정상</span>
              <span class="chip" style="font-size:10px;font-weight:700;color:#f59e0b">⭐ ${esc(grade)}</span>
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px">
            <span class="chip" style="font-size:10.5px">${esc(c.category || 'automation')}</span>
            <span class="chip" style="font-size:10.5px;background:rgba(16,185,129,0.12);color:var(--ok);font-weight:700">
              🎯 ${simPct}% 일치 (${esc(c.match_reason || '추천')})
            </span>
            ${toolCount ? `<span class="chip mono" style="font-size:10px">도구 ${toolCount}개</span>` : ''}
          </div>

          <p class="muted" style="margin:0 0 8px;font-size:11.5px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">
            ${esc(c.description || '표준 통신 규격을 준수하는 검증된 전문 에이전트입니다.')}
          </p>

          ${toolChips ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px">${toolChips}</div>` : ''}
        </div>

        <div style="border-top:1px solid var(--line);padding-top:10px;display:flex;justify-content:space-between;align-items:center;gap:8px">
          <button class="btn sm btn-view-spec" data-agent-id="${c.id}" type="button" style="font-size:11.5px;padding:5px 10px">
            🔍 상세 내용 보기
          </button>
          <button class="btn sm primary btn-direct-replace" data-agent-id="${c.id}" type="button" style="font-size:11.5px;font-weight:700;padding:5px 14px;background:linear-gradient(135deg, #10b981 0%, #059669 100%);border:none;box-shadow:0 2px 6px rgba(16,185,129,0.3)">
            ${currentReplacementMode === 'select' ? '⚡ 이 에이전트 선택' : '⚡ 바로 교체'}
          </button>'''

    new_alt_cards = '''            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
              <span class="kind-badge k-${k}" style="font-size:10px">${k.toUpperCase()}</span>
              <strong style="font-size:13.5px;line-height:1.3">${esc(c.name)}</strong>
              ${c.trial_ok ? `<span title="실제 호출 검증 완료" style="color:var(--ok);display:inline-flex;align-items:center">${ico('check-circle-2', 12, 12)}</span>` : ''}
            </div>
            <div style="display:flex;align-items:center;gap:4px">
              <span class="chip ok" style="font-size:10px;font-weight:700;display:inline-flex;align-items:center;gap:3px">${ico('check-circle-2', 10, 10)} <span>정상</span></span>
              <span class="chip" style="font-size:10px;font-weight:700;color:#f59e0b;display:inline-flex;align-items:center;gap:3px">${ico('star', 10, 10, 'fill-amber')} <span>${esc(grade)}</span></span>
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px">
            <span class="chip" style="font-size:10.5px">${esc(c.category || 'automation')}</span>
            <span class="chip" style="font-size:10.5px;background:rgba(16,185,129,0.12);color:var(--ok);font-weight:700">
              일치도 ${simPct}% (${esc(c.match_reason || '추천')})
            </span>
            ${toolCount ? `<span class="chip mono" style="font-size:10px">도구 ${toolCount}개</span>` : ''}
          </div>

          <p class="muted" style="margin:0 0 8px;font-size:11.5px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">
            ${esc(c.description || '표준 통신 규격을 준수하는 검증된 전문 에이전트입니다.')}
          </p>

          ${toolChips ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px">${toolChips}</div>` : ''}
        </div>

        <div style="border-top:1px solid var(--line);padding-top:10px;display:flex;justify-content:space-between;align-items:center;gap:8px">
          <button class="btn sm btn-view-spec" data-agent-id="${c.id}" type="button" style="font-size:11.5px;padding:5px 10px;display:inline-flex;align-items:center;gap:4px">
            ${ico('search', 12, 12)}
            <span>상세 내용 보기</span>
          </button>
          <button class="btn sm primary btn-direct-replace" data-agent-id="${c.id}" type="button" style="font-size:11.5px;font-weight:700;padding:5px 14px;background:linear-gradient(135deg, #10b981 0%, #059669 100%);border:none;box-shadow:0 2px 6px rgba(16,185,129,0.3);display:inline-flex;align-items:center;gap:4px">
            ${currentReplacementMode === 'select' ? `${ico('zap', 12, 12)} <span>이 에이전트 선택</span>` : `${ico('refresh-cw', 12, 12)} <span>바로 교체</span>`}
          </button>'''

    assert old_alt_cards in c
    c = c.replace(old_alt_cards, new_alt_cards, 1)

    # 7. showAgentReplacementDetail
    old_detail_head = '''          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap">
            <span class="kind-badge k-${k}" style="font-size:11px">${k.toUpperCase()}</span>
            <h3 style="margin:0;font-size:17px">${esc(agent.name)}</h3>
            <span class="chip ok" style="font-size:10.5px;font-weight:700">🟢 정상 가동 (Healthy)</span>
            <span class="chip" style="font-size:10.5px;font-weight:700;color:#f59e0b">⭐ ${esc(agent.eval_grade || 'A')} 등급 (${agent.eval_score || 95}점)</span>
          </div>
          <p class="muted" style="margin:0;font-size:12.5px;line-height:1.5">${esc(agent.description || '검증된 대체 에이전트입니다.')}</p>
        </div>
        <div style="text-align:right">
          <div class="chip" style="font-size:12px;background:rgba(16,185,129,0.12);color:var(--ok);font-weight:700;padding:4px 10px">
            🎯 ${agent.similarity_pct || 90}% 추천 일치
          </div>
        </div>
      </div>

      <dl class="kv" style="margin:10px 0 0;font-size:12px">
        <dt style="color:var(--muted)">엔드포인트 URL</dt>
        <dd style="font-family:monospace;word-break:break-all">${esc(agent.url || '-')}</dd>
        <dt style="color:var(--muted)">카테고리</dt>
        <dd>${esc(agent.category || 'automation')}</dd>
        <dt style="color:var(--muted)">호출 과금 / 정산</dt>
        <dd>${agent.price_usdc ? `${agent.price_usdc} USDC` : '무료 (Free / Open)'}</dd>
        <dt style="color:var(--muted)">추천 사유</dt>
        <dd><strong style="color:var(--ok)">${esc(agent.match_reason || '동일 카테고리 및 최상위 가동률 보장')}</strong></dd>
      </dl>
    </div>

    <div>
      <h4 style="margin:0 0 8px;font-size:13.5px">🛠️ 지원 도구 및 기능 명세 (${tools.length}개)</h4>
      <div>${toolsHtml}</div>
    </div>
  `;

  const confirmBtnText = currentReplacementMode === "select" ? "⚡ 이 에이전트로 연결하기" : "🔄 이 에이전트로 교체하기";
  if ($("btnConfirmReplaceTop")) {
    $("btnConfirmReplaceTop").textContent = confirmBtnText;
    $("btnConfirmReplaceTop").onclick = () => executeAgentReplacement(replacementTargetNodeId, agent);
  }
  if ($("btnConfirmReplaceBottom")) {
    $("btnConfirmReplaceBottom").textContent = confirmBtnText;
    $("btnConfirmReplaceBottom").onclick = () => executeAgentReplacement(replacementTargetNodeId, agent);
  }'''

    new_detail_head = '''          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap">
            <span class="kind-badge k-${k}" style="font-size:11px">${k.toUpperCase()}</span>
            <h3 style="margin:0;font-size:17px">${esc(agent.name)}</h3>
            <span class="chip ok" style="font-size:10.5px;font-weight:700;display:inline-flex;align-items:center;gap:3px">${ico('check-circle-2', 11, 11)} <span>정상 가동 (Healthy)</span></span>
            <span class="chip" style="font-size:10.5px;font-weight:700;color:#f59e0b;display:inline-flex;align-items:center;gap:3px">${ico('star', 11, 11, 'fill-amber')} <span>${esc(agent.eval_grade || 'A')} 등급 (${agent.eval_score || 95}점)</span></span>
          </div>
          <p class="muted" style="margin:0;font-size:12.5px;line-height:1.5">${esc(agent.description || '검증된 대체 에이전트입니다.')}</p>
        </div>
        <div style="text-align:right">
          <div class="chip" style="font-size:12px;background:rgba(16,185,129,0.12);color:var(--ok);font-weight:700;padding:4px 10px">
            일치도 ${agent.similarity_pct || 90}% 추천 일치
          </div>
        </div>
      </div>

      <dl class="kv" style="margin:10px 0 0;font-size:12px">
        <dt style="color:var(--muted)">엔드포인트 URL</dt>
        <dd style="font-family:monospace;word-break:break-all">${esc(agent.url || '-')}</dd>
        <dt style="color:var(--muted)">카테고리</dt>
        <dd>${esc(agent.category || 'automation')}</dd>
        <dt style="color:var(--muted)">호출 과금 / 정산</dt>
        <dd>${agent.price_usdc ? `${agent.price_usdc} USDC` : '무료 (Free / Open)'}</dd>
        <dt style="color:var(--muted)">추천 사유</dt>
        <dd><strong style="color:var(--ok)">${esc(agent.match_reason || '동일 카테고리 및 최상위 가동률 보장')}</strong></dd>
      </dl>
    </div>

    <div>
      <h4 style="margin:0 0 8px;font-size:13.5px;display:flex;align-items:center;gap:6px">
        ${ico('wrench', 14, 14)}
        <span>지원 도구 및 기능 명세 (${tools.length}개)</span>
      </h4>
      <div>${toolsHtml}</div>
    </div>
  `;

  const confirmBtnHtml = currentReplacementMode === "select"
    ? `${ico('zap', 13, 13)} <span>이 에이전트로 연결하기</span>`
    : `${ico('refresh-cw', 13, 13)} <span>이 에이전트로 교체하기</span>`;
  if ($("btnConfirmReplaceTop")) {
    $("btnConfirmReplaceTop").innerHTML = confirmBtnHtml;
    $("btnConfirmReplaceTop").onclick = () => executeAgentReplacement(replacementTargetNodeId, agent);
  }
  if ($("btnConfirmReplaceBottom")) {
    $("btnConfirmReplaceBottom").innerHTML = confirmBtnHtml;
    $("btnConfirmReplaceBottom").onclick = () => executeAgentReplacement(replacementTargetNodeId, agent);
  }'''

    assert old_detail_head in c
    c = c.replace(old_detail_head, new_detail_head, 1)

    # 8. Replacement toasts
    old_repl_toast = '''  const toastMsg = currentReplacementMode === "select"
    ? `✅ '${newAgent.name}' 에이전트가 노드에 성공적으로 연결되었습니다.`
    : `✨ '${oldName}' 노드가 정상 가동 중인 '${newAgent.name}'(으)로 성공적으로 교체되었습니다!`;
  toast(toastMsg);'''

    new_repl_toast = '''  const toastMsg = currentReplacementMode === "select"
    ? `'${newAgent.name}' 에이전트가 노드에 성공적으로 연결되었습니다.`
    : `'${oldName}' 노드가 정상 가동 중인 '${newAgent.name}'(으)로 성공적으로 교체되었습니다!`;
  toast(toastMsg);'''

    assert old_repl_toast in c
    c = c.replace(old_repl_toast, new_repl_toast, 1)

    old_suspend_toast = '''    toast(`🟢 '${node.name}' 노드가 정상 가동 상태로 복원되었습니다.`);
  } else {
    node.is_active = false;
    node.disabled = true;
    node.data = node.data || {};
    node.data.is_active = false;
    node.data.status = "suspended";
    node.data.suspend_reason = "원격 서버 응답 불가 (서비스 중지됨)";
    toast(`⚠️ '${node.name}' 노드가 서비스 중지(비활성화) 상태로 전환되었습니다. 노드에 교체 버튼이 활성화됩니다.`);
  }'''

    new_suspend_toast = '''    toast(`'${node.name}' 노드가 정상 가동 상태로 복원되었습니다.`);
  } else {
    node.is_active = false;
    node.disabled = true;
    node.data = node.data || {};
    node.data.is_active = false;
    node.data.status = "suspended";
    node.data.suspend_reason = "원격 서버 응답 불가 (서비스 중지됨)";
    toast(`'${node.name}' 노드가 서비스 중지(비활성화) 상태로 전환되었습니다. 노드에 교체 버튼이 활성화됩니다.`);
  }'''

    assert old_suspend_toast in c
    c = c.replace(old_suspend_toast, new_suspend_toast, 1)

    with open('agent_market/gateway/dashboard.html', 'w', encoding='utf-8') as f:
        f.write(c)
    print("Templates and modals modernized successfully!")

if __name__ == '__main__':
    update_templates_and_modals()
