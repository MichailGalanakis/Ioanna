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

  const state = {
    deckId: null,
    session: null, // { exercises, index, results, opts, blitz, timer, deadline }
    historyStack: [],
  };

  const TITLES = {
    home: "あ 日本語", edit: "Επεξεργασία", packs: "Πακέτα", stats: "Στατιστικά",
    setup: "Εξάσκηση", practice: "Εξάσκηση", results: "Αποτελέσματα",
  };

  /* ---------------- Πλοήγηση ---------------- */
  function showView(name, push = true) {
    stopBlitz();
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
    if (prev === "stats") renderStats();
    if (prev === "packs") renderPacks();
  }

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.add("hidden"), 2400);
  }

  function speakBtn(text) {
    const b = el("button", "speak-btn", "🔊");
    b.title = "Άκουσε";
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      window.Speech && Speech.speak(text);
    });
    return b;
  }

  /* ---------------- Αρχική ---------------- */
  function renderHome() {
    const decks = Store.getDecks();
    const list = $("deckList");
    list.innerHTML = "";
    $("emptyHint").classList.toggle("hidden", decks.length > 0);

    const streak = Stats.streak();
    const chip = $("streakChip");
    if (streak > 0) {
      chip.textContent = "🔥 Σερί " + streak + (streak === 1 ? " μέρα" : " μέρες") + "! Συνέχισε έτσι.";
      chip.classList.remove("hidden");
    } else chip.classList.add("hidden");

    decks.forEach((deck) => {
      const card = el("div", "deck-card");
      const info = el("div", "deck-info");
      info.appendChild(el("b", null, deck.name));
      const due = window.Srs ? Srs.dueWords(deck.words).length : 0;
      const sub = el("div", "muted small", deck.words.length + " λέξεις" + (due ? " · " + due + " για επανάληψη" : ""));
      info.appendChild(sub);
      card.appendChild(info);

      const actions = el("div", "deck-actions");
      const play = el("button", "mini", "▶");
      play.title = "Εξάσκηση";
      play.addEventListener("click", (e) => { e.stopPropagation(); openSetup(deck.id); });
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
          setTimeout(() => { del.dataset.confirm = "0"; del.textContent = "🗑"; }, 3000);
        }
      });
      actions.appendChild(play);
      actions.appendChild(del);
      card.appendChild(actions);
      card.addEventListener("click", () => openEditor(deck.id));
      list.appendChild(card);
    });
  }

  /* ---------------- Έτοιμα πακέτα ---------------- */
  function renderPacks() {
    const list = $("packList");
    list.innerHTML = "";
    Packs.list().forEach((pack) => {
      const card = el("div", "deck-card");
      const ic = el("div", "pack-icon", pack.icon);
      ic.lang = "ja";
      card.appendChild(ic);
      const info = el("div", "deck-info");
      info.appendChild(el("b", null, pack.name));
      info.appendChild(el("div", "muted small", pack.desc));
      card.appendChild(info);
      const add = el("button", "mini", "+ Προσθήκη");
      add.addEventListener("click", (e) => {
        e.stopPropagation();
        const deck = Store.createDeck(pack.name);
        pack.build().forEach((w) => Store.addWord(deck.id, w));
        toast("Προστέθηκε το πακέτο: " + pack.name);
        state.historyStack = ["home"];
        openEditor(deck.id);
      });
      card.appendChild(add);
      list.appendChild(card);
    });
  }

  /* ---------------- Στατιστικά ---------------- */
  function renderStats() {
    const s = Stats.get();
    $("stStreak").textContent = Stats.streak();
    $("stBest").textContent = Stats.bestStreak();
    $("stAvg").textContent = Stats.avgScore() + "%";
    $("stAns").textContent = s.totalAnswers;

    const grid = $("achvGrid");
    grid.innerHTML = "";
    Achievements.LIST.forEach((a) => {
      const got = s.achievements.includes(a.id);
      const cell = el("div", "achv-cell" + (got ? " got" : ""));
      cell.appendChild(el("div", "achv-icon", got ? a.icon : "🔒"));
      cell.appendChild(el("div", "achv-title", a.title));
      cell.appendChild(el("div", "achv-desc", a.desc));
      grid.appendChild(cell);
    });

    const hl = $("historyList");
    hl.innerHTML = "";
    if (!s.history.length) hl.appendChild(el("p", "muted small", "Δεν υπάρχει ιστορικό ακόμα."));
    s.history.slice(0, 30).forEach((h) => {
      const row = el("div", "history-row");
      const d = new Date(h.ts);
      const date = d.toLocaleDateString("el-GR") + " " + d.toLocaleTimeString("el-GR", { hour: "2-digit", minute: "2-digit" });
      row.appendChild(el("span", "h-pct " + (h.pct >= 75 ? "good" : h.pct >= 50 ? "mid" : "low"), h.pct + "%"));
      const mid = el("div", "h-mid");
      mid.appendChild(el("div", null, h.deckName || "—"));
      mid.appendChild(el("div", "muted small", date + " · " + h.correct + "/" + h.total + " · " + modeLabel(h.mode)));
      row.appendChild(mid);
      hl.appendChild(row);
    });
  }

  function modeLabel(m) {
    return { mixed: "ανάμεικτο", blitz: "μπλιц", listen: "ακρόαση", write: "γραφή" }[m] || "ανάμεικτο";
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
      if (window.Speech && Speech.supported() && (w.jp || w.reading)) row.appendChild(speakBtn(w.reading || w.jp));
      const jp = el("span", "jp", w.jp || "—");
      jp.lang = "ja";
      row.appendChild(jp);
      const mid = el("div", "mn");
      if (w.reading || w.romaji) mid.appendChild(el("div", "rd", [w.reading, w.romaji].filter(Boolean).join(" · ")));
      mid.appendChild(el("div", null, w.meaning || ""));
      if (w.example) { const ex = el("div", "ex muted small", w.example); ex.lang = "ja"; mid.appendChild(ex); }
      if (w.tags && w.tags.length) mid.appendChild(el("div", "tags muted small", w.tags.map((t) => "#" + t).join(" ")));
      row.appendChild(mid);
      const del = el("button", "del", "×");
      del.addEventListener("click", () => { Store.removeWord(deck.id, w.id); renderEditor(); });
      row.appendChild(del);
      list.appendChild(row);
    });
  }

  function addWordFromForm() {
    const jp = $("fJp").value.trim();
    const reading = $("fReading").value.trim();
    const romaji = $("fRomaji").value.trim();
    const meaning = $("fMeaning").value.trim();
    const example = $("fExample").value.trim();
    const tags = $("fTags").value.trim();
    if (!jp && !meaning) { toast("Συμπλήρωσε τουλάχιστον τα ιαπωνικά ή τη σημασία"); return; }
    Store.addWord(state.deckId, { jp, reading, romaji, meaning, example, tags });
    ["fJp", "fReading", "fRomaji", "fMeaning", "fExample", "fTags"].forEach((id) => ($(id).value = ""));
    $("fJp").focus();
    renderEditor();
  }

  /* ---------------- Ρυθμίσεις εξάσκησης ---------------- */
  function openSetup(deckId) {
    const deck = Store.getDeck(deckId);
    if (!deck) return;
    if (deck.words.length < 1) { toast("Πρόσθεσε λέξεις πρώτα"); openEditor(deckId); return; }
    state.deckId = deckId;
    $("setupDeckName").textContent = "Εξάσκηση: " + deck.name;
    $("qCount").value = Math.min(10, Math.max(4, deck.words.length));

    // Κατηγορίες
    const tags = Store.tagsOf(deck);
    const sel = $("catSelect");
    sel.innerHTML = "";
    const optAll = el("option", null, "Όλες οι κατηγορίες");
    optAll.value = "";
    sel.appendChild(optAll);
    tags.forEach((t) => { const o = el("option", null, t); o.value = t; sel.appendChild(o); });
    $("catWrap").classList.toggle("hidden", tags.length === 0);
    updateSetupHint();
    showView("setup");
  }

  function selectedSource() {
    return (document.querySelector('input[name="src"]:checked') || {}).value || "all";
  }

  function filteredWords() {
    const deck = Store.getDeck(state.deckId);
    if (!deck) return [];
    let words = deck.words.slice();
    const cat = $("catSelect").value;
    if (cat) words = words.filter((w) => (w.tags || []).includes(cat));
    const src = selectedSource();
    if (src === "due") words = Srs.dueWords(words);
    else if (src === "mistakes") words = Srs.mistakeWords(words);
    return words;
  }

  function updateSetupHint() {
    const n = filteredWords().length;
    const src = selectedSource();
    let txt = n + " διαθέσιμες λέξεις";
    if (src === "due" && n === 0) txt = "Καμία λέξη για επανάληψη τώρα — δοκίμασε «Όλες οι λέξεις».";
    if (src === "mistakes" && n === 0) txt = "Δεν έχεις καταγεγραμμένα λάθη ακόμα.";
    $("setupHint").textContent = txt;
  }

  function readSetupOptions() {
    return {
      types: {
        mc: $("typeMc").checked, match: $("typeMatch").checked, fill: $("typeFill").checked,
        listen: $("typeListen").checked, write: $("typeWrite").checked,
      },
      direction: (document.querySelector('input[name="dir"]:checked') || {}).value || "jp2mean",
      count: parseInt($("qCount").value, 10) || 10,
      blitz: $("optBlitz").checked,
      romaji: $("optRomaji").checked,
      speak: $("optSpeak").checked,
    };
  }

  function startPractice() {
    const deck = Store.getDeck(state.deckId);
    if (!deck) return;
    const opts = readSetupOptions();
    if (!opts.types.mc && !opts.types.match && !opts.types.fill && !opts.types.listen && !opts.types.write) {
      toast("Διάλεξε τουλάχιστον έναν τύπο άσκησης"); return;
    }
    const words = filteredWords();
    if (words.length === 0) { toast("Δεν υπάρχουν λέξεις με αυτά τα κριτήρια"); return; }

    let count = opts.count;
    if (opts.blitz) count = Math.max(count, 40); // μπλιц: αρκετές ερωτήσεις για 60''
    const exercises = Exercises.buildSession(words, { types: opts.types, direction: opts.direction, count });
    if (exercises.length === 0) { toast("Δεν ήταν δυνατή η δημιουργία ασκήσεων."); return; }

    state.session = { exercises, index: 0, results: [], opts, blitz: opts.blitz, deckWordCount: deck.words.length };
    showView("practice");
    if (opts.blitz) startBlitz();
    else $("blitzBar").classList.add("hidden");
    renderCurrent();
  }

  /* ---------------- Μπλιц ---------------- */
  function startBlitz() {
    const bar = $("blitzBar");
    bar.classList.remove("hidden");
    state.session.deadline = Date.now() + 60000;
    const tick = () => {
      const left = Math.max(0, Math.ceil((state.session.deadline - Date.now()) / 1000));
      const score = state.session.results.filter((r) => r.correct).length;
      bar.textContent = "⏱️ " + left + "''   ·   ⭐ " + score + " πόντοι";
      bar.classList.toggle("urgent", left <= 10);
      if (left <= 0) { stopBlitz(); showResults(); }
    };
    tick();
    state.session.timer = setInterval(tick, 250);
  }
  function stopBlitz() {
    if (state.session && state.session.timer) {
      clearInterval(state.session.timer);
      state.session.timer = null;
    }
  }

  /* ---------------- Εκτέλεση εξάσκησης ---------------- */
  function updateProgress() {
    const s = state.session;
    if (s.blitz) { $("progressFill").style.width = "100%"; $("progressText").textContent = ""; return; }
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
    else if (ex.type === "listen") renderListen(ex, host);
    else if (ex.type === "write") renderWrite(ex, host);
    maybeAutoSpeak(ex);
  }

  function maybeAutoSpeak(ex) {
    if (!window.Speech || !state.session.opts.speak) return;
    if (ex.type === "listen") return; // η ακρόαση μιλά μόνη της παρακάτω
    if (ex.word && (ex.word.jp || ex.word.reading) && ex.promptLabel === Exercises.FIELD_LABEL.jp) {
      Speech.speak(ex.word.reading || ex.word.jp);
    }
  }

  function gradeWordSrs(wordId, correct) {
    if (!window.Srs) return;
    const deck = Store.getDeck(state.deckId);
    if (!deck) return;
    const w = deck.words.find((x) => x.id === wordId);
    if (!w) return;
    Srs.grade(w, correct);
    Store.updateDeck(deck);
  }

  function recordAndNext(ex, correct, given) {
    if (ex.pairs) ex.pairs.forEach((p) => gradeWordSrs(p.id, correct));
    else if (ex.word) gradeWordSrs(ex.word.id, correct);
    Stats.recordAnswer(correct);
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
    if (ex.promptSub) { const sub = el("div", "prompt-sub"); sub.lang = "ja"; sub.textContent = ex.promptSub; card.appendChild(sub); }
    if (state.session.opts.romaji && ex.word && ex.word.romaji && ex.promptLabel === Exercises.FIELD_LABEL.jp) {
      card.appendChild(el("div", "prompt-romaji", ex.word.romaji));
    }
    if (window.Speech && Speech.supported() && ex.word && (ex.word.jp || ex.word.reading) && ex.promptLabel === Exercises.FIELD_LABEL.jp) {
      card.appendChild(speakBtn(ex.word.reading || ex.word.jp));
    }
    return card;
  }

  function nextButton(label) { return el("button", "primary-btn next-btn", label || "Επόμενη ▶"); }

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
        buttons.forEach((bb) => { bb.disabled = true; if (bb.textContent === ex.answer) bb.classList.add("correct"); });
        if (!correct) b.classList.add("wrong");
        const next = nextButton();
        next.addEventListener("click", () => recordAndNext(ex, correct, opt));
        host.appendChild(next);
        if (!state.session.blitz) next.focus();
        if (state.session.blitz) setTimeout(() => recordAndNext(ex, correct, opt), 350);
      });
      buttons.push(b);
      opts.appendChild(b);
    });
    host.appendChild(opts);
  }

  /* --- Ακρόαση --- */
  function renderListen(ex, host) {
    const card = el("div", "prompt-card");
    card.appendChild(el("div", "prompt-label", "Άκουσε και διάλεξε τη σημασία"));
    const big = el("button", "listen-big", "🔊");
    big.addEventListener("click", () => Speech.speak(ex.speak));
    card.appendChild(big);
    host.appendChild(card);
    if (state.session.opts.speak !== false) setTimeout(() => Speech.speak(ex.speak), 250);

    const opts = el("div", "options");
    const buttons = [];
    ex.options.forEach((opt) => {
      const b = el("button", "option", opt);
      b.addEventListener("click", () => {
        const correct = opt === ex.answer;
        buttons.forEach((bb) => { bb.disabled = true; if (bb.textContent === ex.answer) bb.classList.add("correct"); });
        if (!correct) b.classList.add("wrong");
        const next = nextButton();
        next.addEventListener("click", () => recordAndNext(ex, correct, opt));
        host.appendChild(next);
        if (state.session.blitz) setTimeout(() => recordAndNext(ex, correct, opt), 350);
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
      if (input.value.trim() === "") { toast("Γράψε μια απάντηση ή πάτησε Παράλειψη"); return; }
      answered = true;
      const correct = Exercises.checkFill(ex, input.value);
      input.disabled = true;
      submit.classList.add("hidden");
      skip.classList.add("hidden");
      feedback.className = "fill-feedback " + (correct ? "ok" : "no");
      feedback.textContent = correct ? "✓ Σωστά!" : "✗ Σωστή απάντηση: " + ex.answer;
      const next = nextButton();
      next.addEventListener("click", () => recordAndNext(ex, correct, input.value.trim()));
      host.appendChild(next);
      next.focus();
    }
    submit.addEventListener("click", doCheck);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") doCheck(); });
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

  /* --- Γραφή χαρακτήρα (canvas + αυτο-βαθμολόγηση) --- */
  function renderWrite(ex, host) {
    const card = el("div", "prompt-card");
    card.appendChild(el("div", "prompt-label", "Γράψε στα ιαπωνικά: " + ex.promptLabel));
    card.appendChild(el("div", "prompt-main-sm", ex.prompt));
    host.appendChild(card);

    const wrap = el("div", "canvas-wrap");
    const canvas = el("canvas", "draw-canvas");
    const size = Math.min(300, Math.floor(window.innerWidth * 0.8));
    canvas.width = size; canvas.height = size;
    wrap.appendChild(canvas);
    host.appendChild(wrap);
    const ctx = canvas.getContext("2d");
    ctx.lineWidth = 8; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#f1f5f9";
    let drawing = false;
    const pos = (e) => {
      const r = canvas.getBoundingClientRect();
      const t = e.touches ? e.touches[0] : e;
      return { x: (t.clientX - r.left) * (canvas.width / r.width), y: (t.clientY - r.top) * (canvas.height / r.height) };
    };
    const start = (e) => { drawing = true; const p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); e.preventDefault(); };
    const move = (e) => { if (!drawing) return; const p = pos(e); ctx.lineTo(p.x, p.y); ctx.stroke(); e.preventDefault(); };
    const end = () => { drawing = false; };
    canvas.addEventListener("mousedown", start); canvas.addEventListener("mousemove", move);
    window.addEventListener("mouseup", end);
    canvas.addEventListener("touchstart", start, { passive: false });
    canvas.addEventListener("touchmove", move, { passive: false });
    canvas.addEventListener("touchend", end);

    const tools = el("div", "row-btns");
    const clear = el("button", "ghost-btn", "Καθάρισμα");
    clear.addEventListener("click", () => ctx.clearRect(0, 0, canvas.width, canvas.height));
    const reveal = el("button", "primary-btn", "Δες την απάντηση");
    tools.appendChild(clear); tools.appendChild(reveal);
    host.appendChild(tools);

    reveal.addEventListener("click", () => {
      tools.classList.add("hidden");
      const ans = el("div", "write-answer");
      const a = el("span", "jp big-jp", ex.target); a.lang = "ja";
      ans.appendChild(el("div", "muted small", "Σωστή γραφή:"));
      ans.appendChild(a);
      if (ex.reading) { const r = el("div", "rd", ex.reading); r.lang = "ja"; ans.appendChild(r); }
      if (window.Speech && Speech.supported()) ans.appendChild(speakBtn(ex.reading || ex.target));
      host.appendChild(ans);
      ans.appendChild(el("p", "muted small", "Το έγραψες σωστά;"));
      const judge = el("div", "row-btns center");
      const yes = el("button", "primary-btn", "✓ Σωστά");
      const no = el("button", "ghost-btn", "✗ Λάθος");
      yes.addEventListener("click", () => recordAndNext(ex, true, "(αυτο-σωστό)"));
      no.addEventListener("click", () => recordAndNext(ex, false, "(αυτο-λάθος)"));
      judge.appendChild(yes); judge.appendChild(no);
      host.appendChild(judge);
    });
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
      it.lang = "ja"; it.dataset.id = id; it.dataset.side = side;
      return it;
    }
    lefts.forEach((p) => leftCol.appendChild(makeItem(p.left, p.id, "L")));
    rights.forEach((p) => rightCol.appendChild(makeItem(p.right, p.id, "R")));
    grid.appendChild(leftCol); grid.appendChild(rightCol);
    host.appendChild(grid);

    let selected = null, matched = 0, mistakes = 0;
    const total = ex.pairs.length;
    function onClick(e) {
      const it = e.currentTarget;
      if (it.classList.contains("matched")) return;
      if (!selected) { selected = it; it.classList.add("selected"); return; }
      if (selected === it) { it.classList.remove("selected"); selected = null; return; }
      if (selected.dataset.side === it.dataset.side) { selected.classList.remove("selected"); selected = it; it.classList.add("selected"); return; }
      if (selected.dataset.id === it.dataset.id) {
        selected.classList.add("matched"); it.classList.add("matched");
        selected.classList.remove("selected"); selected = null; matched++;
        if (matched === total) {
          const next = nextButton("Επόμενη ▶");
          next.addEventListener("click", () => recordAndNext(ex, mistakes === 0, mistakes + " λάθη"));
          host.appendChild(next);
          if (!state.session.blitz) next.focus();
        }
      } else {
        mistakes++;
        const a = selected, b = it;
        a.classList.add("shake"); b.classList.add("shake"); b.classList.add("selected");
        setTimeout(() => { a.classList.remove("selected", "shake"); b.classList.remove("selected", "shake"); }, 380);
        selected = null;
      }
    }
    grid.querySelectorAll(".match-item").forEach((it) => it.addEventListener("click", onClick));
  }

  /* ---------------- Αποτελέσματα ---------------- */
  function sessionMode() {
    const s = state.session;
    if (s.blitz) return "blitz";
    const t = s.opts.types;
    const only = Object.keys(t).filter((k) => t[k]);
    if (only.length === 1 && (only[0] === "listen" || only[0] === "write")) return only[0];
    return "mixed";
  }

  function showResults() {
    stopBlitz();
    showView("results");
    const s = state.session;
    const total = s.results.length;
    const right = s.results.filter((r) => r.correct).length;
    const pct = total ? Math.round((right / total) * 100) : 0;

    // Καταγραφή τεστ + έλεγχος επιτευγμάτων
    const deck = Store.getDeck(state.deckId);
    Stats.recordTest({ deckId: state.deckId, deckName: deck ? deck.name : "—", correct: right, total, mode: sessionMode() });
    const totalWords = Store.getDecks().reduce((a, d) => a + d.words.length, 0);
    const newAchv = Achievements.check({ pct, mode: sessionMode(), totalWords });

    $("scorePct").textContent = pct + "%";
    document.querySelector(".score-circle").style.setProperty("--p", pct + "%");
    $("scoreText").textContent = right + " σωστά από " + total + (s.blitz ? " · ⭐ " + right + " πόντοι" : "");

    if (window.Geisha) {
      const owned = Stats.get().ornaments || [];
      $("geishaArt").innerHTML = Geisha.svg(pct, owned);
      const msg = Geisha.message(pct);
      $("perfJp").textContent = msg.jp;
      $("perfGr").textContent = msg.gr;
    }

    const na = $("newAchievements");
    na.innerHTML = "";
    newAchv.forEach((a) => {
      const chip = el("div", "achv-new");
      chip.appendChild(el("span", "achv-icon", a.icon));
      chip.appendChild(el("span", null, "Νέο επίτευγμα: " + a.title));
      na.appendChild(chip);
    });

    const rl = $("reviewList");
    rl.innerHTML = "";
    s.results.forEach((r) => {
      const row = el("div", "review-row " + (r.correct ? "ok" : "no"));
      row.appendChild(el("span", "mark", r.correct ? "✓" : "✗"));
      const q = el("div", "q");
      if (r.ex.type === "match") {
        q.appendChild(el("span", null, "Αντιστοίχιση (" + r.ex.pairs.length + " ζεύγη)"));
      } else if (r.ex.type === "write") {
        const jp = el("span", "jp"); jp.lang = "ja"; jp.textContent = r.ex.target;
        q.appendChild(jp); q.appendChild(el("span", "muted", "  ·  " + r.ex.prompt));
      } else {
        const jp = el("span", "jp"); jp.lang = "ja"; jp.textContent = r.ex.type === "listen" ? r.ex.speak : r.ex.prompt;
        q.appendChild(jp); q.appendChild(el("span", "muted", "  →  " + r.ex.answer));
      }
      row.appendChild(q);
      rl.appendChild(row);
    });
  }

  /* ---------------- Δείγμα / Εισαγωγή / Εξαγωγή ---------------- */
  function loadSample() {
    const apply = (data) => {
      const deck = Store.createDeck(data.name || "Δείγμα");
      (data.words || []).forEach((w) => Store.addWord(deck.id, w));
      renderHome();
      toast("Φορτώθηκε το δείγμα: " + (data.words || []).length + " λέξεις");
    };
    if (window.SAMPLE_DECK) return apply(window.SAMPLE_DECK);
    fetch("data/sample-deck.json").then((r) => r.json()).then(apply).catch(() => toast("Δεν ήταν δυνατή η φόρτωση του δείγματος"));
  }

  function exportJson() {
    const deck = Store.getDeck(state.deckId);
    if (!deck) return;
    const words = deck.words.map((w) => ({ jp: w.jp, reading: w.reading, romaji: w.romaji, meaning: w.meaning, example: w.example, tags: w.tags }));
    const blob = new Blob([JSON.stringify({ name: deck.name, words }, null, 2)], { type: "application/json" });
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
      } catch (e) { toast("Μη έγκυρο αρχείο JSON"); }
    };
    reader.readAsText(file);
  }

  /* ---------------- Σύνδεση γεγονότων ---------------- */
  function bindEvents() {
    $("backBtn").addEventListener("click", goBack);
    $("statsBtn").addEventListener("click", () => { renderStats(); showView("stats"); });
    $("packsBtn").addEventListener("click", () => { renderPacks(); showView("packs"); });

    $("newDeckBtn").addEventListener("click", () => {
      const deck = Store.createDeck("Σετ " + (Store.getDecks().length + 1));
      openEditor(deck.id);
      setTimeout(() => { const i = $("deckNameInput"); i.focus(); i.select(); }, 60);
    });
    $("loadSampleBtn").addEventListener("click", loadSample);

    $("deckNameInput").addEventListener("change", (e) => {
      const deck = Store.getDeck(state.deckId);
      if (deck) { deck.name = e.target.value.trim() || "Νέο σετ"; Store.updateDeck(deck); }
    });
    $("addWordBtn").addEventListener("click", addWordFromForm);
    $("fTags").addEventListener("keydown", (e) => { if (e.key === "Enter") addWordFromForm(); });

    $("bulkImportBtn").addEventListener("click", () => {
      const words = Store.parseBulk($("bulkArea").value);
      if (words.length === 0) return toast("Δεν βρέθηκαν λέξεις");
      const deck = Store.getDeck(state.deckId);
      words.forEach((w) => Store.addWord(deck.id, w));
      $("bulkArea").value = "";
      renderEditor();
      toast("Προστέθηκαν " + words.length + " λέξεις");
    });
    $("exportJsonBtn").addEventListener("click", exportJson);
    $("importJsonBtn").addEventListener("click", () => $("importFile").click());
    $("importFile").addEventListener("change", (e) => { if (e.target.files[0]) importJson(e.target.files[0]); e.target.value = ""; });

    $("startFromEditBtn").addEventListener("click", () => openSetup(state.deckId));
    $("startPracticeBtn").addEventListener("click", startPractice);
    $("catSelect").addEventListener("change", updateSetupHint);
    document.querySelectorAll('input[name="src"]').forEach((r) => r.addEventListener("change", updateSetupHint));

    $("resetStatsBtn").addEventListener("click", () => {
      const b = $("resetStatsBtn");
      if (b.dataset.confirm === "1") { Stats.reset(); renderStats(); toast("Τα στατιστικά μηδενίστηκαν"); b.dataset.confirm = "0"; b.textContent = "Μηδενισμός στατιστικών"; }
      else { b.dataset.confirm = "1"; b.textContent = "Πάτησε ξανά για επιβεβαίωση"; setTimeout(() => { b.dataset.confirm = "0"; b.textContent = "Μηδενισμός στατιστικών"; }, 3000); }
    });

    $("againBtn").addEventListener("click", () => openSetup(state.deckId));
    $("homeBtn").addEventListener("click", () => { state.historyStack = ["home"]; showView("home", false); renderHome(); });
  }

  /* ---------------- PWA ---------------- */
  let deferredPrompt = null;
  function setupPwa() {
    window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredPrompt = e; $("installBtn").classList.remove("hidden"); });
    $("installBtn").addEventListener("click", async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
      $("installBtn").classList.add("hidden");
    });
    window.addEventListener("appinstalled", () => $("installBtn").classList.add("hidden"));
    if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
      window.addEventListener("load", () => { navigator.serviceWorker.register("sw.js").catch((e) => console.warn("SW:", e)); });
    }
  }

  function init() {
    bindEvents();
    setupPwa();
    state.historyStack = ["home"];
    renderHome();
    showView("home", false);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
