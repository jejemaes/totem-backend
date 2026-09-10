#!/usr/bin/env python3
"""Grade the totem-resource evals statically against a run's output tree.

Static checks rather than a judgement call: every assertion here is about the
presence or absence of a construct that this project's traps hinge on, so a
regex over the produced files is both faster and more reliable than reading, and
it stays comparable across iterations.

Usage: grade_evals.py <iteration-dir>
Writes grading.json into each <eval>/<config>/ directory.
"""
import json
import re
import sys
from pathlib import Path


def read_tree(outputs: Path) -> dict[str, str]:
    if not outputs.is_dir():
        return {}
    return {
        str(p.relative_to(outputs)): p.read_text(errors="replace")
        for p in outputs.rglob("*")
        if p.is_file()
    }


def joined(files: dict[str, str], pattern: str = r".*\.py$") -> str:
    rx = re.compile(pattern)
    return "\n".join(v for k, v in files.items() if rx.match(k))


def has(files, needle, pattern=r".*\.py$") -> bool:
    return needle in joined(files, pattern)


def rx(files, regex, pattern=r".*\.py$") -> bool:
    return re.search(regex, joined(files, pattern), re.S) is not None


def meta_fields_blocks(text: str) -> list[str]:
    """The body of every `fields = [...]` list, so we can test membership."""
    return re.findall(r"fields\s*=\s*\[(.*?)\]", text, re.S)


def grade_eval0(files):
    svc = joined(files, r".*services\.py$")
    api = joined(files, r".*api/.*\.py$")
    sec = joined(files, r".*security\.py$")
    fixtures = joined(files, r".*fixtures/.*\.json$")
    models = joined(files, r".*models/.*\.py$")
    redirect_service = re.search(
        r"class \w*Redirect\w*Service\((.*?)\):", svc, re.S
    )
    svc_bases = redirect_service.group(1) if redirect_service else ""
    return [
        (
            "RedirectService composes Create, Read and Delete but NOT UpdateMixin",
            bool(svc_bases)
            and "CreateMixin" in svc_bases
            and "ReadMixin" in svc_bases
            and "DeleteMixin" in svc_bases
            and "UpdateMixin" not in svc_bases,
            f"service bases: {' '.join(svc_bases.split())[:160]}" if svc_bases else "no Redirect service class found",
        ),
        (
            "The controller does not inherit ModelController (mixins composed explicitly)",
            bool(re.search(r"class \w*Redirect\w*Controller\(", api))
            and not re.search(r"class \w*Redirect\w*Controller\([^)]*\bModelController\b", api, re.S),
            "controller bases: "
            + " ".join(
                (re.search(r"class \w*Redirect\w*Controller\((.*?)\):", api, re.S) or re.match("", "")).group(1).split()
            )[:160]
            if re.search(r"class \w*Redirect\w*Controller\((.*?)\):", api, re.S)
            else "no Redirect controller found",
        ),
        (
            "permission_map declares an explicit 'delete' key, so DELETE is scoped",
            bool(re.search(r"permission_map\s*=\s*\{[^}]*[\"']delete[\"']", api, re.S)),
            "permission_map present with delete key" if re.search(r"permission_map\s*=\s*\{[^}]*[\"']delete[\"']", api, re.S) else "no scoped delete in permission_map",
        ),
        (
            "Scopes are registered in website/security.py following totem.<app><model>.<op>",
            bool(re.search(r"register_permission\(\s*[\"']totem\.websiteredirect\.", sec)),
            "; ".join(re.findall(r"register_permission\(\s*[\"']([^\"']+)", sec)) or "none",
        ),
        (
            "The new scopes are granted in at least one role fixture",
            "websiteredirect" in fixtures,
            "found in fixtures" if "websiteredirect" in fixtures else "no fixture grants the scope",
        ),
        (
            "The model uses ULIDField as its primary key",
            bool(re.search(r"ULIDField\(.*primary_key\s*=\s*True", models, re.S)),
            "ULIDField pk" if re.search(r"ULIDField\(.*primary_key\s*=\s*True", models, re.S) else "no ULID pk",
        ),
        (
            "A migration file was added",
            any(re.match(r".*migrations/\d{4}_.*\.py$", k) for k in files),
            "; ".join(k for k in files if "migrations/" in k) or "none",
        ),
        (
            "Tests were written for the new resource",
            any("tests/" in k and k.endswith(".py") and "__init__" not in k for k in files),
            "; ".join(k for k in files if "tests/" in k and k.endswith(".py")) or "none",
        ),
    ]


