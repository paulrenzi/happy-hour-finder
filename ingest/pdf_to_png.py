"""Render a menu PDF's pages to PNG so a model can look at them.

    python ingest/pdf_to_png.py <menu.pdf> <out_dir> [zoom=2.0]

Needed because the Read tool renders a PDF with poppler's pdftoppm, which is
NOT installed on this machine -- pointing Read at a .pdf fails outright. Half
the happy hour menus worth having are image-only PDFs, so this is the step
between "we downloaded it" and "something read it".
"""
import os
import sys

import fitz

src, out = sys.argv[1], sys.argv[2]
zoom = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
os.makedirs(out, exist_ok=True)
doc = fitz.open(src)
for i, page in enumerate(doc):
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    p = os.path.join(out, "p%02d.png" % (i + 1))
    pix.save(p)
    print(p, pix.width, pix.height)
