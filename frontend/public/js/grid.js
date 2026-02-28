/**
 * Neural Grid — Cursor Reveal with Auto Fade
 * Adapted from Gaurav Gajjar (MIT License)
 *
 * Effet de grille interactive en arrière-plan.
 * Les cellules s'illuminent au passage du curseur puis s'estompent.
 */

(function () {
  const canvas = document.getElementById('grid');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  let width, height;
  let mouse = { x: -9999, y: -9999 };
  const squareSize = 80;
  let grid = [];

  function resize() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
    initGrid();
  }

  function initGrid() {
    grid = [];
    for (let x = 0; x < width; x += squareSize) {
      for (let y = 0; y < height; y += squareSize) {
        grid.push({ x, y, alpha: 0, fading: false, lastTouched: 0 });
      }
    }
  }

  function getCellAt(x, y) {
    const col = Math.floor(x / squareSize);
    const row = Math.floor(y / squareSize);
    const cols = Math.ceil(height / squareSize);
    return grid[col * cols + row] || null;
  }

  window.addEventListener('resize', resize);

  window.addEventListener('mousemove', (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;

    const cell = getCellAt(mouse.x, mouse.y);
    if (cell && cell.alpha === 0) {
      cell.alpha = 1;
      cell.lastTouched = Date.now();
      cell.fading = false;
    }
  });

  function draw() {
    ctx.clearRect(0, 0, width, height);
    const now = Date.now();

    for (let i = 0; i < grid.length; i++) {
      const cell = grid[i];

      if (cell.alpha > 0 && !cell.fading && now - cell.lastTouched > 500) {
        cell.fading = true;
      }

      if (cell.fading) {
        cell.alpha -= 0.02;
        if (cell.alpha <= 0) {
          cell.alpha = 0;
          cell.fading = false;
        }
      }

      if (cell.alpha > 0) {
        const cx = cell.x + squareSize / 2;
        const cy = cell.y + squareSize / 2;

        const gradient = ctx.createRadialGradient(cx, cy, 5, cx, cy, squareSize);
        gradient.addColorStop(0, `rgba(74, 122, 255, ${cell.alpha})`);
        gradient.addColorStop(1, 'rgba(74, 122, 255, 0)');

        ctx.strokeStyle = gradient;
        ctx.lineWidth = 1.3;
        ctx.strokeRect(cell.x + 0.5, cell.y + 0.5, squareSize - 1, squareSize - 1);
      }
    }

    requestAnimationFrame(draw);
  }

  resize();
  draw();
})();
