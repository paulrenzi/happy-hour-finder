"""Find the schema.org Menu the page ships as an ESCAPED string, not a tag."""
import re, json

h = open("scratchpad/mcglynns_raw.html", encoding="utf-8", errors="replace").read()

BS = chr(92)   # backslash, spelled out so no layer can eat it
Q = '"'

for m in re.finditer(re.escape(BS + Q + '@type' + BS + Q + ':' + BS + Q + 'Menu' + BS + Q), h):
    i = m.start()
    j = i
    while j > 0:
        if h[j] == Q and h[j - 1] != BS:
            break
        j -= 1
    k = i
    while k < len(h):
        if h[k] == Q and h[k - 1] != BS:
            break
        k += 1
    lit = h[j:k + 1]
    print("literal bytes:", len(lit), "| starts:", lit[:60])
    try:
        doc = json.loads(json.loads(lit))
    except Exception as e:
        print("  parse failed:", e)
        continue
    print("  PARSED. @type:", doc.get("@type"),
          "sections:", len(doc.get("hasMenuSection") or []))
    for s in doc.get("hasMenuSection") or []:
        print("   section:", repr(s.get("name")),
              "| desc:", repr((s.get("description") or "")[:70]),
              "|", len(s.get("hasMenuItem") or []), "items")
        for it in (s.get("hasMenuItem") or []):
            off = it.get("offers") or {}
            if isinstance(off, list):
                off = off[0] if off else {}
            print("        -", it.get("name"), "$" + str(off.get("price")))
    print("===")
