/* packs.js — Έτοιμα πακέτα λέξεων: Hiragana, Katakana, JLPT N5 */
(function (global) {
  "use strict";

  // Γκότζουον (46 βασικοί ήχοι) με ρομάτζι
  const ROMAJI = [
    "a","i","u","e","o","ka","ki","ku","ke","ko","sa","shi","su","se","so",
    "ta","chi","tsu","te","to","na","ni","nu","ne","no","ha","hi","fu","he","ho",
    "ma","mi","mu","me","mo","ya","yu","yo","ra","ri","ru","re","ro","wa","wo","n",
  ];
  const HIRA = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん";
  const KATA = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン";

  function kanaPack(chars) {
    const arr = [];
    for (let i = 0; i < ROMAJI.length; i++) {
      const c = chars[i];
      arr.push({ jp: c, reading: c, meaning: ROMAJI[i], romaji: ROMAJI[i], example: "", tags: ["kana"] });
    }
    return arr;
  }

  const N5 = [
    ["私","わたし","watashi","εγώ"],["あなた","あなた","anata","εσύ"],["人","ひと","hito","άνθρωπος"],
    ["日本","にほん","nihon","Ιαπωνία"],["学生","がくせい","gakusei","φοιτητής/μαθητής"],["先生","せんせい","sensei","δάσκαλος"],
    ["学校","がっこう","gakkō","σχολείο"],["水","みず","mizu","νερό"],["お茶","おちゃ","ocha","τσάι"],
    ["ご飯","ごはん","gohan","ρύζι / φαγητό"],["肉","にく","niku","κρέας"],["魚","さかな","sakana","ψάρι"],
    ["犬","いぬ","inu","σκύλος"],["猫","ねこ","neko","γάτα"],["車","くるま","kuruma","αυτοκίνητο"],
    ["家","いえ","ie","σπίτι"],["本","ほん","hon","βιβλίο"],["時間","じかん","jikan","ώρα / χρόνος"],
    ["今日","きょう","kyō","σήμερα"],["明日","あした","ashita","αύριο"],["昨日","きのう","kinō","χθες"],
    ["朝","あさ","asa","πρωί"],["夜","よる","yoru","νύχτα"],["大きい","おおきい","ōkii","μεγάλος"],
    ["小さい","ちいさい","chiisai","μικρός"],["新しい","あたらしい","atarashii","καινούριος"],["古い","ふるい","furui","παλιός"],
    ["高い","たかい","takai","ψηλός / ακριβός"],["安い","やすい","yasui","φθηνός"],["いい","いい","ii","καλός"],
    ["悪い","わるい","warui","κακός"],["食べる","たべる","taberu","τρώω"],["飲む","のむ","nomu","πίνω"],
    ["行く","いく","iku","πηγαίνω"],["来る","くる","kuru","έρχομαι"],["見る","みる","miru","βλέπω"],
    ["聞く","きく","kiku","ακούω / ρωτάω"],["話す","はなす","hanasu","μιλάω"],["読む","よむ","yomu","διαβάζω"],
    ["書く","かく","kaku","γράφω"],["買う","かう","kau","αγοράζω"],
  ].map((r) => ({ jp: r[0], reading: r[1], romaji: r[2], meaning: r[3], example: "", tags: ["N5"] }));

  const PACKS = [
    { id: "hiragana", name: "Hiragana ひらがな", desc: "46 βασικοί χαρακτήρες", icon: "あ", build: () => kanaPack(HIRA) },
    { id: "katakana", name: "Katakana カタカナ", desc: "46 βασικοί χαρακτήρες", icon: "ア", build: () => kanaPack(KATA) },
    { id: "n5", name: "JLPT N5 — Λεξιλόγιο", desc: "40 βασικές λέξεις", icon: "字", build: () => N5.slice() },
  ];

  global.Packs = {
    list: () => PACKS,
    get: (id) => PACKS.find((p) => p.id === id),
  };
})(window);
