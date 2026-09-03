import { nextOccurrence } from "../web/lib.js";
import fs from "fs";
const idx = JSON.parse(fs.readFileSync("web/data/index.json","utf8"));
const zones = (idx.zones||idx).map ? (idx.zones||idx) : [];
let deals = [];
for (const z of (idx.zones||[])) {
  const f = `web/data/zone-${z.id}.json`;
  if (!fs.existsSync(f)) continue;
  for (const v of JSON.parse(fs.readFileSync(f,"utf8")).venues||[])
    for (const d of v.deals||[]) deals.push([v.name, d]);
}
const now = new Date();
const t4 = new Date(now); t4.setDate(t4.getDate()+1); t4.setHours(16,0,0,0);
const t0 = new Date(now); t0.setDate(t0.getDate()+1); t0.setHours(0,0,0,0);
let lost = 0, tomorrowAt0 = 0, tomorrowAt4 = 0;
for (const [name,d] of deals) {
  const a = nextOccurrence(d, t0, 7), b = nextOccurrence(d, t4, 7);
  if (a && a.dayAhead === 0) tomorrowAt0++;
  if (b && b.dayAhead === 0) tomorrowAt4++;
  if (a && a.dayAhead === 0 && !(b && b.dayAhead === 0)) {
    lost++;
    if (lost <= 8) console.log("  dropped by the 4pm anchor:", name, JSON.stringify(a.w));
  }
}
console.log("deals total:", deals.length);
console.log("run TOMORROW, seen with a midnight anchor:", tomorrowAt0);
console.log("run TOMORROW, seen with the 4pm anchor:  ", tomorrowAt4);
console.log("TOMORROW deals the 4pm anchor cannot show:", lost);
