(() => {
  const token = sessionStorage.getItem("whatzabi_admin_access_token");

  if (!token) {
    window.location.replace("/admin/login");
    return;
  }

  const match = window.location.pathname.match(/^\/admin\/pilots\/(\d+)\/view\/?$/);

  if (!match) {
    window.location.replace("/admin/dashboard");
    return;
  }

  const merchantId = match[1];

  const $ = (id) => document.getElementById(id);

  let pendingReinviteUrl = "";
  let pilotPhone = "";
  let pilotName = "";

  function prepareReinviteShare(data) {
    const token = data?.activation?.token;

    if (!token || typeof token !== "string") {
      throw new Error("Jeton d'activation indisponible.");
    }

    pendingReinviteUrl =
      `${location.origin}/auth/activation#token=${encodeURIComponent(token)}`;

    $("reinvite-share").hidden = false;
    $("reinvite-share-status").textContent =
      "Invitation générée. Aucun message encore envoyé.";
  }

  $("share-reinvite-whatsapp").addEventListener("click", () => {
    if (!pendingReinviteUrl) return;

    const phone = pilotPhone.replace(/\D/g, "");

    if (!/^\d{8,15}$/.test(phone)) {
      showMessage("Numéro WhatsApp invalide.", "error");
      return;
    }

    const message = [
      "Bonjour, bienvenue sur Whatzabi !",
      "",
      `Votre espace ${pilotName} est prêt.`,
      "Activez votre compte :",
      pendingReinviteUrl,
      "",
      "Lien personnel et à usage unique."
    ].join("\n");

    window.open(
      `https://wa.me/${phone}?text=${encodeURIComponent(message)}`,
      "_blank",
      "noopener,noreferrer"
    );

    $("reinvite-share-status").textContent =
      "WhatsApp ouvert. Appuyez sur Envoyer.";
  });

  $("copy-reinvite-link").addEventListener("click", async () => {
    if (!pendingReinviteUrl) return;

    try {
      await navigator.clipboard.writeText(pendingReinviteUrl);
      $("reinvite-share-status").textContent = "Lien copié.";
    } catch {
      $("reinvite-share-status").textContent = "Copie impossible.";
    }
  });


  const statusMap = {
    active: ["Actif", "status-active"],
    pending_activation: ["En attente", "status-pending"],
    suspended: ["Suspendu", "status-suspended"],
    expired: ["Expiré", "status-neutral"],
  };

  const activationMap = {
    pending: "En attente d'activation",
    pending_activation: "En attente d'activation",
    activated: "Activé",
    expired: "Invitation expirée",
    revoked: "Invitation révoquée",
    not_invited: "Pas encore invité",
  };

  function formatDate(value) {
    if (!value) return "—";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return "—";
    }

    return new Intl.DateTimeFormat("fr-FR", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  }

  function setText(id, value) {
    const element = $(id);
    if (element) {
      element.textContent =
        value === null || value === undefined || value === ""
          ? "—"
          : String(value);
    }
  }

  function showMessage(message, type = "success") {
    const element = $("pilot-message");
    element.hidden = false;
    element.textContent = message;
    element.className = `form-message ${type}`;
  }

  function clearMessage() {
    $("pilot-message").hidden = true;
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${token}`);

    if (options.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    const response = await fetch(path, {
      ...options,
      headers,
    });

    if (response.status === 401) {
      sessionStorage.removeItem("whatzabi_admin_access_token");
      window.location.replace("/admin/login");
      throw new Error("Session administrateur expirée.");
    }

    let data = null;

    try {
      data = await response.json();
    } catch (_) {
      data = null;
    }

    if (!response.ok) {
      const detail = data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : detail?.message || "Une erreur est survenue.";

      throw new Error(message);
    }

    return data;
  }

  function renderPilot(pilot) {
    const owner = pilot.owner || {};
    const shop = pilot.shop || {};
    const activation = pilot.activation || {};

    document.title = `${pilot.merchant_name || "Pilote"} | Whatzabi Admin`;

    setText("pilot-title", pilot.merchant_name || `Pilote #${merchantId}`);
    setText(
      "pilot-subtitle",
      owner.name || `Pilote #${merchantId}`
    );

    const status =
      statusMap[pilot.onboarding_status] ||
      ["Inconnu", "status-neutral"];

    const statusContainer = $("pilot-status");
    statusContainer.textContent = status[0];
    statusContainer.className = `status-badge ${status[1]}`;

    setText("merchant-name", pilot.merchant_name);
    setText("owner-name", owner.name);
    setText("merchant-phone", pilot.whatsapp_number);
    pilotPhone = String(pilot.whatsapp_number || "");
    pilotName = String(pilot.merchant_name || "votre boutique");

    setText("country-code", pilot.country_code);
    setText("currency-code", shop.currency_code);
    setText("user-count", pilot.user_count);

    setText("subscription-status", pilot.subscription_status);
    setText("created-at", formatDate(pilot.created_at));
    setText(
      "subscription-ends-at",
      formatDate(pilot.subscription_ends_at)
    );

    setText(
      "activation-status",
      activationMap[activation.status] || activation.status || "—"
    );
    setText("invited-at", formatDate(activation.invited_at));
    setText(
      "invitation-expires-at",
      formatDate(activation.expires_at)
    );
    setText("activated-at", formatDate(activation.activated_at));

    setText("shop-name", shop.name);
    setText("shop-code", shop.code);
    setText(
      "shop-status",
      shop.active === true
        ? "Active"
        : shop.active === false
          ? "Inactive"
          : "—"
    );

    const suspended =
      pilot.onboarding_status === "suspended" ||
      pilot.subscription_status === "suspended";

    $("suspend-button").hidden = suspended;
    $("reactivate-button").hidden = !suspended;

    // Une réinvitation sert uniquement au compte qui n'est
    // pas encore activé. Un compte actif utilise le parcours
    // de gestion/réinitialisation de mot de passe.
    const canReinvite =
      owner.active !== true &&
      activation.status !== "activated";

    $("reinvite-button").hidden = !canReinvite;
  }

  async function loadPilot() {
    clearMessage();

    try {
      const pilot = await api(`/admin/pilots/${merchantId}`);
      renderPilot(pilot);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function executeAction(button, action, body, successMessage) {
    const originalText = button.textContent;

    button.disabled = true;
    button.textContent = "Traitement...";

    try {
      await api(`/admin/pilots/${merchantId}/${action}`, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });

      await loadPilot();
      showMessage(successMessage);
    } catch (error) {
      showMessage(error.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  }

  $("extend-button").addEventListener("click", async () => {
    const days = Number($("extend-days").value);

    await executeAction(
      $("extend-button"),
      "extend",
      { days },
      `Accès prolongé de ${days} jours.`
    );
  });


  $("reinvite-button").addEventListener("click", async () => {
    if (!window.confirm(
      "Générer une nouvelle invitation ? L'ancien lien sera invalidé."
    )) return;

    const button = $("reinvite-button");
    button.disabled = true;
    pendingReinviteUrl = "";
    $("reinvite-share").hidden = true;

    try {
      const data = await api(
        `/admin/pilots/${merchantId}/reinvite`,
        {
          method: "POST",
          body: JSON.stringify({ invitation_hours: 48 })
        }
      );

      prepareReinviteShare(data);
      await loadPilot();

      showMessage("Invitation générée. Prête à être envoyée.");
    } catch (error) {
      showMessage(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("suspend-button").addEventListener("click", async () => {
    const confirmed = window.confirm(
      "Suspendre l'accès de ce commerçant à Whatzabi ?"
    );

    if (!confirmed) return;

    await executeAction(
      $("suspend-button"),
      "suspend",
      null,
      "Accès du commerçant suspendu."
    );
  });

  $("reactivate-button").addEventListener("click", async () => {
    await executeAction(
      $("reactivate-button"),
      "reactivate",
      null,
      "Accès du commerçant réactivé."
    );
  });

  // Chargement initial.
  loadPilot();

  // S6.3 — suivi quasi temps réel.
  // Tant que cette fiche est ouverte, on resynchronise silencieusement
  // son état avec le backend toutes les 5 secondes.
  // Cela permet notamment de voir une activation commerçant sans F5.
  const realtimeInterval = window.setInterval(async () => {
    if (document.hidden) {
      return;
    }

    try {
      const pilot = await api(`/admin/pilots/${merchantId}`);
      renderPilot(pilot);
    } catch (error) {
      // Le polling ne doit pas polluer l'interface avec une erreur
      // transitoire. Les erreurs des actions utilisateur restent,
      // elles, affichées normalement.
      console.debug("Pilot realtime refresh skipped:", error.message);
    }
  }, 5000);

  // Nettoyage lorsque l'admin quitte la fiche.
  window.addEventListener("pagehide", () => {
    window.clearInterval(realtimeInterval);
  });
})();
