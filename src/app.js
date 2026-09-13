const fallbackWorkflows = [
  { id: "1-images.json", name: "1-images", mode: "single", keyframeCount: 1, segmentCount: 1 },
  { id: "Blowbang1.json", name: "Blowbang1", mode: "single", keyframeCount: 1, segmentCount: 1 },
  { id: "Pickme_Workflow.json", name: "Pickme_Workflow", mode: "single", keyframeCount: 1, segmentCount: 1 },
  { id: "video_minimax_h3_r2v.json", name: "video_minimax_h3_r2v", mode: "single", keyframeCount: 1, segmentCount: 1 },
  { id: "video_wan2_2_14B_flf2v_2-images-1.json", name: "video_wan2_2_14B_flf2v_2-images-1", mode: "dual", keyframeCount: 2, segmentCount: 1 },
];

const defaultNegativePrompt = "photorealistic, realistic skin texture, 3D render, style shift, art style change, face/hand/foot distortion, background movement";
const userSessionKey = "comfyuiVideoStudioUser";
const userSessionCookie = "comfyui_video_studio_user";
const defaultDevApiBaseUrl = "http://127.0.0.1:8787";
const defaultWorkflowId = "1-images.json";
const configDescriptions = {
  steps: "품질/시간 균형",
  cfgScale: "프롬프트 반영 강도",
  motionShift: "움직임 변화량",
  fps: "초당 프레임 수",
  frames: "생성 프레임 수",
  durationSeconds: "영상 길이",
  seed: "결과 재현값",
};

const state = {
  apiAvailable: false,
  user: { id: "", name: "" },
  workflows: fallbackWorkflows,
  workflow: fallbackWorkflows[0],
  selectedSegment: 1,
  running: false,
  elapsed: 11,
  runProgress: 0,
  segments: [],
  keyframes: [],
  history: [],
  selectedHistoryIndex: 0,
  historyPage: 1,
  historyPageSize: 10,
  activeHistoryTab: "overview",
  systemStatus: null,
  currentTaskId: null,
  latestOutput: null,
  latestOutputs: [],
  latestOutputSource: "",
  latestJob: null,
  cancelRequested: false,
  runVersion: 0,
  segmentDefaults: {},
  metadata: null,
  metadataStatus: null,
  metadataModels: null,
  metadataWorkflowId: "",
  activeMetadataTab: "summary",
  pendingDeleteHistoryIndex: null,
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderSubgraphName(value) {
  const text = String(value || "").trim();
  const match = text.match(/^(.*?)\s*(\([^)]*\))(.*)$/);
  if (!match) {
    return `<span class="segment-name-main">${escapeHtml(text)}</span>`;
  }
  const main = match[1].trim();
  const bracketInfo = `${match[2]}${match[3] || ""}`.trim();
  return `
    <span class="segment-name-main">${escapeHtml(main)}</span>
    <span class="segment-name-detail">${escapeHtml(bracketInfo)}</span>
  `;
}

async function apiRequest(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  const baseUrl = apiBaseUrl();
  if (!baseUrl) return path;
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

function configuredApiBaseUrl() {
  const configValue = window.APP_CONFIG?.API_BASE_URL
    || document.querySelector('meta[name="api-base-url"]')?.content
    || "";
  return String(configValue).trim().replace(/\/$/, "");
}

function apiBaseUrl() {
  const configured = configuredApiBaseUrl();
  if (configured) return configured;
  return window.location.protocol === "file:" ? defaultDevApiBaseUrl : "";
}

function normalizeWorkflow(workflow) {
  return {
    id: workflow.id,
    name: workflow.name || workflow.id.replace(/\.json$/, ""),
    mode: workflow.mode || "multi_segment",
    keyframeCount: workflow.keyframeCount ?? workflow.keyframes ?? 1,
    segmentCount: workflow.segmentCount ?? workflow.segments ?? 1,
  };
}

async function loadWorkflows() {
  try {
    const data = await apiRequest("/api/workflows");
    state.workflows = data.map(normalizeWorkflow);
    state.apiAvailable = true;
  } catch {
    state.workflows = fallbackWorkflows;
    state.apiAvailable = false;
  }
  state.workflow = state.workflows.find((item) => item.id === defaultWorkflowId) || state.workflows[0];
}

async function loadWorkflowSchema(workflowId) {
  try {
    return await apiRequest(`/api/workflows/${encodeURIComponent(workflowId)}/schema`);
  } catch (error) {
    console.warn("Workflow schema failed; using empty prompt fallback.", error);
    return {
      workflowId,
      mode: state.workflow.mode,
      keyframeCount: state.workflow.keyframeCount,
      segmentCount: state.workflow.segmentCount,
      segments: createFallbackSegments(state.workflow),
    };
  }
}

function createFallbackSegments(workflow) {
  return Array.from({ length: workflow.segmentCount || 1 }, (_, index) => ({
    index: index + 1,
    nodeId: "",
    subgraphName: "Subgraph",
    displayName: `Subgraph_${index + 1}`,
    startImageIndex: index + 1,
    endImageIndex: index + 2,
    progress: 0,
    defaultPositivePrompt: "",
    defaultNegativePrompt,
    config: {
      fps: 16,
      frames: index === 0 ? 49 : 96,
      durationSeconds: 3,
      steps: 4,
      cfgScale: 1.0,
      motionShift: 5.0,
      seed: index === 0 ? 4920381920 : 4920381920 + index,
    },
  }));
}

function createSegmentsFromSchema(schema) {
  return (schema.segments || createFallbackSegments(state.workflow)).map((segment, index) => ({
    index: segment.index || index + 1,
    nodeId: segment.nodeId || "",
    subgraphName: segment.subgraphName || "Subgraph",
    displayName: segment.displayName || `${segment.subgraphName || "Subgraph"}_${segment.index || index + 1}`,
    startImageIndex: segment.startImageIndex || index + 1,
    endImageIndex: segment.endImageIndex || index + 2,
    progress: 0,
    positivePrompt: segment.defaultPositivePrompt ?? "",
    negativePrompt: segment.defaultNegativePrompt ?? defaultNegativePrompt,
    negativePromptAddition: "",
    config: {
      ...(segment.config || {}),
      fps: Number(segment.config?.fps ?? 16),
      frames: Number(segment.config?.frames ?? (index === 0 ? 81 : 96)),
      durationSeconds: Number(segment.config?.durationSeconds ?? 3),
      steps: Number(segment.config?.steps ?? 4),
      cfgScale: Number(segment.config?.cfgScale ?? 1.0),
      motionShift: Number(segment.config?.motionShift ?? 5.0),
      seed: Number(segment.config?.seed ?? 4920381920 + index),
    },
    configControls: segment.configControls || [],
  }));
}

function createKeyframes(count) {
  return Array.from({ length: count || 1 }, (_, index) => ({
    index: index + 1,
    file: null,
    upload: null,
    previewUrl: "",
    metaText: "Image: 1024x1024",
  }));
}

async function init() {
  await loadWorkflows();
  applyInitialWorkflowFromQuery();
  renderWorkflowOptions();
  await selectWorkflow(state.workflow.id);
  renderHistory(await loadHistory());
  bindEvents();
  restoreUserSession();
  await refreshSystemStatus(false);
  applyPreviewMode();
}

function applyInitialWorkflowFromQuery() {
  const workflowId = new URLSearchParams(window.location.search).get("workflow");
  if (!workflowId) return;
  const match = state.workflows.find((workflow) => workflow.id === workflowId);
  if (match) state.workflow = match;
}

function setStudioUser(user) {
  state.user = { id: user.id || "", name: user.name || "" };
  $("#userNameText").textContent = state.user.name || state.user.id || "-";
  $("#loginScreen").classList.add("is-hidden");
  $("#studioScreen").classList.remove("is-hidden");
}

function saveUserSession(user) {
  const session = JSON.stringify({ id: user.id, name: user.name });
  sessionStorage.setItem(userSessionKey, session);
  clearPersistentUserSession();
}

function restoreUserSession() {
  try {
    clearPersistentUserSession();
    const stored = sessionStorage.getItem(userSessionKey);
    const user = JSON.parse(stored || "null");
    if (!user?.id || !user?.name) return;
    $("#loginId").value = user.id;
    $("#loginName").value = user.name;
    setStudioUser(user);
  } catch (error) {
    console.warn("Session user is invalid.", error);
    sessionStorage.removeItem(userSessionKey);
  }
}

function clearUserSession() {
  sessionStorage.removeItem(userSessionKey);
  clearPersistentUserSession();
}

function clearPersistentUserSession() {
  localStorage.removeItem(userSessionKey);
  document.cookie = `${userSessionCookie}=; path=/; max-age=0; SameSite=Lax`;
}

async function logoutStudio() {
  state.runVersion += 1;
  state.running = false;
  state.cancelRequested = false;
  state.user = { id: "", name: "" };
  clearUserSession();
  $("#userNameText").textContent = "-";
  $("#loginPassword").value = "";
  $("#studioScreen").classList.add("is-hidden");
  $("#loginScreen").classList.remove("is-hidden");
  $("#generateButton").textContent = "GENERATE VIDEO";
  updateGenerationControls();
  try {
    await selectWorkflow(defaultWorkflowId);
  } catch (error) {
    console.warn("Default workflow reset failed after logout.", error);
    resetRunVisualState();
  }
}

function readCookie(name) {
  const prefix = `${name}=`;
  const value = document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix));
  return value ? decodeURIComponent(value.slice(prefix.length)) : "";
}

