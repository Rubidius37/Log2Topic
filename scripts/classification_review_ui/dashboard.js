"use strict";

let uiLanguage = "en";
const translations = {
  en: {
    pageTitle: "Log2Topic Classification Review", heading: "Classification Review", waiting: "waiting",
    refresh: "Refresh", reviewType: "Review type", all: "All", missingLevel1: "Missing Level 1",
    parentStop: "Stopped at parent", invalidManual: "Invalid manual path", reviewQueue: "Review queue",
    reviewSearch: "Search title or source path", emptyTitle: "Nothing to review",
    emptyBody: "No classification review items match this filter.", sourceSection: "Source section",
    sourceChanged: "Source changed", categoryPaths: "Category paths", clear: "Clear",
    pathSearchLabel: "Path search", categorySearch: "Search category name", apply: "Apply selected categories",
    sourceError: "Check source", other: "Other review", noLevel1: "No recognized Level 1 Heading.",
    stoppedReason: "Could not determine a child category: {value}", unknownReason: "Unknown manual category: {value}",
    responseError: "Could not read the server response. ({status})", requestError: "Request failed. ({status})",
    loading: "Loading classification results.", untitled: "Untitled", noDate: "No date",
    noContent: "Could not load the source section.", selected: "{count} final path(s) selected",
    saving: "Saving source categories and rebuilding hierarchical results.", applied: "Categories applied."
  },
  ko: {
    pageTitle: "Log2Topic 분류 검토", heading: "분류 검토", waiting: "검토 대기",
    refresh: "새로 고침", reviewType: "검토 유형", all: "전체", missingLevel1: "Level 1 없음",
    parentStop: "상위 분류 정지", invalidManual: "수동 경로 오류", reviewQueue: "검토 목록",
    reviewSearch: "제목 또는 원본 경로 검색", emptyTitle: "검토할 항목이 없습니다",
    emptyBody: "현재 필터에 해당하는 분류 검토 항목이 없습니다.", sourceSection: "원본 구간",
    sourceChanged: "원본 변경 감지", categoryPaths: "분류 경로", clear: "선택 해제",
    pathSearchLabel: "경로 검색", categorySearch: "분류 이름 검색", apply: "선택한 분류 적용",
    sourceError: "원본 확인 필요", other: "기타 검토", noLevel1: "인식된 Level 1 Heading이 없습니다.",
    stoppedReason: "하위 분류를 결정하지 못했습니다: {value}", unknownReason: "분류 규칙에 없는 수동 경로입니다: {value}",
    responseError: "서버 응답을 읽을 수 없습니다. ({status})", requestError: "요청에 실패했습니다. ({status})",
    loading: "분류 결과를 불러오는 중입니다.", untitled: "제목 없음", noDate: "날짜 없음",
    noContent: "원본 구간을 불러오지 못했습니다.", selected: "{count}개 최종 경로 선택",
    saving: "원본 분류를 저장하고 계층형 결과를 다시 생성하는 중입니다.", applied: "분류를 적용했습니다."
  },
};

function t(key, values = {}) {
  let value = translations[uiLanguage]?.[key] || translations.en[key] || key;
  Object.entries(values).forEach(([name, replacement]) => {
    value = value.replace(`{${name}}`, String(replacement));
  });
  return value;
}

function applyStaticTranslations() {
  document.documentElement.lang = uiLanguage;
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
    element.setAttribute("aria-label", t(element.dataset.i18nAria));
  });
  document.title = t("pageTitle");
}

async function initializeLocale() {
  try {
    const response = await fetch("/api/locale");
    const payload = await response.json();
    uiLanguage = payload.language === "ko" ? "ko" : "en";
  } catch (_error) {
    uiLanguage = "en";
  }
  applyStaticTranslations();
}

const dashboardSessionId = (() => {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `session_${Date.now()}_${Math.random().toString(36).slice(2)}`;
})();

let dashboardSessionOpen = false;
let dashboardSessionStream = null;

