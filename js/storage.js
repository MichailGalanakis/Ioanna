/* storage.js — Διαχείριση δεδομένων (σετ λέξεων) στο localStorage */
(function (global) {
  "use strict";

  const KEY = "jp-vocab-decks-v1";

  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return [];
      const data = JSON.parse(raw);
      return Array.isArray(data) ? data : [];
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
      deck.words.push({ id: uid(), jp: word.jp || "", reading: word.reading || "", meaning: word.meaning || "" });
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
    /* Δέχεται κείμενο "Ιαπωνικά ; ανάγνωση ; σημασία" ανά γραμμή */
    parseBulk(text) {
      const words = [];
      text.split(/\r?\n/).forEach((line) => {
        const t = line.trim();
        if (!t) return;
        const parts = t.split(/\s*[;,\t]\s*/);
        const jp = (parts[0] || "").trim();
        const reading = (parts[1] || "").trim();
        const meaning = (parts[2] || "").trim();
        if (jp || meaning) words.push({ id: uid(), jp, reading, meaning });
      });
      return words;
    },
    uid,
  };

  global.Store = Store;
})(window);