function bindEvents() {
  $("#loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = $("#loginId").value.trim();
    const password = $("#loginPassword").value.trim();
    const name = $("#loginName").value.trim();
    if (!id || !password || !name) return;
    setStudioUser({ id, name });
    saveUserSession({ id, name });
    setApiStatusChecking();
    await refreshSystemStatus(false);
  });

  $("#logoutButton")?.addEventListener("click", async () => {
    await logoutStudio();
  });

  $("#workflowSelect").addEventListener("change", async (event) => {
    await selectWorkflow(event.target.value);
  });

  $("#positivePrompt").addEventListener("input", (event) => {
    getSelectedSegment().positivePrompt = event.target.value;
    updatePreviewInfo();
  });

  $("#negativePrompt").addEventListener("input", (event) => {
    getSelectedSegment().negativePrompt = event.target.value;
  });

  $("#keyframeGrid").addEventListener("change", (event) => {
    const input = event.target.closest("[data-keyframe-input]");
    if (!input) return;
    const startIndex = Number(input.dataset.keyframeInput);
    applySelectedFiles(startIndex, Array.from(input.files || []));
    input.value = "";
  });
  $("#keyframeGrid").addEventListener("click", (event) => {
    const playButton = event.target.closest("[data-play-output]");
    if (playButton) {
      event.preventDefault();
      event.stopPropagation();
      playResultInPicture(playButton.closest(".result-box"));
      return;
    }
    const button = event.target.closest("[data-clear-keyframe]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    clearKeyframe(Number(button.dataset.clearKeyframe));
  });

  $("#resetSegmentConfigButton").addEventListener("click", resetSegmentConfigsToDefaults);

  $("#generateButton").addEventListener("click", generateJob);
  $("#cancelGenerationButton").addEventListener("click", cancelGeneration);
  $("#refreshButton").addEventListener("click", refreshWorkspace);
  $("#downloadButton").addEventListener("click", () => {
    const output = state.latestOutputSource === "job" ? selectedOutputAsset() || finalOutputAsset() : null;
    if (output?.downloadUrl) {
      window.open(output.downloadUrl, "_blank");
    } else {
      alert("결과 파일이 생성되면 다운로드할 수 있습니다.");
    }
  });
  $("#metadataViewButton").addEventListener("click", openMetadataModal);
  $("#statusButton").addEventListener("click", async () => {
    $("#statusModal").classList.remove("is-hidden");
    await refreshSystemStatus(true);
  });
  $("#refreshStatusButton").addEventListener("click", () => refreshSystemStatus(true));
  $("#testRunpodButton").addEventListener("click", testRunpodConnection);
  $("#closeStatusButton").addEventListener("click", () => $("#statusModal").classList.add("is-hidden"));
  $("#statusModal").addEventListener("click", (event) => {
    if (event.target.id === "statusModal") $("#statusModal").classList.add("is-hidden");
  });
  $("#manualButton").addEventListener("click", openManualModal);
  $("#closeManualButton").addEventListener("click", closeManualModal);
  $("#manualModal").addEventListener("click", (event) => {
    if (event.target.id === "manualModal") closeManualModal();
  });
  $("#closeMetadataModalButton").addEventListener("click", () => $("#metadataModal").classList.add("is-hidden"));
  $("#metadataModal").addEventListener("click", (event) => {
    if (event.target.id === "metadataModal") $("#metadataModal").classList.add("is-hidden");
  });
  $("#metadataWorkflowSelect").addEventListener("change", async (event) => {
    await loadMetadataForWorkflow(event.target.value);
  });
  $("#rebuildMetadataButton").addEventListener("click", rebuildMetadata);
  document.querySelectorAll("[data-metadata-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeMetadataTab = button.dataset.metadataTab;
      renderMetadataModal();
    });
  });
  $("#cancelDeleteHistoryButton").addEventListener("click", closeDeleteHistoryModal);
  $("#confirmDeleteHistoryButton").addEventListener("click", confirmDeleteHistory);
  $("#deleteHistoryModal").addEventListener("click", (event) => {
    if (event.target.id === "deleteHistoryModal") closeDeleteHistoryModal();
  });

  $("#historyButton").addEventListener("click", async () => {
    renderHistory(await loadHistory());
    $("#historyModal").classList.remove("is-hidden");
  });
  $("#closeHistoryButton").addEventListener("click", () => $("#historyModal").classList.add("is-hidden"));
  $("#historyModal").addEventListener("click", (event) => {
    if (event.target.id === "historyModal") $("#historyModal").classList.add("is-hidden");
  });
  document.querySelectorAll("[data-detail-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeHistoryTab = button.dataset.detailTab;
      renderTaskDetail(state.selectedHistoryIndex);
    });
  });
}

function applyPreviewMode() {
  const params = new URLSearchParams(window.location.search);
  const preview = params.get("preview");
  if (!["studio", "studio-images", "history", "status"].includes(preview)) return;

  state.user = { id: "preview", name: "Preview" };
  $("#userNameText").textContent = "Preview";
  $("#loginScreen").classList.add("is-hidden");
  $("#studioScreen").classList.remove("is-hidden");
  if (preview === "studio-images") {
    seedPreviewImages();
  }
  if (preview === "history") {
    $("#historyModal").classList.remove("is-hidden");
  } else if (preview === "status") {
    $("#statusModal").classList.remove("is-hidden");
    renderStatusModal();
  }
}

function seedPreviewImages() {
  const colors = ["#38bdf8", "#f472b6", "#4ade80", "#fbbf24", "#a78bfa"];
  state.keyframes.forEach((keyframe, index) => {
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="320" height="220" viewBox="0 0 320 220">
        <rect width="320" height="220" fill="#0f172a"/>
        <circle cx="${70 + index * 36}" cy="82" r="54" fill="${colors[index % colors.length]}" opacity="0.85"/>
        <path d="M0 170 C70 120 130 230 210 160 C250 125 285 128 320 108 L320 220 L0 220Z" fill="#1e293b"/>
        <text x="22" y="202" fill="#f8fafc" font-family="Arial" font-size="24" font-weight="700">Input ${index + 1}</text>
      </svg>`;
    keyframe.file = null;
    keyframe.upload = null;
    keyframe.previewUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    keyframe.metaText = "preview image";
  });
  renderKeyframeGrid();
}

function manualInlineMarkdown(text) {
  return escapeHtml(text || "")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderManualTable(lines) {
  const rows = lines.map((line) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => manualInlineMarkdown(cell.trim())));
  const hasHeader = rows.length >= 2 && rows[1].every((cell) => /^:?-+:?$/.test(cell));
  const header = hasHeader ? rows[0] : [];
  const body = hasHeader ? rows.slice(2) : rows;
  return `
    <div class="manual-table-wrap">
      <table>
        ${header.length ? `<thead><tr>${header.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead>` : ""}
        <tbody>${body.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody>
      </table>
    </div>
  `;
}

function renderManualMarkdown(markdown) {
  const imageAfterHeading = {
    "2. 로그인과 접속 상태 확인": ["docs/manual-assets/01-login.png", "그림 1. 로그인 화면"],
    "3. 메인 화면 구성": ["docs/manual-assets/02-main.png", "그림 2. 메인 작업 화면"],
    "10. 작업 이력 조회와 관리": ["docs/manual-assets/03-history.png", "그림 3. 작업 이력 및 결과 조회 모달"],
    "11. Metadata View": ["docs/manual-assets/04-view-configs.png", "그림 4. Metadata View 모달"],
  };
  const lines = markdown.split(/\r?\n/);
  const parts = [];
  let listTag = "";
  let inCode = false;
  let codeLines = [];
  const closeList = () => {
    if (listTag) {
      parts.push(`</${listTag}>`);
      listTag = "";
    }
  };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trimEnd();
    const stripped = line.trim();
    if (stripped.startsWith("```")) {
      if (inCode) {
        parts.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCode = false;
      } else {
        closeList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }
    if (!stripped) {
      closeList();
      continue;
    }
    if (stripped.startsWith("|") && stripped.slice(1).includes("|")) {
      closeList();
      const tableLines = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        tableLines.push(lines[i]);
        i += 1;
      }
      i -= 1;
      parts.push(renderManualTable(tableLines));
      continue;
    }
    const heading = stripped.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      const text = heading[2].trim();
      const tag = level === 1 ? "h1" : level === 2 ? "h2" : "h3";
      const id = text.replace(/[^0-9A-Za-z가-힣]+/g, "-").replace(/^-|-$/g, "");
      parts.push(`<${tag} id="${escapeHtml(id)}">${manualInlineMarkdown(text)}</${tag}>`);
      const image = imageAfterHeading[text];
      if (image) {
        parts.push(`<figure><img src="${escapeHtml(image[0])}" alt="${escapeHtml(image[1])}" /><figcaption>${escapeHtml(image[1])}</figcaption></figure>`);
      }
      continue;
    }
    const bullet = stripped.match(/^[-*]\s+(.+)$/);
    const number = stripped.match(/^\d+\.\s+(.+)$/);
    if (bullet || number) {
      const nextTag = number ? "ol" : "ul";
      if (listTag && listTag !== nextTag) closeList();
      if (!listTag) {
        listTag = nextTag;
        parts.push(`<${listTag}>`);
      }
      parts.push(`<li>${manualInlineMarkdown((bullet || number)[1])}</li>`);
      continue;
    }
    closeList();
    parts.push(`<p>${manualInlineMarkdown(stripped)}</p>`);
  }
  closeList();
  return parts.join("\n");
}

function manualHtmlDocument(markdown) {
  const baseHref = new URL("./", window.location.href).href;
  return `<!doctype html>
    <html lang="ko">
      <head>
        <meta charset="utf-8" />
        <base href="${escapeHtml(baseHref)}" />
        <style>
          * { box-sizing: border-box; }
          body { margin: 0; background: #f7f9fc; color: #111827; font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", Arial, sans-serif; line-height: 1.62; }
          main { max-width: 980px; margin: 0 auto; padding: 42px 48px 56px; background: #fff; min-height: 100vh; box-shadow: 0 18px 60px rgba(15, 23, 42, 0.12); }
          h1 { margin: 0 0 12px; font-size: 34px; }
          h2 { border-top: 1px solid #d6dde8; margin: 34px 0 14px; padding-top: 24px; font-size: 25px; }
          h3 { margin: 24px 0 10px; font-size: 18px; }
          p { margin: 0 0 12px; }
          ul, ol { margin: 0 0 14px 22px; padding: 0; }
          li { margin: 5px 0; }
          code { background: #eef4ff; border: 1px solid #d7e5ff; border-radius: 4px; color: #0f56b3; padding: 1px 5px; }
          pre { background: #111827; border-radius: 8px; color: #f8fafc; overflow: auto; padding: 14px; }
          figure { margin: 18px 0 22px; }
          figure img { border: 1px solid #cbd5e1; border-radius: 8px; display: block; max-width: 100%; width: 100%; }
          figcaption { color: #596574; font-size: 13px; margin-top: 8px; text-align: center; }
          .manual-table-wrap { overflow-x: auto; margin: 14px 0 20px; }
          table { border-collapse: collapse; min-width: 720px; width: 100%; }
          th { background: #2563eb; color: #fff; font-weight: 700; }
          th, td { border: 1px solid #d6dde8; padding: 9px 10px; text-align: left; vertical-align: top; }
          td { background: #fbfdff; }
        </style>
      </head>
      <body><main>${renderManualMarkdown(markdown)}</main></body>
    </html>`;
}

async function loadManualHtml() {
  const embedded = $("#manualMarkdownSource")?.textContent || "";
  if (embedded.trim() && embedded.trim() !== "__MANUAL_MARKDOWN__") {
    return manualHtmlDocument(embedded);
  }
  const stamp = Date.now();
  const candidates = [
    { url: `/docs/dobedub-studio-user-manual.md?ts=${stamp}`, type: "markdown" },
    { url: `docs/dobedub-studio-user-manual.md?ts=${stamp}`, type: "markdown" },
    { url: `./docs/dobedub-studio-user-manual.md?ts=${stamp}`, type: "markdown" },
    { url: `/manual?ts=${stamp}`, type: "html" },
  ];
  const failures = [];
  for (const candidate of candidates) {
    try {
      const response = await fetch(candidate.url, { cache: "no-store" });
      if (!response.ok) {
        failures.push(`${candidate.url}: HTTP ${response.status}`);
        continue;
      }
      const text = await response.text();
      if (!text.trim()) {
        failures.push(`${candidate.url}: empty response`);
        continue;
      }
      return candidate.type === "html" ? text : manualHtmlDocument(text);
    } catch (error) {
      failures.push(`${candidate.url}: ${error.message || error}`);
    }
  }
  throw new Error(failures.join("\n"));
}

