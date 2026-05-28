/* app.js — Ελεγκτής διεπαφής */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };

  /* ---------------- Κατάσταση ---------------- */
  const state = {
    deckId: null,
    session: null, // { exercises, index, results }
    historyStack: [],
  };

  const TITLES = {
    home: "あ 日本語",
    edit: "Επεξεργασία",
    setup: "Εξάσκηση",
    practice: "Εξάσκηση",
    results: "Αποτελέσματα",
  };

  /* ---------------- Πλοήγηση ---------------- */
  function showView(name, push = true) {
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    $("view-" + name).classList.add("active");
    $("appTitle").textContent = TITLES[name] || "あ 日本語";
    if (push) state.historyStack.push(name);
    $("backBtn").classList.toggle("hidden", state.historyStack.length <= 1);
    window.scrollTo(0, 0);
  }

  function goBack() {
    if (state.historyStack.length <= 1) return;
    state.historyStack.pop();
    const prev = state.historyStack[state.historyStack.length - 1];
    showView(prev, false);
    if (prev === "home") renderHome();
    if (prev === "edit") renderEditor();
  }

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.add("hidden"), 2200);
  }

  /* ---------------- Αρχική: λίστα σετ ---------------- */
  function renderHome() {
    const decks = Store.getDecks();
    const list = $("deckList");
    list.innerHTML = "";
    $("emptyHint").classList.toggle("hidden", decks.length > 0);

    decks.forEach((deck) => {
      const card = el("div", "deck-card");
      const info = el("div", "deck-info");
      info.appendChild(el("b", null, deck.name));
      info.appendChild(el("div", "muted small", deck.words.length + " λέξεις"));
      card.appendChild(info);

      const actions = el("div", "deck-actions");
      const play = el("button", "mini", "▶");
      play.title = "Εξάσκηση";
      play.addEventListener("click", (e) => {
        e.stopPropagation();
        openSetup(deck.id);
      });
      const del = el("button", "mini danger", "🗑");
      del.title = "Διαγραφή";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        if (del.dataset.confirm === "1") {
          Store.deleteDeck(deck.id);
          renderHome();
          toast("Το σετ διαγράφηκε");
        } else {
          del.dataset.confirm = "1";
          del.textContent = "Διαγραφή;";
          toast('Πάτησε ξανά για διαγραφή του "' + deck.name + '"');
          setTimeout(() => {
            del.dataset.confirm = "0";
            del.textContent = "🗑";
          }, 3000);
        }
      });
      actions.appendChild(play);
      actions.appendChild(del);
      card.appendChild(actions);

      card.addEventListener("click", () => openEditor(deck.id));
      list.appendChild(card);
    });
  }

  /* ---------------- Επεξεργασία σετ ---------------- */
  function openEditor(deckId) {
    state.deckId = deckId;
    renderEditor();
    showView("edit");
  }

  function renderEditor() {
    const deck = Store.getDeck(state.deckId);
    if (!deck) return goBack();
    $("deckNameInput").value = deck.name;
    $("wordCount").textContent = deck.words.length;

    const list = $("wordList");
    list.innerHTML = "";
    if (deck.words.length === 0) {
      list.appendChild(el("p", "muted small", "Δεν υπάρχουν λέξεις ακόμα. Πρόσθεσε μερικές παραπάνω."));
    }
    deck.words.forEach((w) => {
      const row = el("div", "word-row");
      row.appendChild(el("span", "jp", w.jp || "—"));
      const mid = el("div", "mn");
      if (w.reading) mid.appendChild(el("div", "rd", w.reading));
      mid.appendChild(el("div", null, w.meaning || ""));
      row.appendChild(mid);
      const del = el("button", "del", "×");
      del.addEventListener("click", () => {
        Store.removeWord(deck.id, w.id);
        renderEditor();
      });
      row.appendChild(del);
      list.appendChild(row);
    });
  }

  function addWordFromForm() {
    const jp = $("fJp").value.trim();
    const reading = $("fReading").value.trim();
    const meaning = $("fMeaning").value.trim();
    if (!jp && !meaning) {
      toast("Συμπλήρωσε τουλάχιστον τα ιαπωνικά ή τη σημασία");
      return;
    }
    Store.addWord(state.deckId, { jp, reading, meaning });
    $("fJp").value = "";
    $("fReading").value = "";
    $("fMeaning").value = "";
    $("fJp").focus();
    renderEditor();
  }

  /* ---------------- Ρυθμίσεις εξάσκησης ---------------- */
  function openSetup(deckId) {
    const deck = Store.getDeck(deckId);
    if (!deck) return;
    if (deck.words.length < 1) {
      toast("Πρόσθεσε λέξεις πρώτα");
      openEditor(deckId);
      return;
    }
    state.deckId = deckId;
    $("setupDeckName").textContent = "Εξάσκηση: " + deck.name;
    $("qCount").value = Math.min(10, Math.max(4, deck.words.length));
    showView("setup");
  }

  function readSetupOptions() {
    const dir = document.querySelector('input[name="dir"]:checked').value;
    return {
      types: { mc: $("typeMc").checked, match: $("typeMatch").checked, fill: $("typeFill").checked },
      direction: dir,
      count: parseInt($("qCount").value, 10) || 10,
    };
  }

  function startPractice() {
    const deck = Store.getDeck(state.deckId);
    if (!deck) return;
    const opts = readSetupOptions();
    if (!opts.types.mc && !opts.types.match && !opts.types.fill) {
      toast("Διάλεξε τουλάχιστον έναν τύπο άσκησης");
      return;
    }
    const exercises = Exercises.buildSession(deck.words, opts);
    if (exercises.length === 0) {
      toast("Δεν ήταν δυνατή η δημιουργία ασκήσεων. Έλεγξε τα πεδία των λέξεων.");
      return;
    }
    state.session = { exercises, index: 0, results: [] };
    showView("practice");
    renderCurrent();
  }

  /* ---------------- Εκτέλεση εξάσκησης ---------------- */
  function updateProgress() {
    const s = state.session;
    const pct = (s.index / s.exercises.length) * 100;
    $("progressFill").style.width = pct + "%";
    $("progressText").textContent = "Ερώτηση " + (s.index + 1) + " / " + s.exercises.length;
  }

  function renderCurrent() {
    const s = state.session;
    if (s.index >= s.exercises.length) return showResults();
    updateProgress();
    const ex = s.exercises[s.index];
    const host = $("exerciseHost");
    host.innerHTML = "";
    if (ex.type === "mc") renderMc(ex, host);
    else if (ex.type === "fill") renderFill(ex, host);
    else if (ex.type === "match") renderMatch(ex, host);
  }

  function recordAndNext(ex, correct, given) {
    state.session.results.push({ ex, correct, given });
    state.session.index++;
    renderCurrent();
  }

  function promptCard(ex) {
    const card = el("div", "prompt-card");
    card.appendChild(el("div", "prompt-label", ex.promptLabel + " → " + ex.answerLabel));
    const main = el("div", "prompt-main");
    main.lang = "ja";
    main.textContent = ex.prompt;
    card.appendChild(main);
    if (ex.promptSub) {
      const sub = el("div", "prompt-sub");
      sub.lang = "ja";
      sub.textContent = ex.promptSub;
      card.appendChild(sub);
    }
    return card;
  }

  function nextButton(label) {
    const btn = el("button", "primary-btn next-btn", label || "Επόμενη ▶");
    return btn;
  }

  /* --- Πολλαπλής επιλογής --- */
  function renderMc(ex, host) {
    host.appendChild(promptCard(ex));
    const opts = el("div", "options");
    const buttons = [];
    ex.options.forEach((opt) => {
      const b = el("button", "option", opt);
      b.lang = "ja";
      b.addEventListener("click", () => {
        const correct = opt === ex.answer;
        buttons.forEach((bb) => {
          bb.disabled = true;
          if (bb.textContent === ex.answer) bb.classList.add("correct");
        });
        if (!correct) b.classList.add("wrong");
        const next = nextButton();
        next.addEventListener("click", () => recordAndNext(ex, correct, opt));
        host.appendChild(next);
        next.focus();
      });
      buttons.push(b);
      opts.appendChild(b);
    });
    host.appendChild(opts);
  }

  /* --- Συμπλήρωση κενού --- */
  function renderFill(ex, host) {
    host.appendChild(promptCard(ex));
    const input = el("input");
    input.type = "text";
    input.setAttribute("autocapitalize", "none");
    input.setAttribute("autocomplete", "off");
    input.placeholder = "Γράψε την απάντηση…";
    input.lang = ex.answerLabel === Exercises.FIELD_LABEL.meaning ? "el" : "ja";
    host.appendChild(input);

    const submit = el("button", "primary-btn full", "Έλεγχος");
    const feedback = el("div", "fill-feedback");

    let answered = false;
    function doCheck() {
      if (answered) return;
      if (input.value.trim() === "") {
        toast("Γράψε μια απάντηση ή πάτησε Παράλειψη");
        return;
      }
      answered = true;
      const correct = Exercises.checkFill(ex, input.value);
      input.disabled = true;
      submit.classList.add("hidden");
      if (correct) {
        feedback.className = "fill-feedback ok";
        feedback.textContent = "✓ Σωστά!";
      } else {
        feedback.className = "fill-feedback no";
        feedback.textContent = "✗ Σωστή απάντηση: " + ex.answer;
      }
      const next = nextButton();
      next.addEventListener("click", () => recordAndNext(ex, correct, input.value.trim()));
      host.appendChild(next);
      next.focus();
    }

    submit.addEventListener("click", doCheck);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") doCheck();
    });
    host.appendChild(submit);

    const skip = el("button", "ghost-btn full", "Παράλειψη");
    skip.addEventListener("click", () => {
      if (answered) return;
      answered = true;
      input.disabled = true;
      submit.classList.add("hidden");
      skip.classList.add("hidden");
      feedback.className = "fill-feedback no";
      feedback.textContent = "Σωστή απάντηση: " + ex.answer;
      const next = nextButton();
      next.addEventListener("click", () => recordAndNext(ex, false, "(παράλειψη)"));
      host.appendChild(next);
    });
    host.appendChild(skip);
    host.appendChild(feedback);
    setTimeout(() => input.focus(), 50);
  }

  /* --- Αντιστοίχιση --- */
  function renderMatch(ex, host) {
    const info = el("div", "prompt-label", "Αντιστοίχισε: " + ex.leftLabel + " με " + ex.rightLabel);
    info.style.textAlign = "center";
    info.style.marginBottom = "12px";
    host.appendChild(info);

    const grid = el("div", "match-grid");
    const leftCol = el("div", "match-col");
    const rightCol = el("div", "match-col");

    const lefts = Exercises.shuffle(ex.pairs);
    const rights = Exercises.shuffle(ex.pairs);

    function makeItem(text, id, side) {
      const it = el("div", "match-item", text);
      it.lang = "ja";
      it.dataset.id = id;
      it.dataset.side = side;
      return it;
    }
    lefts.forEach((p) => leftCol.appendChild(makeItem(p.left, p.id, "L")));
    rights.forEach((p) => rightCol.appendChild(makeItem(p.right, p.id, "R")));
    grid.appendChild(leftCol);
    grid.appendChild(rightCol);
    host.appendChild(grid);

    let selected = null;
    let matched = 0;
    let mistakes = 0;
    const total = ex.pairs.length;

    function onClick(e) {
      const it = e.currentTarget;
      if (it.classList.contains("matched")) return;
      if (!selected) {
        selected = it;
        it.classList.add("selected");
        return;
      }
      if (selected === it) {
        it.classList.remove("selected");
        selected = null;
        return;
      }
      // Πρέπει να είναι από διαφορετικές στήλες
      if (selected.dataset.side === it.dataset.side) {
        selected.classList.remove("selected");
        selected = it;
        it.classList.add("selected");
        return;
      }
      if (selected.dataset.id === it.dataset.id) {
        selected.classList.add("matched");
        it.classList.add("matched");
        selected.classList.remove("selected");
        selected = null;
        matched++;
        if (matched === total) {
          const next = nextButton("Επόμενη ▶");
          next.addEventListener("click", () => recordAndNext(ex, mistakes === 0, mistakes + " λάθη"));
          host.appendChild(next);
          next.focus();
        }
      } else {
        mistakes++;
        const a = selected,
          b = it;
        a.classList.add("shake");
        b.classList.add("shake");
        b.classList.add("selected");
        setTimeout(() => {
          a.classList.remove("selected", "shake");
          b.classList.remove("selected", "shake");
        }, 380);
        selected = null;
      }
    }

    grid.querySelectorAll(".match-item").forEach((it) => it.addEventListener("click", onClick));
  }

  /* ---------------- Αποτελέσματα ---------------- */
  function showResults() {
    showView("results");
    const s = state.session;
    const total = s.results.length;
    const right = s.results.filter((r) => r.correct).length;
    const pct = total ? Math.round((right / total) * 100) : 0;

    $("scorePct").textContent = pct + "%";
    document.querySelector(".score-circle").style.setProperty("--p", pct + "%");
    $("scoreText").textContent = right + " σωστά από " + total;

    // Γκέισα με έκφραση ανάλογη του σκορ + σχόλιο
    if (window.Geisha) {
      $("geishaArt").innerHTML = window.Geisha.svg(pct);
      const msg = window.Geisha.message(pct);
      $("perfJp").textContent = msg.jp;
      $("perfGr").textContent = msg.gr;
    }

    const rl = $("reviewList");
    rl.innerHTML = "";
    s.results.forEach((r) => {
      const row = el("div", "review-row " + (r.correct ? "ok" : "no"));
      row.appendChild(el("span", "mark", r.correct ? "✓" : "✗"));
      const q = el("div", "q");
      if (r.ex.type === "match") {
        q.appendChild(el("span", null, "Αντιστοίχιση (" + r.ex.pairs.length + " ζεύγη)"));
      } else {
        const jp = el("span", "jp");
        jp.lang = "ja";
        jp.textContent = r.ex.prompt;
        q.appendChild(jp);
        q.appendChild(el("span", "muted", "  →  " + r.ex.answer));
      }
      row.appendChild(q);
      rl.appendChild(row);
    });
  }

  /* ---------------- Δείγμα λέξεων ---------------- */
  function loadSample() {
    const apply = (data) => {
      const deck = Store.createDeck(data.name || "Δείγμα");
      deck.words = (data.words || []).map((w) => ({ id: Store.uid(), jp: w.jp || "", reading: w.reading || "", meaning: w.meaning || "" }));
      Store.updateDeck(deck);
      renderHome();
      toast("Φορτώθηκε το δείγμα: " + deck.words.length + " λέξεις");
    };
    // Χρησιμοποίησε ενσωματωμένα δεδομένα (δουλεύει και χωρίς server / offline)
    if (window.SAMPLE_DECK) return apply(window.SAMPLE_DECK);
    // Εναλλακτικά, φόρτωσε από αρχείο (όταν τρέχει μέσω http)
    fetch("data/sample-deck.json")
      .then((r) => r.json())
      .then(apply)
      .catch(() => toast("Δεν ήταν δυνατή η φόρτωση του δείγματος"));
  }

  /* ---------------- Εισαγωγή / Εξαγωγή ---------------- */
  function exportJson() {
    const deck = Store.getDeck(state.deckId);
    if (!deck) return;
    const blob = new Blob([JSON.stringify({ name: deck.name, words: deck.words.map((w) => ({ jp: w.jp, reading: w.reading, meaning: w.meaning })) }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (deck.name || "set").replace(/[^\w\-]+/g, "_") + ".json";
    a.click();
    URL.revokeObjectURL(url);
  }

  function importJson(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result);
        const words = Array.isArray(data) ? data : data.words || [];
        const deck = Store.getDeck(state.deckId);
        words.forEach((w) => Store.addWord(deck.id, w));
        renderEditor();
        toast("Εισήχθησαν " + words.length + " λέξεις");
      } catch (e) {
        toast("Μη έγκυρο αρχείο JSON");
      }
    };
    reader.readAsText(file);
  }

  /* ---------------- Σύνδεση γεγονότων ---------------- */
  function bindEvents() {
    $("backBtn").addEventListener("click", goBack);

    $("newDeckBtn").addEventListener("click", () => {
      const deck = Store.createDeck("Σετ " + (Store.getDecks().length + 1));
      openEditor(deck.id);
      // Εστίασε στο όνομα ώστε να το αλλάξει εύκολα ο χρήστης
      setTimeout(() => {
        const i = $("deckNameInput");
        i.focus();
        i.select();
      }, 60);
    });
    $("loadSampleBtn").addEventListener("click", loadSample);

    $("deckNameInput").addEventListener("change", (e) => {
      const deck = Store.getDeck(state.deckId);
      if (deck) {
        deck.name = e.target.value.trim() || "Νέο σετ";
        Store.updateDeck(deck);
      }
    });
    $("addWordBtn").addEventListener("click", addWordFromForm);
    $("fMeaning").addEventListener("keydown", (e) => {
      if (e.key === "Enter") addWordFromForm();
    });

    $("bulkImportBtn").addEventListener("click", () => {
      const text = $("bulkArea").value;
      const words = Store.parseBulk(text);
      if (words.length === 0) return toast("Δεν βρέθηκαν λέξεις");
      const deck = Store.getDeck(state.deckId);
      words.forEach((w) => Store.addWord(deck.id, w));
      $("bulkArea").value = "";
      renderEditor();
      toast("Προστέθηκαν " + words.length + " λέξεις");
    });
    $("exportJsonBtn").addEventListener("click", exportJson);
    $("importJsonBtn").addEventListener("click", () => $("importFile").click());
    $("importFile").addEventListener("change", (e) => {
      if (e.target.files[0]) importJson(e.target.files[0]);
      e.target.value = "";
    });

    $("startFromEditBtn").addEventListener("click", () => openSetup(state.deckId));
    $("startPracticeBtn").addEventListener("click", startPractice);

    $("againBtn").addEventListener("click", () => openSetup(state.deckId));
    $("homeBtn").addEventListener("click", () => {
      state.historyStack = ["home"];
      showView("home", false);
      renderHome();
    });
  }

  /* ---------------- PWA: εγκατάσταση + service worker ---------------- */
  let deferredPrompt = null;
  function setupPwa() {
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      deferredPrompt = e;
      $("installBtn").classList.remove("hidden");
    });
    $("installBtn").addEventListener("click", async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
      $("installBtn").classList.add("hidden");
    });
    window.addEventListener("appinstalled", () => $("installBtn").classList.add("hidden"));

    // Ο service worker (offline) δουλεύει μόνο μέσω http/https, όχι ως τοπικό αρχείο
    if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
      window.addEventListener("load", () => {
        navigator.serviceWorker.register("sw.js").catch((e) => console.warn("SW:", e));
      });
    }
  }

  /* ---------------- Εκκίνηση ---------------- */
  function init() {
    bindEvents();
    setupPwa();
    state.historyStack = ["home"];
    renderHome();
    showView("home", false);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
