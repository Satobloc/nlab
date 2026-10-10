"""nLab Mersearch local query parser and record readers (vendored standalone).

No network APIs, shared repository discovery, or foreign data/index requirements.
The code was adapted from the standalone Mercer Searcher 1.x query grammar.
"""
from __future__ import annotations
import fnmatch, json, re
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from mersearch_json_sniff import is_json_document_candidate, PLAINTEXT_JSON_SUFFIXES
except ModuleNotFoundError:
    from .mersearch_json_sniff import is_json_document_candidate, PLAINTEXT_JSON_SUFFIXES
try:
    import mersearch_math as MM
except ModuleNotFoundError:
    from . import mersearch_math as MM

TEXT_EXTS={".txt",".text",".md",".markdown",".rst",".py",".rb",".rhtml",".erb",".rxml",
           ".html",".htm",".xml",".tex",".sql",".jsonl",".csv",".tsv",".yaml",".yml",
           ".js",".mjs",".css",".scss",".conf",".sh",".ini",".cfg",".log",".svg"}
TOOL_NAME="nLab Mersearch"
TOOL_VERSION="1.0-nlab-2026-10"
WORD_RE=re.compile(r"\w+(?:['’.-]\w+)*",re.UNICODE)
STATUS_PATTERNS=[
 ("correction",re.compile(r"\b(correction|correct(?:ed|ion)?|actually|rather|not quite|that's not|that is not)\b",re.I)),
 ("failed-branch",re.compile(r"\b(fail(?:ed|ure)?|dead end|doesn't work|does not work|reject(?:ed|ion)?|wrong)\b",re.I)),
 ("supersession-signal",re.compile(r"\b(supersed(?:e|ed|ing)|replace(?:d|ment)?|revert|no longer|instead)\b",re.I)),
 ("unresolved",re.compile(r"\b(unresolved|open question|not sure|unknown|pending|needs? (?:checking|review)|tbd)\b",re.I)),
 ("derivation",re.compile(r"\b(derive|derived|derivation|therefore|implies?|follows? from)\b",re.I)),
 ("proposal",re.compile(r"\b(propose|proposal|hypothesis|maybe|perhaps|could be|let's try|we should try)\b",re.I))]
TOKENIZER=re.compile(r'[A-Za-z_][\w-]*:"(?:\\.|[^"\\])*"|"(?:\\.|[^"\\])*"|\(|\)|\b(?:AND|OR|NOT)\b|\bNEAR(?:/\d+)?\b|[^\s()]+',re.I)
PRECEDENCE={"OR":1,"AND":2,"NEAR":3,"NOT":4}


@dataclass
class Record:
 path:str;kind:str;text:str;title:str="";conversation_id:str="";message_id:str=""
 speaker:str="";role:str="";timestamp:str="";locator:str="";viewer_url:str=""
@dataclass
class Eval:
 ok:bool; positions:list[int]; terms:list[str]; trace:list[str]; near:list[dict[str,Any]]
@dataclass
class Hit:
 query:str;path:str;kind:str;title:str;conversation_id:str;message_id:str;speaker:str;role:str
 timestamp:str;locator:str;excerpt:str;status_signals:list[str];viewer_url:str;source_sha256:str
 matched_terms:list[str];near_matches:list[dict[str,Any]];match_trace:list[str];topic_hits:list[str]

def norm(x:Any)->str:return re.sub(r"\s+"," ",str(x or "")).strip()
def iso_time(x:Any)->str:
 if x in (None,""):return ""
 try:return datetime.fromtimestamp(float(x),timezone.utc).isoformat()
 except:return norm(x)
def content_text(c:Any)->str:
 if isinstance(c,str):return c
 if not isinstance(c,dict):return ""
 out=[]
 for p in c.get("parts",[]) if isinstance(c.get("parts"),list) else []:
  if isinstance(p,str):out.append(p)
  elif isinstance(p,dict):
   out.extend(str(p[k]) for k in ("text","content","result","output") if isinstance(p.get(k),str))
 if out:return "\n".join(out)
 return next((c[k] for k in ("text","result","output") if isinstance(c.get(k),str)),"")
def iter_conversation(data:Any,path:Path)->Iterable[Record]:
 if not isinstance(data,dict) or not isinstance(data.get("mapping"),dict):return
 title=norm(data.get("title") or path.stem);cid=norm(data.get("conversation_id") or data.get("id"));rows=[]
 for nid,node in data["mapping"].items():
  msg=node.get("message") if isinstance(node,dict) else None
  if not isinstance(msg,dict):continue
  text=content_text(msg.get("content"))
  if not norm(text):continue
  au=msg.get("author") if isinstance(msg.get("author"),dict) else {}
  role=norm(au.get("role"));speaker=norm(au.get("name") or role);mid=norm(msg.get("id") or nid)
  rows.append((msg.get("create_time") or 0,mid,Record(str(path),"conversation-message",text,title,cid,mid,speaker,role,iso_time(msg.get("create_time")),f"message:{mid}")))
 rows.sort(key=lambda x:(x[0] if isinstance(x[0],(int,float)) else 0,x[1]))
 for _,_,r in rows:yield r
