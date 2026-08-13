import React, { useEffect, useRef, useState } from "react";
import { apiClient, AuthSession, HealthResponse } from "../api/client";
import { serviceStatusLabel, qwenStatusLabel } from "../helpers/format";
import { StudioRoute, routePath } from "../router";
import { User } from "../auth";
import { AppShell } from "../components/AppShell";
import { shellNavigate } from "../helpers/navigation";

// E-05 · 1 Access.dc.html의 접속·안내 흐름 화면들.
// design_handoff_dobedub_v3/1 Access.dc.html: 6a 로그인 / 7g 차단·만료·오류 / 6b 매뉴얼.
// 구버전 `.login-screen`(dark 테마) LoginView를 대체한다 - 재사용한 것은 로그인
// 로직(apiClient.login, 에러 문구 매핑)뿐이고 화면 구조·스타일은 v3 토큰으로 재작성.

// 6a · 로그인 — design_handoff 6a "로그인 · 사내 계정 · 시스템 상태 노출".
// 좌측(흰 배경) 브랜드·소개, 우측 폼 + 시스템 상태 카드의 2열 구성.
// 설계 원본과 다르게 뺀 것(더미 데이터 금지 원칙):
// - 좌측의 WORKFLOWS/이번 주 RUN/재사용 프롬프트 통계 3칸 — 로그인 전에는 인증이
//   없어 이 수치를 줄 API를 호출할 수 없다. 소개 문구만 남기고 통계 타일은 제외.
// - 시스템 상태의 "Sandbox Pod" 행 — 조회에 sandbox:read 권한이 필요해 로그인 전에는
//   알 수 없다. 공개 헬스체크(/api/health)로 알 수 있는 ComfyUI·Qwen 두 줄만 표시.
export function LoginScreen({
  onLogin,
  health,
  healthError
}: {
  onLogin: (session: AuthSession) => void;
  health: HealthResponse | null;
  healthError: string;
}) {
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const system = health?.system || health?.legacy;
  const comfyStatus = serviceStatusLabel(
    Boolean(system?.runpod?.configured),
    healthError,
    system?.dryRun ? "DRY-RUN" : undefined
  );
  const qwenStatus = qwenStatusLabel(system?.promptLlm, healthError);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const response = await apiClient.login({ id, password });
      onLogin(response);
    } catch (err) {
      setError(loginErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="v3-login">
      <section className="v3-login-brand">
        <div className="v3-login-brand-top">
          <span className="v3-login-logo" aria-hidden="true" />
          <span className="v3-login-brand-name">DOBEDUB STUDIO</span>
          <span className="v3-login-brand-badge">v3</span>
        </div>
        <div className="v3-login-hero">
          <h1 className="v3-login-hero-title">이미지 사이를 잇는<br />영상 생성 워크스페이스</h1>
          <p className="v3-login-hero-desc">
            키프레임을 올리고 세그먼트별로 프롬프트와 노드 구성값을 설정하면, 하나의 작업으로
            제출돼 구간 영상과 최종 병합본이 생성됩니다.
          </p>
        </div>
        <div className="v3-login-brand-foot">
          <span>사내 전용 · 외부 공유 금지</span>
          <span>문의 · Studio Platform</span>
        </div>
      </section>

      <section className="v3-login-panel">
        <form className="v3-login-form" onSubmit={submit}>
          <div>
            <div className="v3-label">SIGN IN</div>
            <div className="v3-login-title">DOBEDUB STUDIO | 접속</div>
          </div>

          <label className="v3-login-field">
            <span className="v3-label">ID</span>
            <input
              value={id}
              onChange={(event) => setId(event.target.value)}
              placeholder="사번 또는 계정 ID"
              autoComplete="username"
              required
            />
          </label>
          <label className="v3-login-field">
            <span className="v3-label">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="비밀번호"
              autoComplete="current-password"
              required
            />
          </label>

          <button className="v3-primary-button v3-login-submit" type="submit" disabled={submitting}>
            {submitting ? "접속 중..." : "접속하기"}
          </button>

          {error ? (
            <div className="v3-login-error" role="alert">
              <span className="v3-login-error-dot" aria-hidden="true" />
              <span>{error}</span>
            </div>
          ) : null}

          <div className="v3-login-status">
            <div className="v3-label">시스템 상태</div>
            <div className="v3-login-status-row">
              <span>ComfyUI Serverless</span>
              <strong className={`v3-login-status-value is-${comfyStatus.toLowerCase()}`}>{comfyStatus}</strong>
            </div>
            <div className="v3-login-status-row">
              <span>Qwen LLM</span>
              <strong className={`v3-login-status-value is-${qwenStatus.toLowerCase()}`}>{qwenStatus}</strong>
            </div>
          </div>

          <p className="v3-login-note">
            비활성 계정 · 미입력 오류도 같은 자리에 표시됩니다 · 세션은 탭을 닫으면 종료됩니다
          </p>
        </form>
      </section>
    </main>
  );
}

