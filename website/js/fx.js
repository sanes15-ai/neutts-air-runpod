/* Pointer effects: custom cursor, magnetic elements, card tilt, hover video.
   Fine-pointer desktops only; everything no-ops on touch or reduced motion. */
(function () {
  "use strict";

  window.initFX = function initFX() {
    const finePointer = window.matchMedia("(pointer: fine)").matches;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* Hover-play service videos (works for touch too via visibility) */
    document.querySelectorAll("[data-card]").forEach((card) => {
      const video = card.querySelector(".card__video");
      if (!video) return;
      card.addEventListener("mouseenter", () => {
        video.play().catch(() => {});
      });
      card.addEventListener("mouseleave", () => {
        video.pause();
        video.currentTime = 0;
      });
    });

    if (!finePointer || reduced) return;
    document.documentElement.classList.add("has-cursor");

    /* Custom cursor: volt dot + lerped ring */
    const dot = document.getElementById("cursorDot");
    const ring = document.getElementById("cursorRing");
    const label = document.getElementById("cursorLabel");
    const dotX = gsap.quickTo(dot, "x", { duration: 0.08, ease: "power2.out" });
    const dotY = gsap.quickTo(dot, "y", { duration: 0.08, ease: "power2.out" });
    const ringX = gsap.quickTo(ring, "x", { duration: 0.35, ease: "power3.out" });
    const ringY = gsap.quickTo(ring, "y", { duration: 0.35, ease: "power3.out" });

    window.addEventListener("mousemove", (e) => {
      document.documentElement.classList.add("cursor-live");
      dotX(e.clientX); dotY(e.clientY);
      ringX(e.clientX); ringY(e.clientY);
    });

    document.querySelectorAll("[data-cursor]").forEach((el) => {
      el.addEventListener("mouseenter", () => {
        const mode = el.getAttribute("data-cursor");
        label.textContent = mode === "play" ? "play" : "";
        ring.classList.add("is-active");
        gsap.to(ring, {
          scale: mode === "play" ? 2.2 : 1.6,
          backgroundColor: mode === "play" ? "rgba(216,255,62,0.92)" : "rgba(216,255,62,0.12)",
          duration: 0.3,
        });
        gsap.to(dot, { scale: 0, duration: 0.2 });
      });
      el.addEventListener("mouseleave", () => {
        ring.classList.remove("is-active");
        gsap.to(ring, { scale: 1, backgroundColor: "rgba(216,255,62,0)", duration: 0.3 });
        gsap.to(dot, { scale: 1, duration: 0.2 });
      });
    });

    /* Magnetic pull */
    document.querySelectorAll("[data-magnetic]").forEach((el) => {
      const strength = el.classList.contains("btn--xl") ? 0.35 : 0.25;
      const xTo = gsap.quickTo(el, "x", { duration: 0.4, ease: "elastic.out(1,0.4)" });
      const yTo = gsap.quickTo(el, "y", { duration: 0.4, ease: "elastic.out(1,0.4)" });
      el.addEventListener("mousemove", (e) => {
        const r = el.getBoundingClientRect();
        xTo((e.clientX - r.left - r.width / 2) * strength);
        yTo((e.clientY - r.top - r.height / 2) * strength);
      });
      el.addEventListener("mouseleave", () => { xTo(0); yTo(0); });
    });

    /* Card tilt (≤4deg) */
    document.querySelectorAll("[data-card]").forEach((card) => {
      const rx = gsap.quickTo(card, "rotationX", { duration: 0.5, ease: "power2.out" });
      const ry = gsap.quickTo(card, "rotationY", { duration: 0.5, ease: "power2.out" });
      gsap.set(card, { transformPerspective: 900 });
      card.addEventListener("mousemove", (e) => {
        const r = card.getBoundingClientRect();
        ry(((e.clientX - r.left) / r.width - 0.5) * 8);
        rx(-((e.clientY - r.top) / r.height - 0.5) * 8);
      });
      card.addEventListener("mouseleave", () => { rx(0); ry(0); });
    });
  };
})();
