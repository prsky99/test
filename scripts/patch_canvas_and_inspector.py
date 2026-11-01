"""
Python script to update workflow canvas, inspector, and execution functions with Lucide SVG icons.
"""

def update_canvas_and_inspector():
    with open('agent_market/gateway/dashboard.html', 'r', encoding='utf-8') as f:
        c = f.read()

    # 1. Update loadWorkflows template options and gallery prompt
    old_opts = '''      if (templateWorkflows.length > 0) {
        opts += `<optgroup label="📚 추천 검증 템플릿 (TOP ${Math.min(15, templateWorkflows.length)})">` +
          templateWorkflows.slice(0, 15).map(w => `<option value="${w.id}">★ ${esc(w.name)} (${esc(w.category || 'automation')})</option>`).join("") +
          `</optgroup>`;
      }

      opts += `<option value="__open_gallery__">🔍 전체 100+ 템플릿 갤러리 탐색 열기...</option>`;'''

    new_opts = '''      if (templateWorkflows.length > 0) {
        opts += `<optgroup label="추천 검증 템플릿 (TOP ${Math.min(15, templateWorkflows.length)})">` +
          templateWorkflows.slice(0, 15).map(w => `<option value="${w.id}">[추천] ${esc(w.name)} (${esc(w.category || 'automation')})</option>`).join("") +
          `</optgroup>`;
      }

      opts += `<option value="__open_gallery__">전체 100+ 템플릿 갤러리 탐색 열기...</option>`;'''

    assert old_opts in c, "Could not find old_opts in dashboard.html"
    c = c.replace(old_opts, new_opts, 1)

    # 2. focusAiComposer toast
    old_ai_toast = 'toast("✨ AI 자동 생성 프롬프트를 입력하고 Enter를 누르세요.");'
    new_ai_toast = 'toast("AI 자동 생성 프롬프트를 입력하고 Enter를 누르세요.");'
    assert old_ai_toast in c
    c = c.replace(old_ai_toast, new_ai_toast, 1)

    # 3. renderNodes
    old_empty_hero = '''  if (canvasGraph.nodes.length === 0) {
    container.innerHTML = `
      <div class="wf-empty-hero" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:min(660px,94%);background:var(--card, var(--panel));border:1px solid var(--line);border-radius:16px;box-shadow:0 12px 32px rgba(0,0,0,0.12);padding:28px 32px;text-align:center;z-index:10;pointer-events:auto">
        <div style="width:52px;height:52px;border-radius:14px;background:linear-gradient(135deg, rgba(59,130,246,0.15) 0%, rgba(139,92,246,0.15) 100%);margin:0 auto 12px;display:flex;align-items:center;justify-content:center;color:var(--accent)">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="8" height="8" x="3" y="3" rx="2"/><path d="M7 11v4a2 2 0 0 0 2 2h4"/><rect width="8" height="8" x="13" y="13" rx="2"/></svg>
        </div>
        <h3 style="margin:0 0 8px;font-size:18px;font-weight:700">새로운 워크플로우 캔버스</h3>
        <p class="muted" style="margin:0 0 20px;font-size:13px;line-height:1.55">
          검증된 산업별 자동화 템플릿을 탐색하거나, AI 자연어로 파이프라인을 자동 생성하거나,<br>
          새 노드를 자유롭게 추가하고 연결하여 나만의 자율 DAG 오케스트레이션을 완성하세요.
        </p>

        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:12px;margin-bottom:18px;text-align:left">
          <div class="wf-quick-card" onclick="openTemplateGalleryModal()" style="cursor:pointer;padding:14px;border:1px solid var(--line);border-radius:10px;background:var(--bg);transition:all .15s ease">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <span style="font-size:18px">📚</span>
              <strong style="font-size:13.5px">템플릿 갤러리</strong>
            </div>
            <div class="muted" style="font-size:11.5px;line-height:1.4">100+ 산업별 검증 템플릿 탐색 및 1-클릭 로드</div>
            <div style="margin-top:8px;font-size:11.5px;color:var(--accent);font-weight:600">템플릿 열기 →</div>
          </div>

          <div class="wf-quick-card" onclick="focusAiComposer()" style="cursor:pointer;padding:14px;border:1px solid var(--line);border-radius:10px;background:var(--bg);transition:all .15s ease">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <span style="font-size:18px">✨</span>
              <strong style="font-size:13.5px">AI 자동 생성</strong>
            </div>
            <div class="muted" style="font-size:11.5px;line-height:1.4">자연어 한 줄로 최적의 에이전트 파이프라인 합성</div>
            <div style="margin-top:8px;font-size:11.5px;color:#a855f7;font-weight:600">프롬프트 작성 →</div>
          </div>

          <div class="wf-quick-card" onclick="canvasAddNode('trigger')" style="cursor:pointer;padding:14px;border:1px solid var(--line);border-radius:10px;background:var(--bg);transition:all .15s ease">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <span style="font-size:18px">➕</span>
              <strong style="font-size:13.5px">새 노드로 시작</strong>
            </div>
            <div class="muted" style="font-size:11.5px;line-height:1.4">트리거 노드를 배치하고 수동으로 노드 연결</div>
            <div style="margin-top:8px;font-size:11.5px;color:var(--ok);font-weight:600">트리거 추가 →</div>
          </div>
        </div>

        <div style="display:flex;align-items:center;justify-content:center;gap:16px;font-size:11.5px;color:var(--muted);border-top:1px dashed var(--line);padding-top:12px">
          <span>💡 <strong>사용 팁:</strong> 노드 우측 포트(●)를 드래그하여 다른 노드 좌측 포트(●)에 연결하면 데이터 흐름이 이어집니다.</span>
        </div>
      </div>
    `;
    return;
  }'''

    new_empty_hero = '''  if (canvasGraph.nodes.length === 0) {
    container.innerHTML = `
      <div class="wf-empty-hero" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:min(660px,94%);background:rgba(15,23,42,0.88);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid rgba(59,130,246,0.3);border-radius:18px;box-shadow:0 20px 50px rgba(0,0,0,0.5),inset 0 1px 0 rgba(255,255,255,0.08);padding:32px 36px;text-align:center;z-index:10;pointer-events:auto">
        <div style="width:56px;height:56px;border-radius:16px;background:linear-gradient(135deg, rgba(59,130,246,0.2) 0%, rgba(139,92,246,0.2) 100%);border:1px solid rgba(59,130,246,0.35);margin:0 auto 14px;display:flex;align-items:center;justify-content:center;color:#60a5fa;box-shadow:0 0 25px rgba(59,130,246,0.25)">
          ${ico('workflow', 30, 30)}
        </div>
        <h3 style="margin:0 0 8px;font-size:19px;font-weight:700;color:var(--text);letter-spacing:-0.02em">새로운 워크플로우 캔버스</h3>
        <p class="muted" style="margin:0 0 22px;font-size:13px;line-height:1.6;color:var(--muted)">
          검증된 산업별 자동화 템플릿을 탐색하거나, AI 자연어로 파이프라인을 자동 생성하거나,<br>
          새 노드를 자유롭게 추가하고 연결하여 나만의 자율 DAG 오케스트레이션을 완성하세요.
        </p>

        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:12px;margin-bottom:20px;text-align:left">
          <div class="wf-quick-card" onclick="openTemplateGalleryModal()" style="cursor:pointer;padding:16px;border:1px solid rgba(255,255,255,0.08);border-radius:12px;background:rgba(255,255,255,0.03);backdrop-filter:blur(8px);transition:all .2s ease">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;color:#60a5fa">
              ${ico('library', 18, 18)}
              <strong style="font-size:13.5px;color:var(--text)">템플릿 갤러리</strong>
            </div>
            <div class="muted" style="font-size:11.5px;line-height:1.45">100+ 산업별 검증 템플릿 탐색 및 1-클릭 로드</div>
            <div style="margin-top:10px;font-size:11.5px;color:var(--accent);font-weight:600;display:flex;align-items:center;gap:4px">
              <span>템플릿 열기</span>
              ${ico('arrow-right', 12, 12)}
            </div>
          </div>

          <div class="wf-quick-card" onclick="focusAiComposer()" style="cursor:pointer;padding:16px;border:1px solid rgba(168,85,247,0.2);border-radius:12px;background:rgba(168,85,247,0.04);backdrop-filter:blur(8px);transition:all .2s ease">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;color:#c084fc">
              ${ico('sparkles', 18, 18)}
              <strong style="font-size:13.5px;color:var(--text)">AI 자동 생성</strong>
            </div>
            <div class="muted" style="font-size:11.5px;line-height:1.45">자연어 한 줄로 최적의 에이전트 파이프라인 합성</div>
            <div style="margin-top:10px;font-size:11.5px;color:#c084fc;font-weight:600;display:flex;align-items:center;gap:4px">
              <span>프롬프트 작성</span>
              ${ico('arrow-right', 12, 12)}
            </div>
          </div>

          <div class="wf-quick-card" onclick="canvasAddNode('trigger')" style="cursor:pointer;padding:16px;border:1px solid rgba(16,185,129,0.2);border-radius:12px;background:rgba(16,185,129,0.04);backdrop-filter:blur(8px);transition:all .2s ease">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;color:#34d399">
              ${ico('plus-circle', 18, 18)}
              <strong style="font-size:13.5px;color:var(--text)">새 노드로 시작</strong>
            </div>
            <div class="muted" style="font-size:11.5px;line-height:1.45">트리거 노드를 배치하고 수동으로 노드 연결</div>
            <div style="margin-top:10px;font-size:11.5px;color:var(--ok);font-weight:600;display:flex;align-items:center;gap:4px">
              <span>트리거 추가</span>
              ${ico('arrow-right', 12, 12)}
            </div>
          </div>
        </div>

        <div style="display:flex;align-items:center;justify-content:center;gap:8px;font-size:11.5px;color:var(--muted);border-top:1px dashed rgba(255,255,255,0.08);padding-top:14px">
          ${ico('info', 13, 13, 'text-accent')}
          <span><strong>사용 팁:</strong> 노드 우측 포트(●)를 드래그하여 다른 노드 좌측 포트(●)에 연결하면 데이터 흐름이 이어집니다.</span>
        </div>
      </div>
    `;
    return;
  }'''

    assert old_empty_hero in c, "Could not find old_empty_hero in dashboard.html"
    c = c.replace(old_empty_hero, new_empty_hero, 1)

    # 4. renderNodes node cards badges & suspended notice
    old_node_card = '''          <div style="display:flex;align-items:center;gap:4px">
            ${isSuspended ? '<span class="chip sm bad" style="font-size:9px;padding:1px 5px;font-weight:700">⛔ 중지됨</span>' : ''}
            ${ndata.is_custom_input ? '<span class="chip sm" style="font-size:8.5px;padding:1px 4px;background:rgba(59,130,246,0.18);color:#60a5fa;border:1px solid rgba(59,130,246,0.3);font-weight:700">✏️ 수정됨</span>' : ''}
            <span class="status-indicator mono" id="nodeStatus-${n.id}" style="color:${isSuspended ? 'var(--bad)' : 'var(--muted)'};font-size:11px">●</span>
          </div>
        </div>
        <div class="wf-node-body">
          <div style="font-family:monospace;font-size:11px;color:var(--muted);word-break:break-all">${esc(actLabel)}</div>
          <div class="muted" style="font-size:10.5px;line-height:1.3;max-height:28px;overflow:hidden;text-overflow:ellipsis">${esc(desc)}</div>
          ${isSuspended ? `
            <div class="wf-suspended-notice">⚠️ ${esc(suspendMsg)}</div>
            <button class="btn-replace-node-trigger" data-node-id="${n.id}" type="button" title="원클릭으로 정상 서비스 중인 대체 에이전트로 교체">
              🔄 대체 에이전트 교체
            </button>
          ` : ''}'''

    new_node_card = '''          <div style="display:flex;align-items:center;gap:4px">
            ${isSuspended ? `<span class="chip sm bad" style="font-size:9px;padding:1px 5px;font-weight:700;display:inline-flex;align-items:center;gap:3px">${ico('alert-octagon', 10, 10)} <span>중지됨</span></span>` : ''}
            ${ndata.is_custom_input ? `<span class="chip sm" style="font-size:8.5px;padding:1px 4px;background:rgba(59,130,246,0.18);color:#60a5fa;border:1px solid rgba(59,130,246,0.3);font-weight:700;display:inline-flex;align-items:center;gap:2px">${ico('edit-3', 9, 9)} <span>수정됨</span></span>` : ''}
            <span class="status-indicator mono" id="nodeStatus-${n.id}" style="color:${isSuspended ? 'var(--bad)' : 'var(--muted)'};font-size:11px">●</span>
          </div>
        </div>
        <div class="wf-node-body">
          <div style="font-family:monospace;font-size:11px;color:var(--muted);word-break:break-all">${esc(actLabel)}</div>
          <div class="muted" style="font-size:10.5px;line-height:1.3;max-height:28px;overflow:hidden;text-overflow:ellipsis">${esc(desc)}</div>
          ${isSuspended ? `
            <div class="wf-suspended-notice" style="display:flex;align-items:center;gap:4px">
              ${ico('alert-triangle', 11, 11)}
              <span>${esc(suspendMsg)}</span>
            </div>
            <button class="btn-replace-node-trigger" data-node-id="${n.id}" type="button" title="원클릭으로 정상 서비스 중인 대체 에이전트로 교체" style="display:inline-flex;align-items:center;justify-content:center;gap:4px">
              ${ico('refresh-cw', 11, 11)}
              <span>대체 에이전트 교체</span>
            </button>
          ` : ''}'''

    assert old_node_card in c, "Could not find old_node_card in dashboard.html"
    c = c.replace(old_node_card, new_node_card, 1)

    # 5. openInspector badges
    old_insp_badges = '''      if ($("inspAgentHealthBadge")) {
        $("inspAgentHealthBadge").innerHTML = isSusp
          ? '<span class="chip bad sm" style="font-size:10px;font-weight:700">⛔ 서비스 중단</span>'
          : '<span class="chip ok sm" style="font-size:10px;font-weight:700">🟢 정상 가동 (Live)</span>';
      }'''

    new_insp_badges = '''      if ($("inspAgentHealthBadge")) {
        $("inspAgentHealthBadge").innerHTML = isSusp
          ? `<span class="chip bad sm" style="font-size:10px;font-weight:700;display:inline-flex;align-items:center;gap:3px">${ico('alert-octagon', 11, 11)} <span>서비스 중단</span></span>`
          : `<span class="chip ok sm" style="font-size:10px;font-weight:700;display:inline-flex;align-items:center;gap:3px">${ico('check-circle-2', 11, 11)} <span>정상 가동 (Live)</span></span>`;
      }'''

    assert old_insp_badges in c
    c = c.replace(old_insp_badges, new_insp_badges, 1)

    old_insp_status = '''      $("inspStatusBadge").innerHTML = isSusp
        ? '<span class="chip bad" style="font-size:10px;font-weight:700">⛔ 서비스 중단</span>'
        : '<span class="chip ok" style="font-size:10px;font-weight:700">🟢 정상 가동</span>';

      const toggleBtn = $("btnToggleNodeSuspend");
      if (toggleBtn) {
        toggleBtn.textContent = isSusp ? "🟢 정상 활성화로 복원" : "⚠️ 서비스 중지(비활성화) 전환";
        toggleBtn.className = `btn sm ${isSusp ? 'ok' : 'bad'}`;
        toggleBtn.onclick = () => toggleNodeSuspendStatus(node.id);
      }'''

    new_insp_status = '''      $("inspStatusBadge").innerHTML = isSusp
        ? `<span class="chip bad" style="font-size:10px;font-weight:700;display:inline-flex;align-items:center;gap:3px">${ico('alert-octagon', 11, 11)} <span>서비스 중단</span></span>`
        : `<span class="chip ok" style="font-size:10px;font-weight:700;display:inline-flex;align-items:center;gap:3px">${ico('check-circle-2', 11, 11)} <span>정상 가동</span></span>`;

      const toggleBtn = $("btnToggleNodeSuspend");
      if (toggleBtn) {
        toggleBtn.innerHTML = isSusp
          ? `${ico('check-circle-2', 13, 13)} <span>정상 활성화로 복원</span>`
          : `${ico('alert-triangle', 13, 13)} <span>서비스 중지(비활성화) 전환</span>`;
        toggleBtn.className = `btn sm ${isSusp ? 'ok' : 'bad'}`;
        toggleBtn.style.display = "inline-flex";
        toggleBtn.style.alignItems = "center";
        toggleBtn.style.gap = "5px";
        toggleBtn.onclick = () => toggleNodeSuspendStatus(node.id);
      }'''

    assert old_insp_status in c
    c = c.replace(old_insp_status, new_insp_status, 1)

    # 6. testSingleNode
    old_single_test = '''    if (node.type === "trigger") {
      result = { status: "triggered", timestamp: new Date().toISOString(), message: "트리거 신호 정상 발화" };
      toast(`⚡ '${node.name}' 트리거가 성공적으로 발화되었습니다.`);
    } else if (node.type === "router") {
      result = { condition: "default", routed_to: "next_node", status: "routed" };
      toast(`🔀 '${node.name}' 라우팅 조건 분기 완료`);
    } else if (node.resource_id) {
      const payload = {
        resource_id: parseInt(node.resource_id),
        action: node.data?.action || "tools/call",
        tool: node.data?.action || node.data?.tool || "",
        arguments: typeof node.data?.input === "object" ? node.data?.input : {},
        message: typeof node.data?.input === "string" ? node.data?.input : JSON.stringify(node.data?.input || {})
      };
      const res = await api("/admin/api/test/execute", {
        method: "POST",
        json: payload,
        silent: true
      });
      if (res && res.ok) {
        result = res.output || res.response_wire || res;
        latency = res.latency_ms || 45;
        toast(`✅ '${node.name}' 단일 테스트 성공 (${latency}ms)`);
      } else {
        throw new Error((res && res.error) || "응답 실패");
      }
    } else {
      result = {
        node: node.name,
        kind: node.kind,
        action: node.data?.action || "execute",
        input: node.data?.input || {},
        output: `[${node.name}] 실행 결과가 정상적으로 생성되었습니다.`,
        status: "ok"
      };
      toast(`🟢 '${node.name}' 시뮬레이션 테스트 완료`);
    }

    node.data = node.data || {};
    node.data.sample_output = result;

    const badge = $(`nodeBadge-${node.id}`);
    if (badge) {
      badge.textContent = `🟢 테스트 통과 (${latency}ms)`;
      badge.className = "chip ok";
      badge.style.display = "block";
    }
  } catch (err) {
    toast(`⚠️ 단일 테스트 실패: ${err.message}`);
    const badge = $(`nodeBadge-${node.id}`);
    if (badge) {
      badge.textContent = `❌ 테스트 실패`;
      badge.className = "chip bad";
      badge.style.display = "block";
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "▶ 단일 테스트";
    }
  }'''

    new_single_test = '''    if (node.type === "trigger") {
      result = { status: "triggered", timestamp: new Date().toISOString(), message: "트리거 신호 정상 발화" };
      toast(`'${node.name}' 트리거가 성공적으로 발화되었습니다.`);
    } else if (node.type === "router") {
      result = { condition: "default", routed_to: "next_node", status: "routed" };
      toast(`'${node.name}' 라우팅 조건 분기 완료`);
    } else if (node.resource_id) {
      const payload = {
        resource_id: parseInt(node.resource_id),
        action: node.data?.action || "tools/call",
        tool: node.data?.action || node.data?.tool || "",
        arguments: typeof node.data?.input === "object" ? node.data?.input : {},
        message: typeof node.data?.input === "string" ? node.data?.input : JSON.stringify(node.data?.input || {})
      };
      const res = await api("/admin/api/test/execute", {
        method: "POST",
        json: payload,
        silent: true
      });
      if (res && res.ok) {
        result = res.output || res.response_wire || res;
        latency = res.latency_ms || 45;
        toast(`'${node.name}' 단일 테스트 성공 (${latency}ms)`);
      } else {
        throw new Error((res && res.error) || "응답 실패");
      }
    } else {
      result = {
        node: node.name,
        kind: node.kind,
        action: node.data?.action || "execute",
        input: node.data?.input || {},
        output: `[${node.name}] 실행 결과가 정상적으로 생성되었습니다.`,
        status: "ok"
      };
      toast(`'${node.name}' 시뮬레이션 테스트 완료`);
    }

    node.data = node.data || {};
    node.data.sample_output = result;

    const badge = $(`nodeBadge-${node.id}`);
    if (badge) {
      badge.innerHTML = `${ico('check-circle-2', 11, 11)} <span>테스트 통과 (${latency}ms)</span>`;
      badge.className = "chip ok";
      badge.style.display = "inline-flex";
      badge.style.alignItems = "center";
      badge.style.gap = "3px";
    }
  } catch (err) {
    toast(`단일 테스트 실패: ${err.message}`);
    const badge = $(`nodeBadge-${node.id}`);
    if (badge) {
      badge.innerHTML = `${ico('alert-octagon', 11, 11)} <span>테스트 실패</span>`;
      badge.className = "chip bad";
      badge.style.display = "inline-flex";
      badge.style.alignItems = "center";
      badge.style.gap = "3px";
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `${ico('play', 12, 12)} <span>단일 테스트</span>`;
    }
  }'''

    assert old_single_test in c
    c = c.replace(old_single_test, new_single_test, 1)

    # 7. runActiveCanvasWorkflow execution indicators & bridges
    old_run_empty = 'return alert("캔버스에 실행할 노드가 없습니다. 상단 \'📚 템플릿 갤러리 탐색\'에서 템플릿을 불러오거나 \'+ 노드 추가\'로 파이프라인을 구성해주세요.");'
    new_run_empty = 'return alert("캔버스에 실행할 노드가 없습니다. 상단 \'템플릿 갤러리 탐색\'에서 템플릿을 불러오거나 \'+ 노드 추가\'로 파이프라인을 구성해주세요.");'
    assert old_run_empty in c
    c = c.replace(old_run_empty, new_run_empty, 1)

    old_run_node_anim = '''      if (el) el.classList.add("running");
      if (st) { st.textContent = "⚡"; st.style.color = "#3b82f6"; }

      await new Promise(resolve => setTimeout(resolve, 200));

      if (el) {
        el.classList.remove("running");
        el.classList.add("completed");
      }
      if (st) { st.textContent = "✔"; st.style.color = "var(--ok)"; }
      if (bg) {
        bg.textContent = `⚡ ${r.latency_ms}ms · OK`;
        bg.style.display = "block";
      }'''

    new_run_node_anim = '''      if (el) el.classList.add("running");
      if (st) { st.innerHTML = ico('zap', 12, 12); st.style.color = "#3b82f6"; }

      await new Promise(resolve => setTimeout(resolve, 200));

      if (el) {
        el.classList.remove("running");
        el.classList.add("completed");
      }
      if (st) { st.innerHTML = ico('check-circle-2', 12, 12); st.style.color = "var(--ok)"; }
      if (bg) {
        bg.innerHTML = `${ico('zap', 10, 10)} <span>${r.latency_ms}ms · OK</span>`;
        bg.style.display = "inline-flex";
        bg.style.alignItems = "center";
        bg.style.gap = "3px";
      }'''

    assert old_run_node_anim in c
    c = c.replace(old_run_node_anim, new_run_node_anim, 1)

    # 8. Data flow trace & steps list
    old_data_flow = '''          <div class="wf-data-bridge" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
            <div style="display:flex;align-items:center;gap:8px">
              <span class="chip sm" style="font-size:10px;font-weight:700">전달 #${idx + 1}</span>
              <strong>${esc(df.source_name)}</strong>
              <span style="color:#60a5fa">──▶</span>
              <strong>${esc(df.target_name)}</strong>
            </div>
            <div style="font-size:11.5px;color:var(--muted);max-width:380px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(df.passed_data_summary)}">
              📦 <span style="color:var(--text)">${esc(df.passed_data_summary)}</span>
            </div>
            <span class="chip ok sm" style="font-size:10px">${df.size_bytes} Bytes · ${esc(df.status)}</span>
          </div>'''

    new_data_flow = '''          <div class="wf-data-bridge" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
            <div style="display:flex;align-items:center;gap:8px">
              <span class="chip sm" style="font-size:10px;font-weight:700">전달 #${idx + 1}</span>
              <strong>${esc(df.source_name)}</strong>
              <span style="color:#60a5fa;display:inline-flex;align-items:center">${ico('arrow-right', 13, 13)}</span>
              <strong>${esc(df.target_name)}</strong>
            </div>
            <div style="font-size:11.5px;color:var(--muted);max-width:380px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:flex;align-items:center;gap:4px" title="${esc(df.passed_data_summary)}">
              ${ico('package', 12, 12)} <span style="color:var(--text)">${esc(df.passed_data_summary)}</span>
            </div>
            <span class="chip ok sm" style="font-size:10px">${df.size_bytes} Bytes · ${esc(df.status)}</span>
          </div>'''

    assert old_data_flow in c
    c = c.replace(old_data_flow, new_data_flow, 1)

    old_steps_applied = '''          ${hasInput ? `
            <div style="font-size:11px;color:#60a5fa;margin-bottom:6px;background:rgba(59,130,246,0.08);padding:5px 8px;border-radius:4px;border:1px solid rgba(59,130,246,0.2)">
              ⚙️ <strong>적용된 입력 인자 (Applied Input):</strong> <span class="mono">${esc(s.input)}</span>
            </div>
          ` : ''}
          <div style="font-size:12px;color:var(--text);line-height:1.55;white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;background:rgba(0,0,0,0.22);padding:10px 12px;border-radius:6px;overflow-x:auto">${esc(s.output)}</div>
          ${nextStep ? `
            <div class="wf-data-bridge" style="margin-top:8px">
              <span>⬇️</span>
              <span><strong>${esc(s.name)}</strong> 출력 결과가 다음 <strong>Step ${idx + 2} (${esc(nextStep.name)})</strong>의 입력 컨텍스트로 전달되어 실시간 처리되었습니다.</span>
            </div>
          ` : `
            <div class="wf-data-bridge" style="margin-top:8px;border-color:rgba(16,185,129,0.35);background:rgba(16,185,129,0.06)">
              <span>🏁</span>
              <span><strong>${esc(s.name)}</strong> 실행 완료 ➔ 전체 파이프라인 산출물이 최종 종합 결과 보고서로 합성되었습니다.</span>
            </div>
          `}'''

    new_steps_applied = '''          ${hasInput ? `
            <div style="font-size:11px;color:#60a5fa;margin-bottom:6px;background:rgba(59,130,246,0.08);padding:5px 8px;border-radius:4px;border:1px solid rgba(59,130,246,0.2);display:flex;align-items:center;gap:5px">
              ${ico('settings-2', 12, 12)} <strong>적용된 입력 인자 (Applied Input):</strong> <span class="mono">${esc(s.input)}</span>
            </div>
          ` : ''}
          <div style="font-size:12px;color:var(--text);line-height:1.55;white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;background:rgba(0,0,0,0.22);padding:10px 12px;border-radius:6px;overflow-x:auto">${esc(s.output)}</div>
          ${nextStep ? `
            <div class="wf-data-bridge" style="margin-top:8px;display:flex;align-items:center;gap:8px">
              <span>${ico('arrow-down', 13, 13)}</span>
              <span><strong>${esc(s.name)}</strong> 출력 결과가 다음 <strong>Step ${idx + 2} (${esc(nextStep.name)})</strong>의 입력 컨텍스트로 전달되어 실시간 처리되었습니다.</span>
            </div>
          ` : `
            <div class="wf-data-bridge" style="margin-top:8px;border-color:rgba(16,185,129,0.35);background:rgba(16,185,129,0.06);display:flex;align-items:center;gap:8px">
              <span>${ico('flag', 13, 13)}</span>
              <span><strong>${esc(s.name)}</strong> 실행 완료 ➔ 전체 파이프라인 산출물이 최종 종합 결과 보고서로 합성되었습니다.</span>
            </div>
          `}'''

    assert old_steps_applied in c
    c = c.replace(old_steps_applied, new_steps_applied, 1)

    # 9. AI Auto-Composer toast
    old_ai_comp_toast = 'toast("✨ 자연어 요청에 따라 검증된 에이전트 파이프라인이 자동 생성되었습니다!");'
    new_ai_comp_toast = 'toast("자연어 요청에 따라 검증된 에이전트 파이프라인이 자동 생성되었습니다!");'
    assert old_ai_comp_toast in c
    c = c.replace(old_ai_comp_toast, new_ai_comp_toast, 1)

    with open('agent_market/gateway/dashboard.html', 'w', encoding='utf-8') as f:
        f.write(c)

    print("Canvas, inspector, and execution functions modernized successfully!")

if __name__ == '__main__':
    update_canvas_and_inspector()
