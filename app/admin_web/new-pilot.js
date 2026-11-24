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


  let pendingInvitationUrl = "";
  let pendingInvitationPhone = "";
  let pendingMerchantName = "";

  const shareActions = document.getElementById(
    "invitation-share-actions"
  );
  const shareMessage = document.getElementById(
    "invitation-share-message"
  );
  const whatsappButton = document.getElementById(
    "send-invitation-whatsapp"
  );
  const copyButton = document.getElementById(
    "copy-invitation-link"
  );

  function prepareInvitationShare(data, payload) {
    const token = data?.activation?.token;

    if (typeof token !== "string" || token.length < 20) {
      shareActions.hidden = true;
      shareMessage.textContent =
        "Invitation créée, mais lien indisponible. " +
        "Utilisez la réinvitation depuis la fiche pilote.";
      return;
    }

    const phone = String(payload.whatsapp_number || "")
      .replace(/[^0-9]/g, "");

    if (phone.length < 8 || phone.length > 15) {
      shareActions.hidden = true;
      shareMessage.textContent =
        "Numéro international invalide pour WhatsApp.";
      return;
    }

    pendingInvitationUrl =
      `${window.location.origin}/auth/activation` +
      `#token=${encodeURIComponent(token)}`;

    pendingInvitationPhone = phone;
    pendingMerchantName = String(
      data?.pilot?.merchant_name || payload.merchant_name || "votre commerce"
    );

    shareActions.hidden = false;
    shareMessage.textContent =
      "Invitation prête. Aucun message WhatsApp n'a encore été envoyé.";
  }

  whatsappButton?.addEventListener("click", () => {
    if (!pendingInvitationUrl || !pendingInvitationPhone) return;

    const message =
      `Bonjour, bienvenue sur Whatzabi !\\n\\n` +
      `Votre espace ${pendingMerchantName} est prêt.\\n` +
      `Activez votre compte avec ce lien personnel :\\n` +
      `${pendingInvitationUrl}\\n\\n` +
      `Ce lien est confidentiel et à usage unique.`;

    const url =
      `https://wa.me/${pendingInvitationPhone}` +
      `?text=${encodeURIComponent(message)}`;

    window.open(url, "_blank", "noopener,noreferrer");

    shareMessage.textContent =
      "WhatsApp ouvert. Appuyez sur Envoyer pour transmettre l'invitation.";
  });

  copyButton?.addEventListener("click", async () => {
    if (!pendingInvitationUrl) return;

    try {
      await navigator.clipboard.writeText(pendingInvitationUrl);
      shareMessage.textContent = "Lien copié. À transmettre au commerçant.";
    } catch {
      shareMessage.textContent =
        "Copie impossible. Utilisez le bouton WhatsApp.";
    }
  });

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

      prepareInvitationShare(data, payload);

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
