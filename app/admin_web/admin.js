(() => {
  "use strict";

  const TOKEN_KEY = "whatzabi_admin_access_token";

  function getToken() {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  function saveToken(token) {
    sessionStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    sessionStorage.removeItem(TOKEN_KEY);
  }

  async function adminFetch(url, options = {}) {
    const token = getToken();

    const headers = new Headers(options.headers || {});

    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (response.status === 401) {
      clearToken();

      if (!window.location.pathname.endsWith("/admin/login")) {
        window.location.href = "/admin/login";
      }
    }

    return response;
  }

  async function handleLogin(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const button = document.getElementById("login-button");
    const errorBox = document.getElementById("login-error");

    const email = form.email.value.trim();
    const password = form.password.value;

    errorBox.hidden = true;
    errorBox.textContent = "";

    button.disabled = true;
    button.textContent = "Connexion...";

    try {
      const response = await fetch("/admin/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email,
          password,
        }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        const detail = data.detail;

        const message =
          typeof detail === "string"
            ? detail
            : detail && typeof detail.message === "string"
              ? detail.message
              : typeof data.message === "string"
                ? data.message
                : "Identifiants administrateur incorrects.";

        throw new Error(message);
      }

      const token =
        data.access_token ||
        data.token;

      if (!token) {
        throw new Error(
          "Le serveur n'a pas retourné de jeton administrateur."
        );
      }

      saveToken(token);

      window.location.href = "/admin/dashboard";
    } catch (error) {
      clearToken();

      errorBox.textContent =
        error instanceof Error
          ? error.message
          : "Impossible de se connecter.";

      errorBox.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = "Se connecter";
    }
  }

  const loginForm = document.getElementById("admin-login-form");

  if (loginForm) {
    loginForm.addEventListener("submit", handleLogin);
  }

  window.WhatzabiAdmin = {
    getToken,
    saveToken,
    clearToken,
    adminFetch,
  };
})();