def iter_json(obj:Any,path:Path,pointer:str="$")->Iterable[Record]:
 if isinstance(obj,dict):
  for k,v in obj.items():yield from iter_json(v,path,f"{pointer}.{k}")
 elif isinstance(obj,list):
  for i,v in enumerate(obj):yield from iter_json(v,path,f"{pointer}[{i}]")
 elif isinstance(obj,str) and norm(obj):yield Record(str(path),"json-scalar",obj,path.stem,locator=pointer)
def iter_records(path:Path)->Iterable[Record]:
 ext=path.suffix.lower()
 if is_json_document_candidate(path):
  try:
   data=json.loads(path.read_text(encoding="utf-8-sig"))
  except (OSError,UnicodeError,json.JSONDecodeError):
   if ext==".json":return
   # Malformed JSON-shaped plaintext remains searchable as ordinary text.
  else:
   if isinstance(data,list) and len(data)==1 and isinstance(data[0],dict):
    data=data[0]
   conv=list(iter_conversation(data,path) or [])
   yield from (conv if conv else iter_json(data,path))
   return
 if ext in TEXT_EXTS or (ext in PLAINTEXT_JSON_SUFFIXES and ext!=".json"):
  try:lines=path.read_text(encoding="utf-8-sig",errors="replace").splitlines()
  except:return
  for n,line in enumerate(lines,1):
   if norm(line):yield Record(str(path),"text-line",line,path.stem,locator=f"line:{n}")
 elif ext==".pdf":
  try:
   from pypdf import PdfReader
   for n,page in enumerate(PdfReader(str(path)).pages,1):
    text=page.extract_text() or ""
    if norm(text):yield Record(str(path),"pdf-page",text,path.stem,locator=f"page:{n}")
  except:return

def words(text:str)->list[str]:return [m.group(0).casefold() for m in WORD_RE.finditer(text)]
def phrase_positions(text:str,phrase:str)->list[int]:
 needle=words(phrase);hay=words(text)
 if not needle:return []
 n=len(needle);return [i for i in range(len(hay)-n+1) if hay[i:i+n]==needle]
def status(text:str)->list[str]:return [n for n,p in STATUS_PATTERNS if p.search(text)]
def math_norm(text:str)->str:
 s=str(text or "").casefold()
 repl={"π":"pi","θ":"theta","ϕ":"phi","φ":"phi","τ":"tau","δ":"delta","×":"*","·":"*","⋅":"*","÷":"/","−":"-","–":"-","≈":"~"}
 for x,y in repl.items():s=s.replace(x,y)
 cmds={"\\pi":"pi","\\theta":"theta","\\phi":"phi","\\varphi":"phi","\\tau":"tau","\\delta":"delta",
       "\\cdot":"*","\\times":"*","\\div":"/","\\approx":"~","\\left":"","\\right":""}
 for x,y in cmds.items():s=s.replace(x,y)
 frac=re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
 for _ in range(8):
  ns=frac.sub(r"(\1)/(\2)",s)
  if ns==s:break
  s=ns
 s=s.replace("{","(").replace("}",")")
 s=re.sub(r"\s+","",s)
 s=re.sub(r"\(([-+]?\d+(?:\.\d+)?)\)",r"\1",s)
 s=re.sub(r"(?<=\d)(?=[a-z(])","*",s)
 return s
def unquote(s:str)->str:
 s=s.strip()
 if len(s)>=2 and s[0]==s[-1]=='"':
  try:return json.loads(s)
  except json.JSONDecodeError:return s[1:-1]
 return s
def tokenize(q:str)->list[str]:
 raw=TOKENIZER.findall(q);out=[];prev=None
 for tok in raw:
  typ=("LP" if tok=="(" else "RP" if tok==")" else "OP" if re.fullmatch(r"AND|OR|NOT|NEAR(?:/\d+)?",tok,re.I) else "TERM")
  if prev in ("TERM","RP") and typ in ("TERM","LP") or prev in ("TERM","RP") and tok.upper()=="NOT":
   out.append("AND")
  out.append(tok);prev=typ
 return out
def rpn(q:str)->list[str]:
 out=[];ops=[]
 for tok in tokenize(q):
  up=tok.upper()
  if tok=="(":ops.append(tok)
  elif tok==")":
   while ops and ops[-1]!="(":out.append(ops.pop())
   if not ops:raise ValueError("unmatched )")
   ops.pop()
  elif up in ("AND","OR","NOT") or up.startswith("NEAR"):
   op="NEAR" if up.startswith("NEAR") else up
   while ops and ops[-1]!="(" and PRECEDENCE.get(("NEAR" if ops[-1].upper().startswith("NEAR") else ops[-1].upper()),0)>=PRECEDENCE[op]:
    out.append(ops.pop())
   ops.append(tok)
  else:out.append(tok)
 while ops:
  if ops[-1]=="(":raise ValueError("unmatched (")
  out.append(ops.pop())
 return out
