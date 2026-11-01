"""Additive operator recipes, published only after exact execution review.

This module is a local operator tool, never a customer workflow authoring path.
It neither seeds on startup nor alters existing templates or saved workflows.
"""

from copy import deepcopy
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit

from .capability_registry import digest
from .collector import usage
from .owned_data_agents.catalog import SPECS, tool_spec
from .owned_data_agents.service import PREFIX
from .owned_data_agents.staging import origin
from .workflow_templates import agent, bind_resources

VERSION = "operator-reviewed-templates-v1"


def definitions(base_url="https://agentconcierge.biz"):
    base_url = origin(base_url)

    def node(nid, selected, label, arguments, number):
        value = agent(
            nid,
            label,
            base_url + PREFIX + "/" + selected + "/mcp",
            SPECS[selected]["tool"],
            arguments,
            {"path": "content.0.text", "max_text": 12000},
            number,
        )
        value["data"]["operator_agent_id"] = selected
        return value

    def country(nid, code, number):
        return node(
            nid,
            "country-profile",
            "Country Profile: " + code,
            {"country_code": code},
            number,
        )

    def indicator(nid, parent, code, label, number):
        return node(
            nid,
            "economic-indicators",
            label,
            {
                "country_code": "{{$node['"
                + parent
                + "'].output.structuredContent.data.country_code}}",
                "indicator": code,
                "limit": 3,
            },
            number,
        )

    def package(nid, name, number):
        return node(
            nid,
            "package-metadata",
            name + " Current Release",
            {"package": name},
            number,
        )

    def advisory(nid, parent, label, number, version=None):
        return node(
            nid,
            "package-advisories",
            label,
            {
                "package": "{{$node['"
                + parent
                + "'].output.structuredContent.data.package}}",
                "version": version
                or "{{$node['" + parent + "'].output.structuredContent.data.version}}",
                "limit": 3,
            },
            number,
        )

    recipes = [
        (
            "country-development",
            "Country Development Snapshot",
            "Operator-provided workflow: retrieve a country profile and the latest available GDP, population and life-expectancy observations. Source years are included; these are annual records.",
            "data_utility",
            [
                country("country", "US", 1),
                indicator("gdp", "country", "NY.GDP.MKTP.CD", "GDP Observations", 2),
                indicator(
                    "population", "country", "SP.POP.TOTL", "Population Observations", 3
                ),
                indicator(
                    "life",
                    "country",
                    "SP.DYN.LE00.IN",
                    "Life Expectancy Observations",
                    4,
                ),
            ],
        ),
        (
            "country-comparison",
            "Two-Country Economic Comparison",
            "Operator-provided workflow: retrieve United States and South Korea country profiles and GDP observations in current USD. Compare the returned years before interpreting differences.",
            "data_utility",
            [
                country("first", "US", 1),
                indicator(
                    "first_gdp", "first", "NY.GDP.MKTP.CD", "United States GDP", 2
                ),
                country("second", "KR", 3),
                indicator(
                    "second_gdp", "second", "NY.GDP.MKTP.CD", "South Korea GDP", 4
                ),
            ],
        ),
        (
            "dependency-comparison",
            "Two-Package Security Comparison",
            "Operator-provided workflow: resolve current Express and Lodash releases, then check published advisories for each exact version. No returned advisory is not a guarantee of safety.",
            "dev_tools",
            [
                package("first", "express", 1),
                advisory("first_advisories", "first", "Express Release Advisories", 2),
                package("second", "lodash", 3),
                advisory("second_advisories", "second", "Lodash Release Advisories", 4),
            ],
        ),
        (
            "upgrade-advisories",
            "Package Upgrade Advisory Check",
            "Operator-provided workflow: compare published advisories for Express 4.17.1 and its current release. The package is not installed, executed or upgraded; compatibility still needs review.",
            "dev_tools",
            [
                package("package", "express", 1),
                advisory(
                    "installed",
                    "package",
                    "Installed Version 4.17.1 Advisories",
                    2,
                    "4.17.1",
                ),
                advisory("current", "package", "Current Release Advisories", 3),
            ],
        ),
        (
            "research-reading-list",
            "AI Research Reading List",
            "Operator-provided workflow: collect bibliographic records for retrieval-augmented generation and AI agent evaluation in separate reading lists. Preserve DOI links without generating scientific conclusions.",
            "docs_knowledge",
            [
                node(
                    "retrieval",
                    "research-papers",
                    "Retrieval-Augmented Generation Papers",
                    {"query": "retrieval augmented generation", "limit": 3},
                    1,
                ),
                node(
                    "evaluation",
                    "research-papers",
                    "AI Agent Evaluation Papers",
                    {"query": "artificial intelligence agent evaluation", "limit": 3},
                    2,
                ),
            ],
        ),
    ]
    result = []
    for slug, name, description, category, nodes in recipes:
        trigger = {
            "id": "start",
            "type": "trigger",
            "kind": "trigger",
            "name": "Manual Trigger",
            "position": {"x": 60, "y": 160},
            "data": {},
        }
        result.append(
            {
                "seed_key": VERSION + ":" + slug,
                "name": name,
                "description": description,
                "category": category,
                "trigger_type": "manual",
                "is_active": 1,
                "is_template": 0,
                "author": "Agent Concierge Operations",
                "rating_avg": 0,
                "tags": "operator-provided,read-only," + slug,
                "nodes": [trigger, *nodes],
                "edges": [
                    {
                        "id": "edge-" + str(i),
                        "source": left["id"],
                        "target": right["id"],
                    }
                    for i, (left, right) in enumerate(zip([trigger, *nodes], nodes))
                ],
            }
        )
    return deepcopy(result)