// 7g · 차단(403 권한 없음) — design_handoff 7g "차단 · 만료 · 오류 3종".
// 설계 원본은 403·401·서버오류를 한 카드 3분할로 그리지만 README는 "실제로는 별개
// 상태"라고 명시한다. 여기서는 그중 403(직접 URL 진입 시 권한 없음)만 정식 화면으로
// 구현한다 - 401 세션 만료는 토큰 만료 시 로그인 화면(6a)으로 되돌아가는 기존 동작이,
// 서버 오류는 각 화면의 인라인 notice가 담당한다.
//
// 구버전 임시 AccessDeniedModal(modal-layer 오버레이)을 대체한다. 인증된 사용자가
// 권한 없는 라우트에 직접 진입한 상황이므로 사이드바가 있는 AppShell 본문에 그린다
// (권한 없는 메뉴는 사이드바에서 이미 숨겨져 있어, 이 화면은 직접 URL 진입으로만 도달).
export function AccessDeniedScreen({
  user,
  route,
  routeLabel,
  requiredPermission,
  onGoTo
}: {
  user: User;
  route: StudioRoute;
  routeLabel: string;
  requiredPermission: string;
  onGoTo: (route: StudioRoute) => void;
}) {
  const area = route.startsWith("admin.") ? "admin" : "generate";
  const role = user.role || "권한 미지정";
  return (
    <AppShell
      user={user}
      area={area}
      activeItem=""
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="403 · 권한 없음"
      headerTitle="접근 권한이 없습니다"
    >
      <div className="v3-access-denied">
        <div className="v3-access-denied-badge">403</div>
        <h2 className="v3-access-denied-title">이 화면에 접근할 권한이 없습니다</h2>
        <p className="v3-access-denied-desc">
          {routeLabel}은(는) <code>{requiredPermission}</code> 권한이 필요합니다. 현재 역할{" "}
          <code>{role}</code>에는 포함되어 있지 않습니다.
        </p>
        <div className="v3-access-denied-card">
          <div className="v3-access-denied-row">
            <span>필요 권한</span>
            <code>{requiredPermission}</code>
          </div>
          <div className="v3-access-denied-row">
            <span>내 역할</span>
            <code>{role}</code>
          </div>
          <div className="v3-access-denied-row">
            <span>요청 경로</span>
            <code>{routePath(route)}</code>
          </div>
        </div>
        <div className="v3-access-denied-actions">
          <button className="v3-primary-button" type="button" onClick={() => onGoTo("create.load")}>
            Workspace로 이동
          </button>
        </div>
        <p className="v3-access-denied-note">
          권한이 없는 메뉴는 사이드바에서 숨겨집니다 · 직접 URL 진입만 이 화면에 도달합니다.
          접근이 필요하면 관리자에게 권한을 요청하십시오.
        </p>
      </div>
    </AppShell>
  );
}

