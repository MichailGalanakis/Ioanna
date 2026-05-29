/* speech.js — Προφορά ιαπωνικών με το Web Speech API (offline, χωρίς ίντερνετ) */
(function (global) {
  "use strict";

  const synth = global.speechSynthesis;
  let jaVoice = null;

  function pickVoice() {
    if (!synth) return;
    const voices = synth.getVoices();
    jaVoice = voices.find((v) => /ja(-|_)?JP/i.test(v.lang) || /japanese/i.test(v.name)) || null;
  }
  if (synth) {
    pickVoice();
    synth.onvoiceschanged = pickVoice;
  }

  const Speech = {
    supported() {
      return !!synth;
    },
    speak(text, lang) {
      if (!synth || !text) return;
      try {
        synth.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.lang = lang || "ja-JP";
        u.rate = 0.85;
        if (jaVoice) u.voice = jaVoice;
        synth.speak(u);
      } catch (e) {}
    },
    /* Προτίμησε ανάγνωση (kana) για πιο σωστή προφορά, αλλιώς το ιαπωνικό */
    speakWord(word) {
      Speech.speak(word.reading || word.jp);
    },
  };

  global.Speech = Speech;
})(window);
