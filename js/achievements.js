/* achievements.js — Μετάλλια/επιτεύγματα + ξεκλείδωμα στολιδιών γκέισας */
(function (global) {
  "use strict";

  // ctx: { pct, mode, totalWords }  |  s: αντικείμενο στατιστικών
  const LIST = [
    { id: "first_test", icon: "🎌", title: "Πρώτο βήμα", desc: "Ολοκλήρωσε το πρώτο σου τεστ", ornament: null,
      check: (s) => s.history.length >= 1 },
    { id: "perfect", icon: "💯", title: "Τέλεια!", desc: "Πέτυχε 100% σε ένα τεστ", ornament: "flower",
      check: (s, c) => c.pct === 100 },
    { id: "perfect5", icon: "🏅", title: "Αλάνθαστος", desc: "5 τέλεια τεστ στη σειρά", ornament: "crown",
      check: (s) => s.perfectStreak >= 5 },
    { id: "streak3", icon: "🔥", title: "Συνέπεια", desc: "Εξάσκηση 3 μέρες στη σειρά", ornament: "fan",
      check: (s, c, ext) => ext.streak >= 3 },
    { id: "streak7", icon: "⚡", title: "Αφοσίωση", desc: "Εξάσκηση 7 μέρες στη σειρά", ornament: "kimono_gold",
      check: (s, c, ext) => ext.streak >= 7 },
    { id: "answers100", icon: "📚", title: "Εκατοστάρι", desc: "Απάντησε σε 100 ερωτήσεις συνολικά", ornament: null,
      check: (s) => s.totalAnswers >= 100 },
    { id: "words50", icon: "🗂️", title: "Συλλέκτης", desc: "Έχε 50+ λέξεις συνολικά", ornament: "umbrella",
      check: (s, c, ext) => ext.totalWords >= 50 },
    { id: "listener", icon: "👂", title: "Καλό αυτί", desc: "Ολοκλήρωσε τεστ ακρόασης", ornament: null,
      check: (s, c) => c.mode === "listen" },
    { id: "writer", icon: "✍️", title: "Καλλιγράφος", desc: "Ολοκλήρωσε τεστ γραφής", ornament: null,
      check: (s, c) => c.mode === "write" },
    { id: "blitz", icon: "⏱️", title: "Αστραπή", desc: "Ολοκλήρωσε γύρο μπλιц", ornament: "lantern",
      check: (s, c) => c.mode === "blitz" },
  ];

  const Achievements = {
    LIST,
    byId(id) {
      return LIST.find((a) => a.id === id);
    },
    /* Ελέγχει & ξεκλειδώνει· επιστρέφει πίνακα με τα ΝΕΑ επιτεύγματα */
    check(ctx) {
      const s = window.Stats.get();
      const ext = { streak: window.Stats.streak(), totalWords: ctx.totalWords || 0 };
      const unlocked = [];
      LIST.forEach((a) => {
        if (s.achievements.includes(a.id)) return;
        try {
          if (a.check(s, ctx, ext)) {
            window.Stats.unlockAchievement(a.id);
            if (a.ornament) window.Stats.addOrnament(a.ornament);
            unlocked.push(a);
          }
        } catch (e) {}
      });
      return unlocked;
    },
  };

  global.Achievements = Achievements;
})(window);
