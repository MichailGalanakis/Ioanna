# 04 — Αρχιτεκτονική του agentic συστήματος

Η πρόταση, βασισμένη στα ευρήματα των κεφαλαίων 01–03.

---

## Οι πέντε αρχές σχεδιασμού

Κάθε μία προκύπτει απευθείας από ένα εύρημα της έρευνας.

### 1. Το LLM ερευνά, ο κώδικας εκτελεί

**Από:** Alpha Arena — τα μοντέλα υπερ-συναλλάσσονταν και τα fees έφαγαν το PnL.

Το LLM δεν καλεί ποτέ `place_order()`. Παράγει **δομημένες προτάσεις** που
περνούν από ντετερμινιστικούς ελέγχους. Η μηχανή εκτέλεσης είναι κανονικός
κώδικας με μοναδιαία tests, όχι prompt.

### 2. Η αδράνεια είναι το default

**Από:** το κύριο failure mode είναι η υπερβολική δραστηριότητα, όχι η κακή ανάλυση.

Το σύστημα πρέπει να **δικαιολογήσει** κάθε συναλλαγή έναντι του να μην κάνει
τίποτα. Υπάρχει ρητό budget συναλλαγών ανά περίοδο. Όταν εξαντληθεί, το
σύστημα δεν συναλλάσσεται — ανεξάρτητα από το πόσο πειστική είναι η ιδέα.

### 3. Καμία θέση χωρίς γραπτή, προ-καταγεγραμμένη υπόθεση

**Από:** τη ρητή απαίτησή σου για τεκμηρίωση.

Πριν από κάθε είσοδο, γράφεται στη βάση: η υπόθεση, τα δεδομένα, το
αντεπιχείρημα, το κριτήριο ακύρωσης, και το exit plan. **Μετά** την είσοδο
δεν επιτρέπεται τροποποίηση της υπόθεσης — μόνο επισήμανση ως
επαληθευμένη/διαψευσμένη.

### 4. Deflated μετρικές παντού

**Από:** López de Prado — το backtest overfitting συστηματικά υπο-αποδίδει
out-of-sample, και ένας agent κάνει το πρόβλημα χειρότερο κατά τάξεις μεγέθους.

Καμία στρατηγική δεν φτάνει σε live κεφάλαιο με βάση raw Sharpe. Κάθε δοκιμή
καταγράφεται σε trial registry ώστε το N να είναι σωστό.

### 5. Structural edge, όχι predictive edge

**Από:** AIEQ, Eurekahedge, Alpha Arena — η πρόβλεψη δεν δουλεύει.

Προτεραιότητα σε στρατηγικές όπου το κέρδος προέρχεται από **μηχανισμό της
αγοράς** (funding rates, spreads, ανεπάρκειες τιμολόγησης) και όχι από το
να μαντέψεις σωστά.

---

## Τοπολογία

```
┌──────────────────────────────────────────────────────────────┐
│                      GOVERNOR (κώδικας)                       │
│  Ντετερμινιστικός. Καμία απόφαση από LLM δεν τον παρακάμπτει. │
│  · Kill switch  · Trade budget  · Position limits             │
│  · Max drawdown  · Capital allocation ανά πυλώνα               │
└───────────────────────────┬──────────────────────────────────┘
                            │ εγκρίνει / απορρίπτει
        ┌───────────────────┴────────────────────┐
        │                                        │
┌───────▼─────────┐                    ┌─────────▼──────────┐
│  RESEARCH LAYER │                    │  EXECUTION LAYER   │
│      (LLM)      │  ── προτάσεις ──▶  │      (κώδικας)     │
└───────┬─────────┘                    └─────────┬──────────┘
        │                                        │
   ┌────┴──────────────┐              ┌──────────┴─────────┐
   │ Ingestion Agent   │              │ Order Router       │
   │ Analysis Agent    │              │ Position Manager   │
   │ Devil's Advocate  │              │ Reconciliation     │
   │ Risk Agent        │              └──────────┬─────────┘
   │ Validation Agent  │                         │
   └────┬──────────────┘              ┌──────────▼─────────┐
        │                             │  Broker / Exchange │
┌───────▼──────────────────────────┐  │  APIs              │
│  MEMORY & JOURNAL (Postgres)     │  └────────────────────┘
│  · Θέσεις + υποθέσεις             │
│  · Trial registry                 │◀──── post-mortems
│  · Post-mortems                   │
│  · Απόδοση ανά στρατηγική         │
└──────────────────────────────────┘
```

---

## Τα components αναλυτικά

### Governor — η μη διαπραγματεύσιμη δικλείδα

