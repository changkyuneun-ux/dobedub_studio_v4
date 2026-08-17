import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { apiClient, HealthResponse } from "./api/client";
import { isRetiredCreateRoutePath, routeFromLocation, routePath, StudioRoute } from "./router";
// E-01: User/AuthSession types moved to ./auth so components can use them
// without importing this entry file.
import { User, AuthSession } from "./auth";
import "./styles.css";
import { SESSION_USER_STORAGE_KEY, loadAuthSession, clearLoginSession } from "./auth-session";
import { StudioShell } from "./StudioShell";
import { AppShellChromeContext } from "./components/AppShell";
import { LoginScreen, SessionExpiryBanner } from "./screens/accessScreens";

function App() {
  const initialSession = useMemo(() => loadAuthSession(), []);
  const [user, setUser] = useState<User | null>(() => initialSession?.user || null);
  const [route, setRoute] = useState<StudioRoute>(() => routeFromLocation(window.location.pathname, Boolean(initialSession?.user)));
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState("");
  // A-06: 세션 만료 예고 배너용. 로그인/연장 시 토큰 expiresAt을 담아둔다.
  const [sessionExpiresAt, setSessionExpiresAt] = useState<string | undefined>(() => initialSession?.expiresAt);
  const [refreshingSession, setRefreshingSession] = useState(false);

  useEffect(() => {
    let active = true;
    apiClient
      .health()
      .then((value) => {
        if (active) {
          setHealth(value);
          setHealthError("");
        }
      })
      .catch((error: Error) => {
        if (active) {
          setHealthError(error.message);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const nextRoute = routeFromLocation(window.location.pathname, Boolean(user));
    if (!user && window.location.pathname !== routePath("access.login")) {
      navigate("access.login", true);
    } else if (isRetiredCreateRoutePath(window.location.pathname)) {
      // 멀티 Task에서는 결과 확인이 Task History에 통합됐다. 이전 북마크도
      // 주소와 화면을 함께 정규 경로로 보정한다.
      navigate(nextRoute, true);
    } else if (nextRoute !== route) {
      setRoute(nextRoute);
    }
  }, [route, user]);

  useEffect(() => {
    function syncRouteFromHistory() {
      setRoute(routeFromLocation(window.location.pathname, Boolean(user)));
    }
    window.addEventListener("popstate", syncRouteFromHistory);
    return () => window.removeEventListener("popstate", syncRouteFromHistory);
  }, [user]);

  useEffect(() => {
    if (!user) {
      return;
    }
    let active = true;
    async function refreshSessionPermissions() {
      try {
        const response = await apiClient.currentSession();
        if (!active || !response.user) {
          return;
        }
        const raw = sessionStorage.getItem(SESSION_USER_STORAGE_KEY);
        const currentSession = raw ? JSON.parse(raw) as AuthSession : null;
        if (!currentSession?.accessToken) {
          return;
        }
        const nextSession = { ...currentSession, user: response.user };
        sessionStorage.setItem(SESSION_USER_STORAGE_KEY, JSON.stringify(nextSession));
        setUser(response.user);
      } catch {
        // A temporary refresh failure must not discard an otherwise valid session.
      }
    }
    function refreshOnVisible() {
      if (document.visibilityState === "visible") {
        void refreshSessionPermissions();
      }
    }
    void refreshSessionPermissions();
    window.addEventListener("focus", refreshSessionPermissions);
    document.addEventListener("visibilitychange", refreshOnVisible);
    return () => {
      active = false;
      window.removeEventListener("focus", refreshSessionPermissions);
      document.removeEventListener("visibilitychange", refreshOnVisible);
    };
  }, [user?.id]);

  function handleLogin(nextSession: AuthSession) {
    clearLoginSession();
    sessionStorage.setItem(SESSION_USER_STORAGE_KEY, JSON.stringify(nextSession));
    setUser(nextSession.user);
    setSessionExpiresAt(nextSession.expiresAt);
    // 로그인 직후 랜딩은 구버전 전체 워크스페이스가 아니라 신규 S1(2a) 화면이다.
    // E-02: design_handoff 2 Create.dc.html 흐름의 실제 첫 단계.
    navigate("create.load");
  }

  function handleLogout() {
    // The asset-session cookie is HttpOnly and must be cleared by the server.
    void apiClient.logout().catch(() => undefined);
    clearLoginSession();
    setUser(null);
    setSessionExpiresAt(undefined);
    setRoute("access.login");
    window.location.replace(routePath("access.login"));
  }

  // A-06: 무중단 세션 연장. 아직 유효한 토큰으로 refresh를 호출해 새 토큰으로 교체한다.
  async function handleRefreshSession() {
    setRefreshingSession(true);
    try {
      const next = await apiClient.refreshSession();
      clearLoginSession();
      sessionStorage.setItem(SESSION_USER_STORAGE_KEY, JSON.stringify(next));
      setUser(next.user);
      setSessionExpiresAt(next.expiresAt);
    } catch {
      // 연장 실패 시 기존 세션을 그대로 두고 배너도 유지한다 - 만료되면 401 흐름으로 넘어간다.
    } finally {
      setRefreshingSession(false);
    }
  }

  function navigate(nextRoute: StudioRoute, replace = false) {
    setRoute(nextRoute);
    const path = routePath(nextRoute);
    if (window.location.pathname === path) {
      return;
    }
    if (replace) {
      window.history.replaceState(null, "", path);
    } else {
      window.history.pushState(null, "", path);
    }
  }

  // 로그인 화면(6a)은 전역 크롬 없이 자체 브랜드 헤더를 갖는 전체 화면이다. 인증 후에는
  // 구버전 TopBar(상단 메뉴) 대신, AppShell 사이드바가 네비게이션을 전담하고 서비스 상태·
  // 유저/로그아웃·영역 전환은 AppShellChromeContext로 사이드바 하단 계정 블록에 내려준다.
  if (!user || route === "access.login") {
    return <LoginScreen onLogin={handleLogin} health={health} healthError={healthError} />;
  }
  return (
    <div className="app-shell">
      <SessionExpiryBanner
        expiresAt={sessionExpiresAt}
        refreshing={refreshingSession}
        onRefresh={handleRefreshSession}
      />
      <AppShellChromeContext.Provider
        value={{ health, healthError, onLogout: handleLogout, onNavigateRoute: navigate }}
      >
        <StudioShell
          user={user}
          health={health}
          route={route}
          onNavigate={navigate}
        />
      </AppShellChromeContext.Provider>
    </div>
  );
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
