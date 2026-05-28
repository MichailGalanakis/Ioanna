/* stats.js — Στατιστικά προόδου: ιστορικό τεστ, σερί ημερών, σύνολα */
(function (global) {
  "use strict";

  const KEY = "jp-vocab-stats-v1";

  function todayStr(d) {
    d = d || new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      const s = raw ? JSON.parse(raw) : {};
      return {
        history: s.history || [],
        days: s.days || [],
        achievements: s.achievements || [],
        perfectStreak: s.perfectStreak || 0,
        totalAnswers: s.totalAnswers || 0,
        totalCorrect: s.totalCorrect || 0,
        ornaments: s.ornaments || [],
      };
    } catch (e) {
      return { history: [], days: [], achievements: [], perfectStreak: 0, totalAnswers: 0, totalCorrect: 0, ornaments: [] };
    }
  }
  function save(s) {
    localStorage.setItem(KEY, JSON.stringify(s));
  }

  const Stats = {
    get: load,
    todayStr,

    /* Κατέγραψε μία απάντηση (για σύνολα) */
    recordAnswer(correct) {
      const s = load();
      s.totalAnswers++;
      if (correct) s.totalCorrect++;
      save(s);
    },

    /* Κατέγραψε ολοκληρωμένο τεστ· επιστρέφει { stats, pct } */
    recordTest({ deckId, deckName, correct, total, mode }) {
      const s = load();
      const pct = total ? Math.round((correct / total) * 100) : 0;
      s.history.unshift({ ts: Date.now(), deckId, deckName, pct, correct, total, mode: mode || "mixed" });
      if (s.history.length > 200) s.history.length = 200;
      const t = todayStr();
      if (!s.days.includes(t)) s.days.push(t);
      s.perfectStreak = pct === 100 ? s.perfectStreak + 1 : 0;
      save(s);
      return { stats: s, pct };
    },

    /* Τρέχον σερί ημερών (συνεχόμενες μέρες εξάσκησης μέχρι σήμερα/χθες) */
    streak() {
      const s = load();
      const set = new Set(s.days);
      let n = 0;
      const d = new Date();
      // Επιτρέπεται να ξεκινά από σήμερα ή χθες
      if (!set.has(todayStr(d))) d.setDate(d.getDate() - 1);
      while (set.has(todayStr(d))) {
        n++;
        d.setDate(d.getDate() - 1);
      }
      return n;
    },

    bestStreak() {
      const s = load();
      const days = s.days.slice().sort();
      let best = 0, cur = 0, prev = null;
      days.forEach((ds) => {
        const d = new Date(ds);
        if (prev && (d - prev) === 86400000) cur++;
        else cur = 1;
        prev = d;
        if (cur > best) best = cur;
      });
      return best;
    },

    avgScore() {
      const s = load();
      if (!s.history.length) return 0;
      return Math.round(s.history.reduce((a, h) => a + h.pct, 0) / s.history.length);
    },

    addOrnament(id) {
      const s = load();
      if (!s.ornaments.includes(id)) {
        s.ornaments.push(id);
        save(s);
      }
    },
    unlockAchievement(id) {
      const s = load();
      if (!s.achievements.includes(id)) {
        s.achievements.push(id);
        save(s);
        return true;
      }
      return false;
    },
    reset() {
      localStorage.removeItem(KEY);
    },
  };

  global.Stats = Stats;
})(window);
