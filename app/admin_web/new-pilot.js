(() => {
  "use strict";

  const Admin = window.WhatzabiAdmin;

  if (!Admin || !Admin.getToken()) {
    window.location.href = "/admin/login";
    return;
  }

  const form = document.getElementById("new-pilot-form");
  const submitButton = document.getElementById("create-pilot-submit");
  const errorBox = document.getElementById("new-pilot-error");
  const successBox = document.getElementById("new-pilot-success");
  const resultSection = document.getElementById("invitation-result");
  const createdMerchantName = document.getElementById(
    "created-merchant-name"
  );

  function hideMessages() {
    errorBox.hidden = true;
    successBox.hidden = true;
    errorBox.textContent = "";
    successBox.textContent = "";
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function extractError(data, response) {
    const detail = data?.detail;

    if (typeof detail === "string") {
      return detail;
    }

    if (detail && typeof detail.message === "string") {
      return detail.message;
    }

    if (response.status === 409) {
      return "Ce numéro WhatsApp est déjà enregistré.";
    }

    if (response.status === 422) {
      return "Vérifiez les informations saisies.";
    }

    return "Impossible de créer l'accès pilote.";
  }

  function normalizePhone(value) {
    return value.trim().replace(/[\s()-]/g, "");
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideMessages();

    const formData = new FormData(form);

    const payload = {
      merchant_name: String(
        formData.get("merchant_name") || ""
      ).trim(),

      owner_name: String(
        formData.get("owner_name") || ""
      ).trim(),

      whatsapp_number: normalizePhone(
        String(formData.get("whatsapp_number") || "")
      ),

      country_code: String(
        formData.get("country_code") || "BJ"
      ).toUpperCase(),

      currency_code: String(
        formData.get("currency_code") || "XOF"
      ).toUpperCase(),

      duration_days: Number(
        formData.get("duration_days") || 30
      ),

      invitation_hours: Number(
        formData.get("invitation_hours") || 48
      ),
    };

    submitButton.disabled = true;
    submitButton.textContent = "Création en cours…";

    try {
      const response = await Admin.adminFetch(
        "/admin/pilots/invite",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        }
      );

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(extractError(data, response));
      }

      const pilot = data.pilot || {};

      createdMerchantName.textContent =
        pilot.merchant_name || payload.merchant_name;

      successBox.textContent =
        "Accès pilote créé. Le commerçant est en attente d'activation.";
      successBox.hidden = false;

      form.hidden = true;
      resultSection.hidden = false;
    } catch (error) {
      showError(
        error instanceof Error
          ? error.message
          : "Impossible de créer l'accès pilote."
      );
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Donner accès";
    }
  });
})();
