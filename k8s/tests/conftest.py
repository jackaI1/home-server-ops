import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1] / "charts" / "home-ops"
SECRET = "postgres-credentials"


def helm_template(tmp_path, values=None, extra_args=()):
    """Render the chart with helm and return every document as a dict."""
    if shutil.which("helm") is None:
        pytest.fail("helm is required for these tests (brew install helm, or azure/setup-helm in CI)")
    values_file = tmp_path / "values.yaml"
    base = {"postgres": {"existingSecret": SECRET}}
    values_file.write_text(yaml.safe_dump(_merge(base, values or {})))
    result = subprocess.run(
        ["helm", "template", "home-ops", str(CHART), "--namespace", "home-ops",
         "-f", str(values_file), *extra_args],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _merge(base, override):
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def find(docs, kind, name):
    matches = [d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name]
    assert len(matches) == 1, f"expected one {kind}/{name}, found {len(matches)}"
    return matches[0]


@pytest.fixture
def render(tmp_path):
    def _render(values=None, extra_args=()):
        return helm_template(tmp_path, values, extra_args)
    return _render
