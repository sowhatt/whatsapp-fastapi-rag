(() => {
  "use strict";

  const Admin = window.WhatzabiAdmin;

  if (!Admin) {
    console.error("WhatzabiAdmin indisponible");
    return;
  }

  let pilots = [];

  function text(value, fallback = "—") {
    if (value === null || value === undefined || value === "") {
      return fallback;
    }

    return String(value);
  }

  function formatDate(value) {
    if (!value) {
      return "—";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return "—";
    }

    return new Intl.DateTimeFormat("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(date);
  }

  function getPilotStatus(pilot) {
    const statuses = {
      active: {
        label: "Actif",
        className: "status-active",
      },
      pending_activation: {
        label: "En attente",
        className: "status-pending",
      },
      suspended: {
        label: "Suspendu",
        className: "status-suspended",
      },
      expired: {
        label: "Expiré",
        className: "status-neutral",
      },
    };

    return (
      statuses[pilot.onboarding_status] || {
        label: "Inconnu",
        className: "status-neutral",
      }
    );
  }

  function pilotMerchantName(pilot) {
    return (
      pilot.owner?.full_name ||
      pilot.owner_name ||
      pilot.shop_name ||
      `Pilote #${pilot.merchant_id || pilot.id || "?"}`
    );
  }

  function pilotShopName(pilot) {
    return (
      pilot.shop?.name ||
      pilot.active_shop_name ||
      pilot.shop_name ||
      "—"
    );
  }

  function pilotPhone(pilot) {
    return (
      pilot.whatsapp_number ||
      pilot.phone ||
      pilot.owner?.phone ||
      "—"
    );
  }

  function renderSummary(summary) {
    document.getElementById("metric-total").textContent =
      text(summary.total, "0");

    document.getElementById("metric-active").textContent =
      text(summary.active, "0");

    document.getElementById("metric-pending").textContent =
      text(summary.pending_activation, "0");

    document.getElementById("metric-suspended").textContent =
      text(summary.suspended, "0");

    document.getElementById("metric-expiring").textContent =
      text(summary.expiring_soon, "0");
  }

  function renderAdmin(admin) {
    document.getElementById("admin-name").textContent =
      text(admin.full_name, "Super Admin");

    document.getElementById("admin-email").textContent =
      text(admin.email, "");
  }

  function renderPilots(items) {
    const body = document.getElementById("pilots-table-body");
    const count = document.getElementById("pilots-count");

    body.replaceChildren();

    count.textContent =
      `${items.length} pilote${items.length > 1 ? "s" : ""}`;

    if (!items.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");

      cell.colSpan = 7;
      cell.className = "table-empty";
      cell.textContent = "Aucun pilote trouvé.";

      row.appendChild(cell);
      body.appendChild(row);

      return;
    }

    for (const pilot of items) {
      const row = document.createElement("tr");
      const status = getPilotStatus(pilot);

      const values = [
        pilotMerchantName(pilot),
        pilotShopName(pilot),
        pilotPhone(pilot),
        text(pilot.country_code),
      ];

      for (const value of values) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      }

      const statusCell = document.createElement("td");
      const badge = document.createElement("span");

      badge.className = `status-badge ${status.className}`;
      badge.textContent = status.label;

      statusCell.appendChild(badge);
      row.appendChild(statusCell);

      const endCell = document.createElement("td");

      endCell.textContent =
        formatDate(pilot.subscription_ends_at);

      row.appendChild(endCell);

      const actionCell = document.createElement("td");
      const action = document.createElement("button");

      action.type = "button";
      action.className = "table-action";
      action.textContent = "Voir";

      const merchantId =
        pilot.merchant_id ||
        pilot.id;

      action.addEventListener("click", () => {
        if (!merchantId) {
          return;
        }

        window.location.href =
          `/admin/pilots/${encodeURIComponent(merchantId)}`;
      });

      actionCell.appendChild(action);
      row.appendChild(actionCell);

      body.appendChild(row);
    }
  }

  function normalizePilotResponse(data) {
    if (Array.isArray(data)) {
      return data;
    }

    if (Array.isArray(data.items)) {
      return data.items;
    }

    if (Array.isArray(data.pilots)) {
      return data.pilots;
    }

    return [];
  }

  function showError(message) {
    const box = document.getElementById("dashboard-error");

    box.textContent = message;
    box.hidden = false;
  }

  function filterPilots(query) {
    const normalized = query
      .trim()
      .toLocaleLowerCase("fr");

    if (!normalized) {
      renderPilots(pilots);
      return;
    }

    const filtered = pilots.filter((pilot) => {
      const searchable = [
        pilotMerchantName(pilot),
        pilotShopName(pilot),
        pilotPhone(pilot),
        pilot.country_code,
        pilot.subscription_status,
      ]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase("fr");

      return searchable.includes(normalized);
    });

    renderPilots(filtered);
  }

  async function loadDashboard() {
    if (!Admin.getToken()) {
      window.location.href = "/admin/login";
      return;
    }

    try {
      const [meResponse, summaryResponse, pilotsResponse] =
        await Promise.all([
          Admin.adminFetch("/admin/auth/me"),
          Admin.adminFetch("/admin/pilots/summary"),
          Admin.adminFetch("/admin/pilots"),
        ]);

      if (
        !meResponse.ok ||
        !summaryResponse.ok ||
        !pilotsResponse.ok
      ) {
        throw new Error(
          "Impossible de charger le tableau de bord."
        );
      }

      const [admin, summary, pilotsData] =
        await Promise.all([
          meResponse.json(),
          summaryResponse.json(),
          pilotsResponse.json(),
        ]);

      renderAdmin(admin);
      renderSummary(summary);

      pilots = normalizePilotResponse(pilotsData);

      renderPilots(pilots);
    } catch (error) {
      showError(
        error instanceof Error
          ? error.message
          : "Erreur de chargement du tableau de bord."
      );
    }
  }

  document
    .getElementById("pilot-search-input")
    ?.addEventListener("input", (event) => {
      filterPilots(event.target.value);
    });

  document
    .getElementById("logout-button")
    ?.addEventListener("click", () => {
      Admin.clearToken();
      window.location.href = "/admin/login";
    });

  document
    .getElementById("create-pilot-button")
    ?.addEventListener("click", () => {
      window.location.href = "/admin/pilots/new";
    });

  loadDashboard();
})();
