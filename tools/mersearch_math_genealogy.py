#!/usr/bin/env python3
"""nLab standalone Mersearch M4: evidence-led equation recurrence graph, NOT claimed derivations.

Input: provenance-bearing MATH_EXPRESSIONS.jsonl emitted by Mersearch.
Output: MATH_GENEALOGY.json grouping exact polynomial forms, source mirrors,
and individually labeled near-numeric observations.

No text-generation, semantic identity inference, untrusted Python execution,
or genealogy-as-causation. The graph describes independently attested FORM
relationships; documentary lineage needs explicit source evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mersearch_math as M

SCHEMA = "mersearch.math-genealogy.v1"
MAX_NODES = 50000
MAX_EDGES = 60000
MAX_NUMERIC_NEIGHBORS = 3
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T[0-9:.]+(?:Z|[+-]\d{2}:\d{2})?)?$")
UNIT_RE = re.compile(
    r"(?:\\(?:text|mathrm)\s*\{\s*(rad|radians?|degrees?|deg)\s*\}"
    r"|\s+(rad|radians?|degrees?|deg)\s*$)", re.I
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def checked_date(value: Any) -> str:
    """Treat only explicit structured message dates as direct chronology."""
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not (2000 <= parsed.year <= 2100):
            return ""
        if "T" not in value:
            return parsed.date().isoformat()  # source-only day precision
        if parsed.tzinfo is None:
            return ""  # a clock without timezone cannot be chronologically ordered
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except ValueError:
        return ""


def unit_hint(raw: str) -> str:
    found = [((a or b) or "").lower() for a,b in UNIT_RE.findall(raw)]
    tags = {"radians":"rad","radian":"rad","degrees":"deg","degree":"deg"}
    normalized={tags.get(x,x) for x in found}
    if len(normalized)>1:
        return "mixed-or-ambiguous"
    return next(iter(normalized),"not-recorded")


def exact_polynomial_signature(p: dict[str, Any]) -> str:
    """Constant-scale equality fingerprint; never admit approximate operators."""
    if p["operator"] != "=" or p["residual"] is None:
        return ""
    poly = M._safe_poly(p["residual"])
    if poly is None or poly.is_zero:
        return ""
    vars_ = sorted(p["residual"].free_symbols,key=lambda s:s.name)
    if not vars_:
        return ""
    poly = M.S.Poly(p["residual"],*vars_)
    items = poly.terms()
    if not items or len(items)>512:
        return ""
    coefficient0=items[0][1]
    if coefficient0==0:
        return ""
    signature={
        "variables":[symbol.name for symbol in vars_],
        "coefficients":[[list(exp),M.S.srepr(M.S.cancel(coef/coefficient0))]
                        for exp,coef in items]
    }
    return "poly:"+digest(json.dumps(signature,sort_keys=True,separators=(",",":")))


def math_node(row: dict[str,Any]) -> dict[str,Any]:
    raw=row.get("raw")
    if not isinstance(raw,str) or not raw or len(raw)>M.MAX_EXPRESSION_LENGTH:
        raise M.UnsupportedExpression("Equation absent or over parser limit")
    p=M.parse(raw)
    repository=str(row.get("repository") or "")
    path=str(row.get("path") or "")
    record=str(row.get("record_locator") or "")
    line=row.get("source_line",0)
    sha=str(row.get("source_sha256") or "")
    if not repository or not path or not isinstance(line,int) or line<1:
        raise M.UnsupportedExpression("Missing repository, path or line provenance")
    date=checked_date(row.get("timestamp"))
    kind=str(row.get("source_kind") or "")
    # NotebookLM records are derived exports; even a message timestamp needs
    # separate provenance review before claiming an original direct attestation.
    direct=date if kind=="conversation-message" else ""
    unit=unit_hint(raw)
    base_polykey=exact_polynomial_signature(p)
    # A mathematical form with documented degrees/radians is not silently
    # placed in one physical family with a different or unknown unit.
    polykey=(base_polykey+"|unit:"+unit) if base_polykey else ""
    numeric=None
    numeric_basis=""
    variable=""
    if len(p["symbols"]) == 1:
        variable=p["symbols"][0]
        try:
            numeric,numeric_basis=M._numeric_solution(p,variable)
        except (OverflowError,TypeError,ValueError, M.UnsupportedExpression):
            numeric=None
        if numeric is not None and (not math.isfinite(numeric) or abs(numeric)>1e100):
            numeric=None
    row_identity="\0".join([repository,path,sha,record,str(line),raw])
    mirror_identity="\0".join([sha,record,str(line),raw])
    return {
        "id":"eq:"+digest(row_identity),
        "repository":repository,"path":path,"source_sha256":sha,
        "source_url":str(row.get("source_url") or ""),
        "speaker":str(row.get("speaker") or ""),"role":str(row.get("role") or ""),
        "record_locator":record,"source_line":line,
        "message_id":str(row.get("message_id") or ""),
        "conversation_id":str(row.get("conversation_id") or ""),
        "source_kind":kind,
        "raw":raw,"normalized":p["normalized"],
        "operator":p["operator"],"symbols":p["symbols"],"unit_hint":unit,
        "date":direct,"date_basis":"structured-message-timestamp" if direct else "undated-or-soft",
        "source_timestamp_unverified":date if date and not direct else "",
        "polynomial_form_id":polykey,
        "numeric_variable":variable if numeric is not None else "",
        "numeric_value":numeric,"numeric_basis":numeric_basis if numeric is not None else "",
        "mirror_identity":mirror_identity if sha else "",
        "record_identity":"\0".join([repository,path,sha,record])
    }


def _chronology(a: dict,b: dict) -> dict[str,str]:
    if a["date"] and b["date"]:
        if a["date"][:10] == b["date"][:10] and (
            len(a["date"]) == 10 or len(b["date"]) == 10
        ):
            return {"ordering":"same-calendar-day-no-time-order","basis":"at-least-one-day-precision-date"}
        if a["date"] == b["date"]:
            return {"ordering":"same-direct-timestamp","basis":"structured-message-timestamp"}
        return {"ordering":"earlier-to-later-direct-attestation"
                if a["date"] < b["date"] else "later-to-earlier-direct-attestation",
                "basis":"structured-message-timestamp"}
    return {"ordering":"undetermined","basis":"insufficient-direct-timestamps"}


def build(inventory: Path, *, atol:float=0.001, max_nodes:int=MAX_NODES,
          max_edges:int=MAX_EDGES, manifest:dict|None=None) -> dict:
    M.require_symbolic()
    if not math.isfinite(atol) or not 0 < atol <= 1:
        raise ValueError("Finite absolute numeric tolerance must be between 0 and 1.")
    if not 1<=max_nodes<=MAX_NODES or not 1<=max_edges<=MAX_EDGES:
        raise ValueError("Node/edge limits are out of bounds.")
    nodes:list[dict]=[]
    known_ids:set[str]=set()
    stats=Counter()
    with inventory.open(encoding="utf-8") as f:
        for number,line in enumerate(f,1):
            if number>max_nodes:
                raise ValueError(
                    f"Genealogy inventory has more than {max_nodes} rows. "
                    "Refine the corpus or raise the configured bound within supported limits. "
                    "The graph will NOT silently claim complete coverage."
                )
            if len(line)>16000:
                stats["rejected_oversized_jsonl_rows"]+=1
                continue
            try:
                row=json.loads(line)
                if not isinstance(row,dict):
                    raise ValueError("Not an object")
                node=math_node(row)
            except (ValueError,TypeError,M.UnsupportedExpression,
                    OverflowError,RecursionError):
                stats["unparsed_inventory_rows"]+=1
                continue
            if node["id"] in known_ids:
                stats["duplicate_inventory_records"]+=1
                continue
            known_ids.add(node["id"])
            nodes.append(node)
    stats["parsed_nodes"]=len(nodes)
    indexed={n["id"]:n for n in nodes}
    edges:list[dict]=[]
    edge_keys=set()

    def add(a:dict,b:dict,relation:str,details:dict|None=None)->bool:
        if a["id"]==b["id"]:
            return False
        source,target=sorted([a["id"],b["id"]])
        pair=(source,target,relation)
        if pair in edge_keys:return False
        if len(edges)>=max_edges:
            stats["edge_capacity_exceeded"]+=1
            return False
        edge_keys.add(pair)
        edge={"source":source,"target":target,"relation":relation,
              "claim_class":"FORMAL-OR-ARCHIVAL-OBSERVATION",
              "not_claimed":["direct derivation","physical equivalence",
                             "authorship continuity","chronological priority outside indexed corpus"],
              "chronology":_chronology(indexed[source],indexed[target])}
        if details:edge.update(details)
        if relation=="NUMERICALLY_CLOSE_NOT_EQUIVALENT":
            edge["value_source"]=indexed[source]["numeric_value"]
            edge["value_target"]=indexed[target]["numeric_value"]
        edges.append(edge)
        return True

    groups=defaultdict(list)
    mirrors=defaultdict(list)
    for n in nodes:
        if n["polynomial_form_id"]:
            groups[n["polynomial_form_id"]].append(n)
        if n["mirror_identity"]:
            mirrors[n["mirror_identity"]].append(n)

    # Register byte-identical input source mirrors as one archival occurrence,
    # keeping both repo paths visible. This is custody, not independent priority.
    for items in mirrors.values():
        if len(items)<=1:continue
        ordered=sorted(items,key=lambda n:(n["repository"],n["path"],n["id"]))
        anchor=ordered[0]
        for node in ordered[1:]:
            add(anchor,node,"BYTE_IDENTICAL_SOURCE_MIRROR",
                {"evidence":"matching file SHA-256 and equation coordinate"})
    def attest_order(n:dict)->tuple:
        return (0 if n["date"] else 1,n["date"] or "9999",
                n["repository"],n["path"],n["record_locator"],n["source_line"])

    families=[]
    for family_id in sorted(groups):
        members=sorted(groups[family_id],key=attest_order)
        dedup=[]
        seen_mirrors=set()
        for node in members:
            key=node["mirror_identity"] or node["id"]
            if key in seen_mirrors:continue
            seen_mirrors.add(key)
            dedup.append(node)
        dated=sorted([n["date"] for n in dedup if n["date"]])
        families.append({
            "id":family_id,
            "relation":"ALGEBRAICALLY_EQUIVALENT_POLYNOMIAL_EQUALITIES",
            "member_ids":[n["id"] for n in members],
            "archivally_distinct_occurrences":len(dedup),
            "first_direct_attestation":dated[0] if dated else None,
            "last_direct_attestation":dated[-1] if dated else None,
            "undated_occurrences":sum(not n["date"] for n in dedup),
            "priority_claim":"earliest timestamp found in indexed, eligible content only"
                if dated else "no directly dated attestation in this indexed family"
        })
        for item in dedup[1:]:
            relation=("SAME_EQUATION_FORM_REAPPEARS"
                      if item["normalized"]==dedup[0]["normalized"]
                      else "ALGEBRAICALLY_EQUIVALENT_POLYNOMIAL")
            add(dedup[0],item,relation,{"family_id":family_id,
                "proof_scope":"constant-scaled polynomial equality, exact = only; no cross-variable renaming"})

    # Close numerical observations: label every comparison individually.
    # Never use connected components or transitive clustering for approximation.
    numeric_groups=defaultdict(list)
    for n in nodes:
        if n["numeric_value"] is not None and n["numeric_variable"] and n["unit_hint"]!="mixed-or-ambiguous":
            numeric_groups[(n["numeric_variable"],n["unit_hint"])].append(n)
    numeric_degree=Counter()
    for key,group in sorted(numeric_groups.items()):
        group.sort(key=lambda n:(n["numeric_value"],n["id"]))
        for i,a in enumerate(group):
            candidates=0
            for b in group[i+1:]:
                difference=abs(a["numeric_value"]-b["numeric_value"])
                if difference>atol:break
                if a["mirror_identity"] and a["mirror_identity"]==b["mirror_identity"]:continue
                if a["polynomial_form_id"] and a["polynomial_form_id"]==b["polynomial_form_id"]:continue
                if (candidates>=MAX_NUMERIC_NEIGHBORS or
                        numeric_degree[a["id"]]>=MAX_NUMERIC_NEIGHBORS or
                        numeric_degree[b["id"]]>=MAX_NUMERIC_NEIGHBORS):
                    stats["near_numeric_candidates_skipped_by_neighbor_bound"]+=1
                    continue
                if add(a,b,"NUMERICALLY_CLOSE_NOT_EQUIVALENT",{
                    "variable":key[0],"units":key[1],
                    "value_a":a["numeric_value"],"value_b":b["numeric_value"],
                    "absolute_difference":difference,"absolute_tolerance":atol,
                    "scope":"same symbol and same recorded unit category only; no equivalence or derivation inferred"}):
                    candidates+=1
                    numeric_degree[a["id"]]+=1
                    numeric_degree[b["id"]]+=1
    # Do not inadvertently leak all raw source text into a public catalog.
    for node in nodes:
        node.pop("mirror_identity")
        node.pop("record_identity")
    coverage={
        "claim":"PARTIAL_SYMBOLIC_EXTRACTION_NOT_EXHAUSTIVE",
        "source_inventory":str(inventory),
        "source_scan_coverage":(manifest or {}).get("coverage_status","unknown"),
        "indexed_repositories":(manifest or {}).get("archives_searched",[]),
        "missing_repositories":(manifest or {}).get("missing_archives",[]),
        "source_content_coverage_status":(manifest or {}).get("content_coverage_status","unverified"),
        "source_math_extraction_statistics":(manifest or {}).get("math_inventory",{}).get("extraction_statistics",{}),
        "source_inventory_limitations":(manifest or {}).get("inventory_limitations",{}),
        "truncation":"see statistics; source parser and maximum per-record candidates apply"
    }
    return {
        "schema_version":SCHEMA,
        "engine":"nlab-mersearch-M4-local-only",
        "semantics":"a graph of FORM REAPPEARANCES AND EVIDENCE, not causal derivation genealogy",
        "coverage":coverage,
        "options":{"numeric_atol":atol,"max_nodes":max_nodes,
                   "max_edges":max_edges,"numeric_neighbors_per_node":MAX_NUMERIC_NEIGHBORS},
        "statistics":dict(stats),
        "families":families,"nodes":nodes,"edges":edges
    }


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--search-manifest",type=Path,help="SEARCH_RESULTS.json from same scan for coverage basis")
    p.add_argument("--atol",type=float,default=0.001)
    p.add_argument("--max-nodes",type=int,default=MAX_NODES)
    p.add_argument("--max-edges",type=int,default=MAX_EDGES)
    args=p.parse_args()
    manifest=None
    if args.search_manifest:
        manifest=json.loads(args.search_manifest.read_text(encoding="utf-8"))
    result=build(args.inventory,atol=args.atol,max_nodes=args.max_nodes,max_edges=args.max_edges,manifest=manifest)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(args.out),
                      "nodes":len(result["nodes"]),"families":len(result["families"]),
                      "edges":len(result["edges"]),"statistics":result["statistics"],
                      "scope":result["coverage"]["claim"]}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