Απλός, καλά ελεγμένος κώδικας. **Δεν είναι agent.** Δεν έχει πρόσβαση σε LLM.

Επιβάλλει, χωρίς εξαιρέσεις:

| Έλεγχος | Ενδεικτική τιμή |
|---|---|
| Max μέγεθος θέσης | 5% του χαρτοφυλακίου |
| Max έκθεση ανά πυλώνα | κατά κατανομή (βλ. παρακάτω) |
| Max ημερήσιες συναλλαγές | Ρητό budget, π.χ. 5 |
| Max drawdown → auto halt | −15% από το peak |
| Ελάχιστη ρευστότητα venue | Κατώφλι πριν από είσοδο |
| Whitelist οργάνων | Ρητή λίστα· τίποτα εκτός |
| Whitelist venues | Ρητή λίστα |
| Kill switch | Χειροκίνητο, άμεσο, ρευστοποιεί τα πάντα |

> Ο Governor γράφεται **πρώτος** και δεν αλλάζει από το AI. Είναι το σημείο
> όπου η αρχιτεκτονική αναγνωρίζει ότι το LLM θα κάνει λάθος κάποια στιγμή,
> και το κάνει ανεκτό.

### Research Layer — οι agents

**Ingestion Agent** — Συλλέγει και δομεί: τιμές (ccxt, broker APIs), ειδήσεις,
on-chain δεδομένα, funding rates, όρους prediction markets. Έξοδος:
χρονοσφραγισμένα, κανονικοποιημένα γεγονότα. **Καμία κρίση, μόνο δεδομένα.**

**Analysis Agent** — Παράγει υποθέσεις με βάση τα δεδομένα. Έξοδος:
δομημένη πρόταση με πηγές.

**Devil's Advocate Agent** — Ξεχωριστό context, ρητή αποστολή να **γκρεμίσει**
την πρόταση. Ψάχνει: αντίθετα δεδομένα, γιατί το edge μπορεί να είναι
τεχνητό, τι υποθέσεις είναι εύθραυστες, τι tail risk αγνοήθηκε.

*Γιατί υπάρχει:* η Nof1 βρήκε ότι τα μοντέλα έχουν συνεπείς προκαταλήψεις —
μια επενδυτική «προσωπικότητα». Ένας δεύτερος agent με αντίθετη εντολή είναι
ο φθηνότερος τρόπος να τις εκθέσεις. Αν η πρόταση δεν επιβιώσει, δεν
προχωράει.

**Risk Agent** — Ποσοτικοποιεί: μέγιστη πιθανή απώλεια, συσχέτιση με
υπάρχουσες θέσεις, tail scenarios, position sizing με **fractional Kelly**
(ποτέ full Kelly — είναι πολύ επιθετικό στην πράξη).

**Validation Agent** — Ο φύλακας έναντι του overfitting. Τρέχει CPCV,
υπολογίζει Deflated Sharpe και PBO, ελέγχει το trial registry για το σωστό N.
**Έχει δικαίωμα veto.**

### Execution Layer — καθαρός κώδικας

Idempotent order placement (καμία διπλή εντολή σε retry). Reconciliation
μεταξύ τοπικής κατάστασης και κατάστασης exchange σε κάθε κύκλο. Slippage
tracking έναντι της αναμενόμενης τιμής. Αυτόματο retry με backoff, αλλά
**ποτέ αυτόματη αύξηση μεγέθους**.

### Memory & Journal — το «back up» των κινήσεων

Το κομμάτι που ζήτησες ρητά. Postgres, με schema:

```sql
-- Η υπόθεση, καταγεγραμμένη ΠΡΙΝ την είσοδο
positions (
  id, opened_at, instrument, venue, side, size, strategy_pillar,
  hypothesis        TEXT NOT NULL,   -- γιατί μπαίνουμε
  supporting_data   JSONB NOT NULL,  -- πηγές + snapshot δεδομένων
  counter_argument  TEXT NOT NULL,   -- τι λέει ο Devil's Advocate
  invalidation      TEXT NOT NULL,   -- τι θα την ακύρωνε
  exit_plan         TEXT NOT NULL,   -- ορισμένο εκ των προτέρων
  expected_edge_bps NUMERIC,
  risk_assessment   JSONB
);

-- Τι έγινε στην πραγματικότητα
post_mortems (
  position_id, closed_at, realized_pnl, slippage_bps,
  hypothesis_verified BOOLEAN,       -- επαληθεύτηκε;
  what_actually_happened TEXT,
  lesson TEXT,
  attribution JSONB                  -- δεξιότητα vs beta vs τύχη
);

-- ΚΑΘΕ δοκιμή στρατηγικής που έγινε ποτέ — για σωστό deflation
strategy_trials (
  id, tried_at, strategy_hash, params JSONB,
  raw_sharpe, deflated_sharpe, pbo,
  passed BOOLEAN, rejection_reason TEXT
);
```