async function openManualModal() {
  const frame = $("#manualFrame");
  frame.src = "about:blank";
  frame.srcdoc = "<!doctype html><html><body style=\"font-family:sans-serif;padding:32px;\">Loading manual...</body></html>";
  $("#manualModal").classList.remove("is-hidden");
  try {
    frame.srcdoc = await loadManualHtml();
  } catch (error) {
    console.warn(error);
    frame.srcdoc = `<!doctype html>
      <html lang="ko">
        <body style="font-family:sans-serif;padding:32px;color:#991b1b;">
          <h1>사용자 매뉴얼을 불러오지 못했습니다.</h1>
          <p>매뉴얼 원본 파일, 서버 HTML 주입, 또는 정적 파일 경로를 확인해주세요.</p>
          <pre style="white-space:pre-wrap;background:#fee2e2;border:1px solid #fecaca;border-radius:8px;padding:14px;color:#7f1d1d;">${escapeHtml(error.message || String(error))}</pre>
        </body>
      </html>`;
  }
}

function closeManualModal() {
  $("#manualModal").classList.add("is-hidden");
  $("#manualFrame").srcdoc = "";
}

async function refreshSystemStatus(renderModal) {
  try {
    state.systemStatus = await apiRequest("/api/system/status");
  } catch (error) {
    console.warn(error);
    state.systemStatus = {
      ok: false,
      checkedAt: "-",
      executionMode: "offline",
      dryRun: true,
      runpod: { configured: false, endpointId: "", baseUrl: "" },
      workflows: { exists: false, count: 0, items: [] },
      storage: {
        dataDir: { path: "-", writable: false },
        outputsDir: { path: "-", writable: false },
      },
    };
  }
  renderApiStatusPill();
  if (renderModal) renderStatusModal();
}

function setApiStatusChecking() {
  updateStatusPill($("#apiStatusPill"), $("#apiStatusText"), "CHECKING", "warning");
  updateStatusPill($("#loginApiStatusPill"), $("#loginApiStatusText"), "CHECKING", "warning");
}

function renderApiStatusPill() {
  const status = state.systemStatus;
  if (!status) return;
  const label = status.ok ? (status.dryRun ? "DRY-RUN" : "ONLINE") : "CHECK";
  const tone = status.ok && !status.dryRun ? "online" : "warning";
  updateStatusPill($("#apiStatusPill"), $("#apiStatusText"), label, tone);
  updateStatusPill($("#loginApiStatusPill"), $("#loginApiStatusText"), label, tone);
}

function updateStatusPill(pill, text, label, tone) {
  if (!pill || !text) return;
  pill.classList.remove("is-warning", "is-online", "is-busy", "is-error");
  if (tone) pill.classList.add(`is-${tone}`);
  text.textContent = label;
}

function renderApiJobStatus(job) {
  const pill = $("#apiStatusPill");
  const text = $("#apiStatusText");
  if (!pill || !text || !job) return;
  const status = String(job.status || "").toLowerCase();
  const tone = ["fail", "cancelled", "timed_out"].includes(status) ? "error" : "busy";
  updateStatusPill(pill, text, job.statusLabel || runpodStatusLabel(job.rawStatus || job.status), tone);
}

function runpodStatusLabel(status) {
  const key = String(status || "").toUpperCase();
  const labels = {
    QUEUED: "대기",
    IN_QUEUE: "대기",
    IN_PROGRESS: "실행 중",
    RUNNING: "실행 중",
    COMPLETED: "완료",
    SUCCESS: "완료",
    FAILED: "실패",
    CANCELLED: "취소됨",
    TIMED_OUT: "시간 초과",
  };
  return labels[key] || "확인 중";
}

function renderStatusModal() {
  const status = state.systemStatus;
  if (!status) return;
  const modeLabel = status.dryRun ? "Dry-run mode" : "RunPod live mode";
  const runpodLabel = status.runpod.configured ? "Configured" : "Not configured";
  const workflowList = (status.workflows.items || []).slice(0, 6).join(", ");
  const segmentDefaults = status.segmentDefaults || {};
  const defaultsOk = (segmentDefaults.workflowCount || 0) > 0 && segmentDefaults.matchedCount === segmentDefaults.workflowCount;
  const missingDefaults = (segmentDefaults.missingWorkflows || []).join(", ");
  const metadata = status.metadata || {};
  const metadataOk = Boolean(metadata.manifest?.exists && metadata.workflowWidgetMap?.exists && metadata.models?.exists);
  $("#statusGrid").innerHTML = `
    ${statusCard("Execution", modeLabel, status.dryRun ? "Actual RunPod calls are disabled." : "Jobs will be submitted to RunPod.", status.ok && !status.dryRun)}
    ${statusCard("RunPod", runpodLabel, `Endpoint: ${escapeHtml(status.runpod.endpointId || "-")}<br />Base: ${escapeHtml(status.runpod.baseUrl || "-")}`, status.runpod.configured)}
    ${statusCard("Workflows", `${status.workflows.count || 0} files`, `${escapeHtml(status.workflows.dir || "-")}<br />${escapeHtml(workflowList || "No workflow files found.")}`, status.workflows.exists && status.workflows.count > 0)}
    ${statusCard("Segment Defaults", `${segmentDefaults.matchedCount || 0}/${segmentDefaults.workflowCount || 0} matched`, `${escapeHtml(segmentDefaults.bundledPath?.path || "-")}<br />${escapeHtml(defaultsOk ? "All workflow defaults are available." : `Missing: ${missingDefaults || "-"}`)}`, defaultsOk)}
    ${statusCard("Metadata", metadataOk ? "Ready" : "Check files", `Manifest: ${escapeHtml(metadata.manifest?.exists ? "OK" : "Missing")}<br />Widget map: ${escapeHtml(metadata.workflowWidgetMap?.exists ? "OK" : "Missing")}<br />Models: ${escapeHtml(metadata.models?.exists ? "OK" : "Missing")}`, metadataOk)}
    ${statusCard("Storage", status.storage.outputsDir.writable ? "Writable" : "Check path", `Data: ${escapeHtml(status.storage.dataDir.path)}<br />Outputs: ${escapeHtml(status.storage.outputsDir.path)}`, status.storage.dataDir.writable && status.storage.outputsDir.writable)}
    <p class="status-timestamp">Last checked: ${escapeHtml(status.checkedAt || "-")}</p>
  `;
}

async function testRunpodConnection() {
  const notice = $("#statusNotice");
  notice.textContent = "Checking RunPod endpoint...";
  try {
    const result = await apiRequest("/api/runpod/connection");
    const workers = result.workers || {};
    const jobs = result.jobs || {};
    notice.textContent = `${result.message} Workers idle/running: ${workers.idle ?? 0}/${workers.running ?? 0}, Queue: ${jobs.inQueue ?? 0}`;
  } catch (error) {
    console.warn(error);
    notice.textContent = "RunPod connection check failed. API key, endpoint ID, or network access may need attention.";
  }
}

function statusCard(title, value, detail, ok) {
  return `
    <section class="status-card ${ok ? "is-ok" : "is-alert"}">
      <span></span>
      <h3>${escapeHtml(title)}</h3>
      <strong>${escapeHtml(value)}</strong>
      <p>${detail}</p>
    </section>
  `;
}

async function selectWorkflow(workflowId) {
  releaseKeyframePreviews();
  state.workflow = state.workflows.find((item) => item.id === workflowId) || state.workflows[0];
  state.selectedSegment = 1;
  resetOutputState();
  const schema = await loadWorkflowSchema(state.workflow.id);
  state.workflow = {
    ...state.workflow,
    mode: schema.mode || state.workflow.mode,
    keyframeCount: schema.keyframeCount ?? state.workflow.keyframeCount,
    segmentCount: schema.segmentCount ?? state.workflow.segmentCount,
  };
  state.segments = createSegmentsFromSchema(schema);
  state.keyframes = createKeyframes(state.workflow.keyframeCount);
  resetOutputState();
  renderWorkflowOptions();
  renderKeyframeGrid();
  renderSegments();
  renderPreviewSegmentOptions();
  renderSelectedSegment();
  renderMainOutputPreview();
  updateRunProgress(0, 0);
}

async function loadSegmentDefaults(workflowId = state.workflow?.id) {
  if (!workflowId) return null;
  if (state.segmentDefaults[workflowId]) return state.segmentDefaults[workflowId];
  try {
    const defaults = await apiRequest(`/api/segment-defaults/${encodeURIComponent(workflowId)}`);
    state.segmentDefaults[workflowId] = defaults;
    return defaults;
  } catch (error) {
    console.warn("Segment defaults unavailable.", error);
    return null;
  }
}

async function resetSegmentConfigsToDefaults() {
  const defaults = await loadSegmentDefaults();
  const defaultSegments = defaults?.segments || [];
  if (!defaultSegments.length) {
    showNotice("현재 워크플로우의 세그먼트 기본값이 없습니다.");
    return;
  }
  state.segments = state.segments.map((segment, index) => {
    const source = defaultSegments[index] || defaultSegments[0] || {};
    return {
      ...segment,
      defaultId: source.id || segment.defaultId,
      defaultName: source.name || segment.defaultName,
      config: {
        ...segment.config,
        ...(source.config || {}),
        seed: segment.config.seed,
      },
    };
  });
  renderSegments();
  renderSelectedSegment();
  updatePreviewInfo();
  showNotice("세그먼트 설정을 워크플로우 기본값으로 초기화했습니다.");
}

function resetOutputState() {
  state.latestOutput = null;
  state.latestOutputs = [];
  state.latestOutputSource = "";
  state.latestJob = null;
  state.currentTaskId = null;
  state.cancelRequested = false;
  state.runProgress = 0;
  state.elapsed = 0;
  updateGenerationControls();
}

function setAllSegmentProgress(progress) {
  const value = Math.min(100, Math.max(0, Math.round(progress)));
  state.segments = state.segments.map((segment) => ({ ...segment, progress: value }));
}

function updateSegmentProgressFromRun(progress) {
  const count = Math.max(1, state.segments.length);
  const perSegmentRange = 100 / count;
  state.segments = state.segments.map((segment, index) => {
    const start = index * perSegmentRange;
    const segmentProgress = ((progress - start) / perSegmentRange) * 100;
    return {
      ...segment,
      progress: Math.min(100, Math.max(0, Math.round(segmentProgress))),
    };
  });
}

function resetRunVisualState() {
  resetOutputState();
  setAllSegmentProgress(0);
  renderSegments();
  renderKeyframeGrid();
  renderMainOutputPreview();
  updateRunProgress(0, 0);
}

function refreshWorkspace() {
  resetRunVisualState();
  updatePreviewInfo();
  $("#logText").textContent = "";
  $("#logPercent").textContent = "(0%)";
  showNotice("화면을 초기화했습니다.");
}

function renderWorkflowOptions() {
  $("#workflowSelect").innerHTML = state.workflows
    .map((workflow) => `<option value="${escapeHtml(workflow.id)}">Workflow Type: Wan ${escapeHtml(workflow.name)} (${workflow.keyframeCount} keyframes)</option>`)
    .join("");
  $("#workflowSelect").value = state.workflow?.id || state.workflows[0]?.id;
}

function renderSegments() {
  $("#segmentList").innerHTML = state.segments
    .map((segment) => `
      <button class="segment-card ${segment.index === state.selectedSegment ? "is-active" : ""}" type="button" data-segment="${segment.index}">
        <strong class="segment-name">${renderSubgraphName(segment.displayName || `Subgraph_${segment.index}`)}</strong>
        <span class="mini-graph" style="--pct: ${segment.progress}" data-progress="${segment.progress}%"></span>
      </button>
    `)
    .join("");

  document.querySelectorAll(".segment-card").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedSegment = Number(button.dataset.segment);
      renderSegments();
      renderSelectedSegment();
    });
  });
}

