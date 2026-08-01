/* VANTA//APEX — boot, load choreography, and every scroll trigger. */
(function () {
  "use strict";

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isMobile = window.matchMedia("(max-width: 768px)").matches;
  const doc = document.documentElement;

  /* ---------- Reduced motion: static, native-scroll experience ---------- */
  if (reduced) {
    doc.classList.add("reduced-motion");
    document.querySelector(".process").classList.add("process--stacked");
    document.querySelectorAll(".stat__count").forEach((el) => {
      const target = +el.dataset.count;
      el.textContent = el.dataset.decimal ? (target / 10).toFixed(1) : target;
    });
    window.initFX && window.initFX(); // no-ops except hover videos
    return;
  }

  doc.classList.add("js");
  gsap.registerPlugin(ScrollTrigger, SplitText);

  /* ---------- Lenis smooth scroll bridged to ScrollTrigger ---------- */
  const lenis = new Lenis({ lerp: 0.1 });
  window.lenisScrollTo = (y) => lenis.scrollTo(y, { immediate: true });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((t) => lenis.raf(t * 1000));
  gsap.ticker.lagSmoothing(0);

  /* Anchor links scroll through Lenis */
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const target = document.querySelector(a.getAttribute("href"));
      if (!target) return;
      e.preventDefault();
      lenis.scrollTo(target, { offset: 0, duration: 1.4 });
    });
  });

  /* ---------- Preloader: real frame preload -> curtain -> hero ---------- */
  const preCount = document.getElementById("preCount");
  const preBar = document.getElementById("preBar");
  const preloader = document.getElementById("preloader");
  let shown = 0; // displayed progress, monotonic

  lenis.stop();

  const heroTl = buildHeroIntro(); // paused; plays after curtain

  const minWait = new Promise((r) => setTimeout(r, 900));
  const hardCap = new Promise((r) => setTimeout(r, 4000));
  const frames = window.FinishScrub
    ? window.FinishScrub.preload((p) => {
        shown = Math.max(shown, p);
        preCount.textContent = String(Math.round(shown * 100)).padStart(3, "0");
        preBar.style.width = shown * 100 + "%";
      })
    : Promise.resolve();

  Promise.race([Promise.all([frames, minWait]), hardCap]).then(() => {
    preCount.textContent = "100";
    preBar.style.width = "100%";
    gsap.timeline()
      .to(".preloader__inner", { opacity: 0, y: -30, duration: 0.35, ease: "power2.in" })
      .to(".preloader__curtain--volt", { y: "-101%", duration: 0.7, ease: "power4.inOut" }, "wipe")
      .to(".preloader__curtain--carbon", { y: "-101%", duration: 0.7, ease: "power4.inOut" }, "wipe+=0.08")
      .set(".preloader__curtain", { yPercent: 100, y: 0 }, "wipe-=0.35")
      .to(preloader, { autoAlpha: 0, duration: 0.4, ease: "none" }, "wipe+=0.15")
      .add(() => {
        preloader.remove();
        lenis.start();
        heroTl.play();
        ScrollTrigger.refresh();
      }, "wipe+=0.35");
  });

  function buildHeroIntro() {
    const split = new SplitText("#heroTitle .hero__line", { type: "chars" });
    gsap.set(split.chars, { yPercent: 120, rotate: 4 });
    return gsap.timeline({ paused: true })
      .fromTo(".hero__video", { scale: 1.15 }, { scale: 1, duration: 2.2, ease: "power3.out" }, 0)
      .to(split.chars, {
        yPercent: 0, rotate: 0, duration: 0.9, ease: "expo.out",
        stagger: 0.018,
      }, 0.1)
      .to("[data-hero-fade]", {
        opacity: 1, y: 0, duration: 0.7, ease: "power2.out", stagger: 0.09,
      }, 0.55)
      .fromTo(".hero__frame", { opacity: 0 }, { opacity: 1, duration: 0.8 }, 0.4);
  }

  /* Idle scroll cue bounce */
  gsap.to(".hero__cue-chev", { y: 6, repeat: -1, yoyo: true, duration: 0.7, ease: "sine.inOut" });

  /* Hero parallax-out */
  gsap.to(".hero__content", {
    yPercent: -18, opacity: 0.15, ease: "none",
    scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true },
  });
  gsap.to(".hero__shade", {
    opacity: 1.6, ease: "none",
    scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true },
  });

  /* Nav background after leaving hero */
  ScrollTrigger.create({
    start: "top -80",
    onUpdate: (self) => {
      document.getElementById("nav").classList.toggle("is-scrolled", self.scroll() > 80);
    },
  });

  /* ---------- Velocity-reactive marquee ---------- */
  [["#marqueeA", 1], ["#marqueeB", -1]].forEach(([sel, dir]) => {
    const track = document.querySelector(sel);
    const from = dir === 1 ? 0 : -50;
    const to = dir === 1 ? -50 : 0;
    const loop = gsap.fromTo(track, { xPercent: from }, { xPercent: to, duration: 22, ease: "none", repeat: -1 });
    const skewTo = gsap.quickTo(track, "skewX", { duration: 0.4, ease: "power2.out" });
    lenis.on("scroll", (e) => {
      loop.timeScale(gsap.utils.clamp(1, 4, 1 + Math.abs(e.velocity) * 0.06));
      skewTo(gsap.utils.clamp(-12, 12, e.velocity * 0.3) * dir);
    });
  });

  /* ---------- THE FINISH: pinned canvas scrub ---------- */
  const finishStage = document.querySelector(".finish__stage");
  const scrubEnd = isMobile ? "+=250%" : "+=400%";
  const frameProxy = { frame: 0 };
  const N = window.FinishScrub ? window.FinishScrub.frameCount : 0;

  if (N) {
    const finishTl = gsap.timeline({
      scrollTrigger: {
        trigger: ".finish",
        start: "top top",
        end: scrubEnd,
        scrub: 0.6,
        pin: true,
        anticipatePin: 1,
        onUpdate(self) {
          document.getElementById("finishRail").style.height = self.progress * 100 + "%";
          // phase color: magenta while raw, volt once sealed (footage shifts ~55%)
          finishStage.style.setProperty(
            "--phase",
            self.progress > 0.55 ? "var(--volt)" : "var(--neon)"
          );
        },
      },
    });

    finishTl.to(frameProxy, {
      frame: N - 1,
      snap: "frame",
      ease: "none",
      duration: 1,
      onUpdate: () => window.FinishScrub.draw(frameProxy.frame),
    }, 0);

    /* Overlay choreography on the same 0..1 span */
    finishTl
      .to("#wordExposed", { opacity: 0, yPercent: -40, duration: 0.18 }, 0.42)
      .fromTo("#wordArmored", { opacity: 0, yPercent: 40 }, { opacity: 0.9, yPercent: 0, duration: 0.18 }, 0.52)
      .fromTo(".finish__callout--1", { opacity: 0, x: -40 }, { opacity: 1, x: 0, duration: 0.08 }, 0.18)
      .to(".finish__callout--1", { opacity: 0, duration: 0.06 }, 0.42)
      .fromTo(".finish__callout--2", { opacity: 0, x: 40 }, { opacity: 1, x: 0, duration: 0.08 }, 0.5)
      .to(".finish__callout--2", { opacity: 0, duration: 0.06 }, 0.74)
      .fromTo(".finish__callout--3", { opacity: 0, x: -40 }, { opacity: 1, x: 0, duration: 0.08 }, 0.8)
      .to(".finish__hint", { opacity: 0, duration: 0.05 }, 0.08);

    window.FinishScrub.draw(0);
  }

  /* ---------- Services ---------- */
  const svcSplit = new SplitText("#servicesTitle", { type: "lines", mask: "lines" });
  gsap.from(svcSplit.lines, {
    yPercent: 110, duration: 0.9, ease: "expo.out", stagger: 0.08,
    scrollTrigger: { trigger: ".services__head", start: "top 75%", once: true },
  });
  gsap.utils.toArray(".card").forEach((card, i) => {
    gsap.from(card, {
      clipPath: i % 2 ? "inset(0% 0% 100% 0%)" : "inset(100% 0% 0% 0%)",
      yPercent: 6,
      duration: 1, ease: "power4.out", delay: i * 0.12,
      scrollTrigger: { trigger: ".services__grid", start: "top 78%", once: true },
    });
  });

  /* ---------- Process: horizontal pin (desktop) / stack (mobile) ---------- */
  const processSection = document.querySelector(".process");
  if (isMobile) {
    processSection.classList.add("process--stacked");
    gsap.utils.toArray(".panel").forEach((p) => {
      gsap.from(p, {
        opacity: 0, y: 40, duration: 0.8, ease: "power2.out",
        scrollTrigger: { trigger: p, start: "top 82%", once: true },
      });
    });
  } else {
    const track = document.getElementById("processTrack");
    const getDist = () => track.scrollWidth - window.innerWidth;
    const horizTl = gsap.timeline({
      scrollTrigger: {
        trigger: ".process",
        start: "top top",
        end: () => "+=" + getDist(),
        scrub: 0.8,
        pin: true,
        anticipatePin: 1,
        invalidateOnRefresh: true,
        onUpdate(self) {
          document.getElementById("telemetryBar").style.width = self.progress * 100 + "%";
        },
      },
    });
    horizTl.to(track, { x: () => -getDist(), ease: "none" });
    gsap.utils.toArray(".panel__num").forEach((num) => {
      gsap.to(num, {
        xPercent: -22, ease: "none",
        scrollTrigger: { trigger: ".process", start: "top top", end: () => "+=" + getDist(), scrub: true, containerAnimation: horizTl },
      });
    });
  }

  /* ---------- Numbers: count-ups + rule draws ---------- */
  gsap.utils.toArray("[data-stat]").forEach((stat, i) => {
    gsap.from(stat, {
      scaleX: 0, transformOrigin: "left center", duration: 0.7, ease: "power3.out", delay: i * 0.08,
      scrollTrigger: { trigger: ".numbers__grid", start: "top 80%", once: true },
    });
  });
  gsap.utils.toArray(".stat__count").forEach((el) => {
    const target = +el.dataset.count;
    const decimal = !!el.dataset.decimal;
    const proxy = { v: 0 };
    gsap.to(proxy, {
      v: target, duration: 1.6, ease: "expo.out",
      scrollTrigger: { trigger: el, start: "top 85%", once: true },
      onUpdate() {
        el.textContent = decimal
          ? (proxy.v / 10).toFixed(1)
          : Math.round(proxy.v).toLocaleString("en-US");
      },
    });
  });

  /* ---------- Showcase: window expand + parallax + quote ---------- */
  gsap.fromTo("#showcaseWindow",
    { clipPath: "inset(10% 8% round 6px)" },
    {
      clipPath: "inset(0% 0% round 0px)", ease: "none",
      scrollTrigger: { trigger: ".showcase", start: "top 85%", end: "top 15%", scrub: 0.5 },
    });
  gsap.fromTo("#showcaseVideo", { yPercent: -12 }, {
    yPercent: 12, ease: "none",
    scrollTrigger: { trigger: ".showcase", start: "top bottom", end: "bottom top", scrub: true },
  });
  const quoteSplit = new SplitText("#quoteText", { type: "words" });
  gsap.from(quoteSplit.words, {
    opacity: 0, y: 24, duration: 0.6, ease: "power2.out", stagger: 0.025,
    scrollTrigger: { trigger: ".showcase__quote", start: "top 85%", once: true },
  });

  /* ---------- CTA ---------- */
  const ctaSplit = new SplitText("#ctaTitle .cta__line", { type: "chars" });
  gsap.from(ctaSplit.chars, {
    yPercent: 120, duration: 0.8, ease: "expo.out", stagger: 0.02,
    scrollTrigger: { trigger: ".cta", start: "top 70%", once: true },
  });

  /* ---------- Footer rise ---------- */
  gsap.from(".footer__logo", {
    yPercent: 60, opacity: 0, ease: "none",
    scrollTrigger: { trigger: ".footer", start: "top 95%", end: "top 55%", scrub: 0.6 },
  });

  /* ---------- Generic reveals ---------- */
  ScrollTrigger.batch("[data-reveal]", {
    start: "top 85%",
    once: true,
    onEnter: (els) =>
      gsap.to(els, { opacity: 1, y: 0, duration: 0.8, ease: "power2.out", stagger: 0.1 }),
  });

  /* ---------- Pointer FX ---------- */
  window.initFX && window.initFX();

  /* Recalc after fonts + full load (frame images can shift layout timing) */
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => ScrollTrigger.refresh());
  }
  window.addEventListener("load", () => ScrollTrigger.refresh());
})();
