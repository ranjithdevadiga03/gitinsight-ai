/* ===========================================================
   GitInsight AI - Frontend logic
   Talks to the Flask backend via /api/analyze, /api/explain, /api/chat
   =========================================================== */

// ---------- Element references ----------
const repoUrlInput = document.getElementById("repoUrl");
const analyzeBtn   = document.getElementById("analyzeBtn");
const loader       = document.getElementById("loader");
const errorBox     = document.getElementById("errorBox");

const repoInfoSection    = document.getElementById("repo-info");
const overviewSection    = document.getElementById("overview");
const structureSection   = document.getElementById("structure");
const explainSection     = document.getElementById("explain");
const chatbotSection     = document.getElementById("chatbot");

const analysisOutput = document.getElementById("analysisOutput");
const treeList       = document.getElementById("treeList");
const fileSelect     = document.getElementById("fileSelect");
const customFile     = document.getElementById("customFile");
const explainBtn     = document.getElementById("explainBtn");
const explainLoader  = document.getElementById("explainLoader");
const explainOutput  = document.getElementById("explainOutput");
const fileFilter     = document.getElementById("fileFilter");

const chatWindow = document.getElementById("chatWindow");
const chatInput  = document.getElementById("chatInput");
const sendBtn    = document.getElementById("sendBtn");

// ---------- Shared state ----------
let currentTree = [];        // full file tree of the analyzed repo
let chatHistory = [];        // previous chat messages for multi-turn context

// Simple URL validation on the frontend (backend validates again)
function isValidGitHubUrl(value) {
  const url = value.trim();
  return /^(https?:\/\/)?(www\.)?github\.com\/[\w.\-]+\/[\w.\-]+/.test(url) ||
         /^[\w.\-]+\/[\w.\-]+$/.test(url);
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
}

function clearError() {
  errorBox.classList.add("hidden");
}

// Convert a markdown string to HTML (marked.js) with a safe fallback
function md(text) {
  if (window.marked && text) {
    return marked.parse(text);
  }
  return String(text || "").replace(/\n/g, "<br>");
}

// Extract owner/repo from whatever the user typed
function extractOwnerRepo(value) {
  const v = value.trim().replace(/\.git$/, "").replace(/\/$/, "");
  const m = v.match(/github\.com\/([\w.\-]+)\/([\w.\-]+)/) ||
            v.match(/^([\w.\-]+)\/([\w.\-]+)$/);
  return m ? `${m[1]}/${m[2]}` : "";
}

// ==================================================================
// FEATURE 1 + 2 + 3 : Analyze repository
// ==================================================================
async function analyzeRepository() {
  const url = repoUrlInput.value.trim();
  clearError();

  if (!url) {
    showError("Please enter a GitHub repository URL.");
    return;
  }
  if (!isValidGitHubUrl(url)) {
    showError("Invalid GitHub URL. Example: https://github.com/pallets/flask");
    return;
  }

  // Show loading state
  analyzeBtn.disabled = true;
  loader.classList.remove("hidden");

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Analysis failed.");
    }

    renderRepoInfo(data.repo, data.languages);
    renderAnalysis(data.analysis);
    renderTree(data.tree);
    populateFileSelect(data.files);
    document.getElementById("filesAnalyzed").textContent =
      "Files sent to AI: " + (data.files.length ? data.files.join(", ") : "none");

    // Show the result sections
    repoInfoSection.classList.remove("hidden");
    overviewSection.classList.remove("hidden");
    structureSection.classList.remove("hidden");
    explainSection.classList.remove("hidden");
    chatbotSection.classList.remove("hidden");

    // Reset chat for the new repository
    chatHistory = [];
    chatWindow.innerHTML =
      '<div class="msg bot">Repository analyzed! Ask me anything about <b>' +
      (data.repo.name || "it") + "</b>.</div>";

    // Scroll to results
    repoInfoSection.scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    showError(err.message);
  } finally {
    analyzeBtn.disabled = false;
    loader.classList.add("hidden");
  }
}

