import json

from anemone_shell import AnemoneShell
from tools.background3.build_index import build_index


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _background(tmp_path):
    folder = tmp_path / "background3"
    gravity = {
        "name": "gravity",
        "kind": "concept",
        "taxonomy": {
            "kingdom": "science",
            "phylum": "physics",
            "family": "interaction",
            "order": "fundamental_interaction",
            "genus": "gravitation",
            "species": "newtonian_gravity",
            "type": "force_model",
            "name": "gravity",
        },
        "traits": {"fundamental": True},
        "facts": [["gravity", "causes", "acceleration"]],
        "taxonomy_facts": [
            ["gravity", "belongs", "force_model"],
            ["force_model", "belongs", "newtonian_gravity"],
            ["newtonian_gravity", "belongs", "gravitation"],
            ["gravitation", "belongs", "fundamental_interaction"],
            ["fundamental_interaction", "belongs", "interaction"],
            ["interaction", "belongs", "physics"],
            ["physics", "belongs", "science"],
        ],
        "formulas": ["F=G*m1*m2/r^2"],
    }
    acceleration = {
        "name": "acceleration",
        "kind": "concept",
        "taxonomy": {"kingdom": "science", "phylum": "physics", "name": "acceleration"},
        "facts": [["acceleration", "changes", "velocity"]],
        "taxonomy_facts": [],
    }
    _write_jsonl(folder / "taxonomy" / "physics.jsonl", [gravity, acceleration])
    _write_jsonl(
        folder / "connector_seeds.jsonl",
        [{"relation": "causes", "kind": "connector", "seed": "causes", "variants": ["causes", "brings about"]}],
    )
    (folder / "manifest.json").write_text('{"version":"test"}\n', encoding="utf-8")
    build_index(str(folder))
    return folder


def test_lookup_taxonomy_and_connector(tmp_path, capsys):
    shell = AnemoneShell(_background(tmp_path))

    assert shell.cmd_lookup("gravity") == 0
    out = capsys.readouterr().out
    assert "[gravity causes acceleration]" in out
    assert "F=G*m1*m2/r^2" in out

    assert shell.cmd_taxonomy("gravity") == 0
    out = capsys.readouterr().out
    assert "kingdom  science" in out
    assert "[physics belongs science]" in out

    assert shell.cmd_connector("causes") == 0
    out = capsys.readouterr().out
    assert "brings about" in out


def test_overlap_bridge_and_chain(tmp_path, capsys):
    shell = AnemoneShell(_background(tmp_path))

    assert shell.cmd_bridge("gravity", "velocity", max_depth=3) == 0
    out = capsys.readouterr().out
    assert "[gravity causes acceleration]" in out
    assert "[acceleration changes velocity]" in out

    assert shell.cmd_chain(["gravity causes acceleration", "acceleration changes velocity"]) == 0
    assert "chain: valid" in capsys.readouterr().out

    assert shell.cmd_chain(["gravity causes acceleration", "velocity changes speed"]) == 1
    assert "hinge mismatch" in capsys.readouterr().out
