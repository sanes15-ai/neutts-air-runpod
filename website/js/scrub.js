/* THE FINISH — canvas frame-sequence scrub engine.
   Exposes window.FinishScrub: preload(onProgress) -> Promise, draw(frameIndex),
   frameCount. Frames are drawn cover-fit at device pixel ratio. */
(function () {
  "use strict";

  const FRAME_COUNT = 200;
  const framePath = (i) =>
    `assets/frames/peel/finish_${String(i + 1).padStart(4, "0")}.jpg`;

  const canvas = document.getElementById("finishCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const images = new Array(FRAME_COUNT);
  let loaded = 0;
  let currentFrame = 0;

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(canvas.clientWidth * dpr);
    canvas.height = Math.round(canvas.clientHeight * dpr);
    draw(currentFrame);
  }

  function draw(index) {
    currentFrame = Math.max(0, Math.min(FRAME_COUNT - 1, Math.round(index)));
    const img = images[currentFrame] || images.find(Boolean);
    if (!img || !img.complete || !canvas.width) return;
    // cover-fit
    const cw = canvas.width, ch = canvas.height;
    const scale = Math.max(cw / img.naturalWidth, ch / img.naturalHeight);
    const w = img.naturalWidth * scale, h = img.naturalHeight * scale;
    ctx.drawImage(img, (cw - w) / 2, (ch - h) / 2, w, h);
  }

  function preload(onProgress) {
    return new Promise((resolve) => {
      let settled = 0;
      for (let i = 0; i < FRAME_COUNT; i++) {
        const img = new Image();
        img.decoding = "async";
        img.src = framePath(i);
        const done = () => {
          settled++;
          if (img.complete && img.naturalWidth) loaded++;
          if (onProgress) onProgress(settled / FRAME_COUNT);
          if (settled === FRAME_COUNT) {
            resize();
            resolve(loaded);
          }
        };
        img.onload = done;
        img.onerror = done;
        images[i] = img;
      }
    });
  }

  window.addEventListener("resize", resize);

  window.FinishScrub = { preload, draw, frameCount: FRAME_COUNT };
})();
