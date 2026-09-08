const { sourcePrinciples, documents: initialDocuments, answers, fallbackAnswer } = window.SUFEGUIDE_DATA;
let documents = [...initialDocuments];

const state = {
  view: "chat",
  libraryFilter: "全部",
  favorites: JSON.parse(localStorage.getItem("campusguide-favorites") || "[]"),
  lastQuestion: "",
  lastContext: null
};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

function initializeIcons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

function setView(view) {
  state.view = view;
  $$(".view").forEach(el => el.classList.remove("active"));
  $$(".nav-tab").forEach(el => el.classList.toggle("active", el.dataset.view === view));
  $(`#${view}View`).classList.add("active");
  if (view === "library") { renderDocuments(); renderOfficialSources(); }
  if (view === "favorites") renderFavorites();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 1900);
}

function getDoc(id) {
  return documents.find(doc => doc.id === id);
}

async function loadAllDocuments() {
  if (window.location.protocol === "file:") return;
  try {
    const response = await fetch("/api/documents", { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const payload = await response.json();
    if (!Array.isArray(payload.documents)) return;
    const byId = new Map(documents.map(document => [document.id, document]));
    for (const document of payload.documents) byId.set(document.id, { ...byId.get(document.id), ...document });
    documents = [...byId.values()];
    renderDocuments();
    renderFavorites();
  } catch {
    showToast("全部资料加载失败，当前显示本地索引");
  }
}

function getAudienceContext() {
  const college = $("#collegeSelect")?.value || "";
  const level = $("#levelSelect")?.value || "";
  const year = $("#yearSelect")?.value || "";
  const complete = Boolean(college && level && year);
  return { college, level, year, complete };
}

function formatContextLine(context) {
  const text = `${context.college || "未选择学院"} / ${context.level || "未选择培养层次"} / ${context.year || "未选择年份"}`;
  return context.complete ? text : `${text}（信息不完整，正式回答会先追问或降低置信度）`;
}

function sourceStatusIcon(doc) {
  if (doc.statusTone === "pending") return "file-warning";
  if (doc.statusTone === "historical") return "history";
  if (doc.statusTone === "scoped") return "calendar-range";
  if (doc.verified) return "shield-check";
  if (doc.sourceType === "task") return "clipboard-list";
  return "shield-alert";
}

function sourceStatusClass(doc) {
  return doc.statusTone || (doc.verified ? "current" : "pending");
}

function isOfficialUrl(url) {
  return /^https?:\/\//.test(url || "") && url !== "#demo-source";
}
function toggleFavorite(id) {
  if (state.favorites.includes(id)) {
    state.favorites = state.favorites.filter(item => item !== id);
    showToast("已取消收藏");
  } else {
    state.favorites.push(id);
    showToast("已加入收藏");
  }
  localStorage.setItem("campusguide-favorites", JSON.stringify(state.favorites));
  renderSources(state.currentSourceIds || []);
  renderDocuments();
  renderFavorites();
}

function renderSources(ids) {
  state.currentSourceIds = ids;
  const docs = ids.map(getDoc).filter(Boolean);
  $("#sourceCount").textContent = `${docs.length} 份`;
  $("#sourceEmpty").style.display = docs.length ? "none" : "flex";
  const list = $("#sourceList");
  list.innerHTML = docs.map((doc, index) => `
    <article class="source-card" data-source-card="${doc.id}">
      <div class="source-card-top">
        <span class="source-index">${index + 1}</span>
        <h3 class="source-title">${doc.title}</h3>
        <button class="icon-button small ${state.favorites.includes(doc.id) ? "active" : ""}" data-favorite="${doc.id}" aria-label="收藏资料" title="收藏资料">
          <i data-lucide="bookmark${state.favorites.includes(doc.id) ? "-check" : ""}"></i>
        </button>
      </div>
      <div class="source-meta">
        <span class="meta-tag ${sourceStatusClass(doc)}"><i data-lucide="${sourceStatusIcon(doc)}"></i>${doc.status}</span>
        <span class="meta-tag">${doc.issuer}</span>
        <span class="meta-tag">${doc.date}</span>
      </div>
      <p class="source-excerpt">${doc.excerpt}</p>
      <div class="source-card-actions">
        <button class="action-button" data-open-source="${doc.id}"><i data-lucide="scan-text"></i>查看证据</button>
        <button class="action-button" data-open-source="${doc.id}"><i data-lucide="external-link"></i>原文入口</button>
      </div>
    </article>
  `).join("");
  initializeIcons();
}

function showSource(id) {
  const doc = getDoc(id);
  if (!doc) return;
  $("#sourceModalTitle").textContent = doc.title;
  $("#sourceModalBody").innerHTML = `
    <dl class="source-detail-grid">
      <dt>资料编号</dt><dd>${doc.id}</dd>
      <dt>主题</dt><dd>${doc.category}</dd>
      <dt>发布单位</dt><dd>${doc.issuer}</dd>
      <dt>发布日期</dt><dd>${doc.date}</dd>
      <dt>适用对象</dt><dd>${doc.applies}</dd>
      <dt>来源等级</dt><dd>${doc.level}</dd>
      <dt>资料状态</dt><dd>${doc.status}</dd>
      <dt>使用方式</dt><dd>${doc.useMode || "直接证据"}</dd>
      ${doc.registrationIds?.length ? `<dt>登记来源</dt><dd>${doc.registrationIds.join("、")}</dd>` : ""}
    </dl>
    <div class="excerpt-box"><strong>证据片段</strong>${doc.excerpt}</div>
    <p><a class="demo-link" href="${escapeHtml(doc.url || "#")}" ${isOfficialUrl(doc.url) ? "target=\"_blank\" rel=\"noopener\"" : "data-demo-link"}><i data-lucide="external-link"></i> ${isOfficialUrl(doc.url) ? "打开官方入口" : "来源链接待补充"}</a></p>
    <p class="source-provenance"><i data-lucide="badge-check"></i>${escapeHtml(doc.sourceLabel || (doc.url ? "官网公开来源" : "官方或学院提供，来源链接待补充"))}</p>
    <div class="info-callout"><i data-lucide="triangle-alert"></i><span>${doc.note || "请根据资料适用对象和年份使用，最终认定以主管部门为准。"}</span></div>
  `;
  $("#sourceModal").showModal();
  initializeIcons();
}

function highlightSource(id) {
  const target = document.querySelector(`[data-source-card="${id}"]`);
  const sourcePanelVisible = window.getComputedStyle($("#sourcePanel")).display !== "none";
  if (target && sourcePanelVisible) {
    target.classList.add("highlight");
    const panel = $("#sourcePanel");
    const top = target.offsetTop - Math.max(0, (panel.clientHeight - target.offsetHeight) / 2);
    panel.scrollTo({ top, behavior: "smooth" });
    setTimeout(() => target.classList.remove("highlight"), 1700);
  } else {
    showSource(id);
  }
}

function findAnswer(question) {
  return answers.find(answer => answer.test(question)) || buildLocalRetrievalAnswer(question) || fallbackAnswer;
}

function tokenizeQuestion(value) {
  const normalized = String(value || "").toLowerCase().replace(/\s+/g, " ").trim();
  const intentPhrases = ["什么时候", "怎么办", "怎么样", "在哪里", "去哪里", "到哪里", "能不能", "可不可以", "怎么", "如何", "哪里", "哪儿", "去哪", "什么", "多少", "几点", "今天", "现在", "请问", "想问", "咨询", "相关", "规定", "流程", "办理", "申请", "是否", "能否", "应该", "需要"];
  const stopTokens = new Set([...intentPhrases, "学校", "学生", "大学", "一下", "有关", "具体", "情况", "问题", "事情", "关门", "开放"]);
  const tokens = new Set(normalized.match(/[a-z0-9]+/g) || []);

  for (const sequence of normalized.match(/[\u3400-\u9fff]{2,}/g) || []) {
    let subjectText = sequence;
    for (const phrase of intentPhrases) subjectText = subjectText.replaceAll(phrase, " ");
    for (const subject of subjectText.split(/\s+/).filter(Boolean)) {
      if (subject.length > 1) tokens.add(subject);
      for (const size of [2]) {
        for (let index = 0; index <= subject.length - size; index += 1) tokens.add(subject.slice(index, index + size));
      }
    }
  }

  return [...tokens].filter(token => token.length > 1 && !stopTokens.has(token));
}

function localTokenWeights(tokens) {
  const texts = documents.map(document => `${document.title} ${document.keywords} ${document.excerpt} ${document.category} ${document.issuer} ${document.applies}`.toLowerCase());
  return tokens.map(token => {
    const frequency = texts.reduce((count, text) => count + (text.includes(token) ? 1 : 0), 0);
    const rarity = Math.min(3, 1 + Math.log((documents.length + 1) / (frequency + 1)));
    const lengthWeight = token.length >= 4 ? 1.75 : token.length === 3 ? 1.4 : 1;
    return { value: token, weight: rarity * lengthWeight };
  });
}

function scoreLocalField(field, tokens, weight) {
  const text = String(field || "").toLowerCase();
  return tokens.reduce((score, token) => score + (text.includes(token.value) ? weight * token.weight : 0), 0);
}

function buildLocalRetrievalAnswer(question) {
  const tokens = localTokenWeights(tokenizeQuestion(question));
  const ranked = documents.map(document => {
    const searchableText = `${document.title} ${document.keywords} ${document.excerpt} ${document.category} ${document.issuer} ${document.applies}`.toLowerCase();
    const totalTokenWeight = tokens.reduce((sum, token) => sum + token.weight, 0);
    const matchedTokenWeight = tokens.reduce((sum, token) => sum + (searchableText.includes(token.value) ? token.weight : 0), 0);
    const lexicalScore = scoreLocalField(document.title, tokens, 6)
      + scoreLocalField(document.keywords, tokens, 4)
      + scoreLocalField(document.excerpt, tokens, 3);
    const metadataScore = scoreLocalField(`${document.category} ${document.issuer} ${document.applies}`, tokens, 1);
    return { document, lexicalScore, queryCoverage: totalTokenWeight ? matchedTokenWeight / totalTokenWeight : 0, score: lexicalScore + metadataScore };
  }).filter(item => item.lexicalScore >= 9 && item.queryCoverage >= 0.18).sort((left, right) => right.score - left.score);

  if (!ranked.length) return null;
  const minimumScore = Math.max(9, ranked[0].lexicalScore * 0.55);
  const matches = ranked.filter(item => item.lexicalScore >= minimumScore);
  const allHistorical = matches.every(item => item.document.statusTone === "historical");
  const hasHistorical = matches.some(item => item.document.statusTone === "historical");

  return {
    sources: matches.map(item => item.document.id),
    confidence: allHistorical ? "中：找到相关历史资料，现行要求仍需核对" : "中：已检索到相关资料，需结合具体问题核对",
    status: "caution",
    statusText: allHistorical ? "找到历史相关资料" : (hasHistorical ? "找到相关资料（含历史资料）" : "找到相关资料"),
    html: `
      <p><strong>当前问题没有命中精确回答，但知识库检索到了以下高度相关资料。</strong></p>
      <ul>${matches.map((item, index) => `
        <li><strong>${escapeHtml(item.document.title)}</strong><button class="citation" data-source="${item.document.id}">${index + 1}</button><p><small>日期：${escapeHtml(item.document.date || "未标注")}｜状态：${escapeHtml(item.document.status || "适用范围待核对")}</small></p><p>${escapeHtml(item.document.excerpt)}</p></li>
      `).join("")}</ul>
    `,
    note: hasHistorical
      ? "结果中含历史资料，只能用于了解制度沿革，不能替代当前学期或当前年度通知；其余资料也应按标注的年份和适用范围使用。"
      : "以下为资料中的可核验摘要。请按标注的年份和适用范围使用；补充学院、培养层次或目标年份可进一步缩小范围。",
    followups: []
  };
}

async function requestAgentAnswer(question, context) {
  if (window.location.protocol === "file:") return null;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, context }),
      signal: controller.signal
    });

    if (!response.ok) return null;
    const payload = await response.json();
    if (Array.isArray(payload.citations)) {
      const byId = new Map(documents.map(document => [document.id, document]));
      for (const document of payload.citations) byId.set(document.id, { ...byId.get(document.id), ...document });
      documents = [...byId.values()];
    }
    if (!payload.answer) return null;
    return {
      ...payload.answer,
      status: ["insufficient_evidence", "policy_blocked"].includes(payload.status) ? "caution" : payload.answer.status,
      statusText: payload.status === "insufficient_evidence" ? "资料不足，已拒答" : payload.status === "policy_blocked" ? "问题范围受限" : "已根据资料生成",
      note: payload.status === "insufficient_evidence"
        ? "当前资料库没有足够依据，因此没有生成具体规则；请补充问题范围或以主管部门最新通知为准。"
        : payload.status === "policy_blocked"
          ? "该问题涉及安全、隐私或超出校园资料范围；可以改问公开办事流程、政策条件或官方入口。"
        : "回答来自可追溯资料。请结合资料日期和适用对象，以主管部门最新通知为准。",
      followups: payload.answer.followups || []
    };
  } catch (error) {
    if (error?.name !== "AbortError") showToast("后端暂时不可用，已使用本地知识库回答");
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

async function submitQuestion(question) {
  const cleanQuestion = question.trim();
  if (!cleanQuestion) return;
  const pendingId = `pending-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const questionContext = getAudienceContext();
  state.lastQuestion = cleanQuestion;
  state.lastContext = questionContext;
  $("#welcomePanel").style.display = "none";
  $("#suggestions").style.display = "none";

  const messages = $("#messages");
  messages.insertAdjacentHTML("beforeend", `
    <div class="message user">
      <div class="message-body">${escapeHtml(cleanQuestion)}<span class="context-summary">${escapeHtml(formatContextLine(questionContext))}</span></div>
    </div>
    <div class="message assistant pending" data-pending-id="${pendingId}">
      <div class="message-avatar"><i data-lucide="sparkles"></i></div>
      <div class="message-body"><div class="typing"><span></span><span></span><span></span></div></div>
    </div>
  `);
  initializeIcons();
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  $("#questionInput").value = "";
  resizeTextarea($("#questionInput"));

  const startedAt = Date.now();
  const answer = await requestAgentAnswer(cleanQuestion, questionContext) || findAnswer(cleanQuestion);
  const remainingDelay = Math.max(0, 420 - (Date.now() - startedAt));

  setTimeout(() => {
    document.querySelector(`[data-pending-id="${pendingId}"]`)?.remove();
    renderAnswer(answer, questionContext);
  }, remainingDelay);
}

function renderAnswer(answer, context = getAudienceContext()) {
  const sourceIds = answer.sources || [];
  const engineLabel = answer.engine === "hybrid-rag-agent-api"
    ? "混合 RAG"
    : answer.engine === "lexical-rag-agent"
      ? "词法 RAG"
    : answer.engine === "deterministic-agent-api"
      ? "Agent API"
      : "离线规则";
  const statusClass = answer.status === "caution" ? "caution" : "";
  const statusIcon = answer.status === "caution" ? "shield-alert" : "shield-check";
  const statusText = answer.statusText || "已根据资料生成";
  const followups = (answer.followups || []).map(item => `<button class="followup" data-question="${item}">${item}</button>`).join("");
  $("#messages").insertAdjacentHTML("beforeend", `
    <div class="message assistant">
      <div class="message-avatar"><i data-lucide="sparkles"></i></div>
      <div class="message-body answer-card">
        <div class="answer-head">
          <span class="answer-status ${statusClass}"><i data-lucide="${statusIcon}"></i>${statusText}</span>
          <span class="answer-runtime" data-answer-engine="${answer.engine || "local-rules"}">${engineLabel}</span>
          <span class="confidence">${answer.confidence}</span>
        </div>
        <div class="answer-context"><i data-lucide="sliders-horizontal"></i><span>适用对象：${escapeHtml(formatContextLine(context))}</span></div>
        <div class="answer-content">${answer.html}</div>
        <div class="answer-note"><i data-lucide="info"></i><span>${answer.note}</span></div>
        ${followups ? `<div class="followups">${followups}</div>` : ""}
        <div class="answer-actions">
          <button class="action-button" data-copy-answer><i data-lucide="copy"></i>复制</button>
          <button class="action-button" data-helpful><i data-lucide="thumbs-up"></i>有用</button>
          <button class="action-button" data-not-helpful><i data-lucide="thumbs-down"></i>需改进</button>
        </div>
      </div>
    </div>
  `);
  renderSources(sourceIds);
  initializeIcons();
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

async function recordFeedback(helpful, reasons = []) {
  if (!state.lastQuestion || window.location.protocol === "file:") return false;
  try {
    const response = await fetch("/api/tools/call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "record_feedback",
        arguments: { question: state.lastQuestion, helpful, reasons }
      })
    });
    return response.ok;
  } catch {
    return false;
  }
}

function renderDocuments() {
  const query = $("#librarySearch")?.value.trim().toLowerCase() || "";
  const filtered = documents.filter(doc => {
    const matchesFilter = state.libraryFilter === "全部" || doc.category === state.libraryFilter;
    const haystack = `${doc.title} ${doc.issuer} ${doc.category} ${doc.keywords}`.toLowerCase();
    return matchesFilter && haystack.includes(query);
  });
  $("#documentRows").innerHTML = filtered.map(doc => `
    <tr>
      <td>${doc.title}</td>
      <td>${doc.category}</td>
      <td>${doc.issuer}</td>
      <td>${doc.date}</td>
      <td><span class="status-pill ${sourceStatusClass(doc)}"><i data-lucide="${sourceStatusIcon(doc)}"></i>${doc.status}</span></td>
      <td><span class="source-label">${escapeHtml(doc.url && isOfficialUrl(doc.url) ? "官网链接" : "官方/学院提供，待补原文链接")}</span></td>
      <td><div class="table-actions">
        <button class="icon-button small ${state.favorites.includes(doc.id) ? "active" : ""}" data-favorite="${doc.id}" aria-label="收藏" title="收藏"><i data-lucide="bookmark${state.favorites.includes(doc.id) ? "-check" : ""}"></i></button>
        <button class="icon-button small" data-open-source="${doc.id}" aria-label="查看详情" title="查看详情"><i data-lucide="arrow-up-right"></i></button>
      </div></td>
    </tr>
  `).join("");
  $("#tableEmpty").style.display = filtered.length ? "none" : "flex";
  $("#documentRows").closest("table").style.display = filtered.length ? "table" : "none";
  $("#docMetric").textContent = documents.length;
  initializeIcons();
}


function renderOfficialSources() {
  const grid = $("#officialSourceGrid");
  if (!grid) return;
  grid.innerHTML = sourcePrinciples.map(item => `
    <article class="official-source-card">
      <span class="source-priority">${item.priority}</span>
      <h3>${item.name}</h3>
      <p>${item.scope}</p>
      <div class="official-source-foot">
        <span>${item.status}</span>
        <a href="${item.url}" target="_blank" rel="noopener"><i data-lucide="external-link"></i>入口</a>
      </div>
    </article>
  `).join("");
  initializeIcons();
}
function renderFavorites() {
  const docs = state.favorites.map(getDoc).filter(Boolean);
  $("#favoriteGrid").innerHTML = docs.map(doc => `
    <article class="favorite-card">
      <span class="meta-tag ${sourceStatusClass(doc)}">${doc.status}</span>
      <h3>${doc.title}</h3>
      <p>${doc.issuer}<br>${doc.date} · ${doc.applies}</p>
      <div class="favorite-card-foot">
        <button class="action-button" data-open-source="${doc.id}"><i data-lucide="scan-text"></i>查看详情</button>
        <button class="icon-button small" data-favorite="${doc.id}" aria-label="取消收藏" title="取消收藏"><i data-lucide="bookmark-minus"></i></button>
      </div>
    </article>
  `).join("");
  $("#favoriteGrid").style.display = docs.length ? "grid" : "none";
  $("#favoritesEmpty").style.display = docs.length ? "none" : "flex";
  initializeIcons();
}

function resizeTextarea(input) {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
}

document.addEventListener("click", event => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) setView(viewButton.dataset.view);

  const questionButton = event.target.closest("[data-question]");
  if (questionButton) {
    setView("chat");
    submitQuestion(questionButton.dataset.question);
  }

  const sourceButton = event.target.closest("[data-open-source]");
  if (sourceButton) showSource(sourceButton.dataset.openSource);

  const citation = event.target.closest("[data-source]");
  if (citation) highlightSource(citation.dataset.source);

  const favorite = event.target.closest("[data-favorite]");
  if (favorite) toggleFavorite(favorite.dataset.favorite);

  if (event.target.closest("[data-go-library]")) setView("library");

  if (event.target.closest("[data-close-dialog]")) event.target.closest("dialog").close();

  if (event.target.closest("[data-demo-link]")) {
    event.preventDefault();
    showToast("正式版本将在这里打开官方原文");
  }

  if (event.target.closest("[data-copy-answer]")) {
    const card = event.target.closest(".answer-card");
    navigator.clipboard?.writeText(card.querySelector(".answer-content").innerText);
    showToast("回答已复制");
  }

  if (event.target.closest("[data-helpful]")) {
    event.target.closest("[data-helpful]").classList.add("active");
    void recordFeedback(true).then(saved => {
      showToast(saved ? "感谢反馈，已保存到后端" : "感谢反馈，已在当前页面记录");
    });
  }

  if (event.target.closest("[data-not-helpful]")) $("#feedbackModal").showModal();
});

$("#questionForm").addEventListener("submit", event => {
  event.preventDefault();
  submitQuestion($("#questionInput").value);
});

$("#questionInput").addEventListener("input", event => resizeTextarea(event.target));
$("#questionInput").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#questionForm").requestSubmit();
  }
});

$("#librarySearch").addEventListener("input", renderDocuments);
$("#libraryFilters").addEventListener("click", event => {
  const filter = event.target.closest("[data-filter]");
  if (!filter) return;
  state.libraryFilter = filter.dataset.filter;
  $$("[data-filter]").forEach(item => item.classList.toggle("active", item === filter));
  renderDocuments();
});

$("#categoryList").addEventListener("click", event => {
  const category = event.target.closest("[data-category]");
  if (!category) return;
  $$(".category").forEach(item => item.classList.toggle("active", item === category));
  const name = category.dataset.category;
  if (name === "全部") {
    setView("chat");
  } else {
    setView("library");
    state.libraryFilter = name;
    $$("[data-filter]").forEach(item => item.classList.toggle("active", item.dataset.filter === name));
    renderDocuments();
  }
  closeSidebar();
});

$("#infoButton").addEventListener("click", () => $("#infoModal").showModal());
$("#dismissWarning").addEventListener("click", () => $("#demoWarning").remove());

function openSidebar() {
  $("#sidebar").classList.add("open");
  $("#scrim").classList.add("show");
}

function closeSidebar() {
  $("#sidebar").classList.remove("open");
  $("#scrim").classList.remove("show");
}

$("#menuButton").addEventListener("click", openSidebar);
$("#closeMenuButton").addEventListener("click", closeSidebar);
$("#scrim").addEventListener("click", closeSidebar);

$("#feedbackForm").addEventListener("submit", async event => {
  event.preventDefault();
  const reasons = [...event.currentTarget.querySelectorAll("input:checked")].map(item => item.value);
  const savedFeedback = JSON.parse(localStorage.getItem("campusguide-feedback") || "[]");
  savedFeedback.push({ question: state.lastQuestion, reasons, detail: $("#feedbackText").value.trim(), createdAt: new Date().toISOString() });
  localStorage.setItem("campusguide-feedback", JSON.stringify(savedFeedback));
  const backendSaved = await recordFeedback(false, reasons);
  $("#feedbackModal").close();
  event.currentTarget.reset();
  showToast(backendSaved ? "匿名反馈已保存到后端" : "匿名反馈已保存在当前浏览器");
});

$("#sourceModal").addEventListener("click", event => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
$("#infoModal").addEventListener("click", event => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});

renderDocuments();
renderFavorites();
initializeIcons();
loadAllDocuments();
