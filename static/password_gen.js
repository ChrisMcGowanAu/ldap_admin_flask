// static/password_gen.js
// Reusable password generator wiring for any page.
//
// Usage patterns supported:
//  A) <button data-pwgen-url="/api/generate_password" data-pwgen-target="#password">
//  B) Or pass a config object: window.initPasswordGen({ url: "...", button: "...", target: "..." })

(function () {
  async function postJSON(url, data) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}),
    });
    if (!res.ok) throw new Error("Request failed: " + res.status);
    return await res.json();
  }

  async function handleGenerateClick(btn) {
    const url = btn.dataset.pwgenUrl;
    const targetSel = btn.dataset.pwgenTarget;

    if (!url || !targetSel) {
      console.warn("Password gen button missing data-pwgen-url or data-pwgen-target");
      return;
    }

    const target = document.querySelector(targetSel);
    if (!target) {
      console.warn("Password gen target not found:", targetSel);
      return;
    }

    btn.disabled = true;
    const oldText = btn.textContent;
    btn.textContent = "Generating...";

    try {
      const kind = btn.dataset.pwgenKind || btn.dataset.pwgenType || "kid";
      const data = await postJSON(url, {kind: kind});
      if (data && data.password) {
        target.value = data.password;
        target.focus();
        target.select();
      } else {
        alert("Password generator did not return a password.");
      }
    } catch (e) {
      console.error(e);
      alert("Failed to generate password.");
    } finally {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }

  function wireAllPasswordGenButtons() {
    const buttons = document.querySelectorAll("[data-pwgen-url][data-pwgen-target]");
    buttons.forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        handleGenerateClick(btn);
      });
    });
  }

  // Auto-wire on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireAllPasswordGenButtons);
  } else {
    wireAllPasswordGenButtons();
  }

  // Optional manual init
  window.initPasswordGen = function ({ url, button, target }) {
    const btn = document.querySelector(button);
    if (!btn) return;
    btn.dataset.pwgenUrl = url;
    btn.dataset.pwgenTarget = target;
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      handleGenerateClick(btn);
    });
  };
})();

