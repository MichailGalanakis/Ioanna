/* srs.js — Έξυπνη επανάληψη (Leitner). Οι λέξεις που λαθεύεις επιστρέφουν πιο συχνά. */
(function (global) {
  "use strict";

  const DAY = 24 * 60 * 60 * 1000;
  // Διαστήματα ανά επίπεδο (σε ημέρες). Επίπεδο 0 = νέα/άγνωστη λέξη.
  const INTERVALS = [0, 1, 2, 4, 8, 16, 30];
  const MAX = INTERVALS.length - 1;

  function ensure(w) {
    if (!w.srs) w.srs = { level: 0, due: 0, correct: 0, wrong: 0, seen: 0, lastWrong: false };
    return w.srs;
  }

  const Srs = {
    DAY,
    /* Ενημέρωσε την κατάσταση μιας λέξης μετά από απάντηση */
    grade(word, correct) {
      const s = ensure(word);
      s.seen++;
      const now = Date.now();
      if (correct) {
        s.correct++;
        s.lastWrong = false;
        s.level = Math.min(s.level + 1, MAX);
        s.due = now + INTERVALS[s.level] * DAY;
      } else {
        s.wrong++;
        s.lastWrong = true;
        s.level = Math.max(s.level - 1, 0);
        s.due = now + 10 * 60 * 1000; // ξανά σε ~10 λεπτά
      }
      return s;
    },
    isDue(word) {
      const s = ensure(word);
      return s.seen === 0 || s.due <= Date.now();
    },
    /* Λέξεις προς επανάληψη τώρα (με προτεραιότητα στις πιο «ληγμένες») */
    dueWords(words) {
      const now = Date.now();
      return words
        .filter((w) => Srs.isDue(w))
        .sort((a, b) => (a.srs.due || 0) - (b.srs.due || 0) || (b.srs.lastWrong ? 1 : 0) - (a.srs.lastWrong ? 1 : 0));
    },
    /* «Δύσκολες» λέξεις: αυτές που λαθεύεις συχνά ή λάθεψες τελευταία */
    hardWords(words) {
      return words
        .filter((w) => w.srs && (w.srs.lastWrong || w.srs.wrong > 0))
        .map((w) => ({ w, rate: w.srs.seen ? w.srs.wrong / w.srs.seen : 0 }))
        .sort((a, b) => (b.w.srs.lastWrong ? 1 : 0) - (a.w.srs.lastWrong ? 1 : 0) || b.rate - a.rate)
        .map((x) => x.w);
    },
    mistakeWords(words) {
      return words.filter((w) => w.srs && (w.srs.lastWrong || w.srs.wrong > w.srs.correct));
    },
    /* Φιλικό κείμενο για το πότε ξανά */
    nextLabel(word) {
      const s = ensure(word);
      if (s.seen === 0) return "νέα";
      const diff = s.due - Date.now();
      if (diff <= 0) return "τώρα";
      const d = Math.round(diff / DAY);
      if (d >= 1) return "σε " + d + (d === 1 ? " μέρα" : " μέρες");
      return "σε λίγο";
    },
  };

  global.Srs = Srs;
})(window);
