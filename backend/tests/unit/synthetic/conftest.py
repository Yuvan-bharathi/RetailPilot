"""Generate the small synthetic dataset once per test session."""

from pathlib import Path

import pytest

from data.synthetic.config import GeneratorConfig
from data.synthetic.generate import generate
from data.synthetic.reader import Dataset, load_dataset
from tests.unit.synthetic.planning import Planner


@pytest.fixture(scope="session")
def dataset_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("synthetic_small")
    generate(GeneratorConfig(profile="small"), out)
    return out


@pytest.fixture(scope="session")
def dataset(dataset_dir: Path) -> Dataset:
    return load_dataset(dataset_dir)


@pytest.fixture(scope="session")
def planner(dataset: Dataset) -> Planner:
    return Planner(dataset)
