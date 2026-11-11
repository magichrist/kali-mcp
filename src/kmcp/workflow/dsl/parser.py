"""DSL parser for the Playbook Studio workflow language.

Recursive-descent parser that turns a token stream (from
:mod:`kmcp.workflow.dsl.grammar`) into an AST of :class:`PlaybookAST`
nodes. The AST is compiled to a canonical
:class:`kmcp.workflow.yaml_loader.PlaybookDefinition` by
:mod:`kmcp.workflow.dsl.compiler`.

Grammar (per docs/visual/03_DSL_SPECIFICATION.md §3):

    playbook       := header inputs? execution? steps outputs?
    header         := "id" ":" IDENTIFIER
                     "name" ":" STRING
                     ["version" ":" STRING]
                     ["description" ":" STRING]
    inputs         := "inputs" "{" input_decl ("," input_decl)* "}"
    input_decl     := IDENTIFIER ":" type_expr
                     [":" "source" ":" SOURCE]
                     [":" "required" ":" BOOL]
                     [":" "default" ":" literal]
    type_expr      := "string" | "integer" | "float" | "boolean"
                     | "enum" ":" "{" STRING ("," STRING)* "}"
                     | "domain" | "ip" | "cidr" | "url"
                     | "port" | "port_range"
                     | "array" ":" "[" type_expr "]"
                     | "object" ":" "{" "}"
                     | "secret" | "scope_reference"
    execution      := "execution" "{" ["max_parallel" ":" INTEGER]
                     ["timeout" ":" INTEGER] ["resume" ":" BOOL] "}"
    steps          := "steps" "{" step_decl ("," step_decl)* "}"
    step_decl      := IDENTIFIER ":" [module | tool]
                     ["depends_on" ":" "[" IDENTIFIER ("," IDENTIFIER)* "]"]
                     ["when" ":" condition]
                     ["parallel" ":" BOOL]
                     ["foreach" ":" field_ref]
                     ["retry" ":" INTEGER]
                     ["on_failure" ":" "continue" | "skip_dependents" | "abort"]
                     ["checkpoint" ":" BOOL]
                     ["budget" ":" "{" ... "}"]
                     "inputs" ":" "{" input_mapping ("," input_mapping)* "}"
    module         := "module" ":" MODULE_REF
    tool           := "tool" ":" TOOL_NAME
    input_mapping  := IDENTIFIER ":" field_ref | literal
    outputs        := "outputs" "{" output_map ("," output_map)* "}"
    output_map     := IDENTIFIER ":" field_ref
    condition      := field_ref OPERATOR literal
    field_ref      := "{{" steps IDENTIFIER "." field ( "." field )* "}}"
                    | "{{" inputs IDENTIFIER "}}"
                    | "{{" target "}}
    literal        := STRING | INTEGER | FLOAT | BOOL | "null"

Commas between declarations are optional (newlines also separate).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from kmcp.workflow.dsl.grammar import (
    BOOL,
    COLON,
    COMMA,
    DOT,
    EOF,
    EQ,
    FIELD_REF,
    FLOAT,
    GE,
    GT,
    IDENTIFIER,
    INTEGER,
    LBRACE,
    LBRACKET,
    LE,
    LT,
    NE,
    NULL,
    RBRACE,
    RBRACKET,
    STRING,
    Token,
    tokenize,
)


class DSLParseError(ValueError):
    """Raised when DSL source text cannot be parsed."""

    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"line {line}, col {col}: {message}")
        self.line = line
        self.col = col


# ── AST nodes ───────────────────────────────────────────────────────────────


@dataclass
class TypeExpr:
    """A type declaration parsed from DSL."""

    kind: str  # string, integer, float, boolean, domain, ip, cidr, url,
    # port, port_range, secret, scope_reference, enum, array, object
    values: list[str] | None = None  # enum values
    element: TypeExpr | None = None  # array element type


@dataclass
class InputDecl:
    name: str
    type_expr: TypeExpr
    source: str | None = None  # agent | operator | static
    required: bool = False
    default: Any = None


@dataclass
class Execution:
    max_parallel: int | None = None
    timeout: int | None = None
    resume: bool | None = None


@dataclass
class FieldRef:
    """A structured reference: {{steps.X.Y}}, {{inputs.X}}, or {{target}}."""

    kind: str  # "steps" | "inputs" | "target"
    path: list[str]  # e.g. ["dns", "resolved_hosts"] or ["target"] or []

    def __str__(self) -> str:
        if self.kind == "target":
            return "{{target}}"
        if self.kind == "inputs":
            return f"{{{{inputs.{self.path[0]}}}}}"
        return f"{{{{steps.{'.'.join(self.path)}}}}}"


@dataclass
class Literal:
    """A literal value: string, integer, float, boolean, null."""

    kind: str  # "string" | "integer" | "float" | "boolean" | "null"
    value: Any


@dataclass
class InputMapping:
    name: str
    value: FieldRef | Literal


@dataclass
class OutputMap:
    name: str
    field_ref: FieldRef


@dataclass
class StepDecl:
    id: str
    kind: str  # "module" | "tool"
    ref: str  # module reference or tool name
    depends_on: list[str] = dataclass_field(default_factory=list)
    when: str | None = None  # raw condition string, e.g. "{{steps.x.count}} > 0"
    parallel: bool = False
    foreach: FieldRef | None = None
    retry: int = 0
    on_failure: str = "abort"
    checkpoint: bool = False
    budget: dict[str, Any] = dataclass_field(default_factory=dict)
    inputs: list[InputMapping] = dataclass_field(default_factory=list)


@dataclass
class PlaybookAST:
    id: str
    name: str
    version: str
    description: str | None = None
    inputs: list[InputDecl] = dataclass_field(default_factory=list)
    execution: Execution = dataclass_field(default_factory=Execution)
    steps: list[StepDecl] = dataclass_field(default_factory=list)
    outputs: list[OutputMap] = dataclass_field(default_factory=list)


# ── Parser ──────────────────────────────────────────────────────────────────


class _Parser:
    """Recursive-descent parser over a token stream."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ── low-level helpers ─────────────────────────────────────────────────

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _next(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, typ: str) -> Token:
        tok = self._next()
        if tok.type != typ:
            raise DSLParseError(
                f"expected {typ}, got {tok.type} ({tok.value!r})",
                tok.line,
                tok.col,
            )
        return tok

    def _accept(self, typ: str) -> Token | None:
        if self._peek().type == typ:
            return self._next()
        return None

    def _accept_comma_or_newline(self) -> None:
        """Consume an optional comma separator between declarations."""
        self._accept(COMMA)

    def _at(self, *types: str) -> bool:
        return self._peek().type in types

    def _at_keyword(self, word: str) -> bool:
        return self._peek().type == IDENTIFIER and self._peek().value == word

    def _expect_keyword(self, word: str) -> Token:
        tok = self._next()
        if tok.type != IDENTIFIER or tok.value != word:
            raise DSLParseError(
                f"expected keyword {word!r}, got {tok.type} ({tok.value!r})",
                tok.line,
                tok.col,
            )
        return tok

    # ── top-level ─────────────────────────────────────────────────────────

    def parse(self) -> PlaybookAST:
        ast = self._parse_header()

        # Optional sections in order: inputs, execution, steps, outputs
        while not self._at(EOF):
            if self._at_keyword("inputs"):
                ast.inputs = self._parse_inputs()
            elif self._at_keyword("execution"):
                ast.execution = self._parse_execution()
            elif self._at_keyword("steps"):
                ast.steps = self._parse_steps()
            elif self._at_keyword("outputs"):
                ast.outputs = self._parse_outputs()
            else:
                tok = self._peek()
                raise DSLParseError(
                    f"unexpected section {tok.value!r} at line {tok.line}, "
                    f"col {tok.col}; expected one of inputs, execution, steps, outputs",
                    tok.line,
                    tok.col,
                )

        return ast

    def _parse_header(self) -> PlaybookAST:
        # id: IDENTIFIER (may be dotted like custom.domain_recon)
        self._expect_keyword("id")
        self._expect(COLON)
        id_tok = self._expect(IDENTIFIER)
        pb_id = str(id_tok.value)
        while self._at(DOT):
            self._next()  # consume dot
            part_tok = self._next()
            if part_tok.type != IDENTIFIER:
                raise DSLParseError(
                    f"expected identifier segment in dotted id, got {part_tok.type}",
                    part_tok.line,
                    part_tok.col,
                )
            pb_id = f"{pb_id}.{part_tok.value}"

        # name: STRING
        self._expect_keyword("name")
        self._expect(COLON)
        name_tok = self._expect(STRING)
        name = str(name_tok.value)

        version = "1.0"
        description: str | None = None

        if self._at_keyword("version"):
            self._next()
            self._expect(COLON)
            vtok = self._next()
            if vtok.type == STRING or vtok.type == IDENTIFIER:
                version = str(vtok.value)
            else:
                raise DSLParseError(
                    f"expected version string, got {vtok.type}",
                    vtok.line,
                    vtok.col,
                )

        if self._at_keyword("description"):
            self._next()
            self._expect(COLON)
            dtok = self._next()
            if dtok.type == STRING:
                description = str(dtok.value)
            else:
                raise DSLParseError(
                    f"expected description string, got {dtok.type}",
                    dtok.line,
                    dtok.col,
                )

        return PlaybookAST(id=pb_id, name=name, version=version, description=description)

    def _parse_inputs(self) -> list[InputDecl]:
        self._expect_keyword("inputs")
        self._expect(LBRACE)
        decls: list[InputDecl] = []
        while not self._at(RBRACE, EOF):
            decls.append(self._parse_input_decl())
            self._accept_comma_or_newline()
        self._expect(RBRACE)
        return decls

    def _parse_input_decl(self) -> InputDecl:
        name_tok = self._expect(IDENTIFIER)
        name = str(name_tok.value)
        self._expect(COLON)
        type_expr = self._parse_type_expr()
        source: str | None = None
        required = False
        default: Any = None

        while self._at(IDENTIFIER) and str(self._peek().value) in {
            "source",
            "required",
            "default",
        }:
            key_tok = self._next()
            key = str(key_tok.value)
            self._expect(COLON)
            if key == "source":
                src_tok = self._next()
                if src_tok.type != IDENTIFIER or str(src_tok.value) not in {
                    "agent",
                    "operator",
                    "static",
                }:
                    raise DSLParseError(
                        f"source must be agent/operator/static, got {src_tok.value!r}",
                        src_tok.line,
                        src_tok.col,
                    )
                source = str(src_tok.value)
            elif key == "required":
                req_tok = self._next()
                if req_tok.type != BOOL:
                    raise DSLParseError(
                        f"required must be true/false, got {req_tok.type}",
                        req_tok.line,
                        req_tok.col,
                    )
                required = bool(req_tok.value)
            elif key == "default":
                default = self._parse_literal().value

        return InputDecl(
            name=name,
            type_expr=type_expr,
            source=source,
            required=required,
            default=default,
        )

    def _parse_type_expr(self) -> TypeExpr:
        tok = self._next()
        word = str(tok.value)

        if word == "enum":
            # Grammar allows optional colon: enum {..} or enum: {..}
            if self._at(COLON):
                self._next()
            self._expect(LBRACE)
            values: list[str] = []
            while not self._at(RBRACE, EOF):
                vtok = self._expect(STRING)
                values.append(str(vtok.value))
                self._accept_comma_or_newline()
            self._expect(RBRACE)
            return TypeExpr(kind="enum", values=values)

        if word == "array":
            self._expect(COLON)
            self._expect(LBRACKET)
            element = self._parse_type_expr()
            self._expect(RBRACKET)
            return TypeExpr(kind="array", element=element)

        if word == "object":
            self._expect(COLON)
            self._expect(LBRACE)
            self._expect(RBRACE)
            return TypeExpr(kind="object")

        valid_primitives = {
            "string",
            "integer",
            "float",
            "boolean",
            "domain",
            "ip",
            "cidr",
            "url",
            "port",
            "port_range",
            "secret",
            "scope_reference",
        }
        if word in valid_primitives:
            return TypeExpr(kind=word)

        raise DSLParseError(
            f"unknown type {word!r}; expected one of {sorted(valid_primitives)}, "
            f"enum {{...}}, array [...], object {{}}",
            tok.line,
            tok.col,
        )

    def _parse_execution(self) -> Execution:
        self._expect_keyword("execution")
        self._expect(LBRACE)
        exec_ = Execution()
        while not self._at(RBRACE, EOF):
            key_tok = self._expect(IDENTIFIER)
            key = str(key_tok.value)
            self._expect(COLON)
            if key == "max_parallel":
                vtok = self._expect(INTEGER)
                exec_.max_parallel = int(vtok.value)
            elif key == "timeout":
                vtok = self._expect(INTEGER)
                exec_.timeout = int(vtok.value)
            elif key == "resume":
                vtok = self._expect(BOOL)
                exec_.resume = bool(vtok.value)
            else:
                raise DSLParseError(
                    f"unknown execution key {key!r}",
                    key_tok.line,
                    key_tok.col,
                )
            self._accept_comma_or_newline()
        self._expect(RBRACE)
        return exec_

    def _parse_steps(self) -> list[StepDecl]:
        self._expect_keyword("steps")
        self._expect(LBRACE)
        steps: list[StepDecl] = []
        seen_ids: set[str] = set()
        while not self._at(RBRACE, EOF):
            id_tok = self._peek()
            step = self._parse_step_decl()
            if step.id in seen_ids:
                raise DSLParseError(
                    f"duplicate step id: {step.id}",
                    id_tok.line,
                    id_tok.col,
                )
            seen_ids.add(step.id)
            steps.append(step)
            self._accept_comma_or_newline()
        self._expect(RBRACE)
        self._detect_cycles(steps)
        return steps

    def _detect_cycles(self, steps: list[StepDecl]) -> None:
        """Raise DSLParseError if the dependency graph contains a cycle."""
        adj: dict[str, list[str]] = {s.id: list(s.depends_on) for s in steps}
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {s.id: WHITE for s in steps}

        def dfs(node: str, path: list[str]) -> None:
            color[node] = GRAY
            path.append(node)
            for dep in adj.get(node, []):
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    cycle = " → ".join(path[path.index(dep) :] + [dep])
                    raise DSLParseError(f"dependency cycle: {cycle}", 0, 0)
                if color[dep] == WHITE:
                    dfs(dep, path)
            path.pop()
            color[node] = BLACK

        for sid in adj:
            if color[sid] == WHITE:
                dfs(sid, [])

    def _parse_step_decl(self) -> StepDecl:
        id_tok = self._expect(IDENTIFIER)
        step_id = str(id_tok.value)
        self._expect(COLON)

        kind: str | None = None
        ref: str | None = None

        if self._at_keyword("module"):
            self._next()
            if self._at(COLON):
                self._next()  # optional colon: module: ref or module ref
            ref_tok = self._next()
            if ref_tok.type != IDENTIFIER:
                raise DSLParseError(
                    f"expected module reference, got {ref_tok.type}",
                    ref_tok.line,
                    ref_tok.col,
                )
            kind = "module"
            ref = str(ref_tok.value)
            # Allow dotted module refs like dns.resolve — but tokenizer already
            # split on dots. Rejoin if the next token is DOT + IDENTIFIER.
            while self._at(DOT):
                self._next()  # consume dot
                part_tok = self._next()
                if part_tok.type != IDENTIFIER:
                    raise DSLParseError(
                        f"expected module name segment, got {part_tok.type}",
                        part_tok.line,
                        part_tok.col,
                    )
                ref = f"{ref}.{part_tok.value}"
        elif self._at_keyword("tool"):
            self._next()
            if self._at(COLON):
                self._next()  # optional colon: tool: ref or tool ref
            ref_tok = self._next()
            if ref_tok.type != IDENTIFIER:
                raise DSLParseError(
                    f"expected tool name, got {ref_tok.type}",
                    ref_tok.line,
                    ref_tok.col,
                )
            kind = "tool"
            ref = str(ref_tok.value)
        else:
            tok = self._peek()
            raise DSLParseError(
                f"step {step_id!r} must declare module: or tool:",
                tok.line,
                tok.col,
            )

        depends_on: list[str] = []
        when: str | None = None
        parallel = False
        foreach: FieldRef | None = None
        retry = 0
        on_failure = "abort"
        checkpoint = False
        budget: dict[str, Any] = {}

        while True:
            if self._at_keyword("depends_on"):
                self._next()
                if self._at(COLON):
                    self._next()
                self._expect(LBRACKET)
                while not self._at(RBRACKET, EOF):
                    dep_tok = self._expect(IDENTIFIER)
                    depends_on.append(str(dep_tok.value))
                    self._accept_comma_or_newline()
                self._expect(RBRACKET)
            elif self._at_keyword("when"):
                self._next()
                if self._at(COLON):
                    self._next()
                when = self._parse_condition()
            elif self._at_keyword("parallel"):
                self._next()
                if self._at(COLON):
                    self._next()
                vtok = self._expect(BOOL)
                parallel = bool(vtok.value)
            elif self._at_keyword("foreach"):
                self._next()
                if self._at(COLON):
                    self._next()
                foreach = self._parse_field_ref()
            elif self._at_keyword("retry"):
                self._next()
                if self._at(COLON):
                    self._next()
                vtok = self._expect(INTEGER)
                retry = int(vtok.value)
            elif self._at_keyword("on_failure"):
                self._next()
                if self._at(COLON):
                    self._next()
                vtok = self._next()
                if vtok.type != IDENTIFIER or str(vtok.value) not in {
                    "continue",
                    "skip_dependents",
                    "abort",
                }:
                    raise DSLParseError(
                        f"on_failure must be continue/skip_dependents/abort, got {vtok.value!r}",
                        vtok.line,
                        vtok.col,
                    )
                on_failure = str(vtok.value)
            elif self._at_keyword("checkpoint"):
                self._next()
                if self._at(COLON):
                    self._next()
                vtok = self._expect(BOOL)
                checkpoint = bool(vtok.value)
            elif self._at_keyword("budget"):
                self._next()
                if self._at(COLON):
                    self._next()
                self._expect(LBRACE)
                # Budget contents are opaque to the DSL — store as raw key/value
                while not self._at(RBRACE, EOF):
                    bkey = self._expect(IDENTIFIER)
                    self._expect(COLON)
                    bval = self._parse_literal()
                    budget[str(bkey.value)] = bval.value
                    self._accept_comma_or_newline()
                self._expect(RBRACE)
            else:
                break

        # inputs: { mapping... }  (colon optional)
        self._expect_keyword("inputs")
        if self._at(COLON):
            self._next()
        self._expect(LBRACE)
        mappings: list[InputMapping] = []
        while not self._at(RBRACE, EOF):
            mappings.append(self._parse_input_mapping())
            self._accept_comma_or_newline()
        self._expect(RBRACE)

        return StepDecl(
            id=step_id,
            kind=kind,
            ref=ref,
            depends_on=depends_on,
            when=when,
            parallel=parallel,
            foreach=foreach,
            retry=retry,
            on_failure=on_failure,
            checkpoint=checkpoint,
            budget=budget,
            inputs=mappings,
        )

    def _parse_condition(self) -> str:
        """Parse a when condition and return its raw string."""
        tok = self._next()
        if tok.type == STRING:
            # Entire condition is a quoted string: "{{steps.X.Y}} > 0"
            return str(tok.value)
        # Unquoted: field_ref OPERATOR literal
        field = self._parse_field_ref()
        op_tok = self._next()
        if op_tok.type not in {GT, LT, GE, LE, EQ, NE}:
            raise DSLParseError(
                f"expected comparison operator in when condition, got {op_tok.type}",
                op_tok.line,
                op_tok.col,
            )
        lit = self._parse_literal()
        return f"{field} {op_tok.value} {lit.value}"

    def _parse_field_ref(self) -> FieldRef:
        """Parse a {{...}} field reference token."""
        tok = self._next()
        if tok.type == STRING:
            # Quoted form: "{{steps.X.Y}}" — unwrap and parse
            raw = str(tok.value)
            if not (raw.startswith("{{") and raw.endswith("}}")):
                raise DSLParseError(
                    f"expected field reference {{...}}, got string {raw!r}",
                    tok.line,
                    tok.col,
                )
            inner = raw[2:-2].strip()
        elif tok.type == FIELD_REF:
            kind, path = tok.value
            segments = [s for s in path.split(".") if s] if path else []
            return FieldRef(kind=kind, path=segments)
        else:
            raise DSLParseError(
                f"expected field reference, got {tok.type}",
                tok.line,
                tok.col,
            )
        return self._parse_field_ref_inner(inner, tok.line, tok.col)

    def _parse_field_ref_inner(self, inner: str, line: int, col: int) -> FieldRef:
        parts = inner.split(".")
        if parts[0] == "target":
            if len(parts) != 1:
                raise DSLParseError(
                    "{{target}} takes no additional path segments",
                    line,
                    col,
                )
            return FieldRef(kind="target", path=[])
        if parts[0] == "inputs":
            if len(parts) != 2:
                raise DSLParseError(
                    "{{inputs.X}} takes exactly one segment",
                    line,
                    col,
                )
            return FieldRef(kind="inputs", path=[parts[1]])
        if parts[0] == "steps":
            if len(parts) < 2:
                raise DSLParseError(
                    "{{steps.SID.FIELD...}} requires at least step id and field",
                    line,
                    col,
                )
            return FieldRef(kind="steps", path=parts[1:])
        raise DSLParseError(
            f"unknown field reference kind {parts[0]!r}; expected steps/inputs/target",
            line,
            col,
        )

    def _parse_input_mapping(self) -> InputMapping:
        name_tok = self._expect(IDENTIFIER)
        name = str(name_tok.value)
        self._expect(COLON)
        # value is either a field_ref or a literal
        tok = self._peek()
        if tok.type == FIELD_REF:
            value: FieldRef | Literal = self._parse_field_ref()
        elif tok.type == STRING:
            raw = str(tok.value)
            if raw.startswith("{{") and raw.endswith("}}"):
                value = self._parse_field_ref()
            else:
                lit = self._parse_literal()
                value = Literal(kind=lit.kind, value=lit.value)
        else:
            lit = self._parse_literal()
            value = Literal(kind=lit.kind, value=lit.value)
        return InputMapping(name=name, value=value)

    def _parse_outputs(self) -> list[OutputMap]:
        self._expect_keyword("outputs")
        self._expect(LBRACE)
        maps: list[OutputMap] = []
        while not self._at(RBRACE, EOF):
            name_tok = self._expect(IDENTIFIER)
            name = str(name_tok.value)
            self._expect(COLON)
            field_ref = self._parse_field_ref()
            maps.append(OutputMap(name=name, field_ref=field_ref))
            self._accept_comma_or_newline()
        self._expect(RBRACE)
        return maps

    def _parse_literal(self) -> Literal:
        tok = self._next()
        if tok.type == STRING:
            return Literal(kind="string", value=str(tok.value))
        if tok.type == IDENTIFIER:
            # Bare word (e.g. `default: safe`) → string literal
            return Literal(kind="string", value=str(tok.value))
        if tok.type == INTEGER:
            return Literal(kind="integer", value=int(tok.value))
        if tok.type == FLOAT:
            return Literal(kind="float", value=float(tok.value))
        if tok.type == BOOL:
            return Literal(kind="boolean", value=bool(tok.value))
        if tok.type == NULL:
            return Literal(kind="null", value=None)
        raise DSLParseError(
            f"expected literal, got {tok.type} ({tok.value!r})",
            tok.line,
            tok.col,
        )


def parse(text: str) -> PlaybookAST:
    """Parse DSL source text into a :class:`PlaybookAST`."""
    tokens = tokenize(text)
    return _Parser(tokens).parse()


__all__ = [
    "DSLParseError",
    "Execution",
    "FieldRef",
    "InputDecl",
    "InputMapping",
    "Literal",
    "OutputMap",
    "PlaybookAST",
    "StepDecl",
    "TypeExpr",
    "parse",
]