const state = {
  items: [],
  categories: [],
  selectedSourceId: null,
  selectedPaths: new Set(),
  filter: "all",
  reviewSearch: "",
  categorySearch: "",
  busy: false,
};

function kindLabels() {
  return {
    "missing-level-1": t("missingLevel1"), "parent-category": t("parentStop"),
    "invalid-manual": t("invalidManual"), "source-error": t("sourceError"), "other": t("other"),
  };
}

const elements = {};

function pathKey(path) {
  return JSON.stringify(path);
}

function isSameOrAncestorPath(ancestor, candidate) {
  return ancestor.length <= candidate.length
    && ancestor.every((value, index) => value === candidate[index]);
}

function selectedPathArrays() {
  return Array.from(state.selectedPaths).map((value) => JSON.parse(value));
}

function normalizeSelectedPaths(paths) {
  const unique = Array.from(
    new Map(paths.map((path) => [pathKey(path), path])).values()
  );
  return unique.filter(
    (path) => !unique.some(
      (other) => other.length > path.length && isSameOrAncestorPath(path, other)
    )
  );
}

function replaceSelectedPaths(paths) {
  state.selectedPaths = new Set(normalizeSelectedPaths(paths).map((path) => pathKey(path)));
}

function selectCategoryPath(path) {
  const remaining = selectedPathArrays().filter(
    (selected) => !isSameOrAncestorPath(selected, path)
      && !isSameOrAncestorPath(path, selected)
  );
  remaining.push(path);
  replaceSelectedPaths(remaining);
}

function clearCategoryBranch(path) {
  replaceSelectedPaths(
    selectedPathArrays().filter((selected) => !isSameOrAncestorPath(path, selected))
  );
}

function isCategoryPathChecked(path) {
  return selectedPathArrays().some((selected) => isSameOrAncestorPath(path, selected));
}

function formatReviewReason(reason) {
  if (reason === "No recognized Level 1 Heading is active.") {
    return t("noLevel1");
  }
  if (reason.startsWith("Stopped at parent category:")) {
    return t("stoppedReason", { value: reason.split(":", 2)[1].trim() });
  }
  if (reason.startsWith("Unknown manual category:")) {
    return t("unknownReason", { value: reason.split(":", 2)[1].trim() });
  }
  return reason;
}

function selectedItem() {
  return state.items.find((item) => item.source_id === state.selectedSourceId) || null;
}

function filteredItems() {
  const query = state.reviewSearch.trim().toLocaleLowerCase();
  return state.items.filter((item) => {
    if (state.filter !== "all" && item.review_kind !== state.filter) {
      return false;
    }
    if (!query) {
      return true;
    }
    const haystack = [
      item.source_heading,
      item.source_path,
      ...(item.source_heading_path || []),
    ].join(" ").toLocaleLowerCase();
    return haystack.includes(query);
  });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  let payload;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = { message: t("responseError", { status: response.status }) };
  }
  if (!response.ok) {
    throw new Error(payload.message || t("requestError", { status: response.status }));
  }
  return payload;
}

function openDashboardSession() {
  if (dashboardSessionStream) {
    return;
  }
  const stream = new EventSource(
    `/api/session/watch?session_id=${encodeURIComponent(dashboardSessionId)}`
  );
  dashboardSessionStream = stream;
  stream.addEventListener("open", () => {
    dashboardSessionOpen = true;
  });
  stream.addEventListener("error", () => {
    dashboardSessionOpen = false;
  });
}

function closeDashboardSession() {
  dashboardSessionOpen = false;
  if (dashboardSessionStream) {
    dashboardSessionStream.close();
    dashboardSessionStream = null;
  }
}

