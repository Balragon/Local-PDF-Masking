"""엑셀 클립보드 텍스트 파싱과 템플릿 변환. GUI 없이 테스트 가능."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass, replace

Table = list[list[str]]

MODES = ("template", "markdown", "csv", "json")
MODE_LABELS = {
    "template": "사용자 템플릿",
    "markdown": "마크다운 표",
    "csv": "CSV",
    "json": "JSON",
}

# 특수 자리표시자 (열 이름보다 우선하지 않음 — 같은 이름의 열이 있으면 열이 우선)
ROW_NUMBER_KEYS = ("#", "행번호", "n", "row")
ROW_COUNT_KEYS = ("행수", "rows", "count")
COL_COUNT_KEYS = ("열수", "cols")


@dataclass
class FormatSpec:
    """변환 방법 하나. 프리셋으로 저장/불러오기 할 수 있도록 JSON 직렬화 가능."""

    name: str = ""
    mode: str = "template"
    row_template: str = "{1}"
    joiner: str = "\\n"      # 행 사이 (이스케이프 문자열: \n, \t 사용 가능)
    prefix: str = ""         # 전체 앞
    suffix: str = ""         # 전체 뒤
    header_row: bool = True  # 첫 행을 열 이름으로 사용
    skip_blank_rows: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FormatSpec":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        spec = cls(**known)
        if spec.mode not in MODES:
            spec.mode = "template"
        return spec

    def copy(self, **changes) -> "FormatSpec":
        return replace(self, **changes)


# ---------------------------------------------------------------- 파싱

def parse_table(text: str) -> Table:
    """엑셀이 클립보드에 넣는 TSV를 2차원 문자열 배열로.

    - 행 구분: CRLF/LF, 열 구분: 탭
    - 줄바꿈·탭·따옴표가 든 셀은 엑셀이 큰따옴표로 감싸고 따옴표는 두 번 씀 → csv 모듈로 처리
    - 마지막 빈 줄(엑셀이 붙이는 꼬리 개행)은 제거, 모든 행을 같은 열 수로 맞춤
    """
    if not text:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t", quotechar='"',
                        doublequote=True, strict=False)
    rows: Table = [list(r) for r in reader]
    while rows and all(c == "" for c in rows[-1]):
        rows.pop()
    if not rows:
        return []
    width = max(len(r) for r in rows)
    for r in rows:
        r.extend([""] * (width - len(r)))
    return rows


def split_table(table: Table, header_row: bool, skip_blank_rows: bool = True) -> tuple[list[str], Table]:
    """(열 이름 목록, 데이터 행) 으로 분리. 헤더가 없으면 열 이름은 '1', '2', ..."""
    if not table:
        return [], []
    width = len(table[0])
    if header_row:
        headers = [h.strip() for h in table[0]]
        data = table[1:]
    else:
        headers = [str(i + 1) for i in range(width)]
        data = table
    if skip_blank_rows:
        data = [r for r in data if any(c.strip() for c in r)]
    return headers, data


def column_names(table: Table, header_row: bool) -> list[str]:
    """GUI 자리표시자 칩에 쓸 이름들. 헤더가 비어 있으면 번호로 대체."""
    headers, _ = split_table(table, header_row, skip_blank_rows=False)
    return [h if h else str(i + 1) for i, h in enumerate(headers)]


# ---------------------------------------------------------------- 템플릿

_ESC_RE = re.compile(r"\\(n|t|r|\\)")
_ESC_MAP = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}


def unescape(s: str) -> str:
    """한 줄짜리 입력칸에서 \\n, \\t 를 실제 문자로."""
    return _ESC_RE.sub(lambda m: _ESC_MAP[m.group(1)], s)


class TemplateError(ValueError):
    pass


def _scan(template: str) -> list[tuple[bool, str]]:
    """템플릿을 (자리표시자 여부, 내용) 조각으로. str.format 처럼 {{ }} 는 글자 그대로."""
    out: list[tuple[bool, str]] = []
    buf: list[str] = []
    i, n = 0, len(template)
    while i < n:
        c = template[i]
        if c == "{":
            if template.startswith("{{", i):
                buf.append("{")
                i += 2
                continue
            j = template.find("}", i + 1)
            if j == -1 or "{" in template[i + 1:j]:
                buf.append(c)
                i += 1
                continue
            if buf:
                out.append((False, "".join(buf)))
                buf = []
            out.append((True, template[i + 1:j]))
            i = j + 1
        elif c == "}" and template.startswith("}}", i):
            buf.append("}")
            i += 2
        else:
            buf.append(c)
            i += 1
    if buf:
        out.append((False, "".join(buf)))
    return out


def placeholders(template: str) -> list[str]:
    """템플릿에 쓰인 자리표시자 이름(필터 제외) 목록. 중복 제거, 순서 유지."""
    seen: list[str] = []
    for is_field, inner in _scan(template):
        if not is_field:
            continue
        name = inner.split("|", 1)[0].strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def unknown_placeholders(template: str, headers: list[str]) -> list[str]:
    """열 이름·번호·특수 키 어디에도 해당하지 않는 자리표시자."""
    lookup = _build_lookup(headers)
    out = []
    for name in placeholders(template):
        if _resolve_index(name, lookup, len(headers)) is None and not _is_special(name):
            out.append(name)
    return out


def _is_special(name: str) -> bool:
    k = name.lower()
    return k in ROW_NUMBER_KEYS or k in ROW_COUNT_KEYS or k in COL_COUNT_KEYS


def _build_lookup(headers: list[str]) -> dict[str, int]:
    """열 이름 → 인덱스. 같은 이름이 여러 개면 첫 번째. 대소문자 무시 키도 추가."""
    lookup: dict[str, int] = {}
    for i, h in enumerate(headers):
        h = h.strip()
        if not h:
            continue
        lookup.setdefault(h, i)
        lookup.setdefault(h.lower(), i)
    return lookup


def _resolve_index(name: str, lookup: dict[str, int], width: int) -> int | None:
    name = name.strip()
    if name in lookup:
        return lookup[name]
    if name.lower() in lookup:
        return lookup[name.lower()]
    if name.isdigit():
        i = int(name) - 1
        return i if 0 <= i < width else None
    return None


_NUM_RE = re.compile(r"^\s*(-?)([\d,]*)(\.\d+)?\s*$")


def _comma(value: str) -> str:
    m = _NUM_RE.match(value)
    if not m or not m.group(2):
        return value
    sign, whole, frac = m.group(1), m.group(2).replace(",", ""), m.group(3) or ""
    if not whole.isdigit():
        return value
    return f"{sign}{int(whole):,}{frac}"


def _apply_filter(value: str, spec: str) -> str:
    """`이름|필터1|필터2:인자` 형태의 필터 하나 적용."""
    name, _, arg = spec.strip().partition(":")
    name = name.strip().lower()
    if name == "comma":
        return _comma(value)
    if name == "nocomma":
        return value.replace(",", "")
    if name == "upper":
        return value.upper()
    if name == "lower":
        return value.lower()
    if name == "trim":
        return value.strip()
    if name == "default":
        return value if value.strip() else arg
    if name in ("ljust", "rjust", "zfill", "center"):
        try:
            n = int(arg)
        except ValueError as e:
            raise TemplateError(f"필터 '{name}' 에는 숫자 인자가 필요합니다") from e
        return getattr(value, name)(n)
    if name == "replace":
        old, _, new = arg.partition(",")
        return value.replace(old, new)
    if name == "quote":
        return '"' + value.replace('"', '""') + '"'
    if name == "oneline":
        return " ".join(value.split())
    raise TemplateError(f"알 수 없는 필터: {name}")


def render_template(template: str, headers: list[str], row: list[str],
                    row_number: int, row_count: int) -> str:
    lookup = _build_lookup(headers)
    width = len(headers)
    out: list[str] = []
    for is_field, inner in _scan(template):
        if not is_field:
            out.append(inner)
            continue
        parts = inner.split("|")
        name = parts[0].strip()
        idx = _resolve_index(name, lookup, width)
        if idx is not None:
            value = row[idx] if idx < len(row) else ""
        elif name.lower() in ROW_NUMBER_KEYS:
            value = str(row_number)
        elif name.lower() in ROW_COUNT_KEYS:
            value = str(row_count)
        elif name.lower() in COL_COUNT_KEYS:
            value = str(width)
        else:
            out.append("{" + inner + "}")  # 모르는 이름은 그대로 둠 (타이핑 중 깨지지 않도록)
            continue
        for f in parts[1:]:
            if f.strip():
                value = _apply_filter(value, f)
        out.append(value)
    return "".join(out)


# ---------------------------------------------------------------- 렌더링

def _md_cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def render_markdown(headers: list[str], data: Table) -> str:
    if not headers:
        return ""
    cols = [h if h else str(i + 1) for i, h in enumerate(headers)]
    widths = [len(c) for c in cols]
    body = [[_md_cell(c) for c in r] for r in data]
    for r in body:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    widths = [max(w, 3) for w in widths]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"

    lines = [line(cols), "| " + " | ".join("-" * w for w in widths) + " |"]
    lines.extend(line(r) for r in body)
    return "\n".join(lines)


def render_csv(headers: list[str], data: Table, header_row: bool) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if header_row:
        w.writerow(headers)
    w.writerows(data)
    return buf.getvalue().rstrip("\n")


def render_json(headers: list[str], data: Table, header_row: bool) -> str:
    if header_row:
        keys = [h if h else str(i + 1) for i, h in enumerate(headers)]
        obj = [dict(zip(keys, r)) for r in data]
    else:
        obj = data
    return json.dumps(obj, ensure_ascii=False, indent=2)


def render(table: Table, spec: FormatSpec) -> str:
    """표 전체를 spec 대로 텍스트로. 템플릿 오류는 TemplateError."""
    headers, data = split_table(table, spec.header_row, spec.skip_blank_rows)
    if not headers:
        return ""
    if spec.mode == "markdown":
        body = render_markdown(headers, data)
    elif spec.mode == "csv":
        body = render_csv(headers, data, spec.header_row)
    elif spec.mode == "json":
        body = render_json(headers, data, spec.header_row)
    else:
        n = len(data)
        rows = [render_template(spec.row_template, headers, r, i + 1, n) for i, r in enumerate(data)]
        body = unescape(spec.joiner).join(rows)
    meta_row = [""] * len(headers)
    prefix = render_template(unescape(spec.prefix), headers, meta_row, 0, len(data)) if spec.prefix else ""
    suffix = render_template(unescape(spec.suffix), headers, meta_row, 0, len(data)) if spec.suffix else ""
    return prefix + body + suffix


# ---------------------------------------------------------------- 프리셋

BUILTIN_PRESETS: list[FormatSpec] = [
    FormatSpec(name="한 줄씩: 열을 쉼표로", mode="template",
               row_template="{1}, {2}, {3}", joiner="\\n"),
    FormatSpec(name="이름 목록 (쉼표로 이어 붙이기)", mode="template",
               row_template="{1}", joiner=", "),
    FormatSpec(name="번호 매기기", mode="template",
               row_template="{#}. {1}", joiner="\\n"),
    FormatSpec(name="문장 템플릿 예시", mode="template",
               row_template="{1}님 ({2}) - {3|comma}원", joiner="\\n",
               suffix="\\n\\n총 {행수}건"),
    FormatSpec(name="마크다운 표", mode="markdown"),
    FormatSpec(name="CSV", mode="csv"),
    FormatSpec(name="JSON", mode="json"),
]

PRESETS_VERSION = 1


def dump_presets(presets: list[FormatSpec]) -> str:
    return json.dumps({"version": PRESETS_VERSION, "presets": [p.to_dict() for p in presets]},
                      ensure_ascii=False, indent=2)


def load_presets(text: str) -> list[FormatSpec]:
    if not text or not text.strip():
        return []
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = obj.get("presets", []) if isinstance(obj, dict) else obj
    out = []
    for it in items:
        if isinstance(it, dict):
            out.append(FormatSpec.from_dict(it))
    return out


HELP_TEXT = """\
자리표시자
  {열이름}      첫 행의 열 이름으로 참조 (예: {이름}, {부서})
  {1} {2} …    열 번호로 참조 (헤더가 없어도 사용 가능)
  {#}          행 번호 (1부터),   {행수} 전체 행 수,   {열수} 열 수
  {{  }}        중괄호를 글자 그대로 넣을 때

필터 (| 로 이어서, 여러 개 가능)
  {금액|comma}        1234567 → 1,234,567
  {금액|nocomma}      1,234 → 1234
  {이름|trim}         앞뒤 공백 제거
  {코드|upper} {코드|lower}
  {비고|default:없음} 비어 있으면 대신 쓸 값
  {이름|ljust:10} {금액|rjust:12} {번호|zfill:5}
  {비고|replace:a,b}  a 를 b 로 바꿈
  {메모|oneline}      셀 안의 줄바꿈·연속 공백을 한 칸으로
  {값|quote}          큰따옴표로 감싸기

행 사이 / 앞 / 뒤 칸에서는 \\n (줄바꿈), \\t (탭) 을 쓸 수 있습니다.
"""