Το `strategy_trials` είναι κρίσιμο: χωρίς πλήρη καταγραφή **κάθε** δοκιμής,
το Deflated Sharpe υπολογίζεται με λάθος N και δίνει ψευδή ασφάλεια.

---

## Κατανομή κεφαλαίου

Η δομή που προκύπτει από την κατάταξη του κεφαλαίου 01:

```
┌─────────────────────────────────────────────────────┐
│  CORE — 70%                                         │
│  Passive UCITS ETF, DCA + rebalancing                │
│  Ρόλος: αυτό είναι που πραγματικά χτίζει περιουσία   │
│  AI: ελάχιστο (timing rebalance, tax awareness)     │
├─────────────────────────────────────────────────────┤
│  SATELLITE — 25%                                    │
│  Crypto funding-rate arbitrage (delta-neutral)      │
│  Ρόλος: μη συσχετισμένη απόδοση 10–20% APY          │
│  AI: risk management, venue selection, regime exit  │
├─────────────────────────────────────────────────────┤
│  EXPLORATORY — 5%                                   │
│  Prediction markets / Betfair                       │
│  Ρόλος: εκεί που το AI έχει το μεγαλύτερο edge —    │
│         αλλά αναπόδεικτο. Κεφάλαιο που αντέχεις     │
│         να χάσεις εξ ολοκλήρου                       │
│  AI: μέγιστο                                        │
└─────────────────────────────────────────────────────┘
```

**Ο κανόνας ανάπτυξης:** ένας πυλώνας μεγαλώνει μόνο αφού αποδείξει
**deflated** απόδοση σε live κεφάλαιο για τουλάχιστον 6 μήνες. Όχι σε
backtest. Όχι σε paper trading. Σε πραγματικά χρήματα, με πραγματικό slippage.

Αν το exploratory 5% δείξει πραγματικό edge για 6 μήνες, γίνεται 10%. Αν
όχι, μηδενίζεται και δοκιμάζουμε κάτι άλλο.

---

## Stack

| Στρώμα | Επιλογή | Γιατί |
|---|---|---|
| Γλώσσα | Python 3.12 | Όλο το οικοσύστημα quant είναι εκεί |
| Orchestration | LangGraph ή Claude Agent SDK | Το LangGraph χρησιμοποιείται από το TradingAgents· το Agent SDK είναι πιο άμεσο |
| Crypto execution | `ccxt` | Ενιαίο API σε δεκάδες exchanges |
| Equities execution | `alpaca-py` ή IBKR API | Το Alpaca έχει δωρεάν, απεριόριστο paper trading με υψηλή πιστότητα |
| Backtesting | `vectorbt` ή custom | Ταχύτητα για CPCV — χιλιάδες runs |
| Validation | Custom (DSR, PBO, CPCV) | Δεν υπάρχει καλή έτοιμη βιβλιοθήκη· είναι ~300 γραμμές |
| Βάση | PostgreSQL + TimescaleDB | Χρονοσειρές + σχεσιακά στο ίδιο μέρος |
| Παρακολούθηση | Grafana + ειδοποιήσεις | Πρέπει να βλέπεις τι κάνει, πάντα |

**Έτοιμα projects για μελέτη** (όχι για production χρήση ως έχουν):
`TauricResearch/TradingAgents` (multi-agent LLM, LangGraph),
`FinRL` / `FinRL-X` (RL για trading), `Qlib` (Microsoft, quant platform),
`freqtrade` (crypto bot με σοβαρό backtesting), `nautilus_trader`
(event-driven, production-grade).

---

## Τι **δεν** χτίζουμε

Εξίσου σημαντικό:

- ❌ Directional price prediction με LLM — τρεις ανεξάρτητες πηγές δείχνουν ότι δεν δουλεύει
- ❌ HFT / latency arbitrage — δεν μπορούμε να ανταγωνιστούμε, και το LLM latency το αποκλείει
- ❌ Forex / CFD πυλώνα — δομικά αρνητικό EV
- ❌ Οτιδήποτε παράγει σήματα για τρίτους — ενεργοποιεί MiFID II
- ❌ Στρατηγικές που δεν καταλαβαίνουμε *γιατί* δουλεύουν — αν δεν υπάρχει μηχανισμός, είναι overfitting
