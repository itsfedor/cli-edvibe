"""Media helpers for book branding: background cut-out and icon generation.

Lessons baked in (see skill edvibe-materials-cli, "Book branding playbook"):

* Image models (flux) never return transparency and stubbornly place the scene
  at ~45% height — so generate the CHARACTER alone on a flat background and
  cut it out here; composite locally (HTML + Playwright), never via fal.
* A border flood-fill misses background-coloured areas ENCLOSED by the
  character (an "A" with a see-through counter, gaps between books). Those
  stay as light blobs on a dark cover, so `cut_background` also removes
  interior background-coloured blobs (>= min_blob px).
* Icons render at 64px (sections) / 40px (lessons); a 256px square PNG is
  plenty. Numbers must stay readable: light gradient ends need contrast >= 3:1
  against white — keep both gradient stops reasonably dark (see DEFAULT_PALETTE).
"""
from collections import deque


def _pil():
    """Lazy PIL import: the CLI must work without Pillow for non-media commands."""
    from PIL import Image, ImageFilter
    return Image, ImageFilter

# 12 distinct, sufficiently dark gradients (verified white-digit contrast)
DEFAULT_PALETTE = [
    ("#D6434F", "#D85C38"),  # coral
    ("#8E2DE2", "#4A00E0"),  # violet
    ("#008FCC", "#0047B3"),  # blue
    ("#C2570B", "#A34A06"),  # amber
    ("#0B7A56", "#1E9E63"),  # green
    ("#EC008C", "#D9486A"),  # magenta
    ("#0090B8", "#006B90"),  # cyan
    ("#E63A22", "#C01E60"),  # red-rose
    ("#5F2C82", "#3D8C8A"),  # violet-teal
    ("#E64A6B", "#5A70E8"),  # rose-blue
    ("#2E7D1F", "#46911C"),  # green
    ("#4568DC", "#9A549D"),  # blue-purple
]

EMOJI = {
    "alarm-clock": "23f0", "mantelpiece-clock": "1f570-fe0f", "rocket": "1f680",
    "vertical-traffic-light": "1f6a6", "person-running": "1f3c3", "brick": "1f9f1",
    "round-pushpin": "1f4cd", "artist-palette": "1f3fa", "link": "1f517",
    "compass": "1f9ed", "question-mark": "2753", "puzzle-piece": "1f9e9",
}


def _neighbours(x, y):
    return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))


def cut_background(src, dst, tol=40, clean_holes=True, min_blob=20, feather=0.8):
    """Cut a flat-colour background off src -> RGBA dst.

    tol: L1 colour distance from the corner sample treated as background.
    clean_holes: also erase interior (enclosed) background-coloured blobs.
    Returns dict with stats (removed %, holes cleaned).
    """
    Image, ImageFilter = _pil()
    im = Image.open(src).convert("RGB")
    w, h = im.size
    px = im.load()
    bg = px[3, 3]

    def is_bg(p):
        return abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2]) <= tol

    seen = [[False] * h for _ in range(w)]
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            if is_bg(px[x, y]) and not seen[x][y]:
                seen[x][y] = True
                dq.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if is_bg(px[x, y]) and not seen[x][y]:
                seen[x][y] = True
                dq.append((x, y))
    while dq:
        x, y = dq.popleft()
        for nx, ny in _neighbours(x, y):
            if 0 <= nx < w and 0 <= ny < h and not seen[nx][ny] and is_bg(px[nx, ny]):
                seen[nx][ny] = True
                dq.append((nx, ny))

    holes = []
    if clean_holes:
        for y in range(h):
            for x in range(w):
                if seen[x][y] or not is_bg(px[x, y]):
                    continue
                blob, dq2 = [], deque([(x, y)])
                seen[x][y] = True
                while dq2:
                    cx, cy = dq2.popleft()
                    blob.append((cx, cy))
                    for nx, ny in _neighbours(cx, cy):
                        if 0 <= nx < w and 0 <= ny < h and not seen[nx][ny] and is_bg(px[nx, ny]):
                            seen[nx][ny] = True
                            dq2.append((nx, ny))
                if len(blob) >= min_blob:
                    holes.append(len(blob))

    alpha = Image.new("L", (w, h), 255)
    ap = alpha.load()
    n_bg = 0
    for y in range(h):
        for x in range(w):
            if seen[x][y]:
                ap[x, y] = 0
                n_bg += 1
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(feather))
    out = im.convert("RGBA")
    out.putalpha(alpha)
    bbox = alpha.getbbox()
    if bbox:
        m = 6
        out = out.crop((max(0, bbox[0] - m), max(0, bbox[1] - m),
                        min(w, bbox[2] + m), min(h, bbox[3] + m)))
    out.save(dst)
    return {"bg": bg, "size": out.size,
            "removed_pct": round(n_bg * 100 / (w * h), 1),
            "holes_cleaned": holes}


