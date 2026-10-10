"""nLab standalone Mersearch M1/M2/M3: bounded mathematical extraction, structural and algebraic search.

UNTRUSTED SOURCE SAFETY:
  * No eval(), exec(), sympy.sympify(), parse_expr(), or dynamically loaded code.
  * Hand-built AST whitelist. Functions and operators tightly limited.
  * Algebraic equivalence: polynomial equalities with constant nonzero scaling;
    no implicit claims for rational-function domains, transcendental identities,
    unit systems, physical observables, or derivational provenance.
  * Numeric proximity is labeled NUMERICALLY_CONSISTENT, never equivalent.
  * All matches identify exact source excerpt and extraction limitations.

Optional dependency: sympy >= 1.12. CLI fails visibly for symbolic features if
missing; basic Mersearch/chronology and legacy math: continue to function.
"""
from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Any

try:
    import sympy as S
except ImportError:
    S = None

VERSION = "nlab-m1-m3-2026-10"
MAX_SOURCE_LINES = 2400
MAX_SOURCE_CANDIDATES = 64
MAX_EXPRESSION_LENGTH = 190
MAX_TOKENS = 96
MAX_SYMBOLS = 8
MAX_POLY_DEGREE = 10
MAX_MATCH_EVIDENCE = 6

GREEK = {
    "π": " pi ", "Π": " pi ", "θ": "theta", "Θ": "Theta",
    "ϕ": "phi", "φ": "phi", "Φ": "Phi", "τ": "tau",
    "δ": "delta", "Δ": "Delta", "μ": "mu", "λ": "lambda",
    "ω": "omega", "Ω": "Omega", "α": "alpha", "β": "beta",
    "γ": "gamma", "σ": "sigma", "ρ": "rho", "ε": "epsilon",
}
TEX_SYMBOLS = {
    "pi": " pi ", "theta": "theta", "Theta": "Theta", "phi": "phi", "varphi": "phi",
    "Delta": "Delta", "Phi": "Phi",
    "tau": "tau", "delta": "delta", "mu": "mu", "lambda": "lambda",
    "omega": "omega", "alpha": "alpha", "beta": "beta",
    "gamma": "gamma", "sigma": "sigma", "rho": "rho",
    "epsilon": "epsilon",
    "cdot": "*", "times": "*", "div": "/",
    "left": "", "right": "",
}
ALLOWED_FUNCS = {"sin", "cos", "tan", "sqrt", "exp", "log", "abs"}
TOKEN_RE = re.compile(
    r"(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
    r"|[A-Za-z_][A-Za-z_0-9]*|\*\*|[+\-*/^()]"
)
EQUALITY_RE = re.compile(r"(?<![<>=!])(?:=|≈|≃|\\approx)(?![=])")
PROSE_BREAK = re.compile(
    r"(?:^|[,;:]|->|→|\b(?:is|was|gives|yielded|yields|equals|"
    r"then|therefore|so|hence|with|have|found|compute|calculate|"
    r"estimate|means|namely|where)\b)\s*", re.I
)
LATEX_INLINE = re.compile(r"\$(?!\$)([^$\n]{2,240})\$|\\\((.{2,240}?)\\\)")
TEXT_UNITS = re.compile(r"^\s*(?:radians?|rad|degrees?|deg|c|m|s)\b", re.I)


class UnsupportedExpression(ValueError):
    """The expression is outside our safely supported mathematical subset."""


def dependency_state() -> str:
    return "available" if S is not None else "missing-sympy"


def require_symbolic() -> None:
    if S is None:
        raise RuntimeError(
            "Symbolic search requires SymPy. Install 'sympy>=1.12,<2' "
            "or use the stable math: notation search."
        )


def _frac_convert(text: str) -> str:
    """Convert bounded nested TeX fractions with a recursive brace scanner."""
    def brace(s: str, start: int) -> tuple[str, int]:
        if start >= len(s) or s[start] != "{":
            raise UnsupportedExpression("TeX fraction needs braced arguments")
        depth = 1
        for k in range(start + 1, len(s)):
            if s[k] == "{":
                depth += 1
            elif s[k] == "}":
                depth -= 1
                if depth == 0:
                    return s[start + 1:k], k + 1
        raise UnsupportedExpression("Unclosed TeX fraction")

    for _ in range(12):
        at = text.find(r"\frac")
        if at < 0:
            return text
        p = at + 5
        while p < len(text) and text[p].isspace():
            p += 1
        num, p = brace(text, p)
        while p < len(text) and text[p].isspace():
            p += 1
        den, end = brace(text, p)
        text = text[:at] + "((" + num + ")/(" + den + "))" + text[end:]
        if len(text) > 500:
            raise UnsupportedExpression("Expanded fraction too large")
    if r"\frac" in text:
        raise UnsupportedExpression("Fraction nesting limit reached")
    return text


