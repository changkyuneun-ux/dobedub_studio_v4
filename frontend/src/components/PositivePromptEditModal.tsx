import React from "react";

type Props = {
  title?: string;
  description: string;
  workerName: string;
  fileName: string;
  value: string;
  saving: boolean;
  failureMessage?: string;
  permissionLabel?: string;
  onChange: (value: string) => void;
  onClose: () => void;
  onSave: () => void;
};

export function PositivePromptEditModal({
  title = "Positive Prompt 수정",
  description,
  workerName,
  fileName,
  value,
  saving,
  failureMessage,
  permissionLabel,
  onChange,
  onClose,
  onSave
}: Props) {
  return (
    <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="positivePromptEditTitle">
      <div className="v3-modal-panel v3-prompt-edit-modal">
        <div className="v3-panel-title-row">
          <div id="positivePromptEditTitle" className="v3-panel-title">{title}</div>
          <button className="v3-secondary-button" type="button" disabled={saving} onClick={onClose}>닫기</button>
        </div>
        <p className="v3-muted-text">{description}</p>
        <div className="v3-summary-card">
          <div className="v3-summary-row"><span>작업자</span><strong>{workerName || "-"}</strong></div>
          <div className="v3-summary-row"><span>파일</span><strong>{fileName || "-"}</strong></div>
          {failureMessage ? <div className="v3-summary-row"><span>실패 사유</span><strong>{failureMessage}</strong></div> : null}
          {permissionLabel ? <div className="v3-summary-row"><span>수정 권한</span><strong>{permissionLabel}</strong></div> : null}
        </div>
        <textarea className="v3-prompt-edit-textarea" aria-label="Positive Prompt" value={value} onChange={(event) => onChange(event.target.value)} autoFocus />
        <div className="v3-modal-actions">
          <button className="v3-secondary-button" type="button" disabled={saving} onClick={onClose}>취소</button>
          <button className="v3-primary-button" type="button" disabled={saving || !value.trim()} onClick={onSave}>{saving ? "저장 중" : "저장"}</button>
        </div>
      </div>
    </div>
  );
}
