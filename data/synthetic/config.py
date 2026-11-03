"""Generator configuration: seed, size profile, history window and which scenarios to plant."""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    n_products: int
    days: int
    bills_per_store_day: int


PROFILES: dict[str, Profile] = {
    "full": Profile(name="full", n_products=300, days=180, bills_per_store_day=500),
    "small": Profile(name="small", n_products=80, days=120, bills_per_store_day=200),
    "tiny": Profile(name="tiny", n_products=30, days=60, bills_per_store_day=60),
}

ALL_SCENARIOS: frozenset[int] = frozenset({1, 2, 3, 4, 5})


@dataclass(frozen=True, slots=True)
class GeneratorConfig:
    profile: Profile | str = "full"
    seed: int = 42
    end_date: date = date(2026, 11, 2)  # last day of history; the nightly run is for the next day
    scenarios: frozenset[int] = ALL_SCENARIOS

    @property
    def resolved_profile(self) -> Profile:
        return PROFILES[self.profile] if isinstance(self.profile, str) else self.profile

    @property
    def start_date(self) -> date:
        return self.end_date - timedelta(days=self.resolved_profile.days - 1)

    @property
    def run_date(self) -> date:
        return self.end_date + timedelta(days=1)

    @property
    def days(self) -> list[date]:
        return [self.start_date + timedelta(days=i) for i in range(self.resolved_profile.days)]