def normalize(raw: str) -> str:
    if len(raw) > MAX_EXPRESSION_LENGTH:
        raise UnsupportedExpression("Expression too long")
    s = str(raw).strip().strip("$")
    s = s.replace(r"\[", "").replace(r"\]", "").replace(r"\(", "").replace(r"\)", "")
    s = _frac_convert(s)
    s = s.replace(r"\approx", "≈").replace(r"\simeq", "≃")
    # Common optical phase notation uses Delta-phi as ONE observable, not the
    # product of unrelated variables named Delta and phi.
    s = re.sub(r"\\Delta\s*\\(?:phi|varphi)\b|Δ\s*φ", "Delta_phi", s)
    s = re.sub(r"\\Delta\s*\\theta\b|Δ\s*θ", "Delta_theta", s)
    # Preserve the raw source for units; strip only explicitly supported
    # display-unit markup from the parsed right-hand expression.
    s = re.sub(r"\\(?:text|mathrm)\s*\{\s*(?:rad|radians|deg|degrees)\s*\}", "", s, flags=re.I)
    s = re.sub(r"\\([A-Za-z]+)", lambda m: TEX_SYMBOLS.get(m.group(1), "\\" + m.group(1)), s)
    for old, new in GREEK.items():
        s = s.replace(old, new)
    for old, new in {"×": "*", "·": "*", "⋅": "*", "÷": "/",
                     "−": "-", "–": "-", "⁻": "-", "²": "^2", "³": "^3"}.items():
        s = s.replace(old, new)
    s = s.replace("{", "(").replace("}", ")")
    s = re.sub(r"\s+(?:rad|radians|degrees|deg)\s*$", "", s, flags=re.I)
    s = re.sub(r"_\s*\(\s*(\d+)\s*\)", r"_\1", s)
    if "\\" in s or "[" in s or "]" in s:
        raise UnsupportedExpression("Unsupported TeX command/notation")
    return s.strip()


def _tokens(text: str) -> list[str]:
    stripped = text.replace(" ", "").replace("\t", "")
    matches = list(TOKEN_RE.finditer(text))
    if not matches or "".join(m.group() for m in matches) != stripped:
        raise UnsupportedExpression("Unrecognized source characters")
    result: list[str] = []
    prev = ""
    for match in matches:
        t = match.group()
        curr_atom = t == "(" or t[0].isalnum() or t[0] == "_" or t[0] == "."
        prev_atom = prev == ")" or (
            prev and (prev[0].isalnum() or prev[0] == "_" or prev[0] == ".")
        )
        function_call = prev in ALLOWED_FUNCS and t == "("
        # A name followed by parentheses may be a function call; fail closed
        # unless it is explicitly whitelisted. Require B*(x+1) for products.
        if prev and t=="(" and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*",prev) and prev not in ALLOWED_FUNCS|{"pi","E"}:
            raise UnsupportedExpression("Unknown function or ambiguous implicit multiplication; write * explicitly")
        if result and prev_atom and curr_atom and not function_call:
            result.append("*")
        result.append("**" if t == "^" else t)
        prev = t
    if len(result) > MAX_TOKENS:
        raise UnsupportedExpression("Too many expression tokens")
    return result


