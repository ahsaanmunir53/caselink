"""STIX 2.1: export approved cases for sharing with other agencies, import Hoshiyar's website indicators.

Export: one STIX `grouping` per case (context "suspicious-activity"), indicators for websites and
emails, and the case's identifiers (phones, IBANs, licence numbers) in a `note`, because STIX has no
object type for phone numbers or bank accounts. Everything is marked TLP:AMBER (limited sharing).
IDs are UUIDv5, so exporting twice gives the same objects.
"""

import uuid
from datetime import UTC, datetime

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/caselink/stix")
TLP_AMBER = "marking-definition--f88d31f6-486f-44da-b317-01333bde0b82"
EPOCH = "2026-01-01T00:00:00.000Z"


def _id(kind: str, key: str) -> str:
    return f"{kind}--{uuid.uuid5(_NS, f'{kind}:{key}')}"


def _ts(dt: datetime | None) -> str:
    dt = dt or datetime.now(UTC)
    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def case_bundle(cases: list[tuple], app_name: str = "CaseLink") -> dict:
    """cases: list of (Case, facts) pairs."""
    identity = _id("identity", app_name)
    objects: list[dict] = [{"type": "identity", "spec_version": "2.1", "id": identity, "created": EPOCH, "modified": EPOCH,
                            "name": app_name, "identity_class": "system",
                            "description": "Analyst tool that links fraud reports into cases. Cases are approved by people."}]
    for case, facts in cases:
        refs: list[str] = []
        created, modified = _ts(case.created_at), _ts(case.updated_at)
        for e in facts["entities"]:
            if e["official"] or e["kind"] not in ("domain", "email"):
                continue
            key = f"{e['kind']}:{e['value']}"
            pattern = (f"[domain-name:value = '{_esc(e['value'])}']" if e["kind"] == "domain"
                       else f"[email-addr:value = '{_esc(e['value'])}']")
            ind = _id("indicator", key)
            if ind not in {o["id"] for o in objects}:
                objects.append({"type": "indicator", "spec_version": "2.1", "id": ind, "created_by_ref": identity,
                                "created": created, "modified": modified, "name": e["value"],
                                "indicator_types": ["malicious-activity"], "pattern": pattern, "pattern_type": "stix",
                                "valid_from": _ts(facts["first_seen"]), "object_marking_refs": [TLP_AMBER]})
            refs.append(ind)
        lines = [f"{e['kind']}: {e['value']} (in {len(e['reports'])} reports)" for e in facts["entities"]
                 if not e["official"] and e["kind"] in ("phone", "iban", "license", "handle")]
        summary = " ".join(s["text"] for s in (case.summary or {}).get("sentences", []))
        note_id = _id("note", case.id)
        group_id = _id("grouping", case.id)
        objects.append({"type": "note", "spec_version": "2.1", "id": note_id, "created_by_ref": identity, "created": created,
                        "modified": modified, "abstract": f"{case.id} identifiers",
                        "content": "\n".join(lines) or "No phone, IBAN or licence identifiers.",
                        "object_refs": [group_id], "object_marking_refs": [TLP_AMBER]})
        objects.append({"type": "grouping", "spec_version": "2.1", "id": group_id, "created_by_ref": identity,
                        "created": created, "modified": modified, "name": f"{case.id}: {case.title}",
                        "description": (summary or case.title)[:4000] + f" Reports: {len(facts['reports'])}. "
                                       f"Reported loss: PKR {facts['total_loss']:,}.",
                        "context": "suspicious-activity", "object_refs": refs or [identity],
                        "object_marking_refs": [TLP_AMBER]})
    return {"type": "bundle", "id": f"bundle--{uuid.uuid4()}", "objects": objects}


def reports_from_bundle(bundle: dict, source: str = "hoshiyar") -> list[dict]:
    """Turn indicators in a STIX bundle (for example Hoshiyar's export) into intelligence reports."""
    objects = bundle.get("objects") if isinstance(bundle, dict) else None
    if not isinstance(objects, list):
        raise ValueError("Not a STIX bundle.")
    campaigns = {o.get("id"): o for o in objects if isinstance(o, dict) and o.get("type") == "campaign"}
    links: dict[str, list[str]] = {}
    for o in objects:
        if isinstance(o, dict) and o.get("type") == "relationship" and o.get("relationship_type") == "indicates":
            links.setdefault(o.get("source_ref"), []).append(o.get("target_ref"))
    out = []
    for o in objects:
        if not isinstance(o, dict) or o.get("type") != "indicator":
            continue
        name = str(o.get("name") or "")[:200]
        if not name:
            continue
        camp = [campaigns[c].get("name") for c in links.get(o.get("id"), []) if c in campaigns]
        label = ", ".join(str(x) for x in (o.get("labels") or [])[:2]) or "scam"
        text = (f"{source.title()} confirmed a scam website: {name}. {o.get('description') or ''}. "
                + (f"Campaign: {'; '.join(str(c) for c in camp[:2])}." if camp else "")).strip()
        out.append({"source": source, "channel": "stix", "received_at": o.get("valid_from") or o.get("created"),
                    "language": "en", "kind": _kind(label), "text": text[:2000]})
    return out


def _kind(label: str) -> str:
    low = label.lower()
    for key, kind in (("delivery", "parcel"), ("government", "bisp"), ("bank", "bank_otp"), ("job", "overseas_job"),
                      ("investment", "task"), ("prize", "prize"), ("family", "family")):
        if key in low:
            return kind
    return "other"
