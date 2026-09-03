import React, { useMemo, useRef, useState } from "react";
import { HealthResponse, WorkflowItem, WorkflowSchema } from "../api/client";
import { User } from "../auth";
import { AppShell } from "../components/AppShell";
import { ProtectedImage } from "../components/ProtectedAssets";
import { shellNavigate } from "../helpers/navigation";
import { KeyframeState, SegmentState, formatImageDimensions, formatUploadSize } from "../helpers/workflow";
import { StudioRoute } from "../router";

type Props = {
  user: User;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  workflows: WorkflowItem[];
  selectedWorkflow: string;
  schema: WorkflowSchema | null;
  keyframes: KeyframeState[];
  segments: SegmentState[];
  running: boolean;
  lengthFrames: number;
  onSelectWorkflow: (workflowId: string) => void;
  onUploadFiles: (index: number, files: FileList | null) => void;
  onClearKeyframe: (index: number) => void;
  onUpdateKeyframePrompt: (index: number, prompt: string) => void;
  onRegenerateKeyframePrompt: (index: number) => void;
  onUpdateNegativePrompt: (prompt: string) => void;
  onLengthFramesChange: (frames: number) => void;
  onRun: () => void;
};

function resolutionText(keyframes: KeyframeState[]) {
  const source = keyframes.find((keyframe) => keyframe.upload?.imageWidth && keyframe.upload?.imageHeight)?.upload;
  return source ? `${source.imageWidth} × ${source.imageHeight}` : "이미지 업로드 후 자동 계산";
}

