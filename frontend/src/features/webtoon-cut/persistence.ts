type PersistedWebtoonCutSession = {
  workspaceHandle?: FileSystemDirectoryHandle;
  inputDirectoryHandle?: FileSystemDirectoryHandle;
  fileHandles?: FileSystemFileHandle[];
  inputMode?: "directory" | "files";
  updatedAt: string;
};

const DB_NAME = "dobedub-webtoon-cut";
const STORE_NAME = "session";
const SESSION_KEY = "active";

export async function loadPersistedWebtoonCutSession(): Promise<PersistedWebtoonCutSession | null> {
  const db = await openDatabase();
  if (!db) return null;
  return new Promise((resolve) => {
    const transaction = db.transaction(STORE_NAME, "readonly");
    const request = transaction.objectStore(STORE_NAME).get(SESSION_KEY);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => resolve(null);
  });
}

export async function persistWorkspaceHandle(workspaceHandle: FileSystemDirectoryHandle) {
  await updateSession((session) => ({ ...session, workspaceHandle }));
}

export async function persistInputDirectoryHandle(inputDirectoryHandle: FileSystemDirectoryHandle) {
  await updateSession((session) => ({
    ...session,
    inputMode: "directory",
    inputDirectoryHandle,
    fileHandles: undefined
  }));
}

export async function persistInputFileHandles(fileHandles: FileSystemFileHandle[]) {
  await updateSession((session) => ({
    ...session,
    inputMode: "files",
    fileHandles,
    inputDirectoryHandle: undefined
  }));
}

export async function clearPersistedInputs() {
  await updateSession((session) => ({
    ...session,
    inputMode: undefined,
    inputDirectoryHandle: undefined,
    fileHandles: undefined
  }));
}

export async function hasHandlePermission(handle: FileSystemHandle, mode: "read" | "readwrite") {
  const permissionHandle = handle as FileSystemHandle & {
    queryPermission?: (descriptor?: { mode: "read" | "readwrite" }) => Promise<PermissionState>;
  };
  return (await permissionHandle.queryPermission?.({ mode })) === "granted";
}

async function updateSession(updater: (session: PersistedWebtoonCutSession) => PersistedWebtoonCutSession) {
  const db = await openDatabase();
  if (!db) return;
  const current = await loadPersistedWebtoonCutSession();
  const next = updater({ ...(current || { updatedAt: "" }), updatedAt: new Date().toISOString() });
  await new Promise<void>((resolve) => {
    const transaction = db.transaction(STORE_NAME, "readwrite");
    const request = transaction.objectStore(STORE_NAME).put(next, SESSION_KEY);
    request.onsuccess = () => resolve();
    request.onerror = () => resolve();
  });
}

function openDatabase(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === "undefined") return Promise.resolve(null);
  return new Promise((resolve) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(STORE_NAME);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
  });
}
