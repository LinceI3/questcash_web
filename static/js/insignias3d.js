// static/js/insignias3d.js

document.addEventListener("DOMContentLoaded", function () {
  // Tarjetas de insignias en la sala de trofeos
  const cards = document.querySelectorAll(".trophy-card");

  // Elementos del modal definido en templates/insignias.html
  const backdrop = document.getElementById("trophyModalBackdrop");
  const modal = document.getElementById("trophyModalCard");
  const imgEl = document.getElementById("trophyModalImg");
  const titleEl = document.getElementById("trophyModalTitle");
  const rarityEl = document.getElementById("trophyModalRarity");
  const statusEl = document.getElementById("trophyModalStatus");
  const howEl = document.getElementById("trophyModalHow");
  const closeBtn = document.getElementById("trophyModalClose");

  console.log("⚙️ insignias3d.js: encontradas", cards.length, "tarjetas");

  if (!cards.length || !backdrop || !modal) {
    return;
  }

  // Helper para abrir el modal a partir de una tarjeta
  function openFromCard(card) {
    // Rellenar contenido desde los data-* de la tarjeta
    const title = card.dataset.title || "Insignia";
    const rarity = card.dataset.rarity || "";
    const status = card.dataset.status || "";
    const how = card.dataset.how || "";
    const imgSrc = card.dataset.img || "";

    titleEl.textContent = title;
    rarityEl.textContent = rarity;
    statusEl.textContent = status;
    howEl.textContent = how;

    if (imgSrc) {
      imgEl.src = imgSrc;
      imgEl.alt = title;
    }

    // Mostrar backdrop + modal con una pequeña animación
    backdrop.style.display = "flex";

    // Si GSAP está disponible, animamos; si no, sólo mostramos
    if (typeof gsap !== "undefined") {
      gsap.set(backdrop, { opacity: 0 });
      gsap.set(modal, { opacity: 0, scale: 0.85, y: 20, rotationY: -18 });

      gsap.to(backdrop, {
        opacity: 1,
        duration: 0.2,
        ease: "power2.out",
      });

      gsap.to(modal, {
        opacity: 1,
        scale: 1,
        y: 0,
        rotationY: 0,
        duration: 0.35,
        ease: "power3.out",
      });
    } else {
      backdrop.style.opacity = 1;
    }
  }

  // Helper para cerrar el modal
  function closeModal() {
    if (typeof gsap !== "undefined") {
      const tl = gsap.timeline({
        defaults: { ease: "power2.in" },
        onComplete: () => {
          backdrop.style.display = "none";
        },
      });

      tl.to(modal, {
        opacity: 0,
        scale: 0.9,
        y: 10,
        rotationY: 10,
        duration: 0.25,
      }).to(
        backdrop,
        {
          opacity: 0,
          duration: 0.2,
        },
        "-=0.15"
      );
    } else {
      backdrop.style.display = "none";
    }
  }

  // Asignar clic a cada tarjeta de insignia
  cards.forEach((card) => {
    card.style.cursor = "pointer";
    card.addEventListener("click", () => {
      console.log("🃏 click en tarjeta", card.dataset.title || "");
      openFromCard(card);
    });

    // Permitir activar con Enter/Space cuando tiene foco
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openFromCard(card);
      }
    });
  });

  // Cerrar al hacer clic en el botón de cerrar
  if (closeBtn) {
    closeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeModal();
    });
  }

  // Cerrar si se hace clic fuera de la tarjeta (en el backdrop)
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) {
      closeModal();
    }
  });

  // Cerrar con tecla Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && backdrop.style.display === "flex") {
      closeModal();
    }
  });
});