function renderPreviewSegmentOptions() {
  $("#previewSegmentSelect").innerHTML = state.segments
    .map((segment) => `<option value="${segment.index}">${escapeHtml(segment.displayName || `Subgraph_${segment.index}`)}</option>`)
    .join("");
  $("#previewSegmentSelect").value = String(state.selectedSegment);
  $("#previewSegmentSelect").onchange = (event) => {
    state.selectedSegment = Number(event.target.value);
    renderSegments();
    renderSelectedSegment();
  };
}

function renderSelectedSegment() {
  const segment = getSelectedSegment();
  if (!segment) return;
  $("#uploadTitle").textContent = `Image Upload - ${state.workflow.keyframeCount} Input Image${state.workflow.keyframeCount > 1 ? "s" : ""}`;
  $("#positivePrompt").value = segment.positivePrompt;
  $("#negativePrompt").value = segment.negativePrompt;
  $("#previewSegmentSelect").value = String(segment.index);
  renderKeyframeGrid();
  renderConfigControls();
  updatePreviewInfo();
  renderMainOutputPreview();
}

function renderKeyframeGrid() {
  const segment = getSelectedSegment();
  const activeIndexes = new Set([
    Number(segment?.startImageIndex || 0),
    Number(segment?.endImageIndex || 0),
  ]);
  const keyframeCards = state.keyframes
    .map((keyframe) => `
      <div class="keyframe-box ${activeIndexes.has(keyframe.index) ? "is-linked" : ""} ${keyframe.previewUrl ? "has-image" : ""}">
        <input type="file" accept="image/*" multiple data-keyframe-input="${keyframe.index}" />
        <span class="keyframe-index">Image ${keyframe.index}</span>
        ${keyframe.previewUrl ? `<button class="keyframe-clear" type="button" title="Remove image" data-clear-keyframe="${keyframe.index}">×</button>` : ""}
        <span class="keyframe-preview">
          ${keyframe.previewUrl
            ? `<img src="${escapeHtml(keyframe.previewUrl)}" alt="Input image ${keyframe.index}" />`
            : `<span class="image-icon" aria-hidden="true"></span>`}
        </span>
        <strong>${keyframe.previewUrl ? escapeHtml(compactText(keyframe.file?.name || keyframe.upload?.fileName || `Image ${keyframe.index}`, 22)) : "Select Image"}</strong>
        <small>${escapeHtml(keyframe.metaText)}</small>
      </div>
    `)
    .join("");
  $("#keyframeGrid").innerHTML = `${keyframeCards}${renderResultPreviewCard()}`;
}

function renderResultPreviewCard() {
  if (state.latestOutputSource !== "job") return "";
  const output = selectedOutputAsset();
  if (!output?.url) {
    if (state.latestOutputs.length && state.segments.length > 1) {
      return `
        <div class="keyframe-box result-box result-box-empty">
          <span class="keyframe-index">Result</span>
          <span class="keyframe-preview output-preview"><span class="result-empty-text">No segment video</span></span>
          <strong>${escapeHtml(getSelectedSegment()?.displayName || `Subgraph_${state.selectedSegment}`)}</strong>
          <small>final output only</small>
        </div>
      `;
    }
    return "";
  }
  const preview = isVideoOutput(output)
    ? `<video src="${escapeHtml(output.url)}" muted playsinline preload="metadata"></video>`
    : `<img src="${escapeHtml(output.url)}" alt="Generated output" />`;
  return `
    <div class="keyframe-box result-box has-image">
      <span class="keyframe-index">Result</span>
      <span class="keyframe-preview output-preview">${preview}</span>
      ${isVideoOutput(output) ? `<button class="result-play-button" type="button" title="Play in Picture-in-Picture" data-play-output>▶</button>` : ""}
      <strong>${escapeHtml(compactText(output.fileName || "Generated output", 22))}</strong>
      <small>${escapeHtml(output.kindLabel || "generated output")}</small>
    </div>
  `;
}

async function playResultInPicture(container) {
  const video = container?.querySelector("video");
  if (!video) return;
  try {
    await video.play();
    if (document.pictureInPictureElement === video) {
      await document.exitPictureInPicture();
      return;
    }
    if (document.pictureInPictureEnabled && video.requestPictureInPicture) {
      await video.requestPictureInPicture();
      return;
    }
    if (video.webkitSupportsPresentationMode && typeof video.webkitSetPresentationMode === "function") {
      video.webkitSetPresentationMode("picture-in-picture");
      return;
    }
    showNotice("이 브라우저는 Picture-in-Picture를 지원하지 않습니다.");
  } catch (error) {
    console.warn(error);
    showNotice("PiP 재생을 시작하지 못했습니다.");
  }
}

function applySelectedFiles(startIndex, files) {
  if (!files.length) return;
  files.forEach((file, offset) => {
    const targetIndex = startIndex + offset;
    if (targetIndex > state.workflow.keyframeCount) return;
    const keyframe = getKeyframe(targetIndex);
    if (keyframe.previewUrl) URL.revokeObjectURL(keyframe.previewUrl);
    keyframe.file = file;
    keyframe.upload = null;
    keyframe.previewUrl = URL.createObjectURL(file);
    keyframe.metaText = `${Math.round(file.size / 1024)}KB · pending upload`;
  });
  renderKeyframeGrid();
}

function clearKeyframe(index) {
  const keyframe = getKeyframe(index);
  if (keyframe.previewUrl?.startsWith("blob:")) URL.revokeObjectURL(keyframe.previewUrl);
  keyframe.file = null;
  keyframe.upload = null;
  keyframe.previewUrl = "";
  keyframe.metaText = "Image: 1024x1024";
  renderKeyframeGrid();
}

function releaseKeyframePreviews() {
  state.keyframes.forEach((keyframe) => {
    if (keyframe.previewUrl?.startsWith("blob:")) URL.revokeObjectURL(keyframe.previewUrl);
  });
}

function syncKeyframesFromHistory(item) {
  const rawKeyframes = Array.isArray(item.raw?.keyframes) ? item.raw.keyframes : [];
  const rawInputImages = Array.isArray(item.raw?.inputImages) ? item.raw.inputImages : [];
  const inputImages = Array.isArray(item.inputImages) ? item.inputImages : [];
  const inputAssets = item.inputAssets || item.raw?.inputAssets || [];
  const candidates = [...inputImages, ...rawInputImages, ...rawKeyframes].map((candidate, index) => ({
    index: Number(candidate.index || index + 1),
    assetId: candidate.assetId || candidate.uploadId || "",
    fileName: candidate.fileName || candidate.filename || "",
  }));
  state.keyframes = state.keyframes.map((keyframe, index) => {
    const candidate = candidates.find((entry) => entry.index === keyframe.index) || candidates[index] || {};
    const assetId = candidate.assetId || inputAssets[index] || "";
    if (!assetId) return keyframe;
    const fileName = candidate.fileName || `history-image-${keyframe.index}`;
    return {
      ...keyframe,
      file: null,
      upload: {
        assetId,
        fileName,
      },
      previewUrl: `/api/files/${encodeURIComponent(assetId)}`,
      metaText: `${fileName} · loaded from history`,
    };
  });
  return state.keyframes.filter((keyframe) => keyframe.upload?.assetId).length;
}

function renderConfigControls() {
  const segment = getSelectedSegment();
  const controls = segment.configControls?.length
    ? segment.configControls.filter((control) => control.key !== "seed")
    : [
        { key: "fps", label: "FPS", min: 8, max: 30, type: "int" },
        { key: "frames", label: "Frames", min: 24, max: 121, type: "int" },
        { key: "steps", label: "Sampling Steps", min: 10, max: 50, type: "int" },
        { key: "cfgScale", label: "CFG Scale", min: 1, max: 12, type: "float" },
        { key: "motionShift", label: "Motion Shift", min: 0, max: 2, type: "float" },
      ];

  $("#configControls").innerHTML = controls
    .map((control) => {
      const isTextControl = ["string", "text"].includes(control.type);
      const hasOptions = Array.isArray(control.options) && control.options.length > 1;
      const step = control.type === "int" ? 1 : 0.1;
      const min = control.min ?? 0;
      const max = control.max ?? Math.max(Number(segment.config[control.key] || 1) * 2, 1);
      const description = control.description || control.note || configDescriptions[control.key] || "";
      const value = segment.config[control.key] ?? control.default ?? "";
      const controlInput = hasOptions
        ? `<select data-config="${escapeHtml(control.key)}" data-config-type="${escapeHtml(control.type)}">
            ${control.options.map((option) => `<option value="${escapeHtml(option)}"${String(option) === String(value) ? " selected" : ""}>${escapeHtml(option)}</option>`).join("")}
          </select>`
        : isTextControl
          ? `<input type="text" value="${escapeHtml(value)}" data-config="${escapeHtml(control.key)}" data-config-type="${escapeHtml(control.type)}" />`
          : `<input type="range" min="${min}" max="${max}" step="${step}" value="${escapeHtml(value)}" data-config="${escapeHtml(control.key)}" data-config-type="${escapeHtml(control.type)}" />`;
      return `
      <label class="range-row">
        <span>${escapeHtml(control.label)}</span>
        <b id="${control.key}Value">${formatConfigValue(segment.config[control.key], control.type)}</b>
        ${controlInput}
        <small>${isTextControl || hasOptions ? "ComfyUI" : `${min}-${max}`}</small>
        <em>${escapeHtml(description)}</em>
      </label>
    `;
    })
    .join("") + `
      <label class="range-row">
        <span>Seed</span>
        <b></b>
        <input type="number" value="${segment.config.seed}" data-config="seed" />
        <small>Randomize</small>
        <em>${escapeHtml(configDescriptions.seed)}</em>
      </label>
    `;

  document.querySelectorAll("[data-config]").forEach((input) => {
    const updateConfigValue = (event) => {
      const key = event.target.dataset.config;
      const type = event.target.dataset.configType || "float";
      const value = ["string", "text"].includes(type) ? event.target.value : Number(event.target.value);
      segment.config[key] = value;
      const valueEl = $(`#${key}Value`);
      const control = segment.configControls?.find((item) => item.key === key);
      if (valueEl) valueEl.textContent = formatConfigValue(value, control?.type);
      updatePreviewInfo();
    };
    input.addEventListener("input", updateConfigValue);
    input.addEventListener("change", updateConfigValue);
  });
}

function formatConfigValue(value, type = "float") {
  const number = Number(value);
  if (!Number.isFinite(number)) return value ?? "";
  if (type === "int") return String(Math.round(number));
  return String(Number(number.toFixed(2)));
}

function updatePreviewInfo() {
  const segment = getSelectedSegment();
  $("#seedText").textContent = segment.config.seed;
  $("#fpsText").textContent = segment.config.fps;
  $("#promptSummary").textContent = segment.positivePrompt;
  $("#logText").textContent = segment.positivePrompt;
  const detail = $("#segmentDetailText");
  if (detail) detail.innerHTML = renderSegmentInfo(segment);
}

