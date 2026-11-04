import json

from excelpaster.core import (
    FormatSpec,
    column_names,
    dump_presets,
    load_presets,
    parse_table,
    render,
    render_template,
    unescape,
    unknown_placeholders,
)

EXCEL = "이름\t부서\t금액\r\n홍길동\t영업\t1234567\r\n김철수\t개발\t89000\r\n"


def test_parse_excel_tsv_strips_trailing_newline():
    t = parse_table(EXCEL)
    assert t == [["이름", "부서", "금액"], ["홍길동", "영업", "1234567"], ["김철수", "개발", "89000"]]


def test_parse_quoted_cell_with_newline_and_quotes():
    # 엑셀은 줄바꿈/따옴표가 든 셀을 큰따옴표로 감싸고 따옴표는 두 번 씀
    text = 'a\tb\r\n"첫줄\n둘째줄"\t"그는 ""안녕""이라 했다"\r\n'
    t = parse_table(text)
    assert t == [["a", "b"], ["첫줄\n둘째줄", '그는 "안녕"이라 했다']]


def test_parse_pads_ragged_rows_and_single_column():
    assert parse_table("a\tb\nc\n") == [["a", "b"], ["c", ""]]
    assert parse_table("x\ny\nz") == [["x"], ["y"], ["z"]]
    assert parse_table("") == []
    assert parse_table("\r\n\r\n") == []


def test_template_by_header_number_and_specials():
    t = parse_table(EXCEL)
    spec = FormatSpec(row_template="{#}/{행수} {이름}({2}) {금액|comma}원", joiner="\\n")
    assert render(t, spec) == "1/2 홍길동(영업) 1,234,567원\n2/2 김철수(개발) 89,000원"


def test_template_without_header_row():
    t = parse_table("홍길동\t영업\n김철수\t개발\n")
    spec = FormatSpec(row_template="{1}-{2}", joiner=", ", header_row=False)
    assert render(t, spec) == "홍길동-영업, 김철수-개발"
    assert column_names(t, False) == ["1", "2"]
    assert column_names(parse_table(EXCEL), True) == ["이름", "부서", "금액"]


def test_prefix_suffix_and_escapes():
    t = parse_table(EXCEL)
    spec = FormatSpec(row_template="{이름}", joiner="\\t", prefix="[{행수}명]\\n", suffix="\\n끝")
    assert render(t, spec) == "[2명]\n홍길동\t김철수\n끝"
    assert unescape(r"a\nb\tc\\d") == "a\nb\tc\\d"


def test_unknown_placeholder_left_as_is_and_reported():
    out = render_template("{이름} {없는열}", ["이름"], ["홍"], 1, 1)
    assert out == "홍 {없는열}"
    assert unknown_placeholders("{이름} {없는열} {#} {2}", ["이름", "부서"]) == ["없는열"]


def test_brace_escape_and_filters():
    headers = ["값", "비고"]
    assert render_template("{{{값}}}", headers, ["x", ""], 1, 1) == "{x}"
    assert render_template("{비고|default:없음}", headers, ["x", ""], 1, 1) == "없음"
    assert render_template("{값|upper}|{값|rjust:4}|{값|zfill:3}", headers, ["ab", ""], 1, 1) == "AB|  ab|0ab"
    assert render_template("{값|comma}", headers, ["-1234.5", ""], 1, 1) == "-1,234.5"
    assert render_template("{값|comma}", headers, ["abc", ""], 1, 1) == "abc"
    assert render_template("{값|nocomma}", headers, ["1,000", ""], 1, 1) == "1000"
    assert render_template("{값|replace:a,b}", headers, ["aaa", ""], 1, 1) == "bbb"
    assert render_template("{값|oneline}", headers, ["a\n  b", ""], 1, 1) == "a b"
    assert render_template("{값|quote}", headers, ['s"q', ""], 1, 1) == '"s""q"'
    assert render_template("{값|trim|lower}", headers, ["  AB ", ""], 1, 1) == "ab"


def test_header_name_case_insensitive_and_duplicates():
    out = render_template("{name}/{NAME}/{2}", ["Name", "Name"], ["a", "b"], 1, 1)
    assert out == "a/a/b"


def test_skip_blank_rows():
    t = parse_table("h\na\n\t\nb\n")
    assert render(t, FormatSpec(row_template="{h}", joiner=",")) == "a,b"
    assert render(t, FormatSpec(row_template="{h}", joiner=",", skip_blank_rows=False)) == "a,,b"


def test_markdown():
    t = parse_table("이름\t비고\n홍길동\ta|b\n김\t\"두\n줄\"\n")
    out = render(t, FormatSpec(mode="markdown"))
    assert out.splitlines() == [
        "| 이름  | 비고     |",
        "| --- | ------ |",
        "| 홍길동 | a\\|b   |",
        "| 김   | 두<br>줄 |",
    ]


def test_csv_and_json():
    t = parse_table(EXCEL)
    assert render(t, FormatSpec(mode="csv")) == "이름,부서,금액\n홍길동,영업,1234567\n김철수,개발,89000"
    assert render(t, FormatSpec(mode="csv", header_row=False)).startswith("이름,부서,금액\n")
    obj = json.loads(render(t, FormatSpec(mode="json")))
    assert obj == [{"이름": "홍길동", "부서": "영업", "금액": "1234567"},
                   {"이름": "김철수", "부서": "개발", "금액": "89000"}]
    assert json.loads(render(t, FormatSpec(mode="json", header_row=False)))[0] == ["이름", "부서", "금액"]


def test_presets_roundtrip_and_bad_input():
    presets = [FormatSpec(name="a", row_template="{1}"), FormatSpec(name="b", mode="csv")]
    back = load_presets(dump_presets(presets))
    assert back == presets
    assert load_presets("") == []
    assert load_presets("not json") == []
    assert load_presets('{"presets":[{"name":"x","mode":"weird","extra":1}]}')[0].mode == "template"
