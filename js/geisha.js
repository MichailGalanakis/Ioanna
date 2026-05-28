/* geisha.js — Σχηματίζει μια γκέισα (SVG) με έκφραση ανάλογη του σκορ + σχόλιο */
(function (global) {
  "use strict";

  // Επίπεδα απόδοσης (από ψηλά προς χαμηλά). `min` = ελάχιστο ποσοστό.
  const TIERS = [
    { min: 95, key: "perfect",   jp: "完璧！",     romaji: "kanpeki!",       gr: "Τέλεια! Άψογη απόδοση!",            bg: "#f5d76e", face: "#fff7f3" },
    { min: 75, key: "joy",       jp: "すごい！",   romaji: "sugoi!",         gr: "Πολύ καλά! Μπράβο σου!",            bg: "#86efac", face: "#fff7f3" },
    { min: 50, key: "encourage", jp: "その調子！", romaji: "sono chōshi!",   gr: "Μπράβο, καλή προσπάθεια!",          bg: "#7dd3fc", face: "#fff7f3" },
    { min: 25, key: "sad",       jp: "もう少し…",  romaji: "mō sukoshi…",    gr: "Θα μπορούσες και καλύτερα.",        bg: "#a5b4fc", face: "#fdf2f8" },
    { min: 0,  key: "anger",     jp: "もっと練習！", romaji: "motto renshū!", gr: "Χρειάζεται περισσότερη εξάσκηση!",  bg: "#fca5a5", face: "#fdf2f8" },
  ];

  function tierFor(pct) {
    return TIERS.find((t) => pct >= t.min) || TIERS[TIERS.length - 1];
  }

  /* ---- βοηθητικά σχήματα ---- */
  function starPoints(cx, cy, spikes, outer, inner, rot) {
    let pts = "";
    const step = Math.PI / spikes;
    let a = (rot || -Math.PI / 2);
    for (let i = 0; i < spikes * 2; i++) {
      const r = i % 2 === 0 ? outer : inner;
      pts += (cx + Math.cos(a) * r).toFixed(1) + "," + (cy + Math.sin(a) * r).toFixed(1) + " ";
      a += step;
    }
    return pts.trim();
  }
  const sparkle = (cx, cy, r, fill) =>
    `<polygon points="${starPoints(cx, cy, 4, r, r * 0.32, -Math.PI / 2)}" fill="${fill || "#fde68a"}"/>`;
  const star5 = (cx, cy, r, fill) =>
    `<polygon points="${starPoints(cx, cy, 5, r, r * 0.45, -Math.PI / 2)}" fill="${fill || "#fbbf24"}"/>`;

  /* ---- μάτια / φρύδια / στόμα ανά έκφραση ---- */
  function eyes(key) {
    const L = 78, R = 122, y = 116;
    const almond = (cx, look) =>
      `<ellipse cx="${cx}" cy="${y}" rx="9" ry="11" fill="#fff"/>` +
      `<ellipse cx="${cx}" cy="${y + (look || 0)}" rx="6" ry="8" fill="#3b2f2f"/>` +
      `<circle cx="${cx + 2}" cy="${y - 3 + (look || 0)}" r="2.2" fill="#fff"/>` +
      `<path d="M${cx - 10},${y - 4} Q${cx},${y - 13} ${cx + 10},${y - 4}" stroke="#b91c1c" stroke-width="1.6" fill="none" stroke-linecap="round"/>`;
    const happy = (cx) =>
      `<path d="M${cx - 10},${y + 3} Q${cx},${y - 9} ${cx + 10},${y + 3}" stroke="#3b2f2f" stroke-width="3.4" fill="none" stroke-linecap="round"/>`;
    const narrow = (cx) =>
      `<path d="M${cx - 9},${y - 1} Q${cx},${y + 4} ${cx + 9},${y - 1}" stroke="#3b2f2f" stroke-width="3.6" fill="none" stroke-linecap="round"/>`;
    switch (key) {
      case "perfect": return star5(L, y, 11, "#fbbf24") + star5(R, y, 11, "#fbbf24");
      case "joy":     return happy(L) + happy(R);
      case "encourage": return almond(L, 0) + almond(R, 0);
      case "sad":     return almond(L, 3) + almond(R, 3) +
        `<path d="M${L - 5},${y + 9} q-3,10 2,14 q5,-4 2,-14 z" fill="#60a5fa"/>`; // δάκρυ
      case "anger":   return narrow(L) + narrow(R);
    }
  }

  function brows(key) {
    const L = 78, R = 122, y = 98;
    const line = (x1, yy1, x2, yy2) =>
      `<path d="M${x1},${yy1} Q${(x1 + x2) / 2},${Math.min(yy1, yy2) - 3} ${x2},${yy2}" stroke="#2a211e" stroke-width="3.4" fill="none" stroke-linecap="round"/>`;
    switch (key) {
      case "perfect":
      case "joy":     return line(L - 11, y - 4, L + 9, y - 6) + line(R - 9, y - 6, R + 11, y - 4);
      case "encourage": return line(L - 11, y, L + 9, y - 1) + line(R - 9, y - 1, R + 11, y);
      case "sad":     return line(L - 11, y + 5, L + 9, y - 2) + line(R - 9, y - 2, R + 11, y + 5); // εσωτερικά ψηλά
      case "anger":   return `<path d="M${L - 11},${y - 4} L${L + 10},${y + 6}" stroke="#2a211e" stroke-width="4" stroke-linecap="round"/>` +
                             `<path d="M${R + 11},${y - 4} L${R - 10},${y + 6}" stroke="#2a211e" stroke-width="4" stroke-linecap="round"/>`; // κατηφή προς κέντρο
    }
  }

  function mouth(key) {
    const cx = 100, y = 150;
    switch (key) {
      case "perfect": return `<path d="M${cx - 17},${y - 3} Q${cx},${y + 22} ${cx + 17},${y - 3} Z" fill="#be123c"/>` +
                             `<path d="M${cx - 13},${y - 1} Q${cx},${y + 2} ${cx + 13},${y - 1} Z" fill="#fff"/>` +
                             `<path d="M${cx - 7},${y + 8} Q${cx},${y + 15} ${cx + 7},${y + 8} Z" fill="#fb7185"/>`;
      case "joy":     return `<path d="M${cx - 13},${y - 1} Q${cx},${y + 16} ${cx + 13},${y - 1} Z" fill="#be123c"/>` +
                             `<path d="M${cx - 9},${y} Q${cx},${y + 2} ${cx + 9},${y} Z" fill="#fff"/>`;
      case "encourage": return `<path d="M${cx - 11},${y} Q${cx},${y + 9} ${cx + 11},${y}" stroke="#be123c" stroke-width="3.5" fill="none" stroke-linecap="round"/>`;
      case "sad":     return `<path d="M${cx - 9},${y + 5} Q${cx},${y - 2} ${cx + 9},${y + 5}" stroke="#be123c" stroke-width="3.2" fill="none" stroke-linecap="round"/>`;
      case "anger":   return `<path d="M${cx - 10},${y + 6} Q${cx},${y - 4} ${cx + 10},${y + 6}" stroke="#9f1239" stroke-width="3.5" fill="none" stroke-linecap="round"/>`;
    }
  }

  function extras(key) {
    switch (key) {
      case "perfect":
        return sparkle(34, 46, 9, "#fde68a") + sparkle(168, 58, 11, "#fde68a") +
               sparkle(26, 130, 8, "#fde68a") + sparkle(176, 126, 9, "#fde68a") +
               star5(150, 30, 7, "#fbbf24");
      case "joy":
        return sparkle(40, 60, 8, "#fef08a") + sparkle(162, 70, 9, "#fef08a");
      case "sad":
        return `<path d="M150,96 q-3,10 2,14 q5,-4 2,-14 z" fill="#93c5fd"/>`; // ιδρώτας/σταγόνα
      case "anger": {
        // σύμβολο θυμού 💢 πάνω δεξιά
        const cx = 156, cy = 44, r = 13, c = "#dc2626";
        let p = "";
        for (let i = 0; i < 4; i++) {
          const a = (i * Math.PI) / 2;
          const x = cx + Math.cos(a) * r, yv = cy + Math.sin(a) * r;
          p += `<path d="M${cx + Math.cos(a) * 4},${cy + Math.sin(a) * 4} Q${x},${yv} ${cx + Math.cos(a + 0.5) * r * 0.7},${cy + Math.sin(a + 0.5) * r * 0.7}" stroke="${c}" stroke-width="3" fill="none" stroke-linecap="round"/>`;
        }
        return p;
      }
      default:
        return "";
    }
  }

  /* ---- ξεκλειδώσιμα στολίδια (από επιτεύγματα) ---- */
  function ornaments(owned) {
    owned = owned || [];
    let s = "";
    if (owned.includes("kimono_gold")) {
      s += `<path d="M55,205 L100,182 L145,205 Z" fill="#b45309"/>` +
           `<path d="M72,206 L100,188 L128,206 Z" fill="#fcd34d"/>`;
    }
    if (owned.includes("flower")) {
      s += [0, 1, 2, 3, 4].map((i) => {
        const a = (i / 5) * Math.PI * 2 - Math.PI / 2;
        return `<circle cx="${(138 + Math.cos(a) * 8).toFixed(1)}" cy="${(40 + Math.sin(a) * 8).toFixed(1)}" r="6" fill="#c084fc"/>`;
      }).join("") + `<circle cx="138" cy="40" r="5" fill="#fde047"/>`;
    }
    if (owned.includes("crown")) {
      s += `<polygon points="${"82,16 90,4 100,12 110,4 118,16"}" fill="#fbbf24" stroke="#b45309" stroke-width="1"/>` +
           `<circle cx="100" cy="9" r="2.5" fill="#ef4444"/>`;
    }
    if (owned.includes("fan")) {
      s += `<g transform="rotate(-18 36 184)"><path d="M36,184 L14,156 A36,36 0 0,1 58,156 Z" fill="#fca5a5" stroke="#b91c1c" stroke-width="1.5"/>` +
           `<path d="M36,184 L22,168 M36,184 L36,150 M36,184 L50,168" stroke="#b91c1c" stroke-width="1"/></g>`;
    }
    if (owned.includes("umbrella")) {
      s += `<g transform="translate(160 26)"><path d="M-20,8 A20,20 0 0,1 20,8 Z" fill="#ef4444"/>` +
           `<path d="M-20,8 A20,20 0 0,1 20,8" fill="none" stroke="#fff" stroke-width="1.5"/>` +
           `<line x1="0" y1="8" x2="0" y2="34" stroke="#7c3a12" stroke-width="2"/></g>`;
    }
    if (owned.includes("lantern")) {
      s += `<g transform="translate(166 176)"><rect x="-12" y="-14" width="24" height="28" rx="11" fill="#dc2626"/>` +
           `<line x1="-12" y1="-4" x2="12" y2="-4" stroke="#7f1d1d" stroke-width="1.4"/>` +
           `<line x1="-12" y1="4" x2="12" y2="4" stroke="#7f1d1d" stroke-width="1.4"/>` +
           `<rect x="-5" y="-20" width="10" height="6" fill="#7c2d12"/></g>`;
    }
    return s;
  }

  /* ---- ολόκληρη η φιγούρα ---- */
  function svg(pct, owned) {
    const t = tierFor(pct);
    const k = t.key;
    return `
<svg viewBox="0 0 200 210" width="100%" height="100%" role="img" aria-label="Γκέισα — ${t.gr}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="bgGrad" cx="50%" cy="42%" r="65%">
      <stop offset="0%" stop-color="${t.bg}"/>
      <stop offset="100%" stop-color="${t.bg}" stop-opacity="0.25"/>
    </radialGradient>
  </defs>
  <circle cx="100" cy="100" r="98" fill="url(#bgGrad)"/>
  ${extras(k)}
  <!-- μαλλιά -->
  <ellipse cx="100" cy="98" rx="74" ry="82" fill="#241c2b"/>
  <ellipse cx="100" cy="30" rx="36" ry="25" fill="#241c2b"/>
  <ellipse cx="44" cy="74" rx="17" ry="20" fill="#241c2b"/>
  <ellipse cx="156" cy="74" rx="17" ry="20" fill="#241c2b"/>
  <!-- κανζάσι (στολίδι μαλλιών) -->
  <line x1="62" y1="32" x2="72" y2="60" stroke="#fbbf24" stroke-width="3" stroke-linecap="round"/>
  <g>
    ${[0, 1, 2, 3, 4].map((i) => {
      const a = (i / 5) * Math.PI * 2 - Math.PI / 2;
      return `<circle cx="${(62 + Math.cos(a) * 8).toFixed(1)}" cy="${(34 + Math.sin(a) * 8).toFixed(1)}" r="6" fill="#fb7185"/>`;
    }).join("")}
    <circle cx="62" cy="34" r="5" fill="#fde047"/>
  </g>
  <!-- πρόσωπο -->
  <ellipse cx="100" cy="118" rx="50" ry="58" fill="${t.face}"/>
  <!-- μάγουλα (ρουζ) -->
  <ellipse cx="74" cy="134" rx="11" ry="6.5" fill="#fda4af" opacity="0.65"/>
  <ellipse cx="126" cy="134" rx="11" ry="6.5" fill="#fda4af" opacity="0.65"/>
  <!-- μύτη -->
  <path d="M100,124 q3,8 -1,12" stroke="#e3b3a3" stroke-width="2" fill="none" stroke-linecap="round"/>
  ${brows(k)}
  ${eyes(k)}
  ${mouth(k)}
  ${ornaments(owned)}
</svg>`;
  }

  global.Geisha = {
    tierFor,
    svg,
    message(pct) {
      const t = tierFor(pct);
      return { jp: t.jp, romaji: t.romaji, gr: t.gr };
    },
  };
})(window);
