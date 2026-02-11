async function loadMe() {
  const who = document.getElementById("who");
  try {
    const res = await fetch("/auth/me");
    if (!res.ok) {
      console.warn("Not logged in:", res.status);
      return null;
    }
    const data = await res.json();
    if (who) {
      who.textContent = `Logged in as: ${data.email} (${data.role})`;
      who.classList.add("text-muted");
    }
    return data;
  } catch (e) {
    console.warn("loadMe error:", e);
    return null;
  }
}

async function logout(e) {
  if (e) e.preventDefault();
  await fetch("/auth/logout", { method: "POST" });
  window.location.href = "/login";
}

const logoutBtn = document.getElementById("logoutBtn");
if (logoutBtn) logoutBtn.addEventListener("click", logout);

loadMe();