function renderSegmentInfo(segment) {
  const output = state.latestOutputSource === "job" ? selectedOutputAsset() : null;
  const finalOutput = state.latestOutputSource === "job" ? finalOutputAsset() : null;
  const config = segment?.config || {};
  const rows = [
    ["Workflow", workflowToken(state.workflow?.id || "")],
    ["View Subgraph", `${segment?.displayName || `Subgraph_${segment?.index || 1}`} / ${state.segments.length || 1}`],
    ["Frames", config.durationSeconds ? `${config.durationSeconds}s` : config.frames],
    ["Steps / CFG", `${formatConfigValue(config.steps, "int")} / ${formatConfigValue(config.cfgScale, "float")}`],
    ["Motion", formatConfigValue(config.motionShift, "float")],
    ["Subgraph Output", output?.fileName || (finalOutput ? "Not saved separately" : "Waiting for generated video")],
    ["Final Output", finalOutput?.fileName || "-"],
  ];
  return rows
    .map(([label, value]) => `<p><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? "-")}</strong></p>`)
    .join("");
}

function workflowToken(workflowId) {
  const match = String(workflowId || "").match(/(\d+)\s*[-_]?key/i);
  return match ? `${match[1]}key` : String(workflowId || "workflow").replace(/\.json$/, "");
}

function normalizeOutputAsset(asset) {
  if (!asset) return null;
  const rawUrl = asset.downloadUrl || asset.url || asset.outputUrl || "";
  if (!rawUrl) return null;
  const fileName = asset.fileName || asset.filename || "generated-output";
  const isVideo = looksLikeVideoAsset({ ...asset, fileName, url: rawUrl });
  const kind = isVideo ? "videos" : (asset.kind || (String(asset.mimeType || "").startsWith("image/") ? "images" : "output"));
  return {
    ...asset,
    url: fileUrlWithMode(rawUrl, "inline"),
    downloadUrl: fileUrlWithMode(asset.downloadUrl || rawUrl, "download"),
    fileName,
    kind,
    mimeType: asset.mimeType || (isVideo ? "video/mp4" : asset.mimeType),
    kindLabel: isVideo ? "generated MP4" : `generated ${kind}`,
    outputRole: asset.outputRole || "",
    segmentIndex: asset.segmentIndex == null ? null : Number(asset.segmentIndex),
  };
}

function fileUrlWithMode(url, mode) {
  const text = String(url || "");
  const isAbsoluteHttp = /^https?:\/\//i.test(text);
  const origin = apiFileOrigin();
  const isLocalFile = text.startsWith("/api/files/")
    || text.startsWith(`${origin}/api/files/`)
    || /^https?:\/\/[^/]+\/api\/files\//.test(text);
  if (!isLocalFile) return url;
  const parsed = new URL(text, origin);
  parsed.searchParams.delete("download");
  parsed.searchParams.delete("inline");
  parsed.searchParams.set(mode === "download" ? "download" : "inline", "1");
  if (isAbsoluteHttp) return parsed.href;
  return apiUrl(`${parsed.pathname}${parsed.search}${parsed.hash}`);
}

function apiFileOrigin() {
  const baseUrl = apiBaseUrl();
  if (baseUrl) return new URL(baseUrl, window.location.href).origin;
  return window.location.origin;
}

function normalizeOutputAssets(assets = []) {
  return assets.map(normalizeOutputAsset).filter(Boolean);
}

function finalOutputAsset(assets = state.latestOutputs) {
  return assets.find((asset) => asset.outputRole === "final")
    || (state.segments.length <= 1 ? assets[0] : assets.find((asset) => !asset.segmentIndex) || null);
}

function historyOutputAssets(item) {
  return item?.outputAssets?.length
    ? normalizeOutputAssets(item.outputAssets)
    : normalizeOutputAssets(item?.outputUrl ? [{ downloadUrl: item.outputUrl, fileName: "remote output", kind: "videos", outputRole: "final" }] : []);
}

function historyOutputAsset(item) {
  const outputs = historyOutputAssets(item);
  return outputs.find((asset) => asset.outputRole === "final")
    || outputs.find((asset) => !asset.segmentIndex)
    || outputs[0]
    || null;
}

function segmentOutputAsset(segmentIndex = state.selectedSegment, assets = state.latestOutputs) {
  return assets.find((asset) => Number(asset.segmentIndex) === Number(segmentIndex) && asset.outputRole !== "final") || null;
}

function selectedOutputAsset() {
  return segmentOutputAsset(state.selectedSegment) || (state.segments.length <= 1 ? finalOutputAsset() : null);
}

function isVideoOutput(output) {
  return looksLikeVideoAsset(output);
}