async function loadData(preserveSelection = true) {
  setBusy(true, t("loading"));
  const previousId = preserveSelection ? state.selectedSourceId : null;
  try {
    const [reviewPayload, categoryPayload] = await Promise.all([
      fetchJson("/api/review-items"),
      fetchJson("/api/categories"),
    ]);
    state.items = reviewPayload.items || [];
    state.categories = categoryPayload.categories || [];
    if (previousId && state.items.some((item) => item.source_id === previousId)) {
      state.selectedSourceId = previousId;
    } else {
      const visible = filteredItems();
      state.selectedSourceId = visible.length ? visible[0].source_id : null;
    }
    syncSelectionFromItem();
    renderAll();
    setMessage("", "");
  } catch (error) {
    state.items = [];
    state.selectedSourceId = null;
    renderAll();
    setMessage(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function syncSelectionFromItem() {
  const item = selectedItem();
  const availablePaths = new Set(
    state.categories
      .filter((category) => category.selectable)
      .map((category) => pathKey(category.path))
  );
  replaceSelectedPaths(
    item
      ? (item.current_categories || [])
          .filter((path) => availablePaths.has(pathKey(path)))
      : []
  );
}

function setBusy(value, message = "") {
  state.busy = value;
  elements.refreshButton.disabled = value;
  elements.applyButton.disabled = value || !selectedItem() || state.selectedPaths.size === 0 || Boolean(selectedItem()?.metadata_stale);
  elements.categoryList.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
    checkbox.disabled = value || checkbox.dataset.selectable !== "true";
  });
  if (message) {
    setMessage(message, "");
  }
}

function setMessage(message, type) {
  elements.actionMessage.textContent = message || "";
  elements.actionMessage.className = "action-message";
  if (type) {
    elements.actionMessage.classList.add(type);
  }
}

function renderCounts() {
  const counts = {
    all: state.items.length,
    "missing-level-1": 0,
    "parent-category": 0,
    "invalid-manual": 0,
  };
  state.items.forEach((item) => {
    if (Object.prototype.hasOwnProperty.call(counts, item.review_kind)) {
      counts[item.review_kind] += 1;
    }
  });
  elements.reviewCount.textContent = String(counts.all);
  elements.countAll.textContent = String(counts.all);
  elements.countMissing.textContent = String(counts["missing-level-1"]);
  elements.countParent.textContent = String(counts["parent-category"]);
  elements.countInvalid.textContent = String(counts["invalid-manual"]);
}

function renderReviewList() {
  const visible = filteredItems();
  elements.reviewList.replaceChildren();
  visible.forEach((item) => {
    const row = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "review-item";
    if (item.source_id === state.selectedSourceId) {
      button.classList.add("active");
    }
    button.addEventListener("click", () => {
      state.selectedSourceId = item.source_id;
      syncSelectionFromItem();
      renderAll();
      setMessage("", "");
    });

    const title = document.createElement("span");
    title.className = "review-item-title";
    title.textContent = item.source_heading || t("untitled");
    const meta = document.createElement("span");
    meta.className = "review-item-meta";
    meta.textContent = `${item.source_log || t("noDate")} · ${item.source_path}:${item.source_line}`;
    const kind = document.createElement("span");
    kind.className = "review-kind";
    const labels = kindLabels();
    kind.textContent = labels[item.review_kind] || labels.other;
    button.append(title, meta, kind);
    row.appendChild(button);
    elements.reviewList.appendChild(row);
  });

  if (!visible.some((item) => item.source_id === state.selectedSourceId)) {
    state.selectedSourceId = visible.length ? visible[0].source_id : null;
    syncSelectionFromItem();
  }
}

function renderWorkspace() {
  const item = selectedItem();
  const hasItem = Boolean(item);
  elements.emptyState.hidden = hasItem;
  elements.reviewWorkspace.hidden = !hasItem;
  if (!item) {
    return;
  }

  elements.sourceBreadcrumb.textContent = (item.source_heading_path || []).join(" > ");
  elements.sourceHeading.textContent = item.source_heading || t("untitled");
  elements.sourceLocation.textContent = `${item.source_path}:${item.source_line} · Source ID ${item.source_id}`;
  elements.sourceContent.textContent = item.content || t("noContent");
  elements.staleIndicator.hidden = !item.metadata_stale;
  elements.reviewReasons.replaceChildren();
  (item.review_reasons || []).forEach((reason) => {
    const badge = document.createElement("span");
    badge.className = "reason-badge";
    badge.textContent = formatReviewReason(reason);
    elements.reviewReasons.appendChild(badge);
  });
  renderCategories();
}

function renderCategories() {
  const query = state.categorySearch.trim().toLocaleLowerCase();
  elements.categoryList.replaceChildren();
  state.categories.forEach((category) => {
    const fullPath = category.path.join(" > ");
    if (query && !fullPath.toLocaleLowerCase().includes(query)) {
      return;
    }
    const row = document.createElement("div");
    row.className = "category-row";
    row.style.paddingLeft = `${8 + (category.depth - 1) * 16}px`;
    const checkbox = document.createElement("input");
    const id = `category-${category.path.map((value) => encodeURIComponent(value)).join("-")}`;
    checkbox.type = "checkbox";
    checkbox.id = id;
    checkbox.dataset.selectable = category.selectable ? "true" : "false";
    checkbox.disabled = !category.selectable || state.busy;
    checkbox.checked = isCategoryPathChecked(category.path);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        selectCategoryPath(category.path);
      } else {
        clearCategoryBranch(category.path);
      }
      renderCategories();
    });
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = category.label;
    label.title = fullPath;
    const depth = document.createElement("span");
    depth.className = "category-depth";
    depth.textContent = `L${category.depth}`;
    row.append(checkbox, label, depth);
    elements.categoryList.appendChild(row);
  });
  updateSelectionState();
}

