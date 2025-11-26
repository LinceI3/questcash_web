// static/js/animations.js
document.addEventListener("DOMContentLoaded", () => {
  if (!window.gsap) return;

  // ------------ ANIMACIÓN DE ENTRADA GENERAL ------------
  const mainEl = document.querySelector("main, .page-fade, .container.page-fade");
  if (mainEl) {
    // Estado inicial seguro
    gsap.set(mainEl, { opacity: 0, y: 20 });

    // Animación de entrada: siempre termina en opacity: 1
    gsap.to(mainEl, {
      opacity: 1,
      y: 0,
      duration: 0.45,
      ease: "power2.out",
      clearProps: "opacity,transform",
    });

    // Salvavidas extra por si alguna animación falla:
    setTimeout(() => {
      mainEl.style.opacity = "1";
      mainEl.style.transform = "none";
    }, 900);
  }

  // ------------ TARJETAS PRINCIPALES (qc-card) ------------
  const cards = gsap.utils.toArray(".qc-card");
  if (cards.length) {
    // Estado inicial controlado por GSAP
    gsap.set(cards, { opacity: 0, y: 18 });

    // Animación hacia un estado final completamente visible
    gsap.to(cards, {
      opacity: 1,
      y: 0,
      duration: 0.5,
      stagger: 0.05,
      ease: "back.out(1.4)",
      clearProps: "opacity,transform",
    });
  }

  // ------------ QUEST CARDS ------------
  const questCards = gsap.utils.toArray(".quest-card");
  if (questCards.length) {
    gsap.from(questCards, {
      opacity: 0,
      y: 16,
      duration: 0.5,
      stagger: 0.06,
      ease: "back.out(1.6)",
      clearProps: "opacity,transform",
    });
  }

  // ------------ PILLS (resúmenes, stats, IA) ------------
  const pills = gsap.utils.toArray(".qc-pill");
  if (pills.length) {
    gsap.from(pills, {
      opacity: 0,
      y: 10,
      duration: 0.4,
      stagger: 0.04,
      ease: "back.out(1.6)",
      clearProps: "opacity,transform",
    });
  }

  // ------------ MOVIMIENTOS (listas) ------------
  const movements = gsap.utils.toArray(".movement-item");
  if (movements.length) {
    gsap.from(movements, {
      opacity: 0,
      x: -16,
      duration: 0.35,
      stagger: 0.03,
      ease: "power2.out",
      clearProps: "opacity,transform",
    });
  }

  // ------------ NOTIFICACIONES ------------
  const notifs = gsap.utils.toArray(".notif-item");
  if (notifs.length) {
    gsap.from(notifs, {
      opacity: 0,
      x: 16,
      duration: 0.35,
      stagger: 0.03,
      ease: "power2.out",
      clearProps: "opacity,transform",
    });
  }

  // ------------ ANILLOS GRANDES (dashboard, detalle quest) ------------
  const bigRings = gsap.utils.toArray(".ring");
  if (bigRings.length) {
    gsap.from(bigRings, {
      opacity: 0,
      scale: 0.75,
      duration: 0.7,
      ease: "back.out(1.8)",
      clearProps: "opacity,transform",
    });
  }

  // ------------ ANILLOS PEQUEÑOS (lista de quests, meta próxima) ------------
  const smallRings = gsap.utils.toArray(".ring-sm");
  if (smallRings.length) {
    gsap.from(smallRings, {
      opacity: 0,
      scale: 0.8,
      duration: 0.6,
      stagger: 0.04,
      ease: "back.out(1.8)",
      clearProps: "opacity,transform",
    });
  }

  // ------------ ANIMACIÓN ESPECIAL PARA LOGIN / REGISTER ------------
  const authCard = document.querySelector(".qc-card.auth-card, .qc-card[data-auth]");
  if (authCard) {
    gsap.from(authCard, {
      opacity: 0,
      y: 24,
      scale: 0.98,
      duration: 0.55,
      ease: "back.out(1.7)",
      clearProps: "opacity,transform",
    });
  }

  // ------------ VANILLATILT (2.5D EN TARJETAS / INSIGNIAS) ------------
  if (window.VanillaTilt) {
    const tiltElements = document.querySelectorAll(
      ".qc-card:not(.auth-card), .quest-card, .qc-badge-image"
    );
    if (tiltElements.length) {
      VanillaTilt.init(tiltElements, {
        max: 8,
        speed: 400,
        glare: true,
        "max-glare": 0.15,
        scale: 1.0,
      });
    }
  }
});