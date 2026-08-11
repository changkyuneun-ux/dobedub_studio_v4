import { useEffect, useState } from "react";
import { StudioRoute } from "../router";
import { User } from "../auth";
import { AppShell } from "../components/AppShell";
import { AuditLogTable } from "../components/AuditLogTable";
import { promptText } from "../helpers/prompts";
import {
  promptCatalogAdminScopes,
  promptAdminScopeAccordionKey,
  promptAdminGroupAccordionKey,
  promptAdminSubcategoryAccordionKey,
  PromptCatalogAdminContentProps,
  categoryGroupFormFrom,
  categoryGroupCodeFromForm,
  categoryFormFrom,
  subcategoryCodeFromForm,
  promptTermCodeFromForm,
  termFormFrom
} from "../helpers/promptCatalogAdminForms";
import { shellNavigateAdmin } from "../helpers/navigation";


// E-04 · 4e "카탈로그 계층" + 3d "용어 관리" — 구버전 PromptCatalogAdminContent를
// v3 토큰으로 다시 그렸다. 로직(스코프→그룹→서브카테고리→용어 트리 탐색, 각 단계
// 폼 상태, 저장/삭제 payload 구성)은 한 글자도 바꾸지 않았고 마크업만 새로 짰다.
// 4e/3d 두 라우트가 이 컴포넌트 하나를 함께 쓰는 이유는 router.ts 주석 참고.
export function PromptCatalogAdminPanelV3({
  user,
  onGoTo,
  focus,
  catalog,
  loading,
  notice,
  onSaveCategoryGroup,
  onDeactivateCategoryGroup,
  onSaveCategory,
  onDeactivateCategory,
  onSaveTerm,
  onDeactivateTerm
}: {
  user: User;
  onGoTo: (route: StudioRoute) => void;
  focus: "hierarchy" | "terms" | "negativeDefaults";
} & PromptCatalogAdminContentProps) {
  const groups = catalog?.groups || [];
  const allScopes = promptCatalogAdminScopes(groups);
  // E-04 · 4b: "Negative 기본값"은 별도 데이터가 아니라 이 트리의 NEGATIVE
  // scope를 필터링한 뷰다(design_handoff 4b 원본 문구: 모든 Run에 적용되는
  // 네거티브는 워크플로 JSON에 내장돼 있고 여기서 관리하지 않음 - 이 화면은 그
  // 위에 "추가"할 선택 용어만 다룬다). scope 선택기 자체를 negative 하나로만
  // 좁혀서 별도 lock 상태 없이 필터만으로 구현한다.
  const scopes = focus === "negativeDefaults" ? allScopes.filter((scope) => scope.key === "negative") : allScopes;
  const [selectedScopeKey, setSelectedScopeKey] = useState<"positive" | "negative">(focus === "negativeDefaults" ? "negative" : "positive");
  const [activeCatalogAdminLevel, setActiveCatalogAdminLevel] = useState<"none" | "category" | "subcategory" | "keyword">("none");
  const [selectedGroupId, setSelectedGroupId] = useState<number | "new">("new");
  const selectedGroup = selectedGroupId === "new" ? null : groups.find((group) => group.id === selectedGroupId) || null;
  const [groupForm, setGroupForm] = useState<Record<string, string>>(categoryGroupFormFrom(selectedGroup, selectedScopeKey));
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | "new">("new");
  const selectedCategory = selectedCategoryId === "new"
    ? null
    : selectedGroup?.subcategories.find((category) => category.id === selectedCategoryId) || null;
  const [categoryForm, setCategoryForm] = useState<Record<string, string | boolean>>(categoryFormFrom(selectedCategory, selectedGroup?.code || "", undefined, selectedGroup?.id));
  const [selectedTermId, setSelectedTermId] = useState<number | "new">("new");
  const selectedTerm = selectedTermId === "new" ? null : selectedCategory?.terms.find((term) => term.id === selectedTermId) || null;
  const [termForm, setTermForm] = useState<Record<string, string>>(termFormFrom(selectedTerm, selectedCategory));
  const [expandedAdminTreeKeys, setExpandedAdminTreeKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    const nextScope = scopes.find((scope) => scope.key === selectedScopeKey) || scopes[0] || null;
    if (nextScope && nextScope.key !== selectedScopeKey) {
      setSelectedScopeKey(nextScope.key);
      return;
    }
    const nextGroup = selectedGroupId === "new" ? null : nextScope?.groups.find((group) => group.id === selectedGroupId) || null;
    if (selectedGroupId !== "new" && !nextGroup) {
      setSelectedGroupId("new");
      setSelectedCategoryId("new");
      setSelectedTermId("new");
      setActiveCatalogAdminLevel("none");
      return;
    }
    const nextCategory = selectedCategoryId === "new" ? null : nextGroup?.subcategories.find((category) => category.id === selectedCategoryId) || null;
    if (selectedCategoryId !== "new" && !nextCategory) {
      setSelectedCategoryId("new");
      setSelectedTermId("new");
      setActiveCatalogAdminLevel(nextGroup ? "category" : "none");
      return;
    }
    const nextTerm = selectedTermId === "new" ? null : nextCategory?.terms.find((term) => term.id === selectedTermId) || null;
    if (selectedTermId !== "new" && !nextTerm) {
      setSelectedTermId("new");
      setActiveCatalogAdminLevel(nextCategory ? "subcategory" : "none");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog]);

  useEffect(() => {
    setGroupForm(categoryGroupFormFrom(selectedGroup, selectedScopeKey));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGroupId, selectedScopeKey, catalog]);

  useEffect(() => {
    setCategoryForm(categoryFormFrom(selectedCategory, selectedGroup?.code || "", undefined, selectedGroup?.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCategoryId, catalog, selectedGroup?.code, selectedGroup?.id]);

  useEffect(() => {
    setTermForm(termFormFrom(selectedTerm, selectedCategory));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTermId, selectedCategoryId, catalog]);

  const groupCode = categoryGroupCodeFromForm(groupForm, selectedScopeKey, selectedGroup);
  const subcategoryCode = subcategoryCodeFromForm(categoryForm, selectedCategory);
  const categoryPayload = {
    ...categoryForm,
    code: subcategoryCode,
    required: Boolean(categoryForm.required),
    maxSelectCount: categoryForm.maxSelectCount ? Number(categoryForm.maxSelectCount) : null,
    groupId: selectedGroup?.id || categoryForm.groupId || null,
    groupCode: selectedGroup?.code || categoryForm.groupCode || "positive_work_style",
    sortOrder: categoryForm.sortOrder ? Number(categoryForm.sortOrder) : 100
  };
  const groupPayload = {
    ...groupForm,
    code: groupCode,
    scopeType: selectedScopeKey === "negative" ? "NEGATIVE" : "POSITIVE",
    sortOrder: groupForm.sortOrder ? Number(groupForm.sortOrder) : 100
  };
  const termCode = promptTermCodeFromForm(termForm, selectedTerm, selectedCategory);
  const termPayload = {
    ...termForm,
    code: termCode,
    canonicalKey: termForm.canonicalKey || termCode,
    categoryId: Number(termForm.categoryId || selectedCategory?.id || 0),
    riskLevel: termForm.riskLevel || "NONE",
    sortOrder: termForm.sortOrder ? Number(termForm.sortOrder) : 100
  };
  const canSaveGroup = Boolean(String(groupForm.nameKo || "").trim() && String(groupForm.nameEn || "").trim());
  const canSaveCategory = Boolean(selectedGroup && String(categoryForm.nameKo || "").trim() && String(categoryForm.nameEn || "").trim());
  const canSaveTerm = Boolean(selectedCategory && String(termForm.labelKo || "").trim() && String(termForm.labelEn || "").trim());

  function toggleAdminTreeAccordion(key: string) {
    setExpandedAdminTreeKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  // 2026-08-11 버그 수정: 실제 DB(scopes=2/groups=16/terms=50)는 정상이었지만, 이
  // 트리가 좌측 사이드바(sidebarExtra)에만 있고 화면 진입 직후 본문은 "관리할
  // 항목을 선택하세요"만 보여줘서 사용자가 "카탈로그 정보가 안 보인다"고 오인했다.
  // 트리 렌더링을 함수로 뽑아 사이드바뿐 아니라 미선택 상태의 본문에도 그대로
  // 보여준다 - 데이터/로직은 동일, 노출 위치만 하나 늘린 것.
  function renderCatalogTree() {
    return (
      <>
        <div className="v3-label" style={{ padding: "0 10px 4px" }}>CATALOG TREE · {groups.length}</div>
        {loading && !catalog ? (
          <p className="v3-muted-text" style={{ padding: "4px 10px" }}>카탈로그를 불러오는 중입니다.</p>
        ) : !scopes.length ? (
          <p className="v3-muted-text" style={{ padding: "4px 10px" }}>
            {focus === "negativeDefaults"
              ? "NEGATIVE 카탈로그가 없습니다."
              : "카탈로그가 비어 있습니다. 아래에서 새 카테고리를 추가하세요."}
          </p>
        ) : null}
        {scopes.map((scope) => {
          const scopeKey = promptAdminScopeAccordionKey(scope.key);
          const scopeExpanded = expandedAdminTreeKeys.has(scopeKey);
          return (
            <div key={scope.key}>
              <button
                type="button"
                className={`v3-segment-nav-item v3-catalog-tree-scope ${selectedScopeKey === scope.key ? "is-active" : ""}`}
                onClick={() => {
                  setSelectedScopeKey(scope.key);
                  toggleAdminTreeAccordion(scopeKey);
                }}
              >
                <div className="v3-segment-nav-head"><span>{scope.label} Prompt</span><span>{scope.groups.length} {scopeExpanded ? "-" : "+"}</span></div>
              </button>
              {scopeExpanded ? (
                <div className="v3-catalog-tree-children">
                  {scope.groups.map((group) => {
                    const groupKey = promptAdminGroupAccordionKey(scope.key, group.id);
                    const groupExpanded = expandedAdminTreeKeys.has(groupKey);
                    return (
                      <div key={group.id}>
                        <button
                          type="button"
                          className={`v3-segment-nav-item v3-catalog-tree-group ${selectedScopeKey === scope.key && selectedGroupId === group.id ? "is-active" : ""}`}
                          onClick={() => {
                            setSelectedScopeKey(scope.key);
                            setSelectedGroupId(group.id);
                            setSelectedCategoryId("new");
                            setSelectedTermId("new");
                            setActiveCatalogAdminLevel("category");
                            toggleAdminTreeAccordion(groupKey);
                          }}
                        >
                          <div className="v3-segment-nav-head"><span>{group.nameKo || group.code}</span><span>{group.subcategories.length} {groupExpanded ? "-" : "+"}</span></div>
                        </button>
                        {groupExpanded ? (
                          <div className="v3-catalog-tree-children">
                            {group.subcategories.map((category) => {
                              const categoryKey = promptAdminSubcategoryAccordionKey(category.id);
                              const categoryExpanded = expandedAdminTreeKeys.has(categoryKey);
                              return (
                                <div key={category.id}>
                                  <button
                                    type="button"
                                    className={`v3-segment-nav-item v3-catalog-tree-subcategory ${selectedCategoryId === category.id ? "is-active" : ""}`}
                                    onClick={() => {
                                      setSelectedScopeKey(scope.key);
                                      setSelectedGroupId(group.id);
                                      setSelectedCategoryId(category.id);
                                      setSelectedTermId("new");
                                      setActiveCatalogAdminLevel("subcategory");
                                      toggleAdminTreeAccordion(categoryKey);
                                    }}
                                  >
                                    <div className="v3-segment-nav-head"><span>{category.nameKo || category.code}</span><span>{(category.terms || []).length} {categoryExpanded ? "-" : "+"}</span></div>
                                  </button>
                                  {categoryExpanded ? (
                                    <div className="v3-catalog-tree-children v3-catalog-tree-terms">
                                      {(category.terms || []).map((term) => (
                                        <button
                                          key={term.id}
                                          type="button"
                                          className={`v3-term-chip v3-catalog-tree-term ${selectedTermId === term.id ? "is-selected" : ""}`}
                                          onClick={() => {
                                            setSelectedScopeKey(scope.key);
                                            setSelectedGroupId(group.id);
                                            setSelectedCategoryId(category.id);
                                            setSelectedTermId(term.id);
                                            setActiveCatalogAdminLevel("keyword");
                                          }}
                                        >
                                          {term.labelKo || term.code}
                                        </button>
                                      ))}
                                    </div>
                                  ) : null}
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
      </>
    );
  }

  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminCatalog"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · 프롬프트 카탈로그"
      headerTitle={focus === "terms" ? "용어 관리" : focus === "negativeDefaults" ? "Negative 기본값" : "카탈로그 계층"}
      headerActions={
        <>
          {focus !== "hierarchy" ? <button className="v3-secondary-button" type="button" onClick={() => onGoTo("admin.catalogHierarchy")}>카탈로그 계층</button> : null}
          {focus !== "terms" ? <button className="v3-secondary-button" type="button" onClick={() => onGoTo("admin.catalogTerms")}>용어 관리</button> : null}
          {focus !== "negativeDefaults" ? <button className="v3-secondary-button" type="button" onClick={() => onGoTo("admin.negativeDefaults")}>Negative 기본값</button> : null}
        </>
      }
      sidebarExtra={
        <div className="v3-step-tracker">
          {renderCatalogTree()}
        </div>
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}

      {focus === "negativeDefaults" ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">내장 네거티브 + 선택 용어 = 세그먼트 네거티브</div>
          </div>
          <p className="v3-muted-text" style={{ padding: "0 16px 16px" }}>
            모든 Run에 적용되는 네거티브는 여기서 관리하지 않습니다 - 기본 네거티브는 워크플로 JSON의 네거티브 노드에 내장되어 있고 읽기 전용입니다(워크플로 정의 화면에서 확인).
            이 화면은 그 위에 추가로 얹을 선택 용어(아래 트리의 Negative 계열)만 관리합니다.
          </p>
          <AuditLogTable targetType="prompt_category_group" pageSize={5} title="변경 이력" />
        </div>
      ) : null}

      {activeCatalogAdminLevel === "none" ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">카탈로그 계층</div>
            <button className="v3-text-link-button" type="button" onClick={() => {
              setSelectedGroupId("new");
              setSelectedCategoryId("new");
              setSelectedTermId("new");
              setActiveCatalogAdminLevel("category");
            }}>New Category</button>
          </div>
          <div style={{ padding: "0 16px 16px" }}>
            <p className="v3-muted-text" style={{ padding: "10px 0" }}>아래 트리에서 카테고리, 서브 카테고리 또는 key word를 선택하면 해당 정보를 관리할 수 있습니다.</p>
            {/* 2026-08-11 버그 수정: 이 카드가 전에는 안내 문구만 보여줘서, 왼쪽 사이드바를
                눈여겨보지 않으면 카탈로그에 데이터가 없는 것처럼 보였다. 좌측과 동일한 트리를
                본문에도 그대로 그려 진입 즉시 실제 데이터(현재 groups={groups.length})가
                보이게 한다. */}
            <div className="v3-step-tracker" style={{ border: "1px solid var(--v3-border-inner)", borderRadius: 10, padding: "6px 0" }}>
              {renderCatalogTree()}
            </div>
          </div>
        </div>
      ) : null}

      {activeCatalogAdminLevel === "category" ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">카테고리 관리</div>
            <button className="v3-text-link-button" type="button" onClick={() => {
              setSelectedGroupId("new");
              setSelectedCategoryId("new");
              setSelectedTermId("new");
              setActiveCatalogAdminLevel("category");
            }}>New Category</button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16 }}>
            <div className="v3-reuse-grid">
              <label className="v3-checklist-item" style={{ display: "block" }}>Name KO
                <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={String(groupForm.nameKo || "")} onChange={(event) => setGroupForm({ ...groupForm, nameKo: event.target.value })} />
              </label>
              <label className="v3-checklist-item" style={{ display: "block" }}>Name EN
                <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={String(groupForm.nameEn || "")} onChange={(event) => setGroupForm({ ...groupForm, nameEn: event.target.value })} />
              </label>
            </div>
            <label className="v3-checklist-item" style={{ display: "block" }}>Description
              <textarea className="v3-scene-textarea" style={{ width: "100%", marginTop: 6 }} rows={2} value={String(groupForm.description || "")} onChange={(event) => setGroupForm({ ...groupForm, description: event.target.value })} />
            </label>
            <div className="v3-inline-actions">
              <button className="v3-primary-button" type="button" disabled={loading || !canSaveGroup} onClick={() => onSaveCategoryGroup(groupPayload, selectedGroup?.id)}>Save Category</button>
              {selectedGroup ? <button className="v3-secondary-button" type="button" onClick={() => {
                setSelectedCategoryId("new");
                setSelectedTermId("new");
                setActiveCatalogAdminLevel("subcategory");
              }}>New Sub Category</button> : null}
              {selectedGroup ? <button className="v3-secondary-button" type="button" disabled={loading} onClick={() => onDeactivateCategoryGroup(selectedGroup.id)}>Delete Category</button> : null}
            </div>
          </div>
        </div>
      ) : null}

      {activeCatalogAdminLevel === "subcategory" || activeCatalogAdminLevel === "keyword" ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">{selectedCategory?.nameKo || "새 서브 카테고리"}</div>
            <span className="v3-card-header-meta">{selectedGroup?.nameKo || "상위 카테고리 없음"}</span>
          </div>
          {activeCatalogAdminLevel === "subcategory" ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16 }}>
              <div className="v3-inline-actions" style={{ justifyContent: "flex-end" }}>
                <button className="v3-text-link-button" type="button" disabled={!selectedGroup} onClick={() => {
                  setSelectedCategoryId("new");
                  setSelectedTermId("new");
                  setActiveCatalogAdminLevel("subcategory");
                }}>New Sub Category</button>
              </div>
              <div className="v3-reuse-grid">
                <label className="v3-checklist-item" style={{ display: "block" }}>Name KO
                  <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={String(categoryForm.nameKo || "")} onChange={(event) => setCategoryForm({ ...categoryForm, nameKo: event.target.value })} />
                </label>
                <label className="v3-checklist-item" style={{ display: "block" }}>Name EN
                  <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={String(categoryForm.nameEn || "")} onChange={(event) => setCategoryForm({ ...categoryForm, nameEn: event.target.value })} />
                </label>
              </div>
              <label className="v3-checklist-item" style={{ display: "block" }}>Description
                <textarea className="v3-scene-textarea" style={{ width: "100%", marginTop: 6 }} rows={2} value={String(categoryForm.description || "")} onChange={(event) => setCategoryForm({ ...categoryForm, description: event.target.value })} />
              </label>
              <div className="v3-inline-actions">
                <button className="v3-primary-button" type="button" disabled={loading || !canSaveCategory} onClick={() => onSaveCategory(categoryPayload, selectedCategory?.id)}>Save Sub Category</button>
                {selectedCategory ? <button className="v3-secondary-button" type="button" onClick={() => {
                  setSelectedTermId("new");
                  setActiveCatalogAdminLevel("keyword");
                }}>New Key Word</button> : null}
                {selectedCategory ? <button className="v3-secondary-button" type="button" disabled={loading} onClick={() => onDeactivateCategory(selectedCategory.id)}>Delete Sub Category</button> : null}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {activeCatalogAdminLevel === "keyword" ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">키워드 관리</div>
            <button className="v3-text-link-button" type="button" disabled={!selectedCategory} onClick={() => {
              setSelectedTermId("new");
              setActiveCatalogAdminLevel("keyword");
            }}>New Key Word</button>
          </div>
          {selectedCategory ? (
            <div style={{ display: "flex", gap: 14, padding: 16 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 160 }}>
                {selectedCategory.terms.map((term) => (
                  <button
                    key={term.id}
                    type="button"
                    className={`v3-term-chip ${selectedTermId === term.id ? "is-selected" : ""}`}
                    onClick={() => {
                      setSelectedTermId(term.id);
                      setActiveCatalogAdminLevel("keyword");
                    }}
                  >
                    {term.labelKo || term.code}
                  </button>
                ))}
              </div>
              <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10 }}>
                <div className="v3-reuse-grid">
                  <label className="v3-checklist-item" style={{ display: "block" }}>Label KO
                    <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={termForm.labelKo || ""} onChange={(event) => setTermForm({ ...termForm, labelKo: event.target.value })} />
                  </label>
                  <label className="v3-checklist-item" style={{ display: "block" }}>Label EN
                    <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={termForm.labelEn || ""} onChange={(event) => setTermForm({ ...termForm, labelEn: event.target.value })} />
                  </label>
                </div>
                <label className="v3-checklist-item" style={{ display: "block" }}>Prompt Text
                  <textarea className="v3-scene-textarea" style={{ width: "100%", marginTop: 6 }} rows={2} value={termForm.promptText || ""} onChange={(event) => setTermForm({ ...termForm, promptText: event.target.value })} />
                </label>
                <label className="v3-checklist-item" style={{ display: "block" }}>Negative Text
                  <textarea className="v3-scene-textarea" style={{ width: "100%", marginTop: 6 }} rows={2} value={termForm.negativeText || ""} onChange={(event) => setTermForm({ ...termForm, negativeText: event.target.value })} />
                </label>
                <label className="v3-checklist-item" style={{ display: "block" }}>Description
                  <textarea className="v3-scene-textarea" style={{ width: "100%", marginTop: 6 }} rows={2} value={termForm.description || ""} onChange={(event) => setTermForm({ ...termForm, description: event.target.value })} />
                </label>
                <div className="v3-inline-actions">
                  <button className="v3-primary-button" type="button" disabled={loading || !canSaveTerm} onClick={() => onSaveTerm(termPayload, selectedTerm?.id)}>Save Key Word</button>
                  {selectedTerm ? <button className="v3-secondary-button" type="button" disabled={loading} onClick={() => onDeactivateTerm(selectedTerm.id)}>Delete Key Word</button> : null}
                </div>
              </div>
            </div>
          ) : <p className="v3-muted-text" style={{ padding: 16 }}>서브 카테고리를 선택하거나 먼저 저장한 후 key word를 추가하세요.</p>}
        </div>
      ) : null}
    </AppShell>
  );
}
