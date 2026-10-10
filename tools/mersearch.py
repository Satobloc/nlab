#!/usr/bin/env python3
"""Standalone read-only Mersearch for Satobloc/nlab, without other-repository access.

By default searches nLab SOFTWARE files inside this checkout, not the live
nLab wiki database. Add wiki exports as local text/JSON under this repository
when permission and export provenance are established.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

try:
    import mersearch_core as C
    import mersearch_math as M
except ImportError:
    from . import mersearch_core as C
    from . import mersearch_math as M

REPO_ROOT=Path(__file__).resolve().parents[1]
REPO_NAME="Satobloc/nlab"
REPO_BRANCH="master"
VERSION="1.0-nlab-local"
EXCLUDES=frozenset({
    ".git",".mersearch","vendor","node_modules","__pycache__",
    ".venv","venv",".bundle","tmp","log","cache","page_content",
    "webs","diagram_cache","secret","build","dist","prior_art","quarantine"
})
SENSITIVE=frozenset({
    "database.yml","environment_variables.rb",".env",".env.local",
    "id_rsa","id_ed25519","credentials.yml","secrets.yml"
})
MAX_BYTES=25_000_000
MAX_RECORDS=300_000
MAX_PATHS=50_000


def root_relative(argument:str, *, must_exist:bool=False)->Path:
    """Strictly enforce local paths and avoid symlink traversal."""
    p=Path(argument)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("absolute paths and parent traversal are forbidden; use nlab-relative paths")
    candidate=REPO_ROOT/p
    current=REPO_ROOT
    for part in candidate.relative_to(REPO_ROOT).parts:
        current=current/part
        if current.is_symlink():
            raise ValueError("symbolic links cannot be used as a search scope or output")
    try:
        candidate.resolve(strict=False).relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("path resolves outside Satobloc/nlab") from exc
    if must_exist and not candidate.exists():
        raise ValueError("no local nlab file/directory: "+argument)
    return candidate


def scan_files(scopes:list[Path], exclude:set[str], max_bytes:int, stats:Counter):
    seen=set()
    for scope in scopes:
        iterator=scope.rglob("*") if scope.is_dir() else (scope,)
        for path in iterator:
            stats["paths_examined"]+=1
            if stats["paths_examined"]>MAX_PATHS:
                stats["path_cap_exceeded"]+=1
                return
            if path.is_symlink() or not path.is_file():
                continue
            relative=path.relative_to(REPO_ROOT)
            parts=[p.casefold() for p in relative.parts]
            if any(p in exclude for p in parts[:-1]):
                stats["excluded_paths"]+=1
                continue
            if parts[-1] in SENSITIVE:
                stats["excluded_sensitive"]+=1
                continue
            if len(parts)>=2 and parts[:2]==["public","mathjax"] and "vendor" in exclude:
                stats["excluded_paths"]+=1
                continue
            if not path.resolve().is_relative_to(REPO_ROOT):
                stats["refused_external_paths"]+=1
                continue
            if path.stat().st_size>max_bytes:
                stats["oversized_skipped"]+=1
                continue
            if path.stat().st_size==0:
                stats["empty_skipped"]+=1
                continue
            suffix=path.suffix.lower()
            if suffix not in C.TEXT_EXTS and not C.is_json_document_candidate(path):
                stats["unknown_format_skipped"]+=1
                continue
            text_path=relative.as_posix()
            if text_path in seen:continue
            seen.add(text_path)
            stats["files_scanned"]+=1
            yield path,text_path


def hash_file(path:Path, cache:dict[str,str])->str:
    key=str(path)
    if key not in cache:
        cache[key]=hashlib.sha256(path.read_bytes()).hexdigest()
    return cache[key]


def localized_excerpt(text:str,positions:list[int],limit:int=450)->str:
    flat=C.norm(text)
    positions_tokens=list(C.WORD_RE.finditer(flat))
    token=min(positions) if positions else 0
    start=positions_tokens[token].start() if token<len(positions_tokens) else 0
    lo=max(0,start-limit//3)
    hi=min(len(flat),lo+limit)
    return ("…" if lo else "")+flat[lo:hi]+("…" if hi<len(flat) else "")


def capability_manifest()->dict:
    return {
      "schema_version":"nlab-mersearch.capabilities.v1",
      "name":"nLab Mersearch","version":VERSION,"repository":REPO_NAME,
      "root":"fixed checkout containing this script","single_repository_only":True,
      "network_access":False,"external_repository_paths_allowed":False,
      "database_access":False,"wiki_pages_included":False,
      "content":"local nLab Rails/Python/Ruby/TeX/docs and optional local wiki exports",
      "syntax":"AND OR NOT, parentheses, quoted phrases, implicit AND, NEAR/n",
      "fields":{
        "body":"text or phrase","name":"filename","path":"nlab-relative path",
        "ext":"extension","title":"record title","type":"record kind",
        "math":"notation-normalized lexical match, NOT equation proof",
        "equiv":"supported exact polynomial equivalence",
        "contains":"supported AST-subexpression",
        "value":"bounded numerical closeness, NOT physical equivalence",
        "date":"explicit structured conversation timestamps only",
        "role":"explicit structured conversation roles",
        "author":"explicit structured speaker labels",
        "status":"lexical status keywords, not authority"
      },
      "modes":{
        "--capabilities":"self-describing JSON",
        "--examples":"common CLI recipes",
        "--coverage":"no-query local scan statistics",
        "--expr":"Boolean expression","--query":"simple phrase; repeat for OR",
        "--scope":"relative nlab-local path, repeatable",
        "--include-vendor":"allow dependency sources (default excludes vendor and MathJax)",
        "--limit":"max results returned after counting all matching records",
        "--math-inventory":"stream bounded parsed equations to nlab-local JSONL",
        "--math-genealogy":"build evidence-only equation recurrence graph inside nlab",
        "--inventory-only":"build formula index without keyword search",
        "--out":"results within .mersearch/, never an external path"
      },
      "query_examples":[
        '"functor" NEAR/12 "category"',
        '(revision OR revert) AND ext:rb',
        'path:script/src AND math:"\\\\frac{a}{b}"',
        'equiv:"a+b=c"',
        'value:"x=0.25;atol=0.01"'
      ],
      "math":M.capabilities(),
      "exclusions":sorted(EXCLUDES),
      "coverage_limitations":[
        "The nLab wiki page content lives in a database absent from this checkout",
        "This tool does not access any live site or repository other than local nlab",
        "Large or unknown-format files are skipped with accounting",
        "PDFs are parsed only if optional pypdf is installed and content has extractable text",
        "Mathematical equivalence is restricted to documented safe subsets"
      ]
    }


EXAMPLES=(
    "python3 tools/mersearch.py --capabilities",
    "python3 tools/mersearch.py --coverage",
    "python3 tools/mersearch.py --expr '\"category\" NEAR/8 \"functor\"'",
    "python3 tools/mersearch.py --expr '(revision OR author) AND ext:rb' --result-mode files",
    "python3 tools/mersearch.py --query 'markdown' --scope script/src",
    "python3 tools/mersearch.py --expr 'math:\"\\\\frac{a}{b}\"'",
    "python3 tools/mersearch.py --expr 'equiv:\"a+b=c\"'",
    "python3 tools/mersearch.py --inventory-only --math-genealogy --out .mersearch/mathematics",
)


def persist(directory:Path,manifest:dict,hits:list[dict])->list[str]:
    directory.mkdir(parents=True,exist_ok=True)
    created=[]
    data=directory/"SEARCH_RESULTS.json"
    data.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    created.append(data.relative_to(REPO_ROOT).as_posix())
    jsonl=directory/"SEARCH_RESULTS.jsonl"
    with jsonl.open("w",encoding="utf-8") as f:
        for h in hits:f.write(json.dumps(h,ensure_ascii=False)+"\n")
    created.append(jsonl.relative_to(REPO_ROOT).as_posix())
    csvpath=directory/"SEARCH_RESULTS.csv"
    keys=list(hits[0]) if hits else [
        "query","path","kind","title","conversation_id","message_id","speaker","role",
        "timestamp","locator","excerpt","status_signals","source_sha256",
        "matched_terms","near_matches","match_trace","topic_hits","math_evidence",
        "repository","source_url"
    ]
    with csvpath.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
        for h in hits:
            row={k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in h.items()}
            writer.writerow(row)
    created.append(csvpath.relative_to(REPO_ROOT).as_posix())
    md=directory/"SEARCH_RESULTS.md"
    lines=["# nLab Mersearch results","",f"Repository: {REPO_NAME} (local-only)",
           f"Query: {manifest['query'] or '(inventory only)'}",
           f"Hits before limit: {manifest['coverage']['total_results_before_limit']}",
           f"Files scanned: {manifest['coverage']['files_scanned']}",""]
    for h in hits:
        lines.extend([
            "- **"+h["path"]+"** at "+h["locator"],
            "  - "+h["excerpt"],
            "  - SHA-256: "+h["source_sha256"]
        ])
        if h.get("math_evidence"):
            lines.append("  - Symbolic evidence: "+json.dumps(h["math_evidence"],ensure_ascii=False))
    md.write_text("\n".join(lines)+"\n",encoding="utf-8")
    created.append(md.relative_to(REPO_ROOT).as_posix())
    return created


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capabilities",action="store_true")
    p.add_argument("--examples",action="store_true")
    p.add_argument("--coverage",action="store_true")
    p.add_argument("--expr",help="Boolean/NEAR query")
    p.add_argument("--query",action="append",default=[],help="simple phrase; repeated values OR")
    p.add_argument("--scope",action="append",default=[],help="repo-relative file or directory; repeatable")
    p.add_argument("--out",default=".mersearch/results")
    p.add_argument("--exclude",action="append",default=[],help="additional excluded directory name")
    p.add_argument("--include-vendor",action="store_true")
    p.add_argument("--max-bytes",type=int,default=5_000_000)
    p.add_argument("--max-records",type=int,default=MAX_RECORDS)
    p.add_argument("--near",type=int,default=10)
    p.add_argument("--limit",type=int,default=200)
    p.add_argument("--date-from");p.add_argument("--date-to")
    p.add_argument("--sort",choices=["path","date","author","title"],default="path")
    p.add_argument("--descending",action="store_true")
    p.add_argument("--result-mode",choices=["records","files"],default="records")
    p.add_argument("--math-inventory",action="store_true")
    p.add_argument("--math-genealogy",action="store_true")
    p.add_argument("--genealogy-atol",type=float,default=0.001)
    p.add_argument("--inventory-only",action="store_true")
    args=p.parse_args(argv)
    if args.capabilities:
        print(json.dumps(capability_manifest(),ensure_ascii=False,indent=2));return 0
    if args.examples:
        print("\n".join(EXAMPLES));return 0
    if args.max_bytes<1 or args.max_bytes>MAX_BYTES:
        p.error("--max-bytes must be between 1 and "+str(MAX_BYTES))
    if args.max_records<1 or args.max_records>MAX_RECORDS:p.error("invalid --max-records")
    if args.limit<0 or args.limit>20000:p.error("--limit must be between 0 and 20000")
    if args.near<0 or args.near>1000:p.error("--near must be 0..1000")
    if args.expr and args.query:p.error("--expr and --query cannot be combined")
    if args.inventory_only and (args.expr or args.query):p.error("--inventory-only cannot combine with queries")
    if args.coverage and (args.expr or args.query or args.inventory_only):
        p.error("--coverage does not take query or inventory options")
    if args.math_genealogy or args.inventory_only:args.math_inventory=True
    if args.math_inventory:M.require_symbolic()
    query=args.expr or (" OR ".join(json.dumps(q,ensure_ascii=False) for q in args.query) if args.query else "")
    if not query and not args.coverage and not args.inventory_only:
        p.error("provide --expr, --query, --coverage, or --inventory-only")
    if query:
        try:
            tokens=C.rpn(query)
            if any(t.split(":",1)[0].casefold() in {"equiv","contains","value"}
                   for t in tokens if ":" in t):
                M.require_symbolic()
        except (ValueError,IndexError,M.UnsupportedExpression) as exc:
            p.error("invalid query: "+str(exc))
    try:
        scopes=[root_relative(x,must_exist=True) for x in (args.scope or ["."])]
        output=root_relative(args.out)
    except ValueError as exc:p.error(str(exc))
    if not (output==REPO_ROOT/".mersearch" or
            (REPO_ROOT/".mersearch") in output.parents):
        p.error("--out must be below .mersearch/ in the current nlab checkout")
    excluded={s.casefold() for s in EXCLUDES}
    excluded.update(x.casefold() for x in args.exclude)
    if args.include_vendor:excluded.remove("vendor")
    stats=Counter();hits=[];hashes={}
    out_inventory=None
    if args.math_inventory:
        output.mkdir(parents=True,exist_ok=True)
        out_inventory=(output/"MATH_EXPRESSIONS.jsonl").open("w",encoding="utf-8")
    truncated=False
    try:
        for file,relative in scan_files(scopes,excluded,args.max_bytes,stats):
            for record in C.iter_records(file):
                if stats["records_scanned"]>=args.max_records:
                    stats["record_limit_exceeded"]+=1
                    truncated=True;break
                stats["records_scanned"]+=1
                record.path=relative
                if out_inventory:
                    candidates,details=M.extract(record.text)
                    for item in candidates:
                        base_line=(int(record.locator[5:])-1
                                   if record.locator.startswith("line:") else 0)
                        row={
                          "repository":REPO_NAME,"path":relative,
                          "source_sha256":hash_file(file,hashes),
                          "source_url":"https://github.com/"+REPO_NAME+"/blob/"+REPO_BRANCH+"/"+quote(relative,safe="/"),
                          "record_locator":record.locator,"source_kind":record.kind,
                          "message_id":record.message_id,
                          "conversation_id":record.conversation_id,
                          "timestamp":record.timestamp,
                          **{key:val for key,val in item.items() if key!="source_line"},
                          "source_line":base_line+item["source_line"]
                        }
                        out_inventory.write(json.dumps(row,ensure_ascii=False)+"\n")
                        stats["equations_extracted"]+=1
                    for key,n in details.items():
                        stats["math_"+key]+=n
                if not query:continue
                if args.date_from and (not record.timestamp or record.timestamp[:10]<args.date_from):continue
                if args.date_to and (not record.timestamp or record.timestamp[:10]>args.date_to):continue
                try:ev=C.evaluate(record,query,args.near)
                except (ValueError,IndexError,M.UnsupportedExpression) as exc:
                    p.error("search evaluation error: "+str(exc))
                if not ev.ok:continue
                math_evidence=[]
                for field in ev.terms:
                    if ":" not in field:continue
                    kind,raw=field.split(":",1)
                    if kind.casefold() not in {"equiv","contains","value"}:continue
                    proof,_=M.match_source(record.text,kind.casefold(),C.unquote(raw))
                    math_evidence.extend(proof)
                hits.append({
                    "query":query,"path":relative,"kind":record.kind,
                    "title":record.title,"conversation_id":record.conversation_id,
                    "message_id":record.message_id,"speaker":record.speaker,
                    "role":record.role,"timestamp":record.timestamp,
                    "locator":record.locator,
                    "excerpt":localized_excerpt(record.text,ev.positions),
                    "status_signals":C.status(record.text),
                    "source_sha256":hash_file(file,hashes),
                    "matched_terms":list(dict.fromkeys(ev.terms)),
                    "near_matches":ev.near,"match_trace":ev.trace,
                    "topic_hits":[],"math_evidence":math_evidence,
                    "repository":REPO_NAME,
                    "source_url":"https://github.com/"+REPO_NAME+"/blob/"+REPO_BRANCH+"/"+quote(relative,safe="/")
                })
            if truncated:break
    finally:
        if out_inventory:out_inventory.close()
    stats["matching_records"]=len(hits)
    if args.sort=="date":
        hits.sort(key=lambda h:(h["timestamp"] or "9999",h["path"],h["locator"]),
                  reverse=args.descending)
    elif args.sort=="title":
        hits.sort(key=lambda h:(h["title"].casefold(),h["path"],h["locator"]),
                  reverse=args.descending)
    elif args.sort=="author":
        hits.sort(key=lambda h:((h["speaker"] or h["role"]).casefold(),h["path"],h["locator"]),
                  reverse=args.descending)
    else:hits.sort(key=lambda h:(h["path"],h["locator"]),reverse=args.descending)
    if args.result_mode=="files":
        unique=[];seen=set()
        for hit in hits:
            if hit["path"] in seen:continue
            seen.add(hit["path"]);unique.append(hit)
        hits=unique
    total=len(hits)
    returned=hits[:args.limit] if args.limit else hits
    coverage={
        "files_scanned":stats["files_scanned"],"records_scanned":stats["records_scanned"],
        "total_results_before_limit":total,"returned_hits":len(returned),
        "statistics":dict(stats),
        "partial_corpus":bool(stats["oversized_skipped"] or
                              stats["path_cap_exceeded"] or
                              stats["record_limit_exceeded"]),
        "wiki_database_included":False,
        "excluded_names":sorted(excluded),
        "warning":"Not a search of live nLab wiki pages; only checked-in software or separately copied exports."
    }
    if args.coverage:
        print(json.dumps({"repository":REPO_NAME,"coverage":coverage},indent=2))
        return 0
    manifest={
      "schema_version":"nlab-mersearch.search.v1",
      "tool":"nLab Mersearch","version":VERSION,
      "repository":REPO_NAME,"scope":"single-repository-local-only",
      "generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "query":query or "(equation inventory only)",
      "capabilities_command":"python3 tools/mersearch.py --capabilities",
      "roots":[path.relative_to(REPO_ROOT).as_posix() for path in scopes],
      "result_mode":args.result_mode,"sort":args.sort,
      "coverage":coverage,"hits":returned,
      "facets":{
          "kind":dict(Counter(h["kind"] for h in hits)),
          "extension":dict(Counter(Path(h["path"]).suffix.lower() for h in hits))
      },
      "epistemic_warning":"Lexical status is not authority; bounded math resemblance is not physical or historical identity."
    }
    if args.math_genealogy:
        try:
            import mersearch_math_genealogy as G
        except ImportError:
            from . import mersearch_math_genealogy as G
        genealogy=G.build(output/"MATH_EXPRESSIONS.jsonl",
            atol=args.genealogy_atol,
            manifest={
              "coverage_status":"partial" if coverage["partial_corpus"] else "local-scan",
              "content_coverage_status":"wiki-database-not-present",
              "archives_searched":[REPO_NAME],"missing_archives":[],
              "math_inventory":{"extraction_statistics":dict(stats)},
              "inventory_limitations":{"live_wiki_database_excluded":True,
                                       "vendor_skipped":not args.include_vendor}
            })
        (output/"MATH_GENEALOGY.json").write_text(
            json.dumps(genealogy,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        manifest["math_genealogy"]={
            "file":"MATH_GENEALOGY.json",
            "nodes":len(genealogy["nodes"]),"families":len(genealogy["families"]),
            "edges":len(genealogy["edges"]),
            "semantics":"formal recurrence only; no inferred causal derivation"
        }
    files=persist(output,manifest,returned)
    if args.math_inventory:files.append((output/"MATH_EXPRESSIONS.jsonl").relative_to(REPO_ROOT).as_posix())
    if args.math_genealogy:files.append((output/"MATH_GENEALOGY.json").relative_to(REPO_ROOT).as_posix())
    print(json.dumps({"repository":REPO_NAME,"version":VERSION,
                      "results_before_limit":total,"returned":len(returned),
                      "coverage":coverage,"outputs":files},
                     ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