function looksLikeVideoAsset(asset) {
  const values = [
    asset?.kind,
    asset?.mimeType,
    asset?.fileName,
    asset?.filename,
    asset?.url,
    asset?.downloadUrl,
    asset?.outputUrl,
  ].map((value) => String(value || ""));
  return values.some((value) => value.toLowerCase().includes("video"))
    || values.some((value) => /\.(mp4|mov|m4v|webm)(?:$|[?#])/i.test(value));
}

function renderMainOutputPreview() {
  const frame = $("#outputVideoFrame");
  if (!frame) return;
  if (state.latestOutputSource !== "job") {
    frame.innerHTML = `
      <div class="neon-scene" aria-label="생성 영상 프리뷰"></div>
      <div class="player-bar"><span></span><b>0:00</b><i></i></div>
    `;
    return;
  }
  const output = selectedOutputAsset();
  if (!output?.url) {
    const hasFinalOnly = state.latestOutputs.length && state.segments.length > 1;
    frame.innerHTML = hasFinalOnly
      ? `<div class="empty-output-frame">${escapeHtml(getSelectedSegment()?.displayName || `Subgraph_${state.selectedSegment}`)} video is not saved separately.</div>`
      : `
        <div class="neon-scene" aria-label="생성 영상 프리뷰"></div>
        <div class="player-bar"><span></span><b>0:00</b><i></i></div>
      `;
    return;
  }
  if (isVideoOutput(output)) {
    frame.innerHTML = `<video class="main-output-video" src="${escapeHtml(output.url)}" controls playsinline preload="metadata"></video>`;
  } else {
    frame.innerHTML = `<img class="main-output-image" src="${escapeHtml(output.url)}" alt="Generated output" />`;
  }
}

function renderOutputPreview(output, className = "detail-output-video") {
  if (!output?.url) {
    return `<div class="mini-video neon-scene"></div>`;
  }
  if (isVideoOutput(output)) {
    return `<video class="${escapeHtml(className)}" src="${escapeHtml(output.url)}" controls playsinline preload="metadata"></video>`;
  }
  return `<img class="${escapeHtml(className)}" src="${escapeHtml(output.url)}" alt="Generated output" />`;
}

function outputAssetLabel(asset, fallbackIndex = 0, segments = state.segments) {
  if (asset?.outputRole === "segment" || (asset?.segmentIndex && asset?.outputRole !== "final")) {
    const segment = segments.find((item) => Number(item.index) === Number(asset.segmentIndex));
    return segment?.displayName || `Subgraph_${asset.segmentIndex}`;
  }
  if (asset?.outputRole === "final" || !asset?.segmentIndex) return "Final Output";
  return `Output ${fallbackIndex + 1}`;
}

function renderHistoryVideoOutputs(item, historyIndex) {
  const outputs = historyOutputAssets(item);
  if (!outputs.length) {
    return `
      <div class="detail-video">
        <div class="mini-video neon-scene"></div>
        <p>File: -<br />Seed: ${escapeHtml(item.seed)}<br />FPS: ${escapeHtml(item.fps)}<br />Segments: ${escapeHtml(item.segments)}</p>
      </div>
    `;
  }
  const sorted = [...outputs].sort((a, b) => {
    const rank = (asset) => asset.outputRole === "final" || !asset.segmentIndex ? 0 : 1;
    return rank(a) - rank(b) || Number(a.segmentIndex || 0) - Number(b.segmentIndex || 0);
  });
  return `
    <div class="history-output-list">
      ${sorted.map((asset, outputIndex) => `
        <section class="detail-video history-output-card">
          <h3>${escapeHtml(outputAssetLabel(asset, outputIndex, item.segmentItems || []))}</h3>
          ${renderOutputPreview(asset)}
          <p>File: ${escapeHtml(asset.fileName || "-")}<br />Seed: ${escapeHtml(item.seed)}<br />FPS: ${escapeHtml(item.fps)}<br />Segments: ${escapeHtml(item.segments)}</p>
          <button class="secondary-button" type="button" data-download-url="${escapeHtml(asset.downloadUrl || "")}">Download MP4</button>
        </section>
      `).join("")}
    </div>
  `;
}

function getSelectedSegment() {
  return state.segments.find((segment) => segment.index === state.selectedSegment) || state.segments[0];
}

function getKeyframe(index) {
  let keyframe = state.keyframes.find((item) => item.index === index);
  if (!keyframe) {
    keyframe = { index, file: null, upload: null, previewUrl: "", metaText: "Image: 1024x1024" };
    state.keyframes.push(keyframe);
  }
  return keyframe;
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

async function uploadKeyframe(keyframe) {
  if (!keyframe.file) return null;
  if (keyframe.upload) return keyframe.upload;
  const dataUrl = await fileToDataUrl(keyframe.file);
  const upload = await apiRequest("/api/uploads", {
    method: "POST",
    body: JSON.stringify({
      fileName: keyframe.file.name,
      mimeType: keyframe.file.type || "application/octet-stream",
      dataUrl,
    }),
  });
  keyframe.upload = upload;
  keyframe.metaText = `${upload.fileName} · ${(upload.sizeBytes / 1024 / 1024).toFixed(1)}MB · uploaded`;
  return upload;
}

async function uploadPendingKeyframes() {
  for (const keyframe of state.keyframes) {
    await uploadKeyframe(keyframe);
  }
  renderKeyframeGrid();
}

function missingKeyframes() {
  return state.keyframes.filter((keyframe) => !keyframe.file && !keyframe.upload);
}

function buildJobPayload() {
  return {
    workflowId: state.workflow.id,
    user: state.user,
    keyframes: state.keyframes.map((keyframe) => ({
      index: keyframe.index,
      uploadId: keyframe.upload?.assetId || null,
      fileName: keyframe.upload?.fileName || keyframe.file?.name || `mock-keyframe-${keyframe.index}.png`,
    })),
    segments: state.segments.map((segment) => ({
      index: segment.index,
      nodeId: segment.nodeId,
      subgraphName: segment.subgraphName,
      displayName: segment.displayName,
      positivePrompt: segment.positivePrompt,
      negativePromptAddition: segment.negativePromptAddition || segment.negativePrompt,
      config: segment.config,
    })),
  };
}

function buildCurrentSnapshot() {
  return {
    workflowId: state.workflow.id,
    user: state.user,
    keyframes: state.keyframes.map((keyframe) => ({
      index: keyframe.index,
      uploadId: keyframe.upload?.assetId || null,
      fileName: keyframe.upload?.fileName || keyframe.file?.name || keyframe.metaText,
    })),
    segments: state.segments.map((segment) => ({
      index: segment.index,
      nodeId: segment.nodeId,
      subgraphName: segment.subgraphName,
      displayName: segment.displayName,
      positivePrompt: segment.positivePrompt,
      negativePromptAddition: segment.negativePromptAddition || segment.negativePrompt,
      config: { ...segment.config },
    })),
  };
}

function selectedHistoryItem() {
  return state.history[state.selectedHistoryIndex] || state.history[0] || null;
}

async function openMetadataModal() {
  state.metadataWorkflowId = state.workflow?.id || state.workflows[0]?.id || "";
  $("#metadataWorkflowSelect").innerHTML = state.workflows
    .map((workflow) => `<option value="${escapeHtml(workflow.id)}">${escapeHtml(workflow.name || workflow.id)}</option>`)
    .join("");
  $("#metadataWorkflowSelect").value = state.metadataWorkflowId;
  $("#metadataModal").classList.remove("is-hidden");
  await loadMetadataForWorkflow(state.metadataWorkflowId);
}

async function loadMetadataForWorkflow(workflowId) {
  state.metadataWorkflowId = workflowId || state.metadataWorkflowId || state.workflow?.id;
  $("#metadataBody").innerHTML = `<p class="empty-picker">Metadata를 불러오는 중입니다.</p>`;
  try {
    const [status, metadata, models] = await Promise.all([
      apiRequest("/api/metadata/status"),
      apiRequest(`/api/workflows/${encodeURIComponent(state.metadataWorkflowId)}/widget-metadata`),
      apiRequest("/api/metadata/models"),
    ]);
    state.metadataStatus = status;
    state.metadata = metadata;
    state.metadataModels = models;
  } catch (error) {
    console.warn(error);
    state.metadataStatus = null;
    state.metadata = null;
    state.metadataModels = null;
    $("#metadataBody").innerHTML = `<p class="empty-picker">Metadata를 불러오지 못했습니다.</p>`;
    return;
  }
  renderMetadataModal();
}

async function rebuildMetadata() {
  const button = $("#rebuildMetadataButton");
  button.disabled = true;
  button.textContent = "Rebuilding...";
  try {
    await apiRequest("/api/metadata/rebuild", { method: "POST" });
    await loadMetadataForWorkflow(state.metadataWorkflowId);
  } catch (error) {
    console.warn(error);
    $("#metadataBody").innerHTML = `<p class="empty-picker">Metadata 재생성에 실패했습니다.</p>`;
  } finally {
    button.disabled = false;
    button.textContent = "Rebuild Metadata";
  }
}

function renderMetadataModal() {
  document.querySelectorAll("[data-metadata-tab]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.metadataTab === state.activeMetadataTab);
  });
  if ($("#metadataWorkflowSelect").value !== state.metadataWorkflowId) {
    $("#metadataWorkflowSelect").value = state.metadataWorkflowId;
  }
  const renderers = {
    summary: renderMetadataSummary,
    subgraphs: renderMetadataSubgraphs,
    parameters: renderMetadataParameters,
    models: renderMetadataModels,
    nodes: renderMetadataNodes,
  };
  $("#metadataBody").innerHTML = (renderers[state.activeMetadataTab] || renderMetadataSummary)();
}

function renderMetadataSummary() {
  const metadata = state.metadata || {};
  const manifest = state.metadataStatus?.manifest || {};
  return `
    <div class="metadata-summary">
      <table>
        <tr><td>Workflow ID</td><td>${escapeHtml(metadata.workflowId || "-")}</td></tr>
        <tr><td>Node Count</td><td>${escapeHtml(metadata.nodeCount ?? "-")}</td></tr>
        <tr><td>Subgraphs</td><td>${escapeHtml((metadata.segments || []).length)}</td></tr>
        <tr><td>Generated At</td><td>${escapeHtml(manifest.generatedAt || "-")}</td></tr>
        <tr><td>Object Info Snapshot</td><td>${manifest.hasObjectInfoSnapshot ? "YES" : "NO"}</td></tr>
        <tr><td>Fingerprint</td><td><code>${escapeHtml(String(manifest.fingerprint || "-").slice(0, 24))}</code></td></tr>
      </table>
    </div>
  `;
}

function renderMetadataSubgraphs() {
  const segments = state.metadata?.segments || [];
  return segments.length
    ? segments.map((segment) => `
        <article class="metadata-card">
          <h3>${escapeHtml(segment.displayName || `Subgraph_${segment.index}`)}</h3>
          <table>
            <tr><td>Node ID</td><td>${escapeHtml(segment.nodeId || "-")}</td></tr>
            <tr><td>Class Type</td><td>${escapeHtml(segment.classType || "-")}</td></tr>
            <tr><td>Positive Node</td><td>${escapeHtml(segment.positiveNode || "-")}</td></tr>
            <tr><td>Negative Node</td><td>${escapeHtml(segment.negativeNode || "-")}</td></tr>
            <tr><td>Start Image</td><td>${escapeHtml(segment.startImageNode || "-")}</td></tr>
            <tr><td>End Image</td><td>${escapeHtml(segment.endImageNode || "-")}</td></tr>
          </table>
        </article>
      `).join("")
    : `<p class="empty-picker">Subgraph metadata가 없습니다.</p>`;
}

function renderMetadataParameters() {
  const segments = state.metadata?.segments || [];
  return segments.length
    ? segments.map((segment) => `
        <article class="metadata-card">
          <h3>${escapeHtml(segment.displayName || `Subgraph_${segment.index}`)}</h3>
          ${(segment.params || []).map((param) => `
            <section class="metadata-param">
              <strong>${escapeHtml(param.label || param.param)}</strong>
              <small>${escapeHtml(param.param)} · default ${escapeHtml(param.default ?? "-")}</small>
              <pre>${escapeHtml(JSON.stringify(param.targets || [], null, 2))}</pre>
            </section>
          `).join("") || "<p>No parameters.</p>"}
        </article>
      `).join("")
    : `<p class="empty-picker">Parameter metadata가 없습니다.</p>`;
}

function renderMetadataModels() {
  const models = state.metadata?.models || state.metadataModels?.models || {};
  const entries = Object.entries(models);
  return entries.length
    ? entries.map(([group, values]) => `
        <article class="metadata-card">
          <h3>${escapeHtml(group)}</h3>
          <ul>${(values || []).map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>
        </article>
      `).join("")
    : `<p class="empty-picker">Model metadata가 없습니다.</p>`;
}

function renderMetadataNodes() {
  const nodes = state.metadata?.nodes || [];
  return nodes.length
    ? `<div class="metadata-node-list">
        ${nodes.map((node) => `
          <details class="metadata-node">
            <summary><strong>${escapeHtml(node.nodeId)}</strong> ${escapeHtml(node.title || node.classType)}</summary>
            <p>Class: <code>${escapeHtml(node.classType || "-")}</code></p>
            <pre>${escapeHtml(JSON.stringify({ inputs: node.inputs || [], links: node.links || [] }, null, 2))}</pre>
          </details>
        `).join("")}
      </div>`
    : `<p class="empty-picker">Node metadata가 없습니다.</p>`;
}

function showNotice(message) {
  const notice = $("#modalNotice");
  const modalOpen = !$("#historyModal")?.classList.contains("is-hidden");
  if (notice && modalOpen) {
    notice.textContent = message;
    notice.classList.add("is-visible");
  } else if ($("#logText")) {
    $("#logText").textContent = message;
  } else {
    alert(message);
  }
}

function readableErrorMessage(error) {
  const raw = error?.message || String(error || "Unknown error");
  try {
    const parsed = JSON.parse(raw);
    return parsed.error || parsed.message || raw;
  } catch {
    return raw;
  }
}

async function generateJob() {
  if (state.running) return;
  const runVersion = ++state.runVersion;
  const missing = missingKeyframes();
  if (missing.length) {
    alert(`필요한 입력 이미지 ${missing.length}개가 비어 있습니다. Image ${missing.map((item) => item.index).join(", ")} 슬롯을 채워주세요.`);
    return;
  }
  resetRunVisualState();
  state.running = true;
  state.cancelRequested = false;
  $("#generateButton").textContent = "SUBMITTING...";
  updateGenerationControls();

  try {
    await uploadPendingKeyframes();
    const created = await apiRequest("/api/jobs", {
      method: "POST",
      body: JSON.stringify(buildJobPayload()),
    });
    state.currentTaskId = created.taskId;
    $("#generateButton").textContent = "GENERATING...";
    updateGenerationControls();
    const finalJob = await pollJob(created.taskId, runVersion);
    if (!finalJob) return;
    if (String(finalJob?.status || "").toLowerCase() === "success") {
      handleCompletedJob(finalJob);
      renderHistory(await loadHistory());
    } else if (String(finalJob?.status || "").toLowerCase() === "cancelled") {
      renderApiJobStatus(finalJob);
      updateRunProgress(100, finalJob.elapsedSeconds || state.elapsed, "RunPod job cancelled.", finalJob);
      state.latestJob = finalJob;
    } else {
      handleCompletedJob(finalJob);
      renderHistory(await loadHistory());
    }
  } catch (error) {
    console.warn(error);
    const message = readableErrorMessage(error);
    renderApiJobStatus({ status: "fail", rawStatus: "FAILED", statusLabel: "실패" });
    updateRunProgress(state.runProgress, state.elapsed, `RunPod 실행 실패: ${message}`);
    alert(`RunPod 실행 실패\n\n${message}`);
  } finally {
    if (runVersion === state.runVersion) {
      state.running = false;
      state.cancelRequested = false;
      $("#generateButton").textContent = "GENERATE VIDEO";
      updateGenerationControls();
    }
  }
}

async function cancelGeneration() {
  if (!state.running || !state.currentTaskId || state.cancelRequested) return;
  state.cancelRequested = true;
  updateGenerationControls();
  updateRunProgress(state.runProgress, state.elapsed, "Cancel requested. Waiting for RunPod confirmation...");
  try {
    const job = await apiRequest(`/api/jobs/${encodeURIComponent(state.currentTaskId)}/cancel`, { method: "POST" });
    renderApiJobStatus(job);
    updateRunProgress(job.progress || 100, job.elapsedSeconds || state.elapsed, "RunPod job cancelled.", job);
  } catch (error) {
    console.warn(error);
    state.cancelRequested = false;
    updateGenerationControls();
    updateRunProgress(state.runProgress, state.elapsed, `Cancel failed: ${readableErrorMessage(error)}`);
  }
}

function updateGenerationControls() {
  const cancelButton = $("#cancelGenerationButton");
  const generateButton = $("#generateButton");
  if (!cancelButton || !generateButton) return;
  cancelButton.classList.toggle("is-hidden", !state.running);
  cancelButton.disabled = !state.currentTaskId || state.cancelRequested;
  cancelButton.textContent = state.cancelRequested ? "Cancelling..." : "Cancel Generation";
  generateButton.disabled = state.running;
}

async function pollJob(taskId, runVersion = state.runVersion) {
  let done = false;
  let latestJob = null;
  while (!done) {
    if (runVersion !== state.runVersion) return null;
    const job = await apiRequest(`/api/jobs/${encodeURIComponent(taskId)}`);
    if (runVersion !== state.runVersion) return null;
    latestJob = job;
    renderApiJobStatus(job);
    updateRunProgress(job.progress || 0, job.elapsedSeconds || 0, job.message || job.status, job);
    done = ["success", "fail", "cancelled", "timed_out"].includes(String(job.status).toLowerCase());
    if (!done) {
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
  }
  if (runVersion !== state.runVersion) return null;
  await refreshSystemStatus(false);
  return latestJob;
}

function handleCompletedJob(job) {
  state.latestJob = job || null;
  const outputs = normalizeOutputAssets(job?.outputAssets || []);
  if (!outputs.length && job?.outputUrl) {
    outputs.push(normalizeOutputAsset({ downloadUrl: job.outputUrl, fileName: "remote output", kind: "videos", outputRole: "final" }));
  }
  state.latestOutputs = outputs;
  state.latestOutputSource = outputs.length ? "job" : "";
  state.latestOutput = selectedOutputAsset() || finalOutputAsset();
  if (String(job?.status).toLowerCase() === "success") {
    state.segments = state.segments.map((segment) => ({ ...segment, progress: 100 }));
    state.runProgress = 100;
  }
  renderSegments();
  renderKeyframeGrid();
  renderMainOutputPreview();
  updatePreviewInfo();
}

function updateRunProgress(progress, elapsedSeconds, message, job = null) {
  state.runProgress = Math.min(100, Math.max(0, Math.round(progress)));
  state.elapsed = Math.round(elapsedSeconds);
  updateSegmentProgressFromRun(state.runProgress);
  $(".progress-ring").style.setProperty("--pct", state.runProgress);
  $("#runProgressText").textContent = `${state.runProgress}%`;
  $("#globalProgressText").textContent = `${state.runProgress}%`;
  $("#globalProgressBar").style.width = `${state.runProgress}%`;
  $("#elapsedText").textContent = formatElapsed(state.elapsed);
  $("#logPercent").textContent = `(${state.runProgress}%)`;
  renderSegments();
  if (job?.rawStatus) {
    $("#logText").textContent = `RUNPOD STATUS : ${String(job.rawStatus).toUpperCase()}`;
  } else if (message) {
    $("#logText").textContent = message;
  }
}

function formatElapsed(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `00:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

async function loadHistory() {
  try {
    const data = await apiRequest("/api/history?pageSize=200");
    state.history = (data.items || []).map(normalizeHistoryItem);
  } catch {
    if (!state.history.length) {
      state.history = [
        normalizeHistoryItem({
          taskId: "task_demo_001",
          timestamp: "2026-07-28 18:39:36",
          prompt: "",
          config: "Wan node: FPS 16, Steps 4",
          status: "Completed",
          workflow: "1-images.json",
          seed: 4920381920,
          fps: 24,
          segments: 1,
        }),
      ];
    }
  }
  return state.history;
}

function normalizeHistoryItem(item) {
  const rawSegments = Array.isArray(item.segments) ? item.segments : [];
  const firstSegment = rawSegments[0];
  const config = firstSegment?.config || item.configJson || {};
  const segmentCount = item.segmentCount || item.segment_count || rawSegments.length || Number(item.segments) || 1;
  const outputAssets = normalizeOutputAssets(item.outputAssets || []);
  const firstOutputUrl = finalOutputAsset(outputAssets)?.url || outputAssets[0]?.url || item.remoteOutputUrls?.[0] || "";
  const positivePrompts = normalizePromptItems(item.positivePrompts, "positive", item, rawSegments);
  const negativePrompts = normalizePromptItems(item.negativePrompts, "negative", item, rawSegments);
  return {
    raw: item,
    taskId: item.taskId || item.task_id || `task_${Date.now()}`,
    timestamp: item.timestamp || item.startedAt || item.createdAt || "-",
    workerName: item.workerName || item.user?.name || item.userName || "-",
    prompt: positivePrompts.map((prompt) => prompt.text).join(" | ") || item.prompt || item.positivePrompt || firstSegment?.positivePrompt || "",
    positivePrompts,
    config: item.config || `Wan node: FPS ${config.fps || item.fps || 16}, Steps ${config.steps || 4}${config.durationSeconds ? `, Duration ${config.durationSeconds}s` : ""}`,
    status: item.status || "Completed",
    workflow: item.workflow || item.workflowName || item.workflowId || state.workflow.id,
    seed: config.seed || item.seed || 4920381920,
    fps: config.fps || item.fps || 24,
    segmentItems: rawSegments,
    segments: segmentCount,
    configJson: config,
    wanNodeConfig: item.wanNodeConfig || {},
    negativePrompt: negativePrompts.map((prompt) => prompt.text).join(" | ") || item.negativePrompt || firstSegment?.negativePromptAddition || "",
    negativePrompts,
    outputUrl: item.outputUrl || item.outputFile || firstOutputUrl,
    outputAssets,
    inputAssets: item.inputAssets || [],
    inputImages: normalizeInputImages(item),
  };
}

function configFromWanNodeSegment(segment) {
  const config = { ...(segment?.config || {}) };
  (segment?.params || []).forEach((param) => {
    const key = param.uiKey;
    if (!key || param.value === undefined || param.value === null) return;
    config[key] = param.value;
  });
  return config;
}

function normalizePromptItems(items, type, item, segments = []) {
  if (Array.isArray(items) && items.length) {
    return items
      .map((entry, index) => ({
        index: Number(entry?.index || index + 1),
        text: String(typeof entry === "string" ? entry : entry?.text || entry?.prompt || "").trim(),
      }))
      .filter((entry) => entry.text);
  }
  const segmentKey = type === "positive" ? "positivePrompt" : "negativePromptAddition";
  const fromSegments = segments
    .map((segment, index) => ({
      index: Number(segment.index || index + 1),
      text: String(segment[segmentKey] || "").trim(),
    }))
    .filter((entry) => entry.text);
  if (fromSegments.length) return fromSegments;
  const fallback = type === "positive"
    ? item.positivePrompt || item.prompt || ""
    : item.negativePrompt || "";
  return splitPromptList(fallback);
}

function splitPromptList(value) {
  const text = String(value || "").trim();
  if (!text) return [];
  const parts = text.split("|").map((part) => part.trim()).filter(Boolean);
  return (parts.length ? parts : [text]).map((part, index) => ({
    index: index + 1,
    text: part.replace(/^\s*\d+\s*[:.)-]\s*/, "").trim(),
  })).filter((entry) => entry.text);
}

function normalizeInputImages(item) {
  if (Array.isArray(item.inputImages) && item.inputImages.length) {
    return item.inputImages.map((image, index) => ({
      index: Number(image.index || index + 1),
      assetId: image.assetId || "",
      fileName: image.fileName || image.filename || "-",
    }));
  }
  const inputAssets = item.inputAssets || [];
  const keyframes = item.keyframes || [];
  const count = Math.max(inputAssets.length, keyframes.length);
  return Array.from({ length: count }, (_, index) => {
    const keyframe = keyframes[index] || {};
    return {
      index: Number(keyframe.index || index + 1),
      assetId: keyframe.uploadId || inputAssets[index] || "",
      fileName: keyframe.fileName || "-",
    };
  }).filter((image) => image.assetId || image.fileName !== "-");
}

function renderHistory(historyItems = state.history) {
  const total = historyItems.length;
  const pageSize = state.historyPageSize;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  state.historyPage = Math.min(Math.max(1, state.historyPage), pageCount);
  const pageStart = (state.historyPage - 1) * pageSize;
  const pageItems = historyItems.slice(pageStart, pageStart + pageSize);
  state.selectedHistoryIndex = Math.min(state.selectedHistoryIndex, Math.max(0, total - 1));
  if (total && (state.selectedHistoryIndex < pageStart || state.selectedHistoryIndex >= pageStart + pageItems.length)) {
    state.selectedHistoryIndex = pageStart;
  }
  $("#historyRows").innerHTML = pageItems
    .map((item, localIndex) => {
      const index = pageStart + localIndex;
      return `
      <tr class="${index === state.selectedHistoryIndex ? "is-selected" : ""}" data-history="${index}">
        <td class="sequence-cell">${index + 1}</td>
        <td>${escapeHtml(formatTimestamp(item.timestamp))}</td>
        <td>${escapeHtml(item.workerName || "-")}</td>
        <td>${renderPromptCell(item.positivePrompts, index, "positive")}</td>
        <td>${renderPromptCell(item.negativePrompts, index, "negative")}</td>
        <td><span class="status-tag ${isSuccess(item.status) ? "completed" : "failed"}">${escapeHtml(item.status)}</span></td>
        <td><button class="view-button" type="button" data-view-history="${index}">□</button></td>
        <td><button class="secondary-button" type="button" data-download="${index}">Download MP4</button></td>
        <td><button class="rework-button" type="button" data-rework-history="${index}">재작업</button></td>
        <td><button class="danger-button history-delete-button" type="button" data-delete-history="${index}">삭제</button></td>
      </tr>
    `;
    })
    .join("");
  renderHistoryPagination(total, pageCount);

  document.querySelectorAll("tr[data-history]").forEach((row) => {
    row.addEventListener("click", () => selectHistoryRow(Number(row.dataset.history || 0)));
  });
  document.querySelectorAll("[data-view-history]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      showHistoryOutput(Number(button.dataset.viewHistory || 0));
    });
  });
  document.querySelectorAll("[data-download]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const item = state.history[Number(button.dataset.download)];
      const output = historyOutputAsset(item);
      if (output?.downloadUrl) {
        window.open(output.downloadUrl, "_blank");
      } else {
        showNotice("생성된 MP4 파일이 없습니다.");
      }
    });
  });
  document.querySelectorAll("[data-delete-history]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openDeleteHistoryModal(Number(button.dataset.deleteHistory));
    });
  });
  document.querySelectorAll("[data-rework-history]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await applyHistoryConfig(Number(button.dataset.reworkHistory), { closeHistoryModal: true, sourceLabel: "재작업" });
    });
  });
  document.querySelectorAll("[data-copy-prompt]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const item = state.history[Number(button.dataset.copyIndex)];
      const field = button.dataset.copyPrompt;
      const prompts = field === "negative" ? item?.negativePrompts : item?.positivePrompts;
      await copyText(formatPromptListForCopy(prompts));
    });
  });
  renderTaskDetail(state.selectedHistoryIndex);
}

function renderHistoryPagination(total, pageCount) {
  const container = $("#historyPagination");
  if (!container) return;
  if (!total) {
    container.innerHTML = `<span>0 / 0</span>`;
    return;
  }
  const start = (state.historyPage - 1) * state.historyPageSize + 1;
  const end = Math.min(total, state.historyPage * state.historyPageSize);
  const pages = Array.from({ length: pageCount }, (_, index) => index + 1);
  container.innerHTML = `
    <span>${start}-${end} / ${total}</span>
    <div>
      <button class="secondary-button" type="button" data-history-page="${state.historyPage - 1}" ${state.historyPage <= 1 ? "disabled" : ""}>Prev</button>
      ${pages.map((page) => `
        <button class="secondary-button ${page === state.historyPage ? "is-active" : ""}" type="button" data-history-page="${page}">${page}</button>
      `).join("")}
      <button class="secondary-button" type="button" data-history-page="${state.historyPage + 1}" ${state.historyPage >= pageCount ? "disabled" : ""}>Next</button>
    </div>
  `;
  document.querySelectorAll("[data-history-page]").forEach((button) => {
    button.addEventListener("click", () => {
      const page = Number(button.dataset.historyPage);
      if (!Number.isFinite(page) || page < 1 || page > pageCount || page === state.historyPage) return;
      state.historyPage = page;
      state.selectedHistoryIndex = (page - 1) * state.historyPageSize;
      renderHistory(state.history);
    });
  });
}

function renderPromptCell(prompts, historyIndex, field) {
  const list = (prompts || []).filter((prompt) => prompt.text);
  const copyText = formatPromptListForCopy(list);
  if (!list.length) return `<span class="muted-text">-</span>`;
  return `
    <div class="prompt-cell" title="${escapeHtml(copyText)}">
      <ol>
        ${list.map((prompt, index) => `<li><span>${escapeHtml(compactText(prompt.text, index === 0 ? 48 : 36))}</span></li>`).join("")}
      </ol>
      <button class="copy-button" type="button" data-copy-prompt="${field}" data-copy-index="${historyIndex}">Copy</button>
    </div>
  `;
}

function formatPromptListForCopy(prompts = []) {
  return prompts
    .filter((prompt) => prompt?.text)
    .map((prompt, index) => `${prompt.index || index + 1}. ${prompt.text}`)
    .join("\n");
}

async function copyText(text) {
  if (!text) {
    showNotice("복사할 내용이 없습니다.");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    showNotice("프롬프트를 복사했습니다.");
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
    showNotice("프롬프트를 복사했습니다.");
  }
}

function openDeleteHistoryModal(index) {
  if (!state.history[index]?.taskId) {
    showNotice("삭제할 작업 ID가 없습니다.");
    return;
  }
  state.pendingDeleteHistoryIndex = index;
  $("#deleteHistoryModal").classList.remove("is-hidden");
}

function closeDeleteHistoryModal() {
  state.pendingDeleteHistoryIndex = null;
  $("#deleteHistoryModal").classList.add("is-hidden");
  $("#confirmDeleteHistoryButton").disabled = false;
  $("#confirmDeleteHistoryButton").textContent = "삭제";
}

async function confirmDeleteHistory() {
  const index = state.pendingDeleteHistoryIndex;
  const item = state.history[index];
  if (!item?.taskId) {
    closeDeleteHistoryModal();
    showNotice("삭제할 작업 ID가 없습니다.");
    return;
  }
  const button = $("#confirmDeleteHistoryButton");
  button.disabled = true;
  button.textContent = "삭제 중...";
  try {
    await apiRequest(`/api/history/${encodeURIComponent(item.taskId)}/delete`, { method: "POST" });
    closeDeleteHistoryModal();
    state.history = await loadHistory();
    state.selectedHistoryIndex = Math.min(index, Math.max(0, state.history.length - 1));
    renderHistory(state.history);
    showNotice("작업 내역과 연결된 asset을 삭제했습니다.");
  } catch (error) {
    console.warn(error);
    button.disabled = false;
    button.textContent = "삭제";
    showNotice(`삭제 실패: ${readableErrorMessage(error)}`);
  }
}

function selectHistoryRow(index) {
  state.selectedHistoryIndex = index;
  renderHistory(state.history);
}

function showHistoryOutput(index) {
  state.selectedHistoryIndex = index;
  state.activeHistoryTab = "video";
  renderHistory(state.history);
}

function compactText(value, maxLength) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function formatTimestamp(value) {
  const text = String(value || "-");
  return text.replace(" ", "\n");
}

function isSuccess(status) {
  return ["completed", "success"].includes(String(status).toLowerCase());
}

function segmentSummary(config = {}) {
  const frames = config.durationSeconds ? `${config.durationSeconds}s` : `${config.frames || "-"}f`;
  return `FPS ${config.fps || "-"} · ${frames} · Steps ${config.steps || "-"} · CFG ${config.cfgScale ?? "-"}`;
}

function renderTaskDetail(index) {
  const item = state.history[index] || state.history[0];
  if (!item) {
    $("#detailBody").innerHTML = `<p class="empty-picker">작업 이력이 없습니다.</p>`;
    return;
  }
  state.selectedHistoryIndex = index;

  document.querySelectorAll("[data-detail-tab]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.detailTab === state.activeHistoryTab);
  });

  const output = historyOutputAsset(item);
  const segmentCards = Array.from({ length: Number(item.segments) || 1 }, (_, segmentIndex) => `
    <div class="detail-segment">
      <span class="mini-graph" data-progress="${isSuccess(item.status) ? "100%" : "0%"}"></span>
      <div>
        <strong>${escapeHtml(item.segmentItems?.[segmentIndex]?.displayName || item.segmentItems?.[segmentIndex]?.subgraphName || `Subgraph_${segmentIndex + 1}`)}</strong><br />
        <small>${escapeHtml(segmentSummary(item.segmentItems?.[segmentIndex]?.config || item.configJson || {}))}</small>
      </div>
    </div>
  `).join("");
  const configRows = `
    <tr><td>Workflow</td><td>${escapeHtml(item.workflow)}</td></tr>
    <tr><td>Worker</td><td>${escapeHtml(item.workerName || "-")}</td></tr>
    <tr><td>FPS</td><td>${escapeHtml(item.fps)}</td></tr>
    <tr><td>Seed</td><td>${escapeHtml(item.seed)}</td></tr>
    <tr><td>Segments</td><td>${escapeHtml(item.segments)}</td></tr>
    <tr><td>Input Images</td><td>${escapeHtml(item.inputImages?.length || item.inputAssets?.length || 0)}</td></tr>
    <tr><td>Output</td><td>${escapeHtml(output?.fileName || item.outputUrl || "-")}</td></tr>
    <tr><td>Status</td><td>${escapeHtml(item.status)}</td></tr>
  `;
  const actions = `
    <div class="detail-actions">
      <button class="rework-button" type="button" data-apply-history="${index}">재작업</button>
    </div>
  `;

  if (state.activeHistoryTab === "images") {
    const assets = item.inputImages?.length
      ? item.inputImages.map((image) => `
          <li>
            <strong>${escapeHtml(image.assetId || "-")}</strong>
            <span>(${escapeHtml(image.fileName || "-")})</span>
          </li>
        `).join("")
      : "<li>No input image was recorded.</li>";
    $("#detailBody").innerHTML = `
      <div class="detail-config">
        <h3>Input Images</h3>
        <ul class="asset-list">${assets}</ul>
      </div>
      ${actions}
    `;
  } else if (state.activeHistoryTab === "config") {
    const wanNodeConfig = item.wanNodeConfig?.segments?.length
      ? item.wanNodeConfig
      : {
          workflowId: item.workflow,
          segments: (item.segmentItems || []).map((segment, segmentIndex) => ({
            index: segment.index || segmentIndex + 1,
            displayName: segment.displayName || segment.subgraphName || `Subgraph_${segmentIndex + 1}`,
            config: segment.config || item.configJson || {},
          })),
        };
    $("#detailBody").innerHTML = `
      <div class="detail-config">
        <h3>Node Config</h3>
        <table>${configRows}</table>
        <pre class="config-json">${escapeHtml(JSON.stringify(wanNodeConfig, null, 2))}</pre>
      </div>
      ${actions}
    `;
  } else if (state.activeHistoryTab === "video") {
    $("#detailBody").innerHTML = `
      ${renderHistoryVideoOutputs(item, index)}
      ${actions}
    `;
  } else {
    $("#detailBody").innerHTML = `
      <div class="detail-segments">${segmentCards}</div>
      <div class="detail-config">
        <h3>Prompt</h3>
        <table>
          <tr><td>Positive</td><td><pre class="prompt-list-pre">${escapeHtml(formatPromptListForCopy(item.positivePrompts) || "-")}</pre></td></tr>
          <tr><td>Negative</td><td><pre class="prompt-list-pre">${escapeHtml(formatPromptListForCopy(item.negativePrompts) || "-")}</pre></td></tr>
        </table>
      </div>
      <div class="detail-config">
        <h3>Node Config</h3>
        <table>${configRows}</table>
      </div>
      <div class="detail-video">
        ${renderOutputPreview(output)}
        <p>File: ${escapeHtml(output?.fileName || "-")}<br />Seed: ${escapeHtml(item.seed)}<br />FPS: ${escapeHtml(item.fps)}<br />Segments: ${escapeHtml(item.segments)}</p>
      </div>
      ${actions}
    `;
  }

  document.querySelectorAll("[data-apply-history]").forEach((button) => {
    button.addEventListener("click", () => applyHistoryConfig(Number(button.dataset.applyHistory), { closeHistoryModal: true, sourceLabel: "재작업" }));
  });
  document.querySelectorAll("#detailBody [data-download]").forEach((button) => {
    button.addEventListener("click", () => {
      const historyItem = state.history[Number(button.dataset.download)];
      const output = historyOutputAsset(historyItem);
      if (output?.downloadUrl) {
        window.open(output.downloadUrl, "_blank");
      } else {
        showNotice("생성된 MP4 파일이 없습니다.");
      }
    });
  });
  document.querySelectorAll("#detailBody [data-download-url]").forEach((button) => {
    button.addEventListener("click", () => {
      const url = button.dataset.downloadUrl;
      if (url) {
        window.open(url, "_blank");
      } else {
        showNotice("생성된 MP4 파일이 없습니다.");
      }
    });
  });
}

function workflowIdFromHistoryItem(item) {
  if (!item) return state.workflow?.id;
  if (state.workflows.some((workflow) => workflow.id === item.workflow)) return item.workflow;
  const keyMatch = String(item.workflow || "").match(/(\d+)\s*[-_]?key/i);
  if (keyMatch) {
    const mappedId = `${keyMatch[1]}-images.json`;
    if (state.workflows.some((workflow) => workflow.id === mappedId)) return mappedId;
  }
  const imageCount = item.inputImages?.length || item.inputAssets?.length || item.raw?.keyframes?.length || item.raw?.keyframeCount;
  if (imageCount) {
    const mappedId = `${imageCount}-images.json`;
    if (state.workflows.some((workflow) => workflow.id === mappedId)) return mappedId;
  }
  return state.workflow?.id;
}

async function applyHistoryConfig(index, options = {}) {
  const item = state.history[index];
  if (!item) return;

  const targetWorkflowId = workflowIdFromHistoryItem(item);
  if (targetWorkflowId && state.workflows.some((workflow) => workflow.id === targetWorkflowId)) {
    await selectWorkflow(targetWorkflowId);
  }
  const loadedImageCount = syncKeyframesFromHistory(item);
  resetOutputState();

  const sourceSegments = item.segmentItems?.length
    ? item.segmentItems
    : [{ positivePrompt: item.prompt, negativePromptAddition: item.negativePrompt, config: item.configJson }];
  const wanSegments = item.wanNodeConfig?.segments || item.raw?.wanNodeConfig?.segments || [];
  state.segments = state.segments.map((segment, segmentIndex) => {
    const source = sourceSegments[segmentIndex] || sourceSegments[0] || {};
    const wanSource = wanSegments[segmentIndex] || wanSegments.find((candidate) => Number(candidate.index) === segment.index) || {};
    const wanConfig = configFromWanNodeSegment(wanSource);
    return {
      ...segment,
      positivePrompt: source.positivePrompt || item.prompt || segment.positivePrompt,
      negativePrompt: source.negativePromptAddition || item.negativePrompt || segment.negativePrompt,
      negativePromptAddition: source.negativePromptAddition || source.negativePrompt || item.negativePrompt || segment.negativePromptAddition || "",
      config: { ...segment.config, ...(source.config || item.configJson || {}), ...wanConfig },
    };
  });
  state.selectedSegment = 1;
  renderSegments();
  renderPreviewSegmentOptions();
  renderSelectedSegment();
  renderKeyframeGrid();
  renderMainOutputPreview();
  if (options.closeHistoryModal) $("#historyModal").classList.add("is-hidden");
  showNotice(`${options.sourceLabel || "Config"} 정보를 생성 화면에 불러왔습니다. 입력 이미지 ${loadedImageCount}개 로드됨.`);
}

init();
