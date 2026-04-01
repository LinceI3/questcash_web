// static/js/animations.js
document.addEventListener("DOMContentLoaded", () => {
  if (!window.gsap) return;

  // ------------ ANIMACIÓN DE ENTRADA GENERAL ------------
  const mainEl = document.querySelector("main, .page-fade, .container.page-fade");
  if (mainEl) {
    // No tocamos opacity del contenedor principal para evitar vistas "apagadas".
    gsap.from(mainEl, {
      y: 12,
      duration: 0.32,
      ease: "power2.out",
      clearProps: "transform",
      overwrite: true,
    });

    // Salvavidas extra por si alguna animación falla.
    setTimeout(() => {
      mainEl.style.opacity = "1";
      mainEl.style.transform = "none";
      mainEl.style.filter = "none";
    }, 700);
  }

  // ------------ TARJETAS PRINCIPALES (qc-card) ------------
  const cards = gsap.utils.toArray(".qc-card");
  if (cards.length) {
    gsap.from(cards, {
      opacity: 0,
      y: 18,
      duration: 0.42,
      stagger: 0.05,
      ease: "power2.out",
      clearProps: "opacity,transform",
      overwrite: true,
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

  // ------------ SALVAVIDAS GLOBAL DE VISIBILIDAD ------------
  window.setTimeout(() => {
    const safetyTargets = document.querySelectorAll(
      "main, .page-fade, .container.page-fade, .qc-card, .quest-card, .qc-pill, .movement-item, .notif-item, .ring, .ring-sm"
    );

    safetyTargets.forEach((el) => {
      el.style.opacity = "1";
      el.style.transform = "none";
      el.style.filter = "none";
    });
  }, 1200);

  // ------------ HOVER LIFT (elevar elementos al pasar el mouse) ------------
  const canHover = window.matchMedia && window.matchMedia("(hover: hover)").matches;
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (canHover && !reduceMotion) {
    const hoverLiftElements = document.querySelectorAll(
      ".qc-card:not(.auth-card), .quest-card, .qc-user-chip, .qc-badge-image"
    );

    hoverLiftElements.forEach((el) => {
      let isAnimating = false;

      el.addEventListener("mouseenter", () => {
        if (isAnimating) return;
        isAnimating = true;

        gsap.to(el, {
          y: -6,
          scale: 1.015,
          duration: 0.22,
          ease: "power2.out",
          overwrite: true,
          onComplete: () => {
            isAnimating = false;
          },
        });
      });

      el.addEventListener("mouseleave", () => {
        gsap.to(el, {
          y: 0,
          scale: 1,
          duration: 0.22,
          ease: "power2.out",
          overwrite: true,
        });
      });
    });
  }

  // ------------ ACHIEVEMENT TOASTS + RANK UP OVERLAY ------------
  const achievementToasts = document.querySelectorAll("[data-achievement-toast]");
  achievementToasts.forEach((toast, index) => {
    const showDelay = 180 + (index * 220);
    const hideDelay = 5200 + (index * 260);

    window.setTimeout(() => {
      toast.classList.add("is-visible");
    }, showDelay);

    const closeToast = () => {
      if (!toast.isConnected) return;
      toast.classList.remove("is-visible");
      toast.classList.add("is-hiding");
      window.setTimeout(() => {
        if (toast.isConnected) toast.remove();
      }, 360);
    };

    const closeBtn = toast.querySelector("[data-achievement-close]");
    if (closeBtn) {
      closeBtn.addEventListener("click", closeToast);
    }

    window.setTimeout(closeToast, hideDelay);
  });

  const rankOverlay = document.querySelector("[data-rankup-overlay]");
  if (rankOverlay) {
    const closeRankOverlay = () => {
      if (!rankOverlay.isConnected) return;
      rankOverlay.classList.remove("is-visible");
      rankOverlay.classList.add("is-hiding");
      window.setTimeout(() => {
        if (rankOverlay.isConnected) rankOverlay.remove();
      }, 420);
    };

    window.setTimeout(() => {
      rankOverlay.classList.add("is-visible");
    }, 120);

    rankOverlay.querySelectorAll("[data-rankup-close]").forEach((el) => {
      el.addEventListener("click", closeRankOverlay);
    });

    const onKeyDown = (event) => {
      if (event.key === "Escape" && document.body.contains(rankOverlay)) {
        closeRankOverlay();
        document.removeEventListener("keydown", onKeyDown);
      }
    };

    document.addEventListener("keydown", onKeyDown);
  }
});