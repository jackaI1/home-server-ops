from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "mac-psync-smoke"


@pytest.fixture
def sample_dir(tmp_path):
    """A copy of the saved sample results, so a test can change files safely."""
    import shutil

    target = tmp_path / "results"
    shutil.copytree(SAMPLES, target)
    return target