def _build(node: ast.AST, symbols: dict[str, Any], depth: int = 0):
    if depth > 24:
        raise UnsupportedExpression("Expression depth limit")
    if isinstance(node, ast.Constant):
        if type(node.value) not in (int, float):
            raise UnsupportedExpression("Only numeric literals")
        raw = str(node.value)
        if len(raw) > 28:
            raise UnsupportedExpression("Number too long")
        return S.Rational(raw)
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return S.pi
        if node.id == "E":
            return S.E
        if node.id in ALLOWED_FUNCS:
            raise UnsupportedExpression("Bare function symbol")
        if len(symbols) >= MAX_SYMBOLS and node.id not in symbols:
            raise UnsupportedExpression("Too many free variables")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,32}", node.id):
            raise UnsupportedExpression("Invalid symbol")
        if node.id not in symbols:
            symbols[node.id] = S.Symbol(node.id)
        return symbols[node.id]
    if isinstance(node, ast.UnaryOp):
        value = _build(node.operand, symbols, depth+1)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise UnsupportedExpression("Unsupported unary operator")
    if isinstance(node, ast.BinOp):
        a = _build(node.left, symbols, depth+1)
        b = _build(node.right, symbols, depth+1)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            if b == 0:
                raise UnsupportedExpression("Division by zero")
            return a / b
        if isinstance(node.op, ast.Pow):
            if b.is_integer is not True or b.is_number is not True:
                raise UnsupportedExpression("Symbolic/noninteger powers excluded")
            exp = int(b)
            if abs(exp) > 10:
                raise UnsupportedExpression("Power exceeds complexity bound")
            return a ** exp
        raise UnsupportedExpression("Unsupported binary operator")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or len(node.args) != 1 or node.keywords:
            raise UnsupportedExpression("Only supported unary functions")
        fn = node.func.id
        if fn not in ALLOWED_FUNCS:
            raise UnsupportedExpression("Unknown mathematical function")
        a = _build(node.args[0], symbols, depth+1)
        table = {"sin": S.sin, "cos": S.cos, "tan": S.tan,
                 "sqrt": S.sqrt, "exp": S.exp, "log": S.log, "abs": S.Abs}
        return table[fn](a)
    raise UnsupportedExpression("Unsafe AST node")


@lru_cache(maxsize=2048)
def parse(raw: str) -> dict[str, Any]:
    """Parse a single equality or expression. No Python/SymPy text evaluator."""
    require_symbolic()
    normalized = normalize(raw)
    m = EQUALITY_RE.search(normalized)
    operator = m.group() if m else None
    parts = (normalized[:m.start()], normalized[m.end():]) if m else (normalized,)
    if not all(parts):
        raise UnsupportedExpression("Missing expression side")
    syms: dict[str, Any] = {}
    expressions = []
    for part in parts:
        tokens = _tokens(part)
        try:
            tree = ast.parse("".join(tokens), mode="eval")
        except SyntaxError as exc:
            raise UnsupportedExpression("Unparseable math syntax") from exc
        expressions.append(_build(tree.body, syms))
    return {
        "raw": raw,
        "normalized": normalized,
        "operator": operator,
        "sides": expressions,
        "symbols": sorted(syms),
        "expression": expressions[0],
        "residual": expressions[0] - expressions[1] if len(expressions) == 2 else None,
    }


