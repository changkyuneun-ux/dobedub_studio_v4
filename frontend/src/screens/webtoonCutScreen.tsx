import React, { DragEvent, useMemo, useRef, useState } from "react";
import { HealthResponse } from "../api/client";
import { User } from "../auth";
import { AppShell } from "../components/AppShell";
import { webtoonCutJobStore, WebtoonCutReprocessMode, useWebtoonCutJob } from "../features/webtoon-cut/webtoonCutStore";
import { shellNavigate } from "../helpers/navigation";
import { StudioRoute } from "../router";

type Props = { user: User; health: HealthResponse | null; onGoTo: (route: StudioRoute) => void };

export function WebtoonCutScreen({ user, health: _health, onGoTo }: Props) {
  const snapshot = useWebtoonCutJob();
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [reprocessMode, setReprocessMode] = useState<WebtoonCutReprocessMode>("strong-horizontal-transition");
  const selectedReviewUnit = snapshot.units.find((unit) => unit.id === snapshot.selectedReviewUnitId)
    || snapshot.units.find((unit) => unit.status === "review_required" || unit.status === "unsupported");
  const progress = snapshot.totalUnits ? Math.round((snapshot.completedUnits / snapshot.totalUnits) * 100) : 0;
  const unsupportedCount = useMemo(() => snapshot.units.filter((unit) => unit.status === "unsupported").length, [snapshot.units]);

  function chooseInputFiles() {
    fileInput.current?.click();
  }

  async function chooseInputDirectory() {
    if (window.showDirectoryPicker) {
      try {
        const directory = await window.showDirectoryPicker({ mode: "readwrite" });
        await webtoonCutJobStore.selectDirectory(directory);
        return;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }
    setDragging(false);
  }

  async function chooseFiles(files: FileList | null) {
    if (!files?.length) return;
    await webtoonCutJobStore.selectFiles([...files]);
  }

  async function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.items.length) {
      await webtoonCutJobStore.selectDroppedItems(event.dataTransfer.items);
      return;
    }
    await webtoonCutJobStore.selectFiles([...event.dataTransfer.files]);
  }

  return (
    <AppShell
      user={user}
      area="local"
      activeItem="webtoonCuts"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="LOCAL · WEBTOON CUT SPLIT"
      headerTitle="이미지 컷 분할"
      headerActions={<span className="v3-status-chip is-ok">ECS 로그인됨 · 브라우저 로컬 처리</span>}
    >
      <section className="v3-screen-section v3-webtoon-cut-section">
        <div className="v3-batch-section-title"><span>1</span><strong>컷 분할 작업 생성</strong></div>
        <div className="v3-webtoon-cut-create">
          <div className="v3-webtoon-cut-card">
            <label>처리 구조</label>
            <strong>브라우저 로컬 처리</strong>
            <small>업로드 · 다운로드 없음</small>
            <span className="v3-webtoon-cut-good">✓ ECS는 화면 코드와 정책만 제공</span>
          </div>

          <div
            className={`v3-webtoon-cut-dropzone${dragging ? " is-dragging" : ""}`}
            onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => void handleDrop(event)}
          >
            <label>입력 선택</label>
            <div className="v3-webtoon-cut-input-actions">
              <button className="v3-secondary-button" type="button" onClick={chooseInputFiles}>파일 선택</button>
              <button className="v3-secondary-button" type="button" onClick={() => void chooseInputDirectory()} disabled={!window.showDirectoryPicker}>폴더 선택</button>
            </div>
            <input
              ref={fileInput}
              className="v3-batch-hidden-input"
              type="file"
              multiple
              accept=".jpg,.jpeg,.png,.webp,.gif,.pdf,.zip,image/jpeg,image/png,image/webp,image/gif,application/pdf,application/zip,application/x-zip-compressed"
              onChange={(event) => void chooseFiles(event.target.files)}
            />
            <small>파일 또는 폴더 선택 / 끌어놓기. PDF · JPG · PNG · WEBP · GIF · ZIP · 폴더. 폴더 선택은 출력 권한까지 함께 확보합니다.</small>
          </div>

          <div className="v3-webtoon-cut-action">
            <button className="v3-primary-button" type="button" disabled={!snapshot.totalUnits || snapshot.status === "running"} onClick={() => void webtoonCutJobStore.processSelectedInputs()}>
              작업 요청
            </button>
            <small>{snapshot.totalUnits ? `${snapshot.totalUnits}개 원본 · PNG · 원본 해상도 crop` : "입력 선택 후 처리정보 표시"}</small>
          </div>
        </div>
        <div className="v3-webtoon-cut-info-grid">
          <div><span>처리 대상</span><strong>{snapshot.totalUnits ? `${snapshot.totalUnits}개 파일` : "-"}</strong><small>{unsupportedCount ? `PDF/ZIP 등 후속 처리 ${unsupportedCount}개` : "지원 이미지 즉시 처리"}</small></div>
          <div><span>작업 위치</span><strong>{snapshot.workLocation || "-"}</strong><small>선택한 입력 기준으로 자동 파생</small></div>
          <div><span>출력 위치</span><strong>{snapshot.outputLocation || "-"}</strong><small>PNG · manifest.json · summary.csv · _debug/</small></div>
          <div><span>적용 정책</span><strong>자동 감지 · 원본 crop</strong><small>I2V 입력 이미지 목적</small></div>
          <div><span>검수 정책</span><strong>수평 전환은 검수에서 재처리</strong><small>continuous_sequence 후보만 적용</small></div>
        </div>
        {snapshot.notice ? <p className="v3-inline-notice">{snapshot.notice}</p> : null}
      </section>

      <section className="v3-screen-section v3-webtoon-cut-section">
        <div className="v3-batch-section-title"><span>2</span><strong>진행 중 작업</strong><em>다른 화면 이동 후 재진입해도 현재 탭의 작업 핸들을 유지</em></div>
        <div className="v3-webtoon-cut-running">
          <div className="v3-webtoon-cut-progress">
            <strong>{snapshot.jobId || "CUT-대기"}</strong>
            <span>{snapshot.inputName || "입력 대기"}</span>
            <div className="v3-webtoon-cut-progressbar"><i style={{ width: `${progress}%` }} /></div>
            <small>{snapshot.completedUnits} / {snapshot.totalUnits} · {progress}%</small>
          </div>
          <div className="v3-webtoon-cut-metrics">
            <div><small>완료 원본</small><strong>{snapshot.completedUnits}</strong></div>
            <div><small>생성 컷</small><strong>{snapshot.generatedCuts}</strong></div>
            <div><small>검수 필요</small><strong>{snapshot.reviewUnits}</strong></div>
            <div><small>오류/누락</small><strong>{snapshot.failedUnits}</strong></div>
          </div>
        </div>
      </section>

      <section className="v3-screen-section v3-webtoon-cut-section">
        <div className="v3-batch-section-title"><span>3</span><strong>검수 필요</strong></div>
        <div className="v3-webtoon-cut-review">
          <div className="v3-webtoon-cut-review-list">
            <div className="v3-webtoon-cut-review-head"><span>원본</span><span>판정</span><span>컷</span><span>확인</span></div>
            {snapshot.units.filter((unit) => unit.status === "review_required" || unit.status === "unsupported" || unit.status === "failed").map((unit) => (
              <button
                key={unit.id}
                type="button"
                className={`v3-webtoon-cut-review-row${selectedReviewUnit?.id === unit.id ? " is-selected" : ""}`}
                onClick={() => webtoonCutJobStore.selectReviewUnit(unit.id)}
              >
                <span>{unit.sourcePath}</span>
                <b>{unit.flag}</b>
                <span>{unit.cutCount}</span>
                <small>보기</small>
              </button>
            ))}
            {!snapshot.units.some((unit) => unit.status === "review_required" || unit.status === "unsupported" || unit.status === "failed") ? <div className="v3-empty-panel">검수 필요 항목이 없습니다.</div> : null}
          </div>
          <div className="v3-webtoon-cut-review-panel">
            <strong>{selectedReviewUnit?.fileName || "검수 항목 선택"}</strong>
            <p>{selectedReviewUnit?.message || "컷 누락 또는 긴 연속 결과가 있으면 여기에 재처리 옵션이 표시됩니다."}</p>
            <label>재처리 유형
              <select value={reprocessMode} onChange={(event) => setReprocessMode(event.target.value as WebtoonCutReprocessMode)}>
                <option value="strong-horizontal-transition">수평 장면 전환</option>
              </select>
            </label>
            <ul>
              <li>continuous_sequence처럼 긴 결과에만 수평 장면 전환 검출</li>
              <li>전체 폭 95% 이상에서 명암·색상이 급변하는 선만 채택</li>
              <li>최소 컷 높이와 경계 간 거리로 장식선을 제거</li>
            </ul>
            <button className="v3-primary-button" type="button" disabled={!selectedReviewUnit || selectedReviewUnit.flag !== "continuous_sequence" || snapshot.status === "running"} onClick={() => selectedReviewUnit ? void webtoonCutJobStore.reprocessReviewUnit(selectedReviewUnit.id, reprocessMode) : undefined}>
              선택 유형으로 재처리
            </button>
          </div>
        </div>
      </section>
    </AppShell>
  );
}
