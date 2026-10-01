import json
import tempfile
from pathlib import Path

from formfill.source import load_source

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "source.json"


def test_loads_flat_json():
    source = load_source(FIXTURE)
    assert source == {
        "full_name": "Jane Doe",
        "date_of_birth": "1998-04-15",
        "email": "jane@example.com",
    }


def test_flattens_nested_objects_and_lists():
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as fh:
        json.dump({"a": {"b": "c"}, "items": [{"x": 1}, {"x": 2}], "skip_me": None}, fh)
        path = Path(fh.name)
    source = load_source(path)
    assert source["a.b"] == "c"
    assert source["items.0.x"] == 1
    assert source["items.1.x"] == 2
    assert "skip_me" not in source
