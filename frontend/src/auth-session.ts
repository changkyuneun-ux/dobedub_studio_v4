import { User, AuthSession } from "./auth";

export const LOGIN_DISABLED_FOR_DEV = false;
// sessionStorage는 같은 탭의 새로고침에서는 유지되고 탭/브라우저 종료 시 정리된다.
// 따라서 새로고침까지 로그아웃으로 취급하지 않도록 복원은 항상 허용한다.
export const RESTORE_LOGIN_SESSION_ON_REFRESH = true;
export const SESSION_USER_STORAGE_KEY = "dobedub.react.user.db-auth.v1";
export const LEGACY_SESSION_USER_STORAGE_KEYS = ["dobedub.react.user", "dobedub.react.user.auth"];
export const DEV_USER: User = { id: "dobedub", name: "장균은", role: "SUPER_ADMIN", permissions: ["admin:*"], isActive: true };

export function loadAuthSession(): AuthSession | null {
  // 이전 로컬/구버전 키만 정리하고, 현재 탭의 JWT 세션은 보존한다.
  clearLoginSession(RESTORE_LOGIN_SESSION_ON_REFRESH);
  if (LOGIN_DISABLED_FOR_DEV) {
    const session = { user: DEV_USER, accessToken: "" };
    sessionStorage.setItem(SESSION_USER_STORAGE_KEY, JSON.stringify(session));
    return session;
  }
  try {
    const raw = sessionStorage.getItem(SESSION_USER_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<AuthSession>;
    if (!parsed.user || !parsed.accessToken) {
      clearLoginSession();
      return null;
    }
    if (parsed.expiresAt && Date.parse(parsed.expiresAt) <= Date.now()) {
      clearLoginSession();
      return null;
    }
    return parsed as AuthSession;
  } catch {
    clearLoginSession();
    return null;
  }
}

export function loadSessionUser(): User | null {
  return loadAuthSession()?.user || null;
}

export function clearLoginSession(keepCurrent = false) {
  if (typeof sessionStorage !== "undefined") {
    [...LEGACY_SESSION_USER_STORAGE_KEYS, ...(keepCurrent ? [] : [SESSION_USER_STORAGE_KEY])]
      .forEach((key) => sessionStorage.removeItem(key));
    for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith("dobedub.react.user") && !(keepCurrent && key === SESSION_USER_STORAGE_KEY)) {
        sessionStorage.removeItem(key);
      }
    }
  }
  if (typeof localStorage !== "undefined") {
    for (let index = localStorage.length - 1; index >= 0; index -= 1) {
      const key = localStorage.key(index);
      if (key?.startsWith("dobedub.react.user")) {
        localStorage.removeItem(key);
      }
    }
  }
}
