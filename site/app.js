(() => {
  const header = document.querySelector("[data-header]");
  const menuButton = document.querySelector(".menu-button");
  const nav = document.querySelector(".site-nav");
  const toast = document.querySelector(".copy-toast");
  const isEnglish = document.documentElement.lang.toLowerCase().startsWith("en");
  let toastTimer;

  const updateHeader = () => header?.classList.toggle("is-scrolled", window.scrollY > 8);
  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });

  menuButton?.addEventListener("click", () => {
    const open = menuButton.getAttribute("aria-expanded") === "true";
    menuButton.setAttribute("aria-expanded", String(!open));
    nav?.classList.toggle("is-open", !open);
  });

  nav?.addEventListener("click", (event) => {
    if (!(event.target instanceof HTMLAnchorElement)) return;
    nav.classList.remove("is-open");
    menuButton?.setAttribute("aria-expanded", "false");
  });

  const showToast = (message) => {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 2200);
  };

  const copyText = async (text) => {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw new Error("copy failed");
  };

  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copy);
      if (!target) return;
      try {
        await copyText(target.textContent);
        const original = button.textContent;
        button.textContent = isEnglish ? "Copied" : "Kopyalandı";
        showToast(isEnglish ? "Code copied to the clipboard." : "Kod panoya kopyalandı.");
        setTimeout(() => { button.textContent = original; }, 1800);
      } catch {
        showToast(isEnglish ? "Copy failed; select and copy the text." : "Kopyalama başarısız oldu; metni seçerek kopyalayın.");
      }
    });
  });
})();