def fingerprint(workflow):
    """Compare recipe meaning across disposable and operating resource IDs."""
    return digest(
        {
            "name": workflow["name"],
            "description": workflow["description"],
            "category": workflow["category"],
            "trigger_type": workflow["trigger_type"],
            "nodes": [
                {
                    "id": n["id"],
                    "type": n["type"],
                    "name": n["name"],
                    "kind": n["kind"],
                    "data": {
                        k: n.get("data", {}).get(k)
                        for k in (
                            "operator_agent_id",
                            "action",
                            "input",
                            "output_select",
                        )
                    },
                }
                for n in workflow["nodes"]
            ],
            "edges": workflow["edges"],
        }
    )


def review(proof_db, *, now=None, recipes=None):
    """Read exact recent successful runs; failed candidates never gain publication."""
    now = time.time() if now is None else now
    approved = {}
    with sqlite3.connect(
        Path(proof_db).resolve().as_uri() + "?mode=ro", uri=True
    ) as db:
        db.row_factory = sqlite3.Row
        for recipe in (recipes or definitions)():
            marker = db.execute(
                "SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?",
                (recipe["seed_key"],),
            ).fetchone()
            if not marker:
                continue
            run = db.execute(
                "SELECT * FROM workflow_runs WHERE workflow_id=? ORDER BY created DESC LIMIT 1",
                (marker[0],),
            ).fetchone()
            if (
                not run
                or run["status"] != "succeeded"
                or not run["finished"]
                or not 0 <= now - run["finished"] < 86400
            ):
                continue
            snapshot = json.loads(run["snapshot"])
            if digest(snapshot) != run["digest"] or fingerprint(
                snapshot
            ) != fingerprint(recipe):
                continue
            valid = True
            for n in snapshot["nodes"]:
                if n["type"] == "trigger":
                    continue
                outcome = db.execute(
                    "SELECT * FROM workflow_node_runs WHERE run_id=? AND node_id=?",
                    (run["id"], n["id"]),
                ).fetchone()
                rid = n.get("resource_id") or n["data"].get("resource_id")
                resource = db.execute(
                    "SELECT * FROM resources WHERE id=?", (rid,)
                ).fetchone()
                tools = [tool_spec(n["data"]["operator_agent_id"])]
                pin = snapshot["bindings"].get(n["id"], {})
                if (
                    not outcome
                    or outcome["status"] != "succeeded"
                    or outcome["attempts"] != 1
                    or not outcome["output"]
                    or not resource
                    or resource["kind"] != "mcp"
                    or resource["url"] != n["data"]["resource_ref"]["url"]
                    or urlsplit(resource["url"]).path
                    != PREFIX + "/" + n["data"]["operator_agent_id"] + "/mcp"
                    or not resource["active"]
                    or json.loads(resource["usage_full_tools"] or "[]") != tools
                    or resource["usage_tools_hash"]
                    != usage.tools_hash(usage.compact_tools(tools))
                    or pin.get("usage_tools_hash") != resource["usage_tools_hash"]
                ):
                    valid = False
                    break
            if valid:
                approved[recipe["seed_key"]] = {
                    "run_id": run["id"],
                    "finished": run["finished"],
                    "fingerprint": fingerprint(recipe),
                }
    return approved


