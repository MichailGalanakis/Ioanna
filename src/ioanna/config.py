"""Live configuration: the decisions, in one place.

Each choice below is argued in the research docs. They are collected here so
there is a single file to change when one is revisited, and so the reasoning
travels with the value rather than living in a commit message.

The one number that is genuinely personal is `CONTRIBUTION_AMOUNT`. Everything
else follows from the research.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .core import ContributionSchedule, RebalanceBands, TargetAllocation
from .governor import Limits

D = Decimal


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstrumentSpec:
    """What the venue will actually accept for an instrument.

    `lot_size` is the smallest tradeable increment. It matters more than it
    looks: IBKR requires an instrument to clear $5m average daily volume and
    $5bn market cap before fractional trading is enabled for European stocks
    and ETFs, and many popular UCITS funds do not qualify. Planning a purchase
    of 3.87 shares of something that only trades in whole units produces an
    order the broker rejects, or worse, silently truncates.
    """

    symbol: str
    isin: str
    lot_size: Decimal
    currency: str = "EUR"
    description: str = ""

    @property
    def is_fractional(self) -> bool:
        return self.lot_size < 1


#: Vanguard FTSE All-World, accumulating, Irish-domiciled.
#:
#: Chosen over IWDA+EIMI: one fund covers developed and emerging together, so
#: the core needs no internal rebalancing and therefore generates no taxable
#: disposals of its own. The two-fund route saves about 2bp a year in TER --
#: €10 on €50,000 -- which a second commission each month more than spends.
#:
#: Accumulating is the non-negotiable part. Greek tax withholds 5% on
#: dividends as they are received, so a distributing share class creates a
#: taxable event every quarter for no benefit.
VWCE = InstrumentSpec(
    symbol="VWCE",
    isin="IE00BK5BQT80",
    lot_size=D("1"),  # assume whole shares until IBKR confirms otherwise
    currency="EUR",
    description="Vanguard FTSE All-World UCITS ETF (Acc)",
)


# ---------------------------------------------------------------------------
# The passive core
# ---------------------------------------------------------------------------

CORE_ALLOCATION = TargetAllocation({VWCE.symbol: D("1")})

#: The one number that depends on personal circumstances rather than research.
#:
#: Set at the point where IBKR's €3 commission floor stops dominating: at €650
#: the commission is 0.5% of the order, and it keeps falling from there. At
#: €500 it is 0.62% -- nearly three times the fund's own 0.22% expense ratio,
#: which is a strange thing to pay to access a cheap fund.
#:
#: If the affordable contribution is materially below this, the right response
#: is a different venue, not a smaller or less frequent contribution. Brokers
#: with free ETF savings plans exist; paying 1% in commissions to save 0.22%
#: in TER is a bad trade however good the fund is. See
#: `research.costs.minimum_viable_contribution`.
CONTRIBUTION_AMOUNT = D("650")

#: Monthly, not quarterly.
#:
#: Contributing less often pays the commission floor fewer times but leaves
#: cash uninvested while it waits. At retail sizes the second cost is larger:
#: monthly totals about 0.95% a year against quarterly's 1.22%, because a
#: month of foregone return on €6,000 exceeds the €3 saved. Verified in
#: `research.costs.contribution_frequency_cost`.
CONTRIBUTION_SCHEDULE = ContributionSchedule(
    amount=CONTRIBUTION_AMOUNT,
    day_of_month=1,
    # Three months of catch-up after downtime. Beyond that the missed
    # contributions are skipped rather than deferred -- returning from a long
    # outage should not put a year of contributions into one day's price.
    max_catch_up=3,
)

#: Swedroe's 5/25 rule. With a single-fund core nothing can drift against
#: anything, so these bind only once the satellite pillar exists and the core
#: has to be rebalanced against it.
CORE_BANDS = RebalanceBands(absolute=D("0.05"), relative=D("0.25"))

#: Minimum order value, set to the same 0.5% commission ceiling as the
#: contribution. A €300 rebalancing order pays 1% to correct a drift that is
#: almost certainly smaller than 1% -- the cure costing more than the disease.
MIN_ORDER = D("650")


# ---------------------------------------------------------------------------
# Venue
# ---------------------------------------------------------------------------

#: Interactive Brokers Ireland. The realistic choice for UCITS access from
#: Greece with an API: EU-domiciled after Brexit, €3 flat on Western European
#: stocks for typical order sizes, and a paper account that mirrors production.
VENUE = "ibkr"


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

#: Deliberately tighter than the system needs today.
#:
#: The core is a single fund, so `max_position_fraction` has to allow 100% or
#: nothing could be bought at all. That is safe only because the instrument
#: whitelist has one entry in it -- the concentration limit is doing no work
#: here, and the whitelist is doing all of it.
LIVE_LIMITS = Limits(
    max_position_fraction=D("1.0"),
    max_pillar_fraction={
        "core": D("1.0"),
        # Zero until Gate 2 and Gate 3 are passed. A pillar that cannot be
        # funded cannot trade, which is the intended state for anything that
        # has not yet demonstrated an edge with real money.
        "satellite": D("0"),
        "exploratory": D("0"),
    },
    # One contribution and at most one rebalance per day. The core has no
    # reason to trade more often, and the Alpha Arena failure mode was
    # overtrading.
    max_trades_per_day=2,
    max_drawdown=D("0.35"),
    min_liquidity_multiple=D("10"),
    max_state_age_seconds=300.0,
    allowed_venues=frozenset({VENUE}),
    allowed_instruments=frozenset({VWCE.symbol}),
)

#: Note the drawdown limit is 35%, not the 15% used for active strategies.
#:
#: A global equity index fell 34% in March 2020 and 55% in 2008. Halting a
#: passive core at 15% would liquidate at the bottom of an ordinary bear
#: market and call it risk management. The 35% level is not a view on
#: valuations -- it is a level a diversified index has historically only
#: breached in a genuine systemic event, which is the only case where a human
#: should be looking at this anyway.


INSTRUMENTS: dict[str, InstrumentSpec] = {VWCE.symbol: VWCE}


# ---------------------------------------------------------------------------
# Consistency
# ---------------------------------------------------------------------------


def validate() -> list[str]:
    """Check the config against itself and against the cost model.

    Configuration drifts. A limit gets loosened for a test, a contribution
    changes, and nothing complains because each value is individually valid --
    it is the relationships between them that break. This returns the
    problems rather than raising, so a caller can log them all at startup.
    """
    from .research.costs import IBKR_EUROPE, minimum_viable_contribution

    problems: list[str] = []

    if CONTRIBUTION_AMOUNT < MIN_ORDER:
        problems.append(
            f"contribution ({CONTRIBUTION_AMOUNT}) is below MIN_ORDER "
            f"({MIN_ORDER}): every cycle would round to nothing and carry "
            "forward forever"
        )

    viable = minimum_viable_contribution()
    if CONTRIBUTION_AMOUNT < viable:
        cost = IBKR_EUROPE.one_way_cost(CONTRIBUTION_AMOUNT) / CONTRIBUTION_AMOUNT
        problems.append(
            f"contribution ({CONTRIBUTION_AMOUNT}) pays {cost:.2%} in "
            f"commission; below {viable} a venue with free ETF savings plans "
            "beats IBKR"
        )

    for symbol in CORE_ALLOCATION.instruments:
        if symbol not in LIVE_LIMITS.allowed_instruments:
            problems.append(f"{symbol} is allocated but not whitelisted")
        if symbol not in INSTRUMENTS:
            problems.append(f"{symbol} has no instrument spec")

    if VENUE not in LIVE_LIMITS.allowed_venues:
        problems.append(f"venue {VENUE!r} is not whitelisted")

    if LIVE_LIMITS.max_pillar_fraction.get("core", D("0")) <= 0:
        problems.append("core pillar has no budget: nothing can be bought")

    # A single-instrument core needs a 100% position limit, which is only safe
    # because the whitelist has one entry. If the whitelist grows, this stops
    # being true and the limit has to come down with it.
    if (
        len(LIVE_LIMITS.allowed_instruments) > 1
        and LIVE_LIMITS.max_position_fraction >= D("1")
    ):
        problems.append(
            "max_position_fraction is 100% with more than one tradeable "
            "instrument: the concentration limit is doing no work"
        )

    return problems
