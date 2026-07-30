# Ioanna — Agentic Investment Research

Έρευνα και αρχιτεκτονική για ένα **agentic AI σύστημα αυτόματων επενδύσεων**.

Το repo δεν περιέχει (ακόμα) κώδικα που εκτελεί συναλλαγές. Περιέχει τη
βάση έρευνας πάνω στην οποία θα χτιστεί το σύστημα — γιατί το ζητούμενο
ήταν ρητά «να βασίζεται σε έρευνα και εκπαίδευση ώστε να κάνει back up τις
επενδυτικές του κινήσεις».

## Δομή

| Αρχείο | Περιεχόμενο |
|---|---|
| [`research/01-landscape.md`](research/01-landscape.md) | Όλοι οι τρόποι επένδυσης: μετοχές, ETF, forex/CFD, crypto, στοίχημα, prediction markets, DeFi, ακίνητα, ομόλογα — με ρεαλιστικές αποδόσεις και ποσοστά ζημιάς |
| [`research/02-ai-edge.md`](research/02-ai-edge.md) | Πού το AI έχει **αποδεδειγμένο** edge και πού όχι. Τι λένε τα πραγματικά δεδομένα (Alpha Arena, AIEQ, AI hedge funds) |
| [`research/03-copy-trading.md`](research/03-copy-trading.md) | Copy trading: πώς λειτουργεί, τα νούμερα, το ρυθμιστικό πλαίσιο, και πώς το AI μπορεί να βοηθήσει πραγματικά |
| [`research/04-architecture.md`](research/04-architecture.md) | Η προτεινόμενη αρχιτεκτονική του agentic συστήματος |
| [`research/05-roadmap.md`](research/05-roadmap.md) | Σταδιακό πλάνο υλοποίησης, με gates που πρέπει να περαστούν πριν μπουν πραγματικά χρήματα |
| [`research/06-regulatory-tax.md`](research/06-regulatory-tax.md) | Νομικό/φορολογικό πλαίσιο (ΕΕ + Ελλάδα) |
| [`research/sources.md`](research/sources.md) | Πηγές |

## Το βασικό συμπέρασμα σε τρεις γραμμές

1. Το AI **δεν** προβλέπει τιμές αξιόπιστα. Στο μοναδικό live πείραμα με
   frontier μοντέλα (Alpha Arena, Hyperliquid), 4 στα 6 έχασαν χρήματα και
   το PnL κυριαρχήθηκε από προμήθειες υπερ-συναλλαγών.
2. Το AI **έχει** πραγματικό edge σε: επεξεργασία κειμένου/ειδήσεων σε
   κλίμακα, εντοπισμό ασυνεπειών τιμολόγησης, πειθαρχία εκτέλεσης, έρευνα
   και τεκμηρίωση, risk management, και αξιολόγηση copy-trading providers.
3. Η βιώσιμη διαδρομή είναι **market-neutral / arbitrage-style στρατηγικές
   με μετρήσιμο edge**, όχι directional πρόβλεψη — με passive core ως βάση.

## Στάτους

Φάση έρευνας ολοκληρωμένη. Επόμενο βήμα: επιλογή στρατηγικού πυλώνα και
υλοποίηση του research/backtest harness (Φάση 1 του roadmap).
