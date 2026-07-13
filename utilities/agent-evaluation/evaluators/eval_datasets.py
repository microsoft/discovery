"""Dataset discovery, scope resolution, and Foundry-dataset assembly helpers.

These are the reusable, side-effect-free pieces the evaluation pipeline uses to:
  - discover which evaluation scopes a project supports (data-driven: a scope
    "<name>" is backed by a "<name>-evaluators.json" dataset file),
  - resolve a scope's dataset file (project-specific first, then default/),
  - mint a fresh, length-bounded investigation id per run,
  - assemble a Foundry-compatible combined dataset from captured response rows.

A scope requires NO code change to add: just drop a "<scope>-evaluators.json"
dataset file under the project directory or default/. Conventional scopes are
shared, tool-calling, and retrieval.
"""

import random
import re
import time
from pathlib import Path

# A scope "<scope>" is backed by a dataset file "<scope>-evaluators.json".
DATASET_SUFFIX = "-evaluators.json"

_INVESTIGATION_NAME_MAX = 24
_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
# Length of the random collision-breaking suffix (base-36 characters).
_INVESTIGATION_RAND_LEN = 3


def scope_filename(scope: str) -> str:
    """Dataset filename backing a scope (uniform: '<scope>-evaluators.json')."""
    return f"{scope}{DATASET_SUFFIX}"


def discover_scopes(datasets_dir: Path, project: str) -> list[str]:
    """All scopes available to a project: the union of '<scope>-evaluators.json'
    files in the project directory and in default/ (project overrides default)."""
    scopes: set[str] = set()
    for directory in (datasets_dir / project, datasets_dir / "default"):
        if directory.is_dir():
            for path in directory.glob(f"*{DATASET_SUFFIX}"):
                scopes.add(path.name[: -len(DATASET_SUFFIX)])
    return sorted(scopes)


def parse_scopes(raw: str, available: list[str]) -> list[str]:
    """Resolve a user's scope selection against the scopes actually available
    (discovered from dataset files). 'all' expands to every available scope."""
    if raw.strip().lower() == "all":
        return list(available)
    scopes = []
    for token in raw.split(","):
        scope = token.strip().lower()
        if not scope:
            continue
        if scope not in available:
            print(f"WARNING: scope '{scope}' has no '{scope_filename(scope)}' "
                  f"dataset for this project or in default/ (skipped). "
                  f"Available: {', '.join(available) or '(none)'}, all")
            continue
        scopes.append(scope)
    return scopes


def resolve_dataset(scope: str, datasets_dir: Path, project: str) -> Path | None:
    """Resolve a scope's dataset file: project-specific first, then default/."""
    filename = scope_filename(scope)
    project_path = datasets_dir / project / filename
    default_path = datasets_dir / "default" / filename
    if project_path.is_file():
        return project_path
    if default_path.is_file():
        return default_path
    print(f"  WARNING: no {filename} for project '{project}' or in default/ -- skipping scope")
    return None


def _to_base36(value: int) -> str:
    """Compact, lexicographically-sortable base-36 encoding of a non-negative int
    (values of equal magnitude keep equal width, so string order == numeric order)."""
    if value == 0:
        return "0"
    digits = ""
    while value:
        value, rem = divmod(value, 36)
        digits = _BASE36[rem] + digits
    return digits


def make_investigation_name(prefix: str, agent: str) -> str:
    """Build a fresh, unique investigation id for a pipeline run.

    Discovery requires investigation ids to be 3-24 characters containing only
    letters, digits, and hyphens. One investigation is created per agent per run
    so evaluation traffic stays isolated from any user/production investigations.

    Naming schema: ``<prefix>-<timestamp>-<agent>-<rand>`` where

      - ``prefix``    is a fixed, sanitized label (e.g. "eval") shared by every
        run, so it does not disturb ordering.
      - ``timestamp`` is a base-36 encoding of the current epoch seconds placed
        directly after the prefix. Because it is the first varying component and
        base-36 preserves numeric order, sorting the ids in *descending* order
        puts the newest investigation on top.
      - ``agent``     is the (possibly truncated) agent slug, so the name carries
        a recognizable part of the agent it belongs to.
      - ``rand``      is a short random base-36 suffix that breaks collisions when
        two runs of the same agent start within the same second.

    The agent slug is truncated as needed so the whole id stays within the
    24-character budget.
    """
    pfx = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-") or "eval"
    agent_slug = re.sub(r"[^a-z0-9]+", "-", agent.lower()).strip("-")
    stamp = _to_base36(int(time.time()))
    rand = "".join(random.choice(_BASE36) for _ in range(_INVESTIGATION_RAND_LEN))
    # Reserve room for prefix, stamp, rand suffix, and three hyphen separators.
    avail = _INVESTIGATION_NAME_MAX - len(pfx) - len(stamp) - len(rand) - 3
    agent_slug = agent_slug[: max(0, avail)].strip("-")
    parts = [p for p in (pfx, stamp, agent_slug, rand) if p]
    return "-".join(parts)[:_INVESTIGATION_NAME_MAX].strip("-")


def ground_truth_fields(src_row: dict) -> dict:
    """Everything in a source dataset row except 'query' and doc-only ('_') keys
    is treated as ground truth to carry into the captured eval row."""
    return {k: v for k, v in src_row.items() if k != "query" and not k.startswith("_")}


def build_data_mapping(rows: list[dict]) -> dict:
    """Map every field present in the captured rows to an {{item.*}} reference so
    the offline evaluators read the captured response and ground-truth columns."""
    mapping: dict = {}
    for row in rows:
        for key in row:
            if key.startswith("_"):
                continue
            mapping.setdefault(key, f"{{{{item.{key}}}}}")
    return mapping


def augment_evaluator_parameters(config: dict, deployment_name: str | None) -> dict:
    """Inject initialization params (deployment_name + pass_threshold) for any
    custom (non-builtin) evaluator that does not already define them, preserving
    any explicit evaluator_parameters from the dataset.

    Scope-agnostic: only the dataset's evaluator list drives behavior, so a
    custom evaluator works in any scope.
    """
    params = dict(config.get("evaluator_parameters", {}))
    for evaluator in config.get("evaluators", []):
        if evaluator.startswith("builtin.") or evaluator in params:
            continue
        params[evaluator] = {"deployment_name": deployment_name, "pass_threshold": 0.5}
    return params


def build_dataset(scope: str, config: dict, eval_rows: list[dict],
                  deployment_name: str | None) -> dict:
    """Assemble a Foundry-compatible combined dataset from captured eval rows.

    Carries the scope's selected evaluators (and any custom evaluator params)
    from the source dataset config, maps every captured field to {{item.*}}, and
    embeds the captured rows as static data.
    """
    dataset = {
        "name": f"investigation-{scope}",
        "evaluators": config.get("evaluators", []),
        "data_mapping": build_data_mapping(eval_rows),
        "data": eval_rows,
    }
    params = augment_evaluator_parameters(config, deployment_name)
    if params:
        dataset["evaluator_parameters"] = params
    return dataset
