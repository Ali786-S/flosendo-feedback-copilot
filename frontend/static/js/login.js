const form = document.getElementById("loginForm");
const msg = document.getElementById("message");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  msg.textContent = "Signing in...";

  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    const res = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json();

    if (!res.ok) {
      msg.textContent = data.detail || "Login failed.";
      return;
    }

    msg.textContent = `Logged in as ${data.role}. Redirecting...`;

    // Redirect based on role 
    if (data.role === "student") window.location.href = "/student";
    else if (data.role === "teacher") window.location.href = "/teacher";
    else if (data.role === "admin") window.location.href = "/admin";
    else window.location.href = "/";
  } catch (err) {
    msg.textContent = "Error connecting to server.";
  }
});