def extract(text: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Bounded, source-located equation candidates; report all truncation."""
    require_symbolic()
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    stats = {"lines_inspected":0,"candidates_seen":0,"parse_rejected":0,
             "skipped_long_lines":0,"truncated_lines":0,"truncated_candidates":0}
    lines = text.splitlines()
    for n, line in enumerate(lines[:MAX_SOURCE_LINES], 1):
        stats["lines_inspected"] += 1
        if len(line) > 600:
            stats["skipped_long_lines"] += 1
            continue
        if "=" not in line and "≈" not in line and "≃" not in line and r"\approx" not in line:
            continue
        chunks = [line]
        for m in LATEX_INLINE.finditer(line):
            chunks.append(m.group(1) or m.group(2))
        for chunk in chunks:
            for clause in re.split(r"[;,\n]", chunk):
                match = EQUALITY_RE.search(clause)
                if not match:
                    continue
                left = clause[:match.start()]
                right = clause[match.end():]
                prefix = list(PROSE_BREAK.finditer(left))
                if prefix:
                    left = left[prefix[-1].end():]
                # Explicitly marked display equations often start with an
                # ordinary label followed by a mathematical expression.
                # Match only a word + whitespace, not variable Result=...
                intro = re.match(r"^\s*(?:result|formula|observation|equation|calculation|computed)\s+(.+)$", left, re.I)
                if intro:
                    left = intro.group(1)
                # An ordinary sentence often introduces one variable: 'Formula B=...'.
                # Do not misread 'Formula B' as the product Formula*B.
                if not re.search(r'[0-9+*/^()\\πθΔφτ]',left) and len(left.strip().split())>1:
                    left=left.strip().split()[-1]
                # Cut after prose following the rightmost complete expression.
                right = re.split(r"\s+(?:where|with|which|because|and|the|for)\b", right, 1, flags=re.I)[0]
                right = re.sub(r"\.\s+[A-Za-z].*$", "", right)
                right = right.strip().rstrip(".!?")
                left = left.strip().lstrip("($")
                raw = (left + match.group() + right).strip()
                if not raw or len(raw)>MAX_EXPRESSION_LENGTH:
                    stats["parse_rejected"] += 1
                    continue
                stats["candidates_seen"] += 1
                try:
                    parsed = parse(raw)
                except (UnsupportedExpression, ValueError, TypeError, OverflowError):
                    stats["parse_rejected"] += 1
                    continue
                if parsed["residual"] is None:
                    continue
                key = (n, parsed["normalized"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"raw":raw,"source_line":n,"operator":parsed["operator"],
                             "normalized":parsed["normalized"],"symbols":parsed["symbols"]})
                if len(rows)>=MAX_SOURCE_CANDIDATES:
                    stats["truncated_candidates"] += 1
                    return rows, stats
    if len(lines)>MAX_SOURCE_LINES:
        stats["truncated_lines"]=len(lines)-MAX_SOURCE_LINES
    return rows, stats


def _safe_poly(e):
    """Polynomial with at most bounded degree; reject variable denominators."""
    if not e.free_symbols or len(e.free_symbols)>MAX_SYMBOLS or e.has(S.Function):
        return None
    denominator = S.denom(S.together(e))
    if denominator.free_symbols:
        return None
    syms = tuple(sorted(e.free_symbols, key=lambda x: x.name))
    try:
        polynomial = S.Poly(e,*syms)
    except (S.PolynomialError, TypeError, ValueError):
        return None
    if polynomial.total_degree()>MAX_POLY_DEGREE:
        return None
    return polynomial


def algebraically_equivalent(query: dict[str, Any], source: dict[str, Any]) -> bool:
    """Sound only for the explicitly bounded, constant-denominator polynomial class."""
    if query["residual"] is None or source["residual"] is None:
        return False
    # An approximation is never proof of an equality, even when its
    # rounded expression happens to have the same algebraic structure.
    if query["operator"] != "=" or source["operator"] != "=":
        return False
    q = query["residual"]
    s = source["residual"]
    if not q.free_symbols or q.free_symbols != s.free_symbols:
        return False
    a,b=_safe_poly(q),_safe_poly(s)
    if a is None or b is None or a.is_zero or b.is_zero:
        return False
    if a.monoms()!=b.monoms():
        return False
    coef_a,coef_b=a.coeffs(),b.coeffs()
    scale=S.cancel(coef_a[0]/coef_b[0])
    if scale==0 or scale.free_symbols or scale.is_finite is not True:
        return False
    return all(S.cancel(x-scale*y)==0 for x,y in zip(coef_a,coef_b))


def structural_contains(query: dict[str, Any], source: dict[str, Any]) -> bool:
    target=query["expression"]
    tree=[]
    for expr in source["sides"]:
        tree.extend(S.preorder_traversal(expr))
    return target in tree


def _numeric_solution(p: dict[str, Any], variable: str|None) -> tuple[float|None,str]:
    """One-symbol linear equalities only; distinguish solved from explicit RHS."""
    if p["residual"] is None:
        if p["expression"].free_symbols:
            return None,""
        expr=p["expression"]
        if expr.is_real is not True:
            return None,""
        return float(expr.evalf(18)),"numeric-expression"
    if len(p["symbols"])!=1:
        return None,""
    name=p["symbols"][0]
    if variable and name != variable:
        return None,""
    sym=S.Symbol(name)
    poly=_safe_poly(p["residual"])
    if poly is None or poly.degree(sym)!=1:
        return None,""
    try:
        coeff=poly.coeff_monomial(sym)
        const=poly.coeff_monomial(1)
        if coeff==0:return None,""
        value=S.cancel(-const/coeff)
        if value.free_symbols or value.is_real is not True:
            return None,""
        n=float(value.evalf(18))
        if not math.isfinite(n) or abs(n)>1e100:
            return None,""
        return n,"solved-linear-equality"
    except (TypeError, ValueError, OverflowError, S.PolynomialError):
        return None,""


def _numeric_request(raw: str) -> tuple[float,str|None,float]:
    # Usage: value:"0.2387;atol=0.003" or value:"B=0.2387;atol=0.003".
    parts=raw.split(";")
    if len(parts)>2:
        raise UnsupportedExpression("Expected number, optional ;atol=...")
    target=parts[0].strip()
    variable=None
    if "=" in target:
        variable, target=target.split("=",1)
        variable=variable.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z_0-9]{0,32}",variable):
            raise UnsupportedExpression("Invalid variable")
    try:value=float(target)
    except ValueError as e:
        raise UnsupportedExpression("value: requires a numeric target") from e
    atol=0.001
    if len(parts)==2:
        if not parts[1].startswith("atol="):
            raise UnsupportedExpression("Use ;atol=... (absolute tolerance)")
        try:atol=float(parts[1][5:])
        except ValueError as e:
            raise UnsupportedExpression("Invalid tolerance") from e
    if not math.isfinite(value) or not math.isfinite(atol) or atol<=0 or atol>1:
        raise UnsupportedExpression("Finite absolute tolerance required (0 < atol <= 1)")
    return value,variable,atol


def match_source(text: str, mode: str, request: str) -> tuple[list[dict[str,Any]],dict[str,int]]:
    """Return provenance-bearing matches, never a bare unsupported false."""
    require_symbolic()
    if mode not in ("equiv", "contains", "value"):
        raise UnsupportedExpression("Unknown mathematical query mode")
    goal = parse(request) if mode != "value" else None
    val, variable, tol = _numeric_request(request) if mode == "value" else (None,None,None)
    if goal and mode=="equiv" and goal["residual"] is None:
        raise UnsupportedExpression("equiv: requires an equality, not an expression fragment")
    spans,stats=extract(text)
    output=[]
    for row in spans:
        expr=parse(row["raw"])
        relation=""
        details={}
        if mode=="equiv" and algebraically_equivalent(goal,expr):
            relation="ALGEBRAICALLY_EQUIVALENT_POLYNOMIAL"
            details={"proof_class":"bounded-polynomial-constant-scale",
                     "scope":"same named variables; constant denominators; no domain-sensitive transformations"}
        elif mode=="contains" and structural_contains(goal,expr):
            relation="CONTAINS_SUBEXPRESSION"
            details={"proof_class":"literal-symbolic-AST-structure"}
        elif mode=="value":
            numeric,derivation=_numeric_solution(expr,variable)
            if numeric is not None and abs(numeric-val)<=tol:
                relation="NUMERICALLY_CONSISTENT"
                details={"source_numeric":numeric,"query_numeric":val,
                         "difference_absolute":abs(numeric-val),
                         "tolerance_absolute":tol,"numeric_provenance":derivation,
                         "scope":"Numerical consistency is not identity, matching observable, or physical evidence"}
        if not relation:
            continue
        output.append({"classification":relation,"expression":row["raw"],
                       "normalized":row["normalized"],"source_line":row["source_line"],
                       "symbol_names":row["symbols"],**details})
        if len(output)>=MAX_MATCH_EVIDENCE:
            break
    return output,stats


def capabilities()->dict[str,Any]:
    return {"module":"mersearch_math","version":VERSION,
            "dependency_sympy":dependency_state(),
            "query_fields":{"equiv":"Bounded polynomial equality, constant scaling only",
                            "contains":"AST subexpression in a source equation",
                            "value":"Single-variable linear solution approximately matches a number; use ;atol=..."},
            "supported_input":"Limited Unicode/LaTeX symbols, \\frac, variables, basic arithmetic, integer powers, selected functions",
            "not_supported":["CAS arbitrary algebraic identities","symbol renaming by default",
                             "transcendental/trigonometric equivalence","units or dimensional analysis",
                             "variable-dependent denominators","unbounded LaTeX",
                             "derivation genealogy proof","free prose semantic matching"],
            "resource_bounds":{"source_lines":MAX_SOURCE_LINES,"source_equations":MAX_SOURCE_CANDIDATES,
                               "expression_tokens":MAX_TOKENS,"symbols":MAX_SYMBOLS,
                               "max_match_evidence":MAX_MATCH_EVIDENCE}}