// ---------- Render repository information ----------
function renderRepoInfo(repo, languages) {
  document.getElementById("repoName").textContent      = repo.name || "-";
  document.getElementById("repoOwner").textContent     = repo.owner || "-";
  document.getElementById("repoLanguage").textContent  = repo.language || "-";
  document.getElementById("repoBranch").textContent    = repo.branch || "-";
  document.getElementById("repoStars").textContent     = repo.stars ?? "-";
  document.getElementById("repoForks").textContent     = repo.forks ?? "-";
  document.getElementById("repoDescription").textContent =
    repo.description || "No description provided.";

  // Language percentage bars
  const bars = document.getElementById("languageBars");
  bars.innerHTML = "";
  const entries = Object.entries(languages || {});
  const total = entries.reduce((sum, [, bytes]) => sum + bytes, 0) || 1;
  entries.sort((a, b) => b[1] - a[1]);
  for (const [name, bytes] of entries) {
    const pct = ((bytes / total) * 100).toFixed(1);
    const row = document.createElement("div");
    row.className = "lang-row";
    row.innerHTML =
      `<span>${name}</span>` +
      `<div class="lang-bar"><span style="width:${pct}%"></span></div>` +
      `<span>${pct}%</span>`;
    bars.appendChild(row);
  }
}

// ---------- Render AI analysis markdown ----------
function renderAnalysis(text) {
  analysisOutput.innerHTML = md(text);
}

// ---------- Render file tree ----------
function renderTree(tree) {
  currentTree = tree;
  drawTree(tree);
}

function drawTree(tree) {
  const filter = fileFilter.value.trim().toLowerCase();
  treeList.innerHTML = "";
  const items = tree.filter((e) => !filter || e.path.toLowerCase().includes(filter));

  if (!items.length) {
    treeList.innerHTML = '<li style="justify-content:center;color:#6b7280">No matching files</li>';
    return;
  }

  for (const entry of items.slice(0, 300)) {
    const li = document.createElement("li");
    if (entry.type === "tree") {
      li.className = "dir";
      li.innerHTML = `<span>&#128193; ${entry.path}/</span>`;
    } else {
      li.innerHTML = `<span>&#128196; ${entry.path}</span>`;
      // Button to explain this file directly from the tree
      const btn = document.createElement("button");
      btn.textContent = "Explain";
      btn.onclick = () => {
        customFile.value = entry.path;
        explainFile();
      };
      li.appendChild(btn);
    }
    treeList.appendChild(li);
  }
}

fileFilter.addEventListener("input", () => drawTree(currentTree));

// ---------- Fill the file dropdown ----------
function populateFileSelect(files) {
  fileSelect.innerHTML = '<option value="">-- select an analyzed file --</option>';
  for (const f of files) {
    const opt = document.createElement("option");
    opt.value = f;
    opt.textContent = f;
    fileSelect.appendChild(opt);
  }
}

// ==================================================================
// FEATURE 4 : Explain a single file
// ==================================================================
async function explainFile() {
  const url = repoUrlInput.value.trim();
  const file = customFile.value.trim() || fileSelect.value;

  clearError();
  if (!file) {
    showError("Select or type a file path to explain.");
    return;
  }

  explainBtn.disabled = true;
  explainLoader.classList.remove("hidden");
  explainOutput.innerHTML = "";

  try {
    const res = await fetch("/api/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, file }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Explanation failed.");
    explainOutput.innerHTML = md(data.explanation);
    explainOutput.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showError(err.message);
  } finally {
    explainBtn.disabled = false;
    explainLoader.classList.add("hidden");
  }
}

// ==================================================================
// FEATURE 5 : Chatbot
// ==================================================================
function addChatMessage(text, role) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = role === "bot" ? md(text) : text;
  chatWindow.appendChild(div);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return div;
}

async function sendChat() {
  const question = chatInput.value.trim();
  if (!question) return;

  const ctx = analysisOutput.textContent || "";
  addChatMessage(question, "user");
  chatHistory.push({ role: "user", content: question });
  chatInput.value = "";

  const pending = addChatMessage("Thinking...", "bot");
  sendBtn.disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        context: ctx,
        history: chatHistory.slice(0, -1), // exclude the just-added message
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Chat failed.");

    pending.innerHTML = md(data.answer);
    chatHistory.push({ role: "assistant", content: data.answer });
  } catch (err) {
    pending.className = "msg bot";
    pending.innerHTML = "<i>" + err.message + "</i>";
  } finally {
    sendBtn.disabled = false;
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }
}

// ---------- Event listeners ----------
analyzeBtn.addEventListener("click", analyzeRepository);
repoUrlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") analyzeRepository();
});

explainBtn.addEventListener("click", explainFile);
fileSelect.addEventListener("change", () => {
  if (fileSelect.value) customFile.value = "";
});

sendBtn.addEventListener("click", sendChat);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});

// Suggested question chips
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    chatInput.value = chip.textContent;
    sendChat();
  });
});

// Sample repository link
document.getElementById("sampleUrl").addEventListener("click", (e) => {
  e.preventDefault();
  repoUrlInput.value = "https://github.com/pallets/flask";
});