export function GrokWorkspaceScreen({
  user, health, onGoTo, workflows, selectedWorkflow, schema, keyframes, segments, running, lengthFrames,
  onSelectWorkflow, onUploadFiles, onClearKeyframe, onUpdateKeyframePrompt, onRegenerateKeyframePrompt,
  onUpdateNegativePrompt, onLengthFramesChange, onRun
}: Props) {
  const selected = workflows.find((workflow) => workflow.id === selectedWorkflow);
  const [dragging, setDragging] = useState<number | null>(null);
  const inputs = useRef<Record<number, HTMLInputElement | null>>({});
  const filled = keyframes.filter((keyframe) => Boolean(keyframe.upload?.assetId)).length;
  const required = schema?.keyframeCount || selected?.keyframeCount || keyframes.length || 1;
  const missing = Math.max(required - filled, 0);
  const promptPending = keyframes.some((keyframe) => keyframe.grokStatus === "GENERATING");
  const linkedSegments = useMemo(() => segments.filter((segment) => segment.startImageIndex > 0), [segments]);
  const missingPrompt = linkedSegments.some((segment) => !segment.positivePrompt.trim());
  const canRun = Boolean(selectedWorkflow) && missing === 0 && !promptPending && !missingPrompt && !running;
  const negativePrompt = segments[0]?.negativePrompt || "";
  const frameSeconds = lengthFrames === 49 ? "약 3초" : lengthFrames === 161 ? "약 10초" : "약 5초 · 기본";

  function dropFiles(index: number, event: React.DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragging(null);
    onUploadFiles(index, event.dataTransfer.files);
  }

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="workspace"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="GENERATE · WORKSPACE · GROK PROMPT"
      headerTitle="이미지-프롬프트 페어링 설정"
      headerActions={<span className="v3-status-chip is-ok">{running ? "SUBMITTING" : "READY TO RUN"}</span>}
      rightPanel={
        <>
          <div className="v3-panel-title">Run Summary</div>
          <div className="v3-summary-card">
            <div className="v3-summary-row"><span>Workflow</span><strong>{selected?.label || selected?.name || "-"}</strong></div>
            <div className="v3-summary-row"><span>Keyframes</span><strong>{filled} / {required}</strong></div>
            <div className="v3-summary-row"><span>Positive Prompt</span><strong>{missingPrompt ? "입력 필요" : "Grok · slot mapped"}</strong></div>
            <div className="v3-summary-row"><span>Output</span><strong>{resolutionText(keyframes)}<br />{lengthFrames} length · 16 FPS</strong></div>
            <div className="v3-summary-row"><span>Seed</span><strong>서버 자동 생성</strong></div>
          </div>
          <div className="v3-grok-callout"><strong>워크플로우 기본값 유지</strong><br />steps, CFG, motion, VAE, codec과 모델 값은 등록된 workflow 기본값을 그대로 사용합니다.</div>
          <button className="v3-primary-button v3-grok-run" type="button" disabled={!canRun} onClick={onRun}>
            {running ? "RunPod 요청 중..." : "RunPod에 실행 요청 →"}
          </button>
          {!canRun && !running ? <p className="v3-muted-text">{missing ? `입력 이미지 ${missing}개가 필요합니다.` : promptPending ? "Grok prompt 생성 중입니다." : "각 이미지의 Positive Prompt를 확인하세요."}</p> : null}
        </>
      }
    >
      <section className="v3-card v3-grok-workflow-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Workflow</div><span className="v3-muted-text">{required} keyframe · {schema?.segmentCount || selected?.segmentCount || segments.length} segment</span></div>
        <div className="v3-grok-workflow-list">
          {workflows.map((workflow) => (
            <button key={workflow.id} type="button" className={`v3-workflow-card ${workflow.id === selectedWorkflow ? "is-selected" : ""}`} disabled={running} onClick={() => onSelectWorkflow(workflow.id)}>
              <span>{workflow.label || workflow.name || workflow.id}</span>
              <small>{workflow.keyframeCount || 1} kf · {workflow.segmentCount || 1} seg · ACTIVE ✓</small>
            </button>
          ))}
        </div>
      </section>

      <section className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Keyframe Image &amp; Positive Prompt</div><span className="v3-muted-text">이미지 업로드 후 슬롯별로 프롬프트 생성 요청</span></div>
        <div className="v3-grok-mappings">
          {keyframes.map((keyframe) => {
            const linked = segments.find((segment) => segment.startImageIndex === keyframe.index);
            const prompt = linked?.positivePrompt ?? keyframe.grokPrompt;
            const sourceSize = keyframe.upload ? formatImageDimensions(keyframe.upload.imageHeight, keyframe.upload.imageWidth) : "";
            const isGenerating = keyframe.grokStatus === "GENERATING";
            const promptActionLabel = isGenerating ? "생성 중..." : keyframe.grokStatus === "IDLE" ? "프롬프트 생성" : "재생성";
            return (
              <div className="v3-grok-mapping" key={keyframe.index}>
                <article
                  className={`v3-grok-image-card ${dragging === keyframe.index ? "is-dragging" : ""}`}
                  onDragEnter={(event) => { event.preventDefault(); setDragging(keyframe.index); }}
                  onDragOver={(event) => event.preventDefault()}
                  onDragLeave={() => setDragging(null)}
                  onDrop={(event) => dropFiles(keyframe.index, event)}
                  onClick={() => inputs.current[keyframe.index]?.click()}
                >
                  <input ref={(node) => { inputs.current[keyframe.index] = node; }} type="file" accept="image/*" hidden onChange={(event) => onUploadFiles(keyframe.index, event.target.files)} />
                  {keyframe.previewUrl ? <div className="v3-grok-image-preview"><ProtectedImage src={keyframe.previewUrl} alt={`입력 이미지 ${keyframe.index}`} /></div> : <div className="v3-grok-image-empty">파일 선택 또는 끌어놓기</div>}
                  <div className="v3-grok-image-info"><strong>SLOT {String(keyframe.index).padStart(2, "0")} · {keyframe.upload?.fileName || "이미지 대기"}</strong><small>{keyframe.upload ? `${formatUploadSize(keyframe.upload.sizeBytes)} · 원본 ${sourceSize}` : "I2V 입력 이미지"}</small>{keyframe.upload ? <button type="button" onClick={(event) => { event.stopPropagation(); onClearKeyframe(keyframe.index); }}>삭제</button> : null}</div>
                </article>
                <article className="v3-grok-prompt-card">
                  <div className="v3-grok-prompt-head"><div><strong>Positive Prompt</strong><span> · SLOT {String(keyframe.index).padStart(2, "0")}에 매핑</span></div><b>{isGenerating ? "GROK · GENERATING" : keyframe.grokStatus === "READY" ? "GROK · READY" : keyframe.grokStatus === "MANUAL_REQUIRED" ? "MANUAL INPUT" : keyframe.grokStatus === "FAILED" ? "GROK · FAILED" : "GROK · WAITING"}</b></div>
                  <textarea aria-label={`Positive Prompt slot ${keyframe.index}`} value={prompt} disabled={!keyframe.upload || isGenerating} onChange={(event) => onUpdateKeyframePrompt(keyframe.index, event.target.value)} placeholder="이미지 업로드 후 프롬프트 생성 버튼을 누르거나 직접 입력할 수 있습니다." />
                  <div className="v3-grok-prompt-foot"><span>{keyframe.grokImageType ? `판정: ${keyframe.grokImageType}` : keyframe.grokError || "원본 이미지와 이 문장이 함께 RunPod에 전달됩니다."}</span>{keyframe.upload ? <button className="v3-secondary-button" type="button" disabled={isGenerating} onClick={() => onRegenerateKeyframePrompt(keyframe.index)}>{promptActionLabel}</button> : null}</div>
                </article>
              </div>
            );
          })}
          <article className="v3-grok-negative-card">
            <div className="v3-grok-prompt-head"><div><strong>Negative Prompt</strong><span> · workflow 기본값</span></div><b>EDITABLE</b></div>
            <textarea aria-label="Negative Prompt" value={negativePrompt} onChange={(event) => onUpdateNegativePrompt(event.target.value)} placeholder="워크플로우 기본 negative prompt" />
          </article>
        </div>
      </section>

      <section className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">실행 설정</div><span className="v3-muted-text">필수값만 선택 · 나머지는 workflow 기본값</span></div>
        <div className="v3-grok-settings">
          <div className="v3-grok-setting is-length"><span>VIDEO LENGTH</span><div>{[49, 81, 161].map((frames) => <button key={frames} type="button" className={frames === lengthFrames ? "is-selected" : ""} onClick={() => onLengthFramesChange(frames)}><b>{frames}</b><small>{frames === 49 ? "약 3초" : frames === 81 ? "약 5초 · 기본" : "약 10초"}</small></button>)}</div></div>
          <div className="v3-grok-setting"><span>WAN RESOLUTION</span><strong>{resolutionText(keyframes)}</strong><small>업로드 이미지에서 계산 · 자동 주입</small></div>
          <div className="v3-grok-setting"><span>FPS</span><strong>16</strong><small>고정</small></div>
          <div className="v3-grok-setting"><span>SEED</span><strong>자동</strong><small>실행 시 서버 생성</small></div>
        </div>
      </section>
    </AppShell>
  );
}