def install(
    store,
    proof_db,
    *,
    base_url="https://agentconcierge.biz",
    recipes=None,
    minimum_per_category=None,
):
    """Publish only reviewed additions, atomically and idempotently.

    Every operating binding is checked again in the write transaction. Existing
    template definitions, customer workflows, schedules and history are untouched.
    """
    from .concierge.execution_availability import workflow_execution_availability

    factory = recipes or definitions
    approved = review(proof_db, recipes=factory)
    if not approved:
        raise ValueError("No exact successful operator template executions qualify.")
    proof_hash = hashlib.sha256(Path(proof_db).read_bytes()).hexdigest()
    result = []
    with store.tx() as db:
        if minimum_per_category:
            from .workflows import public_template

            existing, _ = store.list_workflows(
                is_template=1, active_only=True, limit=1000
            )
            counts = Counter(
                w["category"]
                for w in existing
                if public_template(w)
                and workflow_execution_availability(store, w)["available"]
            )
            for candidate in factory(base_url):
                prior = db.execute(
                    "SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?",
                    (candidate["seed_key"],),
                ).fetchone()
                if not prior and candidate["seed_key"] in approved:
                    counts[candidate["category"]] += 1
            if any(
                counts[key] < minimum for key, minimum in minimum_per_category.items()
            ):
                raise ValueError(
                    "Successful templates do not meet the required category minimums."
                )
        for recipe in factory(base_url):
            key = recipe["seed_key"]
            if key not in approved:
                continue
            prior = db.execute(
                "SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?",
                (key,),
            ).fetchone()
            if prior:
                current = store.get_workflow(prior[0])
                if not current or fingerprint(current) != fingerprint(recipe):
                    raise ValueError(
                        "An existing operator recipe changed; review without replacing it."
                    )
                result.append(
                    {"id": prior[0], "name": current["name"], "created": False}
                )
                continue
            bind_resources(store, recipe)
            for n in recipe["nodes"][1:]:
                resource = (
                    store.resource(n.get("resource_id"))
                    if n.get("resource_id")
                    else None
                )
                identity = n["data"]["operator_agent_id"]
                tools = [tool_spec(identity)]
                if (
                    not resource
                    or resource["key"] != "agentconcierge-owned:" + identity
                    or resource["source"] != "agentconcierge-owned"
                    or resource.get("usage_full_hash") != digest(tools)
                    or resource.get("usage_tools_hash")
                    != usage.tools_hash(usage.compact_tools(tools))
                ):
                    raise ValueError(
                        "A required owned-agent binding or schema needs review."
                    )
            if not workflow_execution_availability(store, recipe)["available"]:
                raise ValueError(
                    "A required workflow connection is currently unavailable."
                )
            identity = _insert_workflow(db, recipe)
            db.execute(
                "INSERT INTO workflow_seed_registry VALUES (?,?)", (key, identity)
            )
            evidence = {
                **approved[key],
                "workflow_id": identity,
                "published_at": time.time(),
                "proof_sha256": proof_hash,
            }
            db.execute(
                "INSERT OR REPLACE INTO meta VALUES (?,?)",
                (key, json.dumps(evidence, sort_keys=True)),
            )
            result.append({"id": identity, "name": recipe["name"], "created": True})
    return result


def _insert_workflow(db, recipe):
    # Reuse Store's fixed insert contract without entering a nested SQLite
    # connection context, which would prematurely commit the outer transaction.
    from .gateway.store import _graph_to_steps

    now = time.time()
    packed = json.dumps(
        {
            "nodes": recipe["nodes"],
            "edges": recipe["edges"],
            "steps": _graph_to_steps(recipe["nodes"], recipe["edges"]),
        }
    )
    cursor = db.execute(
        """INSERT INTO agent_workflows (
                    name, description, category, trigger_type, steps, tags, is_active,
                    is_template, author, author_wallet, parent_workflow_id,
                    forks_count, likes_count, runs_count, rating_avg,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            recipe["name"],
            recipe["description"],
            recipe["category"],
            "manual",
            packed,
            recipe["tags"],
            1,
            1,
            recipe["author"],
            "",
            None,
            0,
            0,
            0,
            0,
            now,
            now,
        ),
    )
    return cursor.lastrowid
