"""엑셀 클립보드 텍스트 파싱과 템플릿 변환. GUI 없이 테스트 가능."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date

Table = list[list[str]]

# 특수 자리표시자 (열 이름보다 우선하지 않음 — 같은 이름의 열이 있으면 열이 우선)
ROW_NUMBER_KEYS = ("#", "행번호", "n", "row")
ROW_COUNT_KEYS = ("행수", "rows", "count")
COL_COUNT_KEYS = ("열수", "cols")
TODAY_KEYS = ("오늘", "today")


@dataclass
class FormatSpec:
    """변환 방법 하나. 프리셋으로 저장/불러오기 할 수 있도록 JSON 직렬화 가능."""

    name: str = ""
    template: str = "{1}"    # 행마다 반복되는 글. 행 사이는 줄바꿈
    header_row: bool = True  # 첫 행을 열 이름으로 사용
    skip_blank_rows: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FormatSpec":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if "template" not in known and "row_template" in d:  # 이전 버전 프리셋
            known["template"] = d["row_template"]
        return cls(**known)

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


def normalize_header(h: str) -> str:
    """열 이름 정리: 앞뒤 공백 제거, 셀 안의 줄바꿈·연속 공백은 한 칸으로 ('입고\\n예정' → '입고 예정')."""
    return " ".join(h.split())


def split_table(table: Table, header_row: bool, skip_blank_rows: bool = True) -> tuple[list[str], Table]:
    """(열 이름 목록, 데이터 행) 으로 분리. 헤더가 없으면 열 이름은 '1', '2', ..."""
    if not table:
        return [], []
    width = len(table[0])
    if header_row:
        headers = [normalize_header(h) for h in table[0]]
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
    return k in ROW_NUMBER_KEYS or k in ROW_COUNT_KEYS or k in COL_COUNT_KEYS or k in TODAY_KEYS


def _build_lookup(headers: list[str]) -> dict[str, int]:
    """열 이름 → 인덱스. 같은 이름이 여러 개면 첫 번째. 대소문자 무시 키도 추가."""
    lookup: dict[str, int] = {}
    for i, h in enumerate(headers):
        h = normalize_header(h)
        if not h:
            continue
        for key in (h, h.lower(), h.replace(" ", ""), h.replace(" ", "").lower()):
            lookup.setdefault(key, i)  # '입고 예정' 은 {입고 예정} 으로도 {입고예정} 으로도 참조 가능
    return lookup


def _resolve_index(name: str, lookup: dict[str, int], width: int) -> int | None:
    name = normalize_header(name)
    for key in (name, name.lower(), name.replace(" ", ""), name.replace(" ", "").lower()):
        if key in lookup:
            return lookup[key]
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


def _today() -> str:
    d = date.today()
    return f"{d.month}/{d.day}"


def render_template(template: str, headers: list[str], row: list[str],
                    row_number: int, row_count: int) -> str:
    """자리표시자를 채운다. 값이 빈 셀이면 양옆 공백 중 하나를 같이 지워 공백이 겹치지 않게 한다."""
    lookup = _build_lookup(headers)
    width = len(headers)
    out: list[str] = []
    eat_space = False  # 직전 자리표시자가 빈 값이었고 앞쪽 공백을 못 지운 경우 → 다음 글의 앞 공백 하나 제거
    for is_field, inner in _scan(template):
        if not is_field:
            if eat_space and inner.startswith(" "):
                inner = inner[1:]
            eat_space = False
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
        elif name.lower() in TODAY_KEYS:
            value = _today()
        else:
            eat_space = False
            out.append("{" + inner + "}")  # 모르는 이름은 그대로 둠 (타이핑 중 깨지지 않도록)
            continue
        for f in parts[1:]:
            if f.strip():
                value = _apply_filter(value, f)
        if value == "":
            prev = out[-1] if out else ""
            so_far = "".join(out).rstrip(" ")
            at_line_start = so_far == "" or so_far.endswith("\n")
            if not at_line_start and prev.endswith(" "):
                out[-1] = prev[:-1]   # 앞 공백 하나 제거
            else:
                eat_space = True      # 줄 머리(들여쓰기)는 두고 뒤 공백 하나 제거
            continue
        eat_space = False
        out.append(value)
    return "".join(out)


def _is_row_line(line: str) -> bool:
    """셀 값이나 행 번호를 참조하는 줄인가. {오늘} {행수} 처럼 행과 무관한 것만 있으면 머리말/꼬리말."""
    global_keys = TODAY_KEYS + ROW_COUNT_KEYS + COL_COUNT_KEYS
    return any(name.lower() not in global_keys for name in placeholders(line))


def split_template(template: str) -> tuple[str, str, str]:
    """템플릿을 (머리말, 행마다 반복할 부분, 꼬리말) 로 나눈다.

    자리표시자가 든 첫 줄부터 마지막 줄까지가 반복 부분이고, 그 앞뒤 줄은 한 번만 나온다.
    자리표시자가 한 줄도 없으면 전체가 반복 부분이다. 꼬리말이 없을 때 끝의 빈 줄은 반복 부분에
    들어가 행 사이를 띄우고, 꼬리말이 있으면 그 빈 줄은 꼬리말 앞의 간격이 된다.
    """
    lines = template.replace("\r\n", "\n").split("\n")
    marked = [i for i, ln in enumerate(lines) if _is_row_line(ln)]
    if not marked:
        return "", template, ""
    first, last = marked[0], marked[-1]
    if not any(ln.strip() for ln in lines[last + 1:]):
        last = len(lines) - 1  # 꼬리말이 없으면 끝의 빈 줄은 반복 부분에 포함 (행 사이 띄우기)
    head = "\n".join(lines[:first])
    body = "\n".join(lines[first:last + 1])
    tail = "\n".join(lines[last + 1:])
    return head, body, tail


# ---------------------------------------------------------------- 렌더링

def render(table: Table, spec: FormatSpec) -> str:
    """템플릿을 표에 적용한 텍스트. 템플릿 오류는 TemplateError.

    { } 가 든 줄들은 행마다 반복되어 줄바꿈으로 이어지고, 그 앞뒤 줄(머리말·꼬리말)은 한 번만 나온다.
    """
    headers, data = split_table(table, spec.header_row, spec.skip_blank_rows)
    if not headers:
        return ""
    n = len(data)
    head, body, tail = split_template(spec.template)
    meta = [""] * len(headers)
    parts = []
    if head:
        parts.append(render_template(head, headers, meta, 0, n))
    parts.extend(render_template(body, headers, r, i + 1, n) for i, r in enumerate(data))
    if tail:
        parts.append(render_template(tail, headers, meta, 0, n))
    return "\n".join(parts)


# ---------------------------------------------------------------- 프리셋

BUILTIN_PRESETS: list[FormatSpec] = [
    FormatSpec(name="입고요청 (품명·규격·재질·수량)",
               template="{오늘}일 입고요청\n{품명} {규격} {재질} {수량}개\n오전입고 바랍니다."),
    FormatSpec(name="품명·규격·재질·수량 한 줄씩", template="{품명} {규격} {재질} {수량}"),
    FormatSpec(name="열을 쉼표로 이어서 한 줄씩", template="{1}, {2}, {3}"),
    FormatSpec(name="번호 매기기", template="{#}. {1}"),
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
{ } 가 들어 있는 줄은 엑셀의 한 행마다 반복되고, 그 앞뒤 줄은 한 번만 나옵니다.

  11/5일 입고요청          ← 머리말 (한 번)
  {품명} {규격} {수량}개    ← 행마다 반복
  오전입고 바랍니다.        ← 꼬리말 (한 번)

반복 줄이 여러 줄이어도 되고, 끝에 빈 줄을 두면 행 사이가 띄어집니다.
빈 셀은 옆의 공백 하나와 함께 사라져 공백이 두 번 생기지 않습니다.

자리표시자
  {열이름}      첫 행의 열 이름으로 참조 (예: {품명}, {수량})
  {1} {2} …    열 번호로 참조 (헤더가 없어도 사용 가능)
  {#}          행 번호 (1부터),   {행수} 전체 행 수,   {오늘} 오늘 날짜 (11/5 형식)
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
"""
