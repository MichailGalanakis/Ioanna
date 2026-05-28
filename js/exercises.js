/* exercises.js — Δημιουργία ασκήσεων από λέξεις */
(function (global) {
  "use strict";

  const FIELD_LABEL = { jp: "Ιαπωνικά", reading: "Ανάγνωση", meaning: "Σημασία" };

  const DIRS = {
    jp2mean: { p: "jp", a: "meaning" },
    mean2jp: { p: "meaning", a: "jp" },
    jp2read: { p: "jp", a: "reading" },
  };

  function shuffle(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function has(word, field) {
    return word && typeof word[field] === "string" && word[field].trim() !== "";
  }

  function normalize(s) {
    return String(s || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "")
      .replace(/[。、．，.,!?！？]/g, "");
  }

  /* Επιλογή έγκυρης κατεύθυνσης για μια λέξη */
  function resolveDir(word, direction) {
    if (direction === "mixed") {
      const valid = Object.values(DIRS).filter((d) => has(word, d.p) && has(word, d.a));
      return valid.length ? valid[Math.floor(Math.random() * valid.length)] : null;
    }
    const d = DIRS[direction];
    return d && has(word, d.p) && has(word, d.a) ? d : null;
  }

  function promptSub(word, dir) {
    // Εμφάνισε ανάγνωση ως βοήθεια όταν δείχνουμε ιαπωνικά, αλλά ΟΧΙ αν η ανάγνωση είναι η απάντηση
    if (dir.p === "jp" && dir.a !== "reading" && has(word, "reading")) return word.reading;
    return "";
  }

  /* ---------- Πολλαπλής επιλογής ---------- */
  function buildMc(word, allWords, direction) {
    const dir = resolveDir(word, direction);
    if (!dir) return null;
    const correct = word[dir.a].trim();

    const distractors = [];
    const seen = new Set([normalize(correct)]);
    shuffle(allWords).forEach((w) => {
      if (distractors.length >= 3) return;
      if (w.id === word.id) return;
      if (!has(w, dir.a)) return;
      const val = w[dir.a].trim();
      if (seen.has(normalize(val))) return;
      seen.add(normalize(val));
      distractors.push(val);
    });
    if (distractors.length === 0) return null; // χρειάζεται τουλάχιστον 1 λάθος επιλογή

    const options = shuffle(distractors.concat([correct]));
    return {
      type: "mc",
      word,
      promptLabel: FIELD_LABEL[dir.p],
      prompt: word[dir.p].trim(),
      promptSub: promptSub(word, dir),
      answerLabel: FIELD_LABEL[dir.a],
      options,
      answer: correct,
    };
  }

  /* ---------- Συμπλήρωση κενού (πληκτρολόγηση) ---------- */
  function buildFill(word, direction) {
    const dir = resolveDir(word, direction);
    if (!dir) return null;
    const answer = word[dir.a].trim();

    const accepted = new Set();
    // Πολλαπλές σημασίες χωρισμένες με / , ;
    answer.split(/[\/,;]/).forEach((s) => {
      const n = normalize(s);
      if (n) accepted.add(n);
    });
    // Αν η απάντηση είναι ιαπωνικά, δέξου και την ανάγνωση
    if (dir.a === "jp" && has(word, "reading")) accepted.add(normalize(word.reading));

    return {
      type: "fill",
      word,
      promptLabel: FIELD_LABEL[dir.p],
      prompt: word[dir.p].trim(),
      promptSub: promptSub(word, dir),
      answerLabel: FIELD_LABEL[dir.a],
      answer,
      accepted: Array.from(accepted),
    };
  }

  /* ---------- Αντιστοίχιση ---------- */
  function buildMatch(allWords, direction) {
    const dir =
      direction === "jp2read" ? { p: "jp", a: "reading" } : { p: "jp", a: "meaning" };
    const usable = allWords.filter((w) => has(w, dir.p) && has(w, dir.a));
    if (usable.length < 3) return null;

    const n = Math.min(5, usable.length);
    const chosen = shuffle(usable).slice(0, n);
    const pairs = chosen.map((w) => ({ id: w.id, left: w[dir.p].trim(), right: w[dir.a].trim() }));
    return {
      type: "match",
      leftLabel: FIELD_LABEL[dir.p],
      rightLabel: FIELD_LABEL[dir.a],
      pairs,
    };
  }

  /* ---------- Σύνθεση συνεδρίας εξάσκησης ---------- */
  function buildSession(words, opts) {
    const exercises = [];
    if (!words || words.length === 0) return exercises;

    const enabled = [];
    if (opts.types.mc) enabled.push("mc");
    if (opts.types.match && words.length >= 3) enabled.push("match");
    if (opts.types.fill) enabled.push("fill");
    if (enabled.length === 0) enabled.push("mc");

    const count = Math.max(1, opts.count | 0);
    let guard = 0;
    const maxGuard = count * 12 + 30;

    while (exercises.length < count && guard < maxGuard) {
      guard++;
      const type = enabled[Math.floor(Math.random() * enabled.length)];
      let ex = null;
      if (type === "match") {
        ex = buildMatch(words, opts.direction);
      } else {
        const word = words[Math.floor(Math.random() * words.length)];
        ex = type === "mc" ? buildMc(word, words, opts.direction) : buildFill(word, opts.direction);
      }
      if (ex) exercises.push(ex);
    }

    // Αν δεν φτάσαμε το count (π.χ. ελλιπή πεδία), επέστρεψε ό,τι μπορέσαμε
    return exercises.slice(0, count);
  }

  function checkFill(exercise, input) {
    return exercise.accepted.includes(normalize(input));
  }

  global.Exercises = { buildSession, checkFill, shuffle, normalize, FIELD_LABEL };
})(window);