def grade_eval1(files):
    schemas = joined(files, r".*schemas/.*\.py$")
    models = joined(files, r".*models/.*\.py$")
    in_meta = any("theme_options" in b for b in meta_fields_blocks(schemas))
    return [
        (
            "theme_options is NOT listed in any schema Meta.fields (would raise ImproperlyConfigured at import)",
            bool(schemas) and not in_meta,
            "theme_options found inside a fields=[...] list" if in_meta else "absent from every fields=[...]",
        ),
        (
            "theme_options is declared by hand as a typed annotation on the schema",
            bool(re.search(r"theme_options\s*:\s*\w", schemas)),
            (re.search(r"theme_options\s*:\s*[^\n=]+", schemas) or re.match("", "")).group(0).strip()[:120]
            if re.search(r"theme_options\s*:\s*\w", schemas)
            else "no annotation found",
        ),
        (
            "theme's choices come from a module-level constant, not an autodiscovered registry",
            bool(re.search(r"choices\s*=", models)),
            (re.search(r"choices\s*=\s*[^\n,)]+", models) or re.match("", "")).group(0).strip()[:120]
            if re.search(r"choices\s*=", models)
            else "no choices on the field",
        ),
        (
            "A migration file was added",
            any(re.match(r".*migrations/\d{4}_.*\.py$", k) for k in files),
            "; ".join(k for k in files if "migrations/" in k) or "none",
        ),
        (
            "Both fields are exposed on the read and the update schema",
            schemas.count("theme_options") >= 2 and schemas.count('"theme"') + schemas.count("'theme'") >= 2,
            f"theme_options x{schemas.count('theme_options')}, theme x{schemas.count(chr(34)+'theme'+chr(34)) + schemas.count(chr(39)+'theme'+chr(39))}",
        ),
    ]


def grade_eval2(files):
    tests = joined(files, r".*tests/.*\.py$")
    keyset = bool(
        re.search(r"set\(fields\)\s*,?\s*\n?\s*set\(\s*\w+\.keys\(\)\s*\)", tests)
        or re.search(r"set\(\s*\w+\.keys\(\)\s*\)\s*,?\s*\n?\s*set\(fields\)", tests)
    )
    return [
        (
            "Uses CommonTestMixin and APITestCaseMixin",
            "CommonTestMixin" in tests and "APITestCaseMixin" in tests,
            "both present" if ("CommonTestMixin" in tests and "APITestCaseMixin" in tests) else "missing one",
        ),
        (
            "Defines an _assert_api_format helper",
            "def _assert_api_format" in tests,
            "defined" if "def _assert_api_format" in tests else "absent",
        ),
        (
            "_assert_api_format asserts the exact key set of the response",
            keyset,
            "key-set assertion present" if keyset else "no set(fields)==set(keys) assertion",
        ),
        (
            "Has permission tests parameterized over (scope, status_code)",
            bool(re.search(r"access_rights|requires_its_own_scope", tests))
            and "parameterized.expand" in tests,
            "present" if re.search(r"access_rights|requires_its_own_scope", tests) and "parameterized.expand" in tests else "absent",
        ),
        (
            "Declares module-level id constants and url/url_detail in setUpTestData",
            bool(re.search(r"^[A-Z][A-Z0-9_]*_ID\d*\s*=", tests, re.M))
            and "url_detail" in tests,
            "constants + url_detail" if re.search(r"^[A-Z][A-Z0-9_]*_ID\d*\s*=", tests, re.M) and "url_detail" in tests else "missing",
        ),
        (
            "Covers every operation the controller exposes, one section each",
            all(
                re.search(p, tests)
                for p in [r"def test_list", r"def test_retrieve", r"def test_create", r"def test_update", r"def test_delete"]
            ),
            "; ".join(sorted({m for m in re.findall(r"def (test_(?:list|retrieve|create|update|delete))\w*", tests)})) or "none",
        ),
    ]


GRADERS = {0: grade_eval0, 1: grade_eval1, 2: grade_eval2}


def main():
    iteration = Path(sys.argv[1])
    summary = []
    for eval_dir in sorted(iteration.glob("eval-*")):
        eval_id = int(eval_dir.name.split("-")[1])
        meta = json.loads((eval_dir / "eval_metadata.json").read_text())
        for config_dir in sorted(d for d in eval_dir.iterdir() if d.is_dir()):
            files = read_tree(config_dir / "outputs")
            results = GRADERS[eval_id](files)
            expectations = [
                {"text": text, "passed": bool(passed), "evidence": str(evidence)}
                for text, passed, evidence in results
            ]
            passed_n = sum(e["passed"] for e in expectations)
            grading = {
                "eval_id": eval_id,
                "eval_name": meta["eval_name"],
                "config": config_dir.name,
                "expectations": expectations,
                "passed": passed_n,
                "total": len(expectations),
                "pass_rate": passed_n / len(expectations) if expectations else 0.0,
            }
            (config_dir / "grading.json").write_text(json.dumps(grading, indent=2, ensure_ascii=False))
            summary.append((eval_dir.name, config_dir.name, passed_n, len(expectations)))

    print(f"{'eval':<10} {'config':<16} {'score':>8}")
    for name, config, p, t in summary:
        print(f"{name:<10} {config:<16} {p:>3}/{t:<4}")


if __name__ == "__main__":
    main()