def field_eval(rec:Record,term:str)->Eval|None:
 if ":" not in term:return None
 field,val=term.split(":",1);field=field.casefold();val=unquote(val).casefold()
 p=Path(rec.path);ext=p.suffix.casefold().lstrip(".");name=p.name.casefold()
 if field=="body":
  pos=phrase_positions(rec.text,val);ok=bool(pos)
  return Eval(ok,pos,[term] if ok else [],[f"FIELD body:{val!r} => {len(pos)} occurrence(s)"],[])
 if field=="math":
  target=math_norm(rec.text);needle=math_norm(val);ok=bool(needle) and needle in target
  return Eval(ok,[],[term] if ok else [],[f"FIELD math:{needle!r} => {ok}"],[])
 if field in ("equiv","contains","value"):
  evidence,_=MM.match_source(rec.text,field,unquote(term.split(":",1)[1]))
  ok=bool(evidence)
  return Eval(ok,[],[term] if ok else [],[f"FIELD {field} => {len(evidence)} supported match(es)"],[])
 if field in ("name","path","ext"):
  target={"name":name,"path":rec.path.casefold(),"ext":ext}[field]
  ok=fnmatch.fnmatchcase(target,val) if any(ch in val for ch in "*?[") else val in target
  return Eval(ok,[],[term] if ok else [],[f"FIELD {field}:{val!r} => {ok}"],[])
 if field in ("type","kind"):
  ok=val in rec.kind.casefold()
  return Eval(ok,[],[term] if ok else [],[f"FIELD {field}:{val!r} => {ok}"],[])
 if field=="has":
  flags={"conversation-source":rec.kind=="conversation-message","pdf-source":rec.kind=="pdf-page",
         "text-source":rec.kind in ("text-line","json-scalar","conversation-message"),
         "message-id":bool(rec.message_id),"conversation-id":bool(rec.conversation_id),"viewer":False}
  ok=flags.get(val,False)
  return Eval(ok,[],[term] if ok else [],[f"FIELD has:{val} => {ok}"],[])
 fmap={"author":rec.speaker or rec.role,"speaker":rec.speaker,"role":rec.role,"title":rec.title,
       "conversation":rec.conversation_id,"cid":rec.conversation_id,"date":rec.timestamp[:10],"status":" ".join(status(rec.text))}
 if field not in fmap:return None
 target=(fmap[field] or "").casefold()
 if field=="date" and ".." in val:
  lo,hi=val.split("..",1);ok=(not lo or target>=lo) and (not hi or target<=hi)
 else:ok=val in target
 return Eval(ok,[],[term] if ok else [],[f"FIELD {field}:{val!r} => {ok}"],[])
def term_eval(rec:Record,term:str)->Eval:
 fe=field_eval(rec,term)
 if fe is not None:return fe
 val=unquote(term);pos=phrase_positions(rec.text,val);ok=bool(pos)
 return Eval(ok,pos,[val] if ok else [],[f"TERM {val!r} => {len(pos)} occurrence(s)"],[])
def evaluate(rec:Record,query:str,default_near:int)->Eval:
 st=[]
 for tok in rpn(query):
  up=tok.upper()
  if up=="NOT":
   a=st.pop();st.append(Eval(not a.ok,[],[],a.trace+[f"NOT => {not a.ok}"],a.near));continue
  if up in ("AND","OR") or up.startswith("NEAR"):
   b=st.pop();a=st.pop()
   if up=="AND":st.append(Eval(a.ok and b.ok,a.positions+b.positions,a.terms+b.terms,a.trace+b.trace+[f"AND => {a.ok and b.ok}"],a.near+b.near))
   elif up=="OR":st.append(Eval(a.ok or b.ok,a.positions+b.positions,a.terms+b.terms,a.trace+b.trace+[f"OR => {a.ok or b.ok}"],a.near+b.near))
   else:
    win=int(up.split("/",1)[1]) if "/" in up else default_near
    pairs=[(x,y,abs(x-y)) for x in a.positions for y in b.positions]
    best=min(pairs,key=lambda z:z[2]) if pairs else None
    ok=a.ok and b.ok and best is not None and best[2]<=win
    detail={"window":win,"left_position":best[0],"right_position":best[1],"distance_tokens":best[2]} if best else {"window":win,"distance_tokens":None}
    st.append(Eval(ok,a.positions+b.positions,a.terms+b.terms,a.trace+b.trace+[f"{up} => {ok}; distance={detail['distance_tokens']}"],a.near+b.near+[detail]))
   continue
  st.append(term_eval(rec,tok))
 if len(st)!=1:raise ValueError("invalid query expression")
 return st[0]