def prepare_emoji(src, dst, canvas=160, glyph=150):
    """Trim transparent padding and fit the glyph into a uniform canvas so
    all emoji render at the same optical size (160px canvas = 80px CSS @2x)."""
    Image, _ = _pil()
    im = Image.open(src).convert("RGBA")
    bbox = im.split()[3].getbbox()
    if bbox:
        im = im.crop(bbox)
    w, h = im.size
    scale = glyph / max(w, h)
    im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.paste(im, ((canvas - im.width) // 2, (canvas - im.height) // 2), im)
    out.save(dst)
    return dst


def generate_icons(spec, outdir):
    """Render a grid of section/lesson icons: gradient + Apple-emoji or number.

    spec: {"cell": 128, "cols": 6, "items": [
        {"kind": "section", "id": 123, "gradient": ["#a", "#b"], "emoji": "path.png"},
        {"kind": "lesson",  "id": 456, "gradient": ["#a", "#b"], "number": 1}]}
    Writes sect_<id>.png / les_<id>.png (2x, 256px) + manifest.json into outdir.
    Returns the manifest list. Requires playwright (lazy import).
    """
    import json
    import os
    Image, _ = _pil()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("generate_icons needs playwright: "
                           "uv run --with playwright python ...") from exc

    os.makedirs(outdir, exist_ok=True)
    cell = spec.get("cell", 128)
    cols = spec.get("cols", 6)
    items = spec["items"]
    cells, manifest = [], []
    for it in items:
        c1, c2 = it["gradient"]
        grad = f"linear-gradient(135deg,{c1},{c2})"
        if it["kind"] == "section":
            if it.get("label"):
                cells.append(f'<div class="cell" style="background:{grad}">'
                             f'<span class="num label" data-fit>{it["label"]}</span></div>')
            else:
                cells.append(f'<div class="cell" style="background:{grad}">'
                             f'<img src="{it["emoji"]}" class="emoji"></div>')
            fname = f'sect_{it["id"]}.png'
        else:
            if it.get("emoji"):
                cells.append(f'<div class="cell" style="background:{grad}">'
                             f'<img src="{it["emoji"]}" class="emoji"></div>')
            else:
                cells.append(f'<div class="cell" style="background:{grad}">'
                             f'<span class="num">{it["number"]}</span></div>')
            fname = f'les_{it["id"]}.png'
        manifest.append({"kind": it["kind"], "id": it["id"], "file": fname,
                         "index": len(cells) - 1})
    rows = (len(cells) + cols - 1) // cols
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jost:wght@600;700;800&display=swap">
<style>* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{cols * cell}px; font-family:'Jost',sans-serif; }}
.grid {{ display:grid; grid-template-columns:repeat({cols},{cell}px); }}
.cell {{ width:{cell}px; height:{cell}px; display:flex; align-items:center;
        justify-content:center; overflow:hidden; position:relative; }}
.cell::after {{ content:''; position:absolute; inset:0;
        background:radial-gradient(closest-side at 50% 52%, rgba(0,0,0,.15), rgba(0,0,0,0) 78%); }}
.emoji {{ width:80px; height:80px; position:relative; z-index:1; }}
.num {{ font-weight:700; font-size:88px; color:#fff; line-height:1; position:relative; z-index:1;
        text-shadow:0 3px 12px rgba(0,0,0,.5), 0 0 3px rgba(0,0,0,.35); }}
.label {{ letter-spacing:-0.03em; }}
</style></head><body><div class="grid">{''.join(cells)}</div></body></html>"""
    page = os.path.join(outdir, "_icons.html")
    open(page, "w").write(html)
    grid_png = os.path.join(outdir, "_icons_grid.png")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(viewport={"width": cols * cell, "height": rows * cell},
                           device_scale_factor=2).new_page()
        pg.goto("file://" + os.path.abspath(page))
        pg.wait_for_timeout(2000)
        try:  # auto-fit text labels (e.g. level tiles "B1+") into the cell width;
            # all labels share the SMALLEST fitted size so they read as one row
            pg.evaluate("""(() => {
                const labels = [...document.querySelectorAll('span[data-fit]')];
                const sizes = labels.map(el => {
                    const cellW = el.parentElement.clientWidth;
                    let fs = 92;
                    el.style.fontSize = fs + 'px';
                    while (el.getBoundingClientRect().width > cellW - 12 && fs > 20) {
                        fs -= 2; el.style.fontSize = fs + 'px';
                    }
                    return fs;
                });
                if (labels.length > 1) {
                    const min = Math.min(...sizes);
                    labels.forEach(el => { el.style.fontSize = min + 'px'; });
                }
                labels.forEach(el => { el.dataset.fitSize = getComputedStyle(el).fontSize; });
            })()""")
        except Exception:  # noqa: BLE001
            pass
        pg.screenshot(path=grid_png, timeout=120000)
        b.close()
    grid = Image.open(grid_png).convert("RGB")
    s = cell * 2
    for m in manifest:
        r, c = divmod(m["index"], cols)
        grid.crop((c * s, r * s, (c + 1) * s, (r + 1) * s)).save(os.path.join(outdir, m["file"]))
    json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"), indent=1)
    return manifest
