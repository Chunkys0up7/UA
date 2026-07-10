"""Loan data-plane endpoints (specs/12 §3). Reads come from the run
registry (CaseRun) + the audit ledger; demographics are stripped at
intake into the isolated store (HR-6) and exposed ONLY via the
monitoring extract (FR-HMD-4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from jsonschema import Draft202012Validator

from app.agent import graph as agent_graph
from app.audit.snapshot import replay
from app.audit.verify import verify_chain
from app.hmda.demographics import DemographicsStore, strip_demographics
from app.logging_config import get_logger

log = get_logger(__name__)
router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_DIR = REPO_ROOT / "data" / "loans"
AUDIT_DB = REPO_ROOT / "data" / "db" / "audit.db"
PACKS_ROOT = REPO_ROOT / "policy" / "packs"
_SCHEMA = json.loads(
    (REPO_ROOT / "specs" / "schemas" / "loan-package.schema.json")
    .read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)
_demographics = DemographicsStore(REPO_ROOT / "data" / "db" / "loans.db")


def _error(status: int, code: str, message: str,
           violations: list | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={
        "code": code, "message": message, "violations": violations or []})


def _package_for(application_id: str) -> dict | None:
    if application_id in agent_graph._submitted_packages:
        return agent_graph._submitted_packages[application_id]
    golden = GOLDEN_DIR / f"{application_id}.json"
    if golden.exists():
        package = json.loads(golden.read_text(encoding="utf-8"))
        strip_demographics(package)  # golden dev path: never expose (HR-6)
        return package
    return None


def _status_of(application_id: str) -> str:
    ledger = agent_graph.get_services().ledger
    snapshot = ledger.get_snapshot(application_id)
    if snapshot:
        return json.loads(snapshot[0])["decision"]["action"]
    run = agent_graph._run_registry.get(application_id)
    if run is not None:
        return "suspended" if run.halted else "ready_for_decision"
    return "received"


@router.post("/loans", status_code=201)
async def submit_loan(package: dict) -> dict:
    errors = sorted(_VALIDATOR.iter_errors(package), key=str)
    if errors:
        raise _error(422, "PACKAGE_VALIDATION_FAILED",
                     "package failed schema validation",
                     [{"path": "/".join(str(p) for p in e.absolute_path),
                       "detail": e.message[:200]} for e in errors[:10]])
    borrower_ids = {b["borrower_id"] for b in package["borrowers"]}
    primaries = [b for b in package["borrowers"] if b["is_primary"]]
    if len(primaries) != 1:
        raise _error(422, "PACKAGE_VALIDATION_FAILED",
                     "exactly one primary borrower required")
    for doc in package["documents"]:
        if doc.get("borrower_id") and doc["borrower_id"] not in borrower_ids:
            raise _error(422, "PACKAGE_VALIDATION_FAILED",
                         f"document {doc['doc_id']} references unknown borrower")
    import ulid
    application_id = str(ulid.new())
    demographics = strip_demographics(package)
    if demographics:
        _demographics.store(application_id, demographics)
    agent_graph.submit_package(application_id, package)
    services = agent_graph.get_services()
    from app.audit.canonical import canonical_json, sha256_hex
    services.ledger.append(
        application_id=application_id, event_type="package_accepted",
        actor="system",
        payload={"package_sha256": sha256_hex(canonical_json(package)),
                 "document_count": len(package["documents"]),
                 "pack_version": services.packs.base_version})
    return {"application_id": application_id, "status": "received",
            "policy_pack_version": services.packs.base_version}


@router.get("/loans")
async def list_loans() -> dict:
    items = []
    seen = set()
    for application_id, package in agent_graph._submitted_packages.items():
        seen.add(application_id)
        items.append(_queue_row(application_id, package))
    for golden in sorted(GOLDEN_DIR.glob("*.json")):
        application_id = golden.stem
        if application_id in seen:
            continue
        package = json.loads(golden.read_text(encoding="utf-8"))
        items.append(_queue_row(application_id, package))
    return {"items": items, "next": None}


def _queue_row(application_id: str, package: dict) -> dict:
    status = _status_of(application_id)
    run = agent_graph._run_registry.get(application_id)
    return {
        "application_id": application_id,
        "status": status,
        "borrower_name": package["borrowers"][0]["full_name"],
        "loan_amount": package["loan"]["amount"],
        "purpose": package["loan"]["purpose"],
        "occupancy": package["loan"]["occupancy"],
        "state": package["property"]["address"]["state"],
        "suggested_action": (run.packet.get("suggested_action")
                             if run and run.packet else None),
        "interrupted": status == "ready_for_decision",
    }


@router.get("/loans/{application_id}")
async def loan_detail(application_id: str) -> dict:
    package = _package_for(application_id)
    if package is None:
        raise _error(404, "NOT_FOUND", f"unknown application {application_id}")
    run = agent_graph._run_registry.get(application_id)
    detail: dict[str, Any] = {
        "application_id": application_id,
        "status": _status_of(application_id),
        "application": {
            "borrower_name": package["borrowers"][0]["full_name"],
            "loan_amount": package["loan"]["amount"],
            "note_rate": package["loan"]["note_rate"],
            "term_months": package["loan"]["term_months"],
            "purpose": package["loan"]["purpose"],
            "occupancy": package["loan"]["occupancy"],
            "property_state": package["property"]["address"]["state"],
            "property_type": package["property"]["property_type"],
            "mlo_nmls_id": package["loan"]["mlo_nmls_id"],
        },
        "four_cs": None, "rules": None, "aus": None, "conditions": [],
        "red_flags": [], "atr": [], "discrepancies": [], "packet": None,
    }
    if run is not None and not run.halted:
        detail.update({
            "four_cs": run.case.four_cs,
            "rules": {
                "overall": run.rules.overall,
                "pack_version": run.rules.pack_version,
                "overlay_pack_version": run.rules.overlay_pack_version,
                "evaluations": [
                    {"rule_id": e.rule_id, "ruleset": e.ruleset,
                     "description": e.description, "severity": e.severity,
                     "outcome": e.outcome, "reason_code": e.reason_code,
                     "citation": e.citation,
                     "inputs": [{"path": i.path, "value": i.value,
                                 "lineage_ref": i.lineage_ref}
                                for i in e.inputs]}
                    for e in run.rules.evaluations],
            },
            "aus": {"recommendation": run.aus.recommendation,
                    "simulator_version": run.aus.simulator_version,
                    "breakdown": run.aus.breakdown,
                    "total_points": run.aus.total_points,
                    "messages": [m.__dict__ for m in run.aus.messages]},
            "conditions": [c.__dict__ for c in run.conditions],
            "red_flags": [f.__dict__ for f in run.case.red_flags],
            "atr": run.case.computed["atr"],
            "discrepancies": [d.__dict__ for d in run.case.discrepancies],
            "packet": run.packet,
        })
    return detail


@router.get("/lineage/{application_id}/{ref}")
async def lineage(application_id: str, ref: str) -> dict:
    run = agent_graph._run_registry.get(application_id)
    if run is None or run.halted:
        raise _error(404, "NOT_FOUND", "no active run for application")
    nodes = run.case.lineage.nodes
    if ref not in nodes:
        raise _error(404, "NOT_FOUND", f"unknown lineage ref {ref}")

    def serialize(node) -> dict:
        return {"ref": node.ref, "kind": node.kind, "label": node.label,
                "value": node.value, "method": node.method,
                "parents": list(node.parents), "source_id": node.source_id,
                "meta": dict(node.meta)}

    ancestors, queue, visited = [], list(nodes[ref].parents), set()
    depth = 0
    while queue and depth < 25:
        next_queue = []
        for parent_ref in queue:
            if parent_ref in visited or parent_ref not in nodes:
                continue
            visited.add(parent_ref)
            ancestors.append(serialize(nodes[parent_ref]))
            next_queue.extend(nodes[parent_ref].parents)
        queue = next_queue
        depth += 1
    return {"node": serialize(nodes[ref]), "ancestors": ancestors}


@router.get("/loans/{application_id}/audit")
async def audit_events(application_id: str, limit: int = 200) -> dict:
    ledger = agent_graph.get_services().ledger
    events = ledger.events(application_id)[:limit]
    return {"items": [
        {"seq": e.seq, "event_id": e.event_id, "event_type": e.event_type,
         "actor": e.actor, "payload": json.loads(e.payload_json),
         "hash": e.hash, "prev_hash": e.prev_hash, "created_at": e.created_at}
        for e in events], "next": None}


@router.get("/loans/{application_id}/audit/verify")
async def audit_verify(application_id: str) -> dict:
    result = verify_chain(AUDIT_DB)
    ledger = agent_graph.get_services().ledger
    snapshot = ledger.get_snapshot(application_id)
    return {"chain_ok": result.ok, "events_total": result.events,
            "app_events": len(ledger.events(application_id)),
            "first_broken_seq": result.first_broken_seq,
            "sealed": snapshot is not None,
            "snapshot_hash": snapshot[1] if snapshot else None}


@router.get("/loans/{application_id}/audit/export")
async def audit_export(application_id: str) -> Response:
    ledger = agent_graph.get_services().ledger
    events = ledger.events(application_id)
    snapshot = ledger.get_snapshot(application_id)
    payload = {
        "application_id": application_id,
        "events": [{"seq": e.seq, "event_type": e.event_type, "actor": e.actor,
                    "payload": json.loads(e.payload_json), "hash": e.hash,
                    "created_at": e.created_at} for e in events],
        "decision_snapshot": json.loads(snapshot[0]) if snapshot else None,
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="audit-{application_id}.json"'})


@router.get("/loans/{application_id}/decision")
async def decision(application_id: str) -> dict:
    """Latest decision with full reason detail and provenance (NFR-7)."""
    ledger = agent_graph.get_services().ledger
    snapshot = ledger.get_snapshot(application_id)
    if snapshot is None:
        raise _error(404, "NOT_FOUND", "not finalized")
    parsed = json.loads(snapshot[0])
    return {"decision": parsed["decision"], "versions": parsed["versions"],
            "snapshot_hash": snapshot[1], "sealed_at": parsed["sealed_at"]}


@router.get("/loans/{application_id}/decisions")
async def decision_history(application_id: str) -> dict:
    """FULL decision history — every sealed decision this loan has ever
    received (e.g. suspend -> re-run -> approve), oldest first, each with
    its reasons, notes, override record, versions, and snapshot hash."""
    ledger = agent_graph.get_services().ledger
    history = []
    for seq, snapshot_json, sha256, sealed_at in ledger.snapshots_for(application_id):
        parsed = json.loads(snapshot_json)
        history.append({
            "seq": seq, "sealed_at": sealed_at, "snapshot_hash": sha256,
            "decision": parsed["decision"], "versions": parsed["versions"],
        })
    human_actions = [
        {"created_at": e.created_at, "actor": e.actor,
         "payload": json.loads(e.payload_json)}
        for e in ledger.events(application_id)
        if e.event_type in ("human_action", "override")]
    return {"decisions": history, "human_actions": human_actions}


@router.get("/loans/{application_id}/adverse-action")
async def adverse_action(application_id: str) -> dict:
    ledger = agent_graph.get_services().ledger
    snapshot = ledger.get_snapshot(application_id)
    if snapshot is None:
        raise _error(404, "NOT_FOUND", "not finalized")
    parsed = json.loads(snapshot[0])
    if parsed["decision"]["action"] != "decline":
        raise _error(404, "NOT_FOUND", "no adverse action (not declined)")
    run = agent_graph._run_registry.get(application_id)
    from app.agent.decisioning import build_adverse_action_notice
    services = agent_graph.get_services()
    package = _package_for(application_id) or (run.package if run else None)
    if package is None:
        raise _error(404, "NOT_FOUND", "package unavailable")
    notice = build_adverse_action_notice(
        reason_codes=tuple(parsed["decision"]["reason_codes"]),
        reason_bindings=services.reason_bindings,
        credit=package["credit"], states_index=services.packs.states_index,
        property_state=package["property"]["address"]["state"])
    return notice


@router.post("/loans/{application_id}/replay")
async def replay_decision(application_id: str) -> dict:
    ledger = agent_graph.get_services().ledger
    snapshot = ledger.get_snapshot(application_id)
    if snapshot is None:
        raise _error(404, "NOT_FOUND", "not finalized")
    result = replay(json.loads(snapshot[0]), packs_root=PACKS_ROOT)
    return {"identical": result.identical, "diffs": list(result.diffs)}


@router.get("/hmda/monitoring-extract")
async def monitoring_extract(response: Response) -> dict:
    response.headers["X-Purpose"] = "fair-lending-monitoring-only"
    return {"rows": _demographics.monitoring_extract()}
