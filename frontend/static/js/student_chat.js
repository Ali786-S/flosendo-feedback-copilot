// Chat elements
const feedbackChatLog = document.getElementById("feedbackChatLog");
const feedbackChatInput = document.getElementById("feedbackChatInput");
const feedbackChatSendBtn = document.getElementById("feedbackChatSendBtn");
const feedbackChatMsg = document.getElementById("feedbackChatMsg");
const feedbackChatFiles = document.getElementById("feedbackChatFiles");
const feedbackChatFilesMsg = document.getElementById("feedbackChatFilesMsg");
const generalChatLog = document.getElementById("generalChatLog");
const generalChatInput = document.getElementById("generalChatInput");
const generalChatSendBtn = document.getElementById("generalChatSendBtn");
const generalChatMsg = document.getElementById("generalChatMsg");

// <input id="generalChatFiles" type="file" multiple />
// <p id="generalChatFilesMsg" ...></p>
const generalChatFiles = document.getElementById("generalChatFiles");
const generalChatFilesMsg = document.getElementById("generalChatFilesMsg");

// store currently selected submission id 
window.selectedSubmissionId = window.selectedSubmissionId || null;

function escapeHtml(str) {
  return String(str || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function appendChat(logEl, who, text) {
  const div = document.createElement("div");
  div.className = "chat-msg";
  const labelClass = who === "You" ? "chat-user" : "chat-bot";
  div.innerHTML = `<span class="${labelClass}">${escapeHtml(who)}:</span> ${escapeHtml(text).replaceAll("\n", "<br/>")}`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}


async function uploadFiles(fileInputEl, statusEl) {
  if (!fileInputEl || !fileInputEl.files || fileInputEl.files.length === 0) return [];

  const files = Array.from(fileInputEl.files);

  // Basic client-side limits (
  const allowedExt = [".pdf", ".docx", ".pptx", ".jpg", ".jpeg", ".png"];
  for (const f of files) {
    const name = (f.name || "").toLowerCase();
    if (!allowedExt.some(ext => name.endsWith(ext))) {
      throw new Error("Only PDF, DOCX, PPTX, JPG, JPEG, PNG files are allowed.");
    }
  }

  if (statusEl) statusEl.textContent = `Uploading ${files.length} file(s)...`;

  const fd = new FormData();
  files.forEach(f => fd.append("files", f));

  const res = await fetch("/api/uploads", {
    method: "POST",
    body: fd
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (statusEl) statusEl.textContent = "";
    throw new Error(data.detail || "Upload failed");
  }

  if (statusEl) statusEl.textContent = `Uploaded: ${data.files.map(x => x.filename).join(", ")}`;

  // Clear selection after upload (optional but usually nicer UX)
  fileInputEl.value = "";

  return data.files || [];
}

async function sendChat(mode, message, submissionId, fileIds = []) {
  const payload = { mode, message };

  if (mode === "feedback") payload.submission_id = submissionId;

  // NEW: attachments (backend can ignore for now, but keep contract)
  payload.file_ids = fileIds;

  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Chat request failed");
  }
  return data.reply;
}

// Feedback chat
feedbackChatSendBtn?.addEventListener("click", async () => {
  feedbackChatMsg.textContent = "";
  if (feedbackChatFilesMsg) feedbackChatFilesMsg.textContent = "";

  const msg = (feedbackChatInput.value || "").trim();
  if (!msg) return;

  const sid = window.selectedSubmissionId;
  if (!sid) {
    feedbackChatMsg.textContent = "Select a submission first (from 'My submissions').";
    return;
  }

  appendChat(feedbackChatLog, "You", msg);
  feedbackChatInput.value = "";
  feedbackChatSendBtn.disabled = true;

  try {
    // upload files if any and then get file IDs
    const uploaded = await uploadFiles(feedbackChatFiles, feedbackChatFilesMsg);
    const fileIds = uploaded.map(f => f.id);

    // send chat with file IDs
    const reply = await sendChat("feedback", msg, sid, fileIds);
    appendChat(feedbackChatLog, "Copilot", reply);
  } catch (e) {
    feedbackChatMsg.textContent = e.message || "Error";
  } finally {
    feedbackChatSendBtn.disabled = false;
  }
});

// General chat
generalChatSendBtn?.addEventListener("click", async () => {
  generalChatMsg.textContent = "";
  if (generalChatFilesMsg) generalChatFilesMsg.textContent = "";

  const msg = (generalChatInput.value || "").trim();
  if (!msg) return;

  appendChat(generalChatLog, "You", msg);
  generalChatInput.value = "";
  generalChatSendBtn.disabled = true;

  try {
    // general chat uploads 
    const uploaded = await uploadFiles(generalChatFiles, generalChatFilesMsg);
    const fileIds = uploaded.map(f => f.id);

    const reply = await sendChat("general", msg, null, fileIds);
    appendChat(generalChatLog, "Copilot", reply);
  } catch (e) {
    generalChatMsg.textContent = e.message || "Error";
  } finally {
    generalChatSendBtn.disabled = false;
  }
});
