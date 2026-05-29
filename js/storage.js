/* storage.js — Διαχείριση δεδομένων (σετ λέξεων) στο localStorage */
(function (global) {
  "use strict";

  const KEY = "jp-vocab-decks-v1";

  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  function normalizeWord(w) {
    return {
      id: w.id || uid(),
      jp: w.jp || "",
      reading: w.reading || "",
      meaning: w.meaning || "",
      romaji: w.romaji || "",
      example: w.example || "",
      tags: Array.isArray(w.tags) ? w.tags : w.tags ? String(w.tags).split(/\s*[,;]\s*/).filter(Boolean) : [],
      srs: w.srs || { level: 0, due: 0, correct: 0, wrong: 0, seen: 0, lastWrong: false },
    };
  }

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return [];
      const data = JSON.parse(raw);
      if (!Array.isArray(data)) return [];
      // Μετάβαση/κανονικοποίηση παλιών δεδομένων
      data.forEach((d) => {
        d.words = (d.words || []).map(normalizeWord);
      });
      return data;
    } catch (e) {
      console.error("Σφάλμα φόρτωσης δεδομένων:", e);
      return [];
    }
  }

  function save(decks) {
    localStorage.setItem(KEY, JSON.stringify(decks));
  }

  const Store = {
    getDecks() {
      return load();
    },
    getDeck(id) {
      return load().find((d) => d.id === id) || null;
    },
    createDeck(name) {
      const decks = load();
      const deck = { id: uid(), name: name || "Νέο σετ", words: [], created: Date.now() };
      decks.push(deck);
      save(decks);
      return deck;
    },
    updateDeck(deck) {
      const decks = load();
      const i = decks.findIndex((d) => d.id === deck.id);
      if (i >= 0) decks[i] = deck;
      else decks.push(deck);
      save(decks);
    },
    deleteDeck(id) {
      save(load().filter((d) => d.id !== id));
    },
    addWord(deckId, word) {
      const deck = this.getDeck(deckId);
      if (!deck) return;
      deck.words.push(normalizeWord(word));
      this.updateDeck(deck);
      return deck;
    },
    removeWord(deckId, wordId) {
      const deck = this.getDeck(deckId);
      if (!deck) return;
      deck.words = deck.words.filter((w) => w.id !== wordId);
      this.updateDeck(deck);
      return deck;
    },
    /* Ενημέρωση SRS/στατιστικών μιας λέξης μέσα σε ένα σετ */
    updateWordSrs(deckId, wordId, srs) {
      const deck = this.getDeck(deckId);
      if (!deck) return;
      const w = deck.words.find((x) => x.id === wordId);
      if (w) {
        w.srs = srs;
        this.updateDeck(deck);
      }
    },
    /* Όλες οι ετικέτες/κατηγορίες ενός σετ */
    tagsOf(deck) {
      const set = new Set();
      (deck.words || []).forEach((w) => (w.tags || []).forEach((t) => set.add(t)));
      return Array.from(set).sort();
    },
    /* Δέχεται κείμενο: jp ; reading ; meaning [ ; romaji ; example ; tags ] ανά γραμμή */
    parseBulk(text) {
      const words = [];
      text.split(/\r?\n/).forEach((line) => {
        const t = line.trim();
        if (!t) return;
        const p = t.split(/\s*[;\t]\s*/).length > 1 ? t.split(/\s*[;\t]\s*/) : t.split(/\s*,\s*/);
        const jp = (p[0] || "").trim();
        const reading = (p[1] || "").trim();
        const meaning = (p[2] || "").trim();
        const romaji = (p[3] || "").trim();
        const example = (p[4] || "").trim();
        const tags = (p[5] || "").trim();
        if (jp || meaning) words.push(normalizeWord({ jp, reading, meaning, romaji, example, tags }));
      });
      return words;
    },
    normalizeWord,
    uid,
  };

  global.Store = Store;
})(window);
