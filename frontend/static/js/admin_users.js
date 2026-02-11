const form = document.getElementById("createUserForm");
const msg = document.getElementById("message");
const userList = document.getElementById("userList");

async function loadUsers() {
  userList.innerHTML = "<li>Loading...</li>";
  const res = await fetch("/api/admin/users");
  if (!res.ok) {
    userList.innerHTML = "<li>Failed to load users</li>";
    return;
  }
  const data = await res.json();
  userList.innerHTML = "";
  data.users.forEach(u => {
    const li = document.createElement("li");
    li.textContent = `${u.email} (${u.role})`;
    userList.appendChild(li);
  });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  msg.textContent = "Creating user...";

  const email = document.getElementById("newEmail").value.trim();
  const role = document.getElementById("newRole").value;
  const password = document.getElementById("newPassword").value;

  const res = await fetch("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, role, password })
  });

  const data = await res.json();

  if (!res.ok) {
    msg.textContent = data.detail || "Failed to create user.";
    return;
  }

  msg.textContent = "User created successfully.";
  form.reset();
  await loadUsers();
});

loadUsers();
