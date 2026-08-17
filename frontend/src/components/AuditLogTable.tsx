import { useEffect, useState } from "react";
import { apiClient, AuditLogItem } from "../api/client";
import { formatTimestamp } from "../helpers/format";

// 2026-08-12: 사용자 요청 - "작업" 칸이 원본 action 문자열(예:
// "prompt_catalog.category_group.update")을 그대로 보여줘 폭을 넓게 잡아야
// 했다. 짧은 한글 라벨로 바꿔 이 칸을 좁히고, 그만큼 확보한 공간을 "상세"
// (JSON 보기) 칸에 배분한다. 매핑에 없는 action은 원본 문자열을 그대로
// 보여준다(신규 action 추가 시 화면이 깨지지 않게).
const AUDIT_ACTION_LABELS: Record<string, string> = {
  "role.permissions.update": "권한 변경",
  "user.create": "사용자 생성",
  "user.update": "사용자 수정",
  "user.deactivate": "사용자 비활성화",
  "user.password_reset": "비밀번호 초기화",
  "prompt_catalog.system_prompt.update": "시스템 프롬프트 수정",
  "prompt_catalog.category_group.create": "카테고리 그룹 생성",
  "prompt_catalog.category_group.update": "카테고리 그룹 수정",
  "prompt_catalog.category.create": "카테고리 생성",
  "prompt_catalog.category.update": "카테고리 수정",
  "prompt_catalog.term.create": "용어 생성",
  "prompt_catalog.term.update": "용어 수정",
  "sandbox_pod.start": "Pod 시작",
  "sandbox_pod.stop": "Pod 중지",
  "task.execution_policy.update": "작업 정책 변경"
};

function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action] || action;
}

// A-04: 감사 로그(`GET /api/admin/audit-logs`)를 화면 여러 곳(3b/4b/5b/7a/7c/신규
// admin.auditLog)에서 재사용하기 위한 표 컴포넌트. 각 화면은 targetType/targetId/
// actorId/action 중 필요한 필터만 props로 넘기고, 이 컴포넌트가 마운트 시 +
// 필터가 바뀔 때마다 apiClient.adminAuditLogs를 직접 호출한다(Create5bScreen 등
// 다른 자체 완결형 화면이 쓰는 useState+useEffect 패턴을 그대로 따름 - 상위
// StudioShell에 상태를 올리지 않는다).
export function AuditLogTable({
  targetType,
  targetId,
  actorId,
  action,
  pageSize = 10,
  title = "변경 이력"
}: {
  targetType?: string;
  targetId?: string;
  actorId?: string;
  action?: string;
  pageSize?: number;
  title?: string;
}) {
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetType, targetId, actorId, action]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setNotice("");
      try {
        const response = await apiClient.adminAuditLogs({ page, pageSize, action, targetType, targetId, actorId });
        if (!cancelled) {
          setItems(response.items || []);
          setTotal(response.total || 0);
        }
      } catch (error) {
        if (!cancelled) {
          setNotice(error instanceof Error ? error.message : "감사 로그를 불러오지 못했습니다.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [page, pageSize, action, targetType, targetId, actorId]);

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total ? (page - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(total, page * pageSize);
  // 시각은 KST와 UTC를 한 줄로 함께 표시한다. 가변 길이가 큰 대상·상세에는
  // 화면의 남는 폭을 더 배정해 넓은 관리 화면을 실제 정보 표시에 활용한다.
  const gridColumns = "minmax(420px,1.65fr) minmax(112px,0.55fr) minmax(140px,0.8fr) minmax(220px,1.15fr) minmax(260px,2.1fr)";

  return (
    <div className="v3-card">
      <div className="v3-card-header">
        <div className="v3-card-header-title">{title}</div>
        <span className="v3-card-header-meta">{total}</span>
      </div>
      {notice ? <p className="v3-inline-notice is-warning">{notice}</p> : null}
      <div className="v3-table-scroll" aria-label={`${title} 표`}>
        <div className="v3-audit-table-content">
          <div className="v3-review-table-head" style={{ gridTemplateColumns: gridColumns }}>
            <span>시각</span><span>행위자</span><span>작업</span><span>대상</span><span>상세</span>
          </div>
          {loading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
          {!loading && !items.length ? <p className="v3-muted-text" style={{ padding: 16 }}>표시할 감사 로그가 없습니다.</p> : null}
          {!loading && items.map((item) => (
            <div className="v3-review-table-row" style={{ gridTemplateColumns: gridColumns }} key={item.id}>
              <span className="v3-review-seg-name v3-audit-timestamp-cell">{formatAuditLogTimestamp(item.createdAtKst || item.createdAt, item.createdAtUtc)}</span>
              <span>{item.actorId || "-"}</span>
              <span title={item.action}>{auditActionLabel(item.action)}</span>
              <span className="v3-audit-target-cell" title={[item.targetType, item.targetId].filter(Boolean).join(" · ") || "-"}>{[item.targetType, item.targetId].filter(Boolean).join(" · ") || "-"}</span>
              <span>
                {item.beforeJson || item.afterJson ? (
                  <details>
                    <summary style={{ cursor: "pointer" }}>보기</summary>
                    {item.beforeJson ? <pre className="v3-payload-json">{JSON.stringify(item.beforeJson, null, 2)}</pre> : null}
                    {item.afterJson ? <pre className="v3-payload-json">{JSON.stringify(item.afterJson, null, 2)}</pre> : null}
                  </details>
                ) : (
                  <span className="v3-muted-text">-</span>
                )}
              </span>
            </div>
          ))}
        </div>
      </div>
      {total > pageSize ? (
        <div className="v3-pagination">
          <span className="v3-pagination-meta">{pageStart}–{pageEnd} / {total}</span>
          <div className="v3-pagination-controls">
            <button className="v3-page-button" type="button" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>이전</button>
            <span className="v3-page-button is-current">{page}</span>
            <button className="v3-page-button" type="button" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>다음</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function formatAuditLogTimestamp(value?: string | null, utcValue?: string | null) {
  return formatTimestamp(value, utcValue).replace(/\n/g, " · ");
}