// 6b · User Manual — design_handoff 6b "User Manual · 목차 + 본문 · 화면 내 상시 접근".
// 구버전 ManualModal(오버레이)을 대체해, 사이드바가 있는 AppShell 본문에 매뉴얼을
// 그리는 전체 화면으로 전환. iframe 문서 내 검색(하이라이트·다음 이동) 로직은
// ManualModal에서 그대로 이관.
//
// 문서 자체의 목차와 상단 검색을 제공한다. iframe 내부의 hash 링크는 부모 SPA를
// 다시 열지 않고 이 문서 안에서만 이동하도록 onLoad 시 가로챈다.
export function ManualScreen({
  user,
  html,
  loading,
  error,
  onGoTo
}: {
  user: User;
  html: string;
  loading: boolean;
  error: string;
  onGoTo: (route: StudioRoute) => void;
}) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const hitsRef = useRef<HTMLElement[]>([]);
  const hitIndexRef = useRef(-1);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchStatus, setSearchStatus] = useState("");

  function clearHighlights() {
    const doc = iframeRef.current?.contentDocument;
    if (!doc) return;
    doc.querySelectorAll<HTMLElement>("mark.manual-hit").forEach((mark) => {
      const text = doc.createTextNode(mark.textContent || "");
      mark.replaceWith(text);
      text.parentNode?.normalize();
    });
    hitsRef.current = [];
    hitIndexRef.current = -1;
  }

  function moveToHit(index: number) {
    const hits = hitsRef.current;
    if (!hits.length) {
      setSearchStatus("검색 결과가 없습니다.");
      return;
    }
    hits.forEach((hit) => hit.classList.remove("is-current"));
    hitIndexRef.current = (index + hits.length) % hits.length;
    const current = hits[hitIndexRef.current];
    current.classList.add("is-current");
    current.scrollIntoView({ behavior: "smooth", block: "center" });
    setSearchStatus(`${hitIndexRef.current + 1} / ${hits.length} 검색 결과`);
  }

  function searchManual() {
    const doc = iframeRef.current?.contentDocument;
    clearHighlights();
    const query = searchQuery.trim();
    if (!doc || !query) {
      setSearchStatus("검색어를 입력하세요.");
      return;
    }

    const needle = query.toLocaleLowerCase();
    const nodes: Text[] = [];
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue?.trim() || node.parentElement?.closest("style, script, mark")) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    while (walker.nextNode()) nodes.push(walker.currentNode as Text);

    nodes.forEach((node) => {
      const value = node.nodeValue || "";
      const lower = value.toLocaleLowerCase();
      let cursor = 0;
      let found = false;
      const fragment = doc.createDocumentFragment();
      while (true) {
        const index = lower.indexOf(needle, cursor);
        if (index === -1) break;
        found = true;
        if (index > cursor) fragment.appendChild(doc.createTextNode(value.slice(cursor, index)));
        const mark = doc.createElement("mark");
        mark.className = "manual-hit";
        mark.textContent = value.slice(index, index + query.length);
        fragment.appendChild(mark);
        cursor = index + query.length;
      }
      if (!found) return;
      if (cursor < value.length) fragment.appendChild(doc.createTextNode(value.slice(cursor)));
      node.replaceWith(fragment);
    });

    hitsRef.current = Array.from(doc.querySelectorAll<HTMLElement>("mark.manual-hit"));
    if (!hitsRef.current.length) {
      setSearchStatus(`"${query}" 검색 결과가 없습니다.`);
      return;
    }
    moveToHit(0);
  }

  function handleManualLoad() {
    clearHighlights();
    setSearchStatus("");
    const doc = iframeRef.current?.contentDocument;
    doc?.addEventListener("click", (event) => {
      // iframe의 Element 생성자는 부모 window의 Element와 다르다. instanceof를
      // 쓰면 항상 false가 될 수 있으므로 nodeType으로 확인한다.
      const target = event.target as Element | null;
      if (!target || target.nodeType !== 1) return;
      const link = target.closest<HTMLAnchorElement>('a[href^="#"]');
      if (!link) return;

      // srcDoc iframe의 상대 hash 링크가 상위 SPA 경로를 다시 여는 브라우저가
      // 있어 세션 초기화 및 로그인 화면 전환으로 이어질 수 있다. 매뉴얼의 모든
      // 내부 앵커는 여기서만 처리한다.
      event.preventDefault();
      event.stopPropagation();
      const anchorId = decodeURIComponent(link.getAttribute("href")?.slice(1) || "");
      const section = anchorId ? doc.getElementById(anchorId) : null;
      if (!section) {
        setSearchStatus("연결된 매뉴얼 항목을 찾지 못했습니다.");
        return;
      }
      section.scrollIntoView({ behavior: "smooth", block: "start" });
    }, true);
  }

  useEffect(() => {
    hitsRef.current = [];
    hitIndexRef.current = -1;
    setSearchQuery("");
    setSearchStatus("");
  }, [html]);

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem=""
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="USER MANUAL"
      headerTitle="사용 설명서"
      headerActions={
        <form
          className="v3-manual-search"
          onSubmit={(event) => {
            event.preventDefault();
            searchManual();
          }}
        >
          <input
            type="search"
            value={searchQuery}
            placeholder="문서 내 검색"
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          <button className="v3-secondary-button" type="submit">검색</button>
          <button className="v3-secondary-button" type="button" onClick={() => moveToHit(hitIndexRef.current + 1)}>다음</button>
        </form>
      }
    >
      <div className="v3-manual">
        {searchStatus ? <p className="v3-manual-status" aria-live="polite">{searchStatus}</p> : null}
        <div className="v3-manual-frame">
          {loading ? (
            <p className="v3-muted-text">사용자 매뉴얼을 불러오는 중입니다.</p>
          ) : error ? (
            <div className="v3-manual-error">
              <h3>사용자 매뉴얼을 불러오지 못했습니다.</h3>
              <p>{error}</p>
            </div>
          ) : (
            <iframe
              ref={iframeRef}
              title="dobedub studio 사용자 매뉴얼"
              sandbox="allow-same-origin"
              onLoad={handleManualLoad}
              srcDoc={html}
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}

// A-06: 세션 만료 예고 배너. 토큰 expiresAt 기준으로 클라이언트가 남은 시간을
// 계산해, 만료 5분 전부터 상단에 배너로 예고하고 "세션 연장" 버튼을 준다(design_handoff
// 7g "만료 5분 전 상단에 배너로 예고"). 연장은 POST /api/auth/refresh(무중단 재발급).
const SESSION_WARN_MS = 5 * 60 * 1000;

export function SessionExpiryBanner({
  expiresAt,
  refreshing,
  onRefresh
}: {
  expiresAt?: string;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    // 20초마다 갱신 - 분 단위 표시라 초 단위 정밀도는 필요 없다.
    const timer = window.setInterval(() => setNow(Date.now()), 20000);
    return () => window.clearInterval(timer);
  }, []);

  if (!expiresAt) {
    return null;
  }
  const remainingMs = new Date(expiresAt).getTime() - now;
  if (remainingMs <= 0 || remainingMs > SESSION_WARN_MS) {
    return null;
  }
  const remainingMin = Math.max(1, Math.ceil(remainingMs / 60000));
  return (
    <div className="v3-session-banner" role="status" aria-live="polite">
      <span className="v3-session-banner-dot" aria-hidden="true" />
      <span>세션이 곧 만료됩니다 · 약 {remainingMin}분 남음. 작성 중인 내용은 이 탭에 유지됩니다.</span>
      <button className="v3-secondary-button" type="button" disabled={refreshing} onClick={onRefresh}>
        {refreshing ? "연장 중..." : "세션 연장"}
      </button>
    </div>
  );
}

export function loginErrorMessage(error: unknown) {
  const message = error instanceof Error ? error.message : "";
  if (message === "Invalid credentials") {
    return "아이디 또는 비밀번호가 올바르지 않습니다.";
  }
  if (message === "User is inactive") {
    return "비활성화된 사용자입니다. 관리자에게 문의하세요.";
  }
  if (message === "id and password are required") {
    return "아이디와 비밀번호를 입력하세요.";
  }
  return message || "로그인에 실패했습니다.";
}
