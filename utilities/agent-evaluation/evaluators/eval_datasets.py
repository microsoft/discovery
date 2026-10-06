"""Dataset discovery, suite resolution, and Foundry-dataset assembly helpers.

These are the reusable, side-effect-free pieces the evaluation pipeline uses to:
  - discover which evaluation suites a dataset directory supports (data-driven:
    a suite "<name>" is backed by a "<name>-evaluators.json" dataset file),
  - resolve a suite's dataset file from the dataset directory,
  - mint a fresh, length-bounded investigation id per run,
  - assemble a Foundry-compatible combined dataset from captured response rows.

A suite requires NO code change to add: just drop a "<suite>-evaluators.json"
dataset file into the dataset directory. Conventional suites are shared,
tool-calling, and retrieval.
"""

import random
import re
import time
from pathlib import Path

# A suite "<suite>" is backed by a dataset file "<suite>-evaluators.json".
DATASET_SUFFIX = "-evaluators.json"

_INVESTIGATION_NAME_MAX = 24
_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
# Length of the random collision-breaking suffix (base-36 characters).
_INVESTIGATION_RAND_LEN = 3


def suite_filename(suite: str) -> str:
    """Dataset filename backing a suite (uniform: '<suite>-evaluators.json')."""
    return f"{suite}{DATASET_SUFFIX}"


def discover_suites(dataset_dir: Path) -> list[str]:
    """All suites available in a dataset directory: every '<suite>-evaluators.json'
    file found directly inside it."""
    suites: set[str] = set()
    if dataset_dir.is_dir():
        for path in dataset_dir.glob(f"*{DATASET_SUFFIX}"):
            suites.add(path.name[: -len(DATASET_SUFFIX)])
    return sorted(suites)


def parse_suites(raw: str, available: list[str]) -> list[str]:
    """Resolve a user's suite selection against the suites actually available
    (discovered from dataset files). 'all' expands to every available suite."""
    if raw.strip().lower() == "all":
        return list(available)
    suites = []
    for token in raw.split(","):
        suite = token.strip().lower()
        if not suite:
            continue
        if suite not in available:
            print(f"WARNING: suite '{suite}' has no '{suite_filename(suite)}' "
                  f"dataset in the dataset directory (skipped). "
                  f"Available: {', '.join(available) or '(none)'}, all")
            continue
        suites.append(suite)
    return suites


def resolve_dataset(suite: str, dataset_dir: Path) -> Path | None:
    """Resolve a suite's dataset file from the dataset directory."""
    filename = suite_filename(suite)
    path = dataset_dir / filename
    if path.is_file():
        return path
    print(f"  WARNING: no {filename} in {dataset_dir} -- skipping suite")
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

    Suite-agnostic: only the dataset's evaluator list drives behavior, so a
    custom evaluator works in any suite.
    """
    params = dict(config.get("evaluator_parameters", {}))
    for evaluator in config.get("evaluators", []):
        if evaluator.startswith("builtin.") or evaluator in params:
            continue
        params[evaluator] = {"deployment_name": deployment_name, "pass_threshold": 0.5}
    return params


def build_dataset(suite: str, config: dict, eval_rows: list[dict],
                  deployment_name: str | None) -> dict:
    """Assemble a Foundry-compatible combined dataset from captured eval rows.

    Carries the suite's selected evaluators (and any custom evaluator params)
    from the source dataset config, maps every captured field to {{item.*}}, and
    embeds the captured rows as static data.
    """
    dataset = {
        "name": f"investigation-{suite}",
        "evaluators": config.get("evaluators", []),
        "data_mapping": build_data_mapping(eval_rows),
        "data": eval_rows,
    }
    params = augment_evaluator_parameters(config, deployment_name)
    if params:
        dataset["evaluator_parameters"] = params
    return dataset