function updateSelectionState() {
  elements.selectedCount.textContent = t("selected", { count: state.selectedPaths.size });
  const item = selectedItem();
  elements.applyButton.disabled = state.busy || !item || item.metadata_stale || state.selectedPaths.size === 0;
}

function renderAll() {
  renderCounts();
  renderReviewList();
  renderWorkspace();
}

async function applyClassification() {
  const item = selectedItem();
  if (!item || !state.selectedPaths.size || state.busy) {
    return;
  }
  const categoryPaths = Array.from(state.selectedPaths).map((value) => JSON.parse(value));
  setBusy(true, t("saving"));
  try {
    const result = await fetchJson("/api/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_id: item.source_id,
        source_fingerprint: item.source_fingerprint,
        category_paths: categoryPaths,
      }),
    });
    const message = result.message || t("applied");
    await loadData(false);
    setMessage(message, "success");
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function bindEvents() {
  document.querySelectorAll(".filter-button").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      document.querySelectorAll(".filter-button").forEach((value) => {
        value.classList.toggle("active", value === button);
      });
      const visible = filteredItems();
      if (!visible.some((item) => item.source_id === state.selectedSourceId)) {
        state.selectedSourceId = visible.length ? visible[0].source_id : null;
        syncSelectionFromItem();
      }
      renderAll();
    });
  });
  elements.reviewSearch.addEventListener("input", (event) => {
    state.reviewSearch = event.target.value;
    renderAll();
  });
  elements.categorySearch.addEventListener("input", (event) => {
    state.categorySearch = event.target.value;
    renderCategories();
  });
  elements.clearSelectionButton.addEventListener("click", () => {
    state.selectedPaths.clear();
    renderCategories();
  });
  elements.refreshButton.addEventListener("click", () => loadData(true));
  elements.applyButton.addEventListener("click", applyClassification);
}

function initializeElements() {
  [
    "reviewCount", "refreshButton", "countAll", "countMissing", "countParent",
    "countInvalid", "reviewSearch", "reviewList", "emptyState", "reviewWorkspace",
    "sourceBreadcrumb", "sourceHeading", "sourceLocation", "reviewReasons",
    "sourceContent", "staleIndicator", "selectedCount", "clearSelectionButton",
    "categorySearch", "categoryList", "actionMessage", "applyButton",
  ].forEach((id) => {
    elements[id] = document.getElementById(id);
  });
}

async function initializeApp() {
  initializeElements();
  await initializeLocale();
  bindEvents();
  window.addEventListener("pagehide", closeDashboardSession);
  window.addEventListener("pageshow", () => {
    if (!dashboardSessionStream) {
      openDashboardSession();
    }
  });
  openDashboardSession();
  loadData(false);
}

initializeApp();
