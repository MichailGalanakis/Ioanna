#!/usr/bin/env node
/* build.js — Παράγει αυτόνομο αρχείο "Ιαπωνικές-Ασκήσεις.html"
 * Ενσωματώνει CSS, JS, εικονίδιο και δείγμα σε ΕΝΑ αρχείο που ανοίγει
 * με διπλό κλικ στον browser — χωρίς server, χωρίς ίντερνετ, χωρίς GitHub. */
const fs = require("fs");
const path = require("path");

const root = __dirname;
const read = (p) => fs.readFileSync(path.join(root, p), "utf8");

let html = read("index.html");

// 1) Ενσωμάτωση CSS
const css = read("css/styles.css");
html = html.replace(
  /<link rel="stylesheet" href="css\/styles\.css"\s*\/>/,
  `<style>\n${css}\n</style>`
);

// 2) Εικονίδιο ως data-URI (ώστε να μην χρειάζεται εξωτερικό αρχείο)
const favB64 = fs.readFileSync(path.join(root, "icons/favicon-64.png")).toString("base64");
html = html.replace(
  /<link rel="icon"[^>]*>/,
  `<link rel="icon" href="data:image/png;base64,${favB64}" type="image/png" />`
);

// 3) Αφαίρεση εξωτερικών αναφορών που δεν δουλεύουν ως τοπικό αρχείο
html = html.replace(/\s*<link rel="manifest"[^>]*>/, "");
html = html.replace(/\s*<link rel="apple-touch-icon"[^>]*>/, "");

// 4) Ενσωμάτωση όλων των <script src="..."> με τη σειρά
html = html.replace(/<script src="([^"]+)"><\/script>/g, (_, src) => {
  const code = read(src);
  return `<script>\n${code}\n</script>`;
});

// Όνομα χωρίς ελληνικά/σύμβολα ώστε να ανοίγει εύκολα σε Chrome κινητού (file://)
const out = "ioanna.html";
fs.writeFileSync(path.join(root, out), html, "utf8");
console.log("✓ Δημιουργήθηκε:", out, "(" + Math.round(Buffer.byteLength(html) / 1024) + " KB)");
