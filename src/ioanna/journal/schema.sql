-- Journal schema.
--
-- Two rules are enforced here rather than in application code, because both
-- are rules about honesty and honesty enforced by convention decays:
--
--   1. A position cannot exist without a written hypothesis, a counter
--      argument, an invalidation condition and an exit plan. NOT NULL plus a
--      length check, so "TBD" and "" do not qualify.
--
--   2. Once written, those fields cannot be edited. A trigger blocks the
--      update. Without this the record silently becomes a place to write down
--      why the trade was always going to work, which is worse than keeping no
--      record at all -- it manufactures evidence of foresight.

CREATE TABLE IF NOT EXISTS positions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at         TEXT    NOT NULL,
    instrument        TEXT    NOT NULL,
    venue             TEXT    NOT NULL,
    side              TEXT    NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity          TEXT    NOT NULL,
    entry_price       TEXT    NOT NULL,
    strategy_pillar   TEXT    NOT NULL,

    -- Written before entry. Immutable after.
    hypothesis        TEXT    NOT NULL CHECK (length(trim(hypothesis))       >= 20),
    supporting_data   TEXT    NOT NULL,
    counter_argument  TEXT    NOT NULL CHECK (length(trim(counter_argument)) >= 20),
    invalidation      TEXT    NOT NULL CHECK (length(trim(invalidation))     >= 10),
    exit_plan         TEXT    NOT NULL CHECK (length(trim(exit_plan))        >= 10),
    expected_edge_bps REAL,
    risk_assessment   TEXT,

    closed_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_positions_open
    ON positions (closed_at) WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_positions_pillar
    ON positions (strategy_pillar);

-- What actually happened. Separate table so the outcome can never be written
-- in the same statement as the hypothesis.
CREATE TABLE IF NOT EXISTS post_mortems (
    position_id            INTEGER PRIMARY KEY REFERENCES positions (id),
    closed_at              TEXT    NOT NULL,
    exit_price             TEXT    NOT NULL,
    realized_pnl           TEXT    NOT NULL,
    slippage_bps           REAL,

    -- The question the journal exists to answer. Deliberately separate from
    -- whether the trade made money: being right for the wrong reason and
    -- being wrong but lucky are different outcomes, and only one of them
    -- should encourage doing it again.
    hypothesis_verified    INTEGER NOT NULL CHECK (hypothesis_verified IN (0, 1)),
    what_actually_happened TEXT    NOT NULL CHECK
                                   (length(trim(what_actually_happened)) >= 20),
    lesson                 TEXT,
    attribution            TEXT
);

-- Immutability. SQLite has no column-level permissions, so a trigger it is.
CREATE TRIGGER IF NOT EXISTS positions_hypothesis_is_immutable
BEFORE UPDATE OF
    hypothesis, supporting_data, counter_argument, invalidation,
    exit_plan, expected_edge_bps, risk_assessment,
    instrument, venue, side, quantity, entry_price, strategy_pillar, opened_at
ON positions
BEGIN
    SELECT RAISE(
        ABORT,
        'the pre-trade record is immutable: hypotheses cannot be revised after entry'
    );
END;

-- A position closes exactly once.
CREATE TRIGGER IF NOT EXISTS positions_close_once
BEFORE UPDATE OF closed_at ON positions
WHEN OLD.closed_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'position is already closed');
END;
