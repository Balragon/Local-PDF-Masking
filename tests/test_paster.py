from datetime import date

from excelpaster.core import (
    FormatSpec,
    column_names,
    looks_like_header,
    parse_column_names,
    resolve_table,
    dump_presets,
    load_presets,
    parse_table,
    render,
    split_table,
    render_template,
    split_template,
    unknown_placeholders,
)

ORDER = ("품명\t규격\t수량\r\nXx형태\t700*350*1600\t1\r\nGAa\t백색도장\t1\r\n111N형태\t600*400*1200\t4\r\n"
         "AR38\t\t20\r\nAED16\t\t8\r\nM161\t\t1\r\n")
ORDER_EXPECTED = """11/5일 입고요청
Xx형태 700*350*1600 1개
GAa 백색도장 1개
111N형태 600*400*1200 4개
AR38 20개
AED16 8개
M161 1개
오전입고 바랍니다."""

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
    spec = FormatSpec(template="{#}/{행수} {이름}({2}) {금액|comma}원")
    assert render(t, spec) == "1/2 홍길동(영업) 1,234,567원\n2/2 김철수(개발) 89,000원"


def test_template_without_header_row():
    t = parse_table("홍길동\t영업\n김철수\t개발\n")
    spec = FormatSpec(template="{1}-{2}", header_row=False)
    assert render(t, spec) == "홍길동-영업\n김철수-개발"
    assert column_names(["", "x"]) == ["1", "x"]


def test_head_body_tail_template():
    spec = FormatSpec(template="11/5일 입고요청\n{품명} {규격} {수량}개\n오전입고 바랍니다.")
    assert render(parse_table(ORDER), spec) == ORDER_EXPECTED
    # 헤더 없이 번호로, 꼬리말 앞 빈 줄 유지
    body = ORDER.split("\r\n", 1)[1]
    spec = FormatSpec(template="11/5일 입고요청\n{1} {2} {3}개\n\n오전입고 바랍니다.", header_row=False)
    assert render(parse_table(body), spec) == ORDER_EXPECTED.replace("\n오전", "\n\n오전")


def test_split_template():
    assert split_template("머리\n{1}\n{2}\n꼬리") == ("머리", "{1}\n{2}", "꼬리")
    assert split_template("{1}") == ("", "{1}", "")
    assert split_template("{1}\n") == ("", "{1}\n", "")          # 꼬리말 없음 → 빈 줄은 반복 부분
    assert split_template("{1}\n\n꼬리") == ("", "{1}", "\n꼬리")  # 꼬리말 있음 → 빈 줄은 꼬리말 앞 간격
    assert split_template("머리만") == ("", "머리만", "")
    # {오늘} {행수} 만 있는 줄은 머리말/꼬리말, 반복 줄 사이의 일반 줄은 반복 부분에 포함
    assert split_template("{오늘}일 요청\n{1}\n---\n{2}\n총 {행수}건") == ("{오늘}일 요청", "{1}\n---\n{2}", "총 {행수}건")


def test_today_placeholder():
    d = date.today()
    assert render_template("{오늘}", ["a"], ["x"], 1, 1) == f"{d.month}/{d.day}"


def test_empty_cell_collapses_one_adjacent_space():
    h = ["a", "b", "c"]
    assert render_template("{a} {b} {c}개", h, ["AR38", "", "20"], 1, 1) == "AR38 20개"
    assert render_template("{a} {b}", h, ["AR38", "", ""], 1, 1) == "AR38"
    assert render_template("{b} {a}", h, ["AR38", "", ""], 1, 1) == "AR38"
    assert render_template("[{b}] {a}", h, ["AR38", "", ""], 1, 1) == "[] AR38"
    assert render_template("{a}  {b}  {c}", h, ["x", "", "z"], 1, 1) == "x   z"  # 공백 하나만 제거
    assert render_template("  {b} {a}", h, ["AR38", "", ""], 1, 1) == "  AR38"  # 들여쓰기는 유지


def test_multiline_template_repeats_per_row():
    t = parse_table(EXCEL)
    spec = FormatSpec(template="■ {이름}\n  부서: {부서}\n")
    assert render(t, spec) == "■ 홍길동\n  부서: 영업\n\n■ 김철수\n  부서: 개발\n"
    assert render(t, FormatSpec(template="{이름}\r\n{부서}")) == "홍길동\n영업\n김철수\n개발"


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
    assert render(t, FormatSpec(template="{h}")) == "a\nb"
    assert render(t, FormatSpec(template="{h}", skip_blank_rows=False)) == "a\n\nb"


def test_presets_roundtrip_and_bad_input():
    presets = [FormatSpec(name="a", template="{1}"), FormatSpec(name="b", template="{2}\n", header_row=False)]
    back = load_presets(dump_presets(presets))
    assert back == presets
    assert load_presets("") == []
    assert load_presets("not json") == []
    # 이전 버전 프리셋(row_template, mode 등) 도 읽힘
    old = '{"presets":[{"name":"x","mode":"template","row_template":"{이름}","joiner":"\\\\n","extra":1}]}'
    assert load_presets(old)[0] == FormatSpec(name="x", template="{이름}")


REAL_HEADER = ("품명\t규격\t\t\t\t재질\t수량\t 매입가 \t 판매가 \t주요사양\t비고\t발주처\t작성일\t"
               "\"입고\n예정\"\t입고일\t출고       예정일\t출고일\r\n")
REAL_ROWS = ("Xx형태\t700*350*1600\t\t\t\tSUS304\t1\t10000\t12000\t\t\tA사\t11/1\t11/5\t\t\t\r\n"
             "AR38\t\t\t\t\t\t20\t\t\t\t\t\t\t\t\t\t\r\n")


def test_real_sheet_header_row():
    t = parse_table(REAL_HEADER + REAL_ROWS)
    assert len(t[0]) == 17
    names = column_names(resolve_table(t, FormatSpec(template="{품명}"))[0])
    assert names[:7] == ["품명", "규격", "3", "4", "5", "재질", "수량"]
    assert names[7] == "매입가" and names[13] == "입고 예정" and names[15] == "출고 예정일"
    spec = FormatSpec(template="{오늘}일 입고요청\n{품명} {규격} {재질} {수량}개\n오전입고 바랍니다.")
    out = render(t, spec)
    assert out.splitlines()[1:] == ["Xx형태 700*350*1600 SUS304 1개", "AR38 20개", "오전입고 바랍니다."]
    # 셀 안 줄바꿈·공백이 든 열 이름도 여러 방식으로 참조 가능
    assert render(t, FormatSpec(template="{입고예정}|{입고 예정}|{매입가}|{출고예정일}")).splitlines()[0] == "11/5|11/5|10000|"
    assert unknown_placeholders("{입고예정} {없음}", split_table(t, True)[0]) == ["없음"]


def test_auto_header_detection():
    data_only = "Xx형태\t700*350*1600\tSUS304\t1\r\nAR38\t\t\t20\r\n"
    with_header = "품명\t규격\t재질\t수량\r\n" + data_only
    tpl = FormatSpec(template="{품명} {규격} {재질} {수량}개")
    # 1) 템플릿에 쓴 이름이 첫 행에 있으면 헤더
    assert looks_like_header(parse_table(with_header), [], tpl.template)
    # 2) 데이터만 복사: 첫 행에 숫자 있음 → 데이터. 모든 행이 들어감
    assert not looks_like_header(parse_table(data_only), [], tpl.template)
    headers, rows, is_header = resolve_table(parse_table(data_only), tpl)
    assert not is_header and len(rows) == 2 and headers == ["1", "2", "3", "4"]
    # 3) 저장된 열 이름이 있으면 데이터만 복사해도 이름으로 참조
    known = parse_column_names("품명, 규격, 재질, 수량")
    assert render(parse_table(data_only), tpl, known) == "Xx형태 700*350*1600 SUS304 1개\nAR38 20개"
    # 저장된 열 이름 + 헤더 포함 복사 → 헤더 건너뜀
    assert render(parse_table(with_header), tpl, known) == "Xx형태 700*350*1600 SUS304 1개\nAR38 20개"
    # 4) 번호 템플릿 + 헤더 있음: 첫 행엔 숫자 없고 아래엔 있음 → 헤더로 판단
    num = FormatSpec(template="{1} {4}")
    assert render(parse_table(with_header), num) == "Xx형태 1\nAR38 20"
    # 숫자가 전혀 없는 명단은 전부 데이터
    names_only = "홍길동\t영업\n김철수\t개발\n"
    assert render(parse_table(names_only), FormatSpec(template="{1}")) == "홍길동\n김철수"
    # 강제 지정도 그대로 동작
    assert render(parse_table(names_only), FormatSpec(template="{1}", header_row=True)) == "김철수"


def test_parse_column_names():
    assert parse_column_names("품명, 규격, , , , 재질, 수량") == ["품명", "규격", "", "", "", "재질", "수량"]
    assert parse_column_names("품명\t규격\t\t재질") == ["품명", "규격", "", "재질"]
    assert parse_column_names("  ") == []
    # 실제 헤더 행 17열을 저장해 두고 데이터만 복사
    known = [c for c in parse_table(REAL_HEADER)[0]]
    known = [" ".join(k.split()) for k in known]
    out = render(parse_table(REAL_ROWS), FormatSpec(template="{품명} {규격} {재질} {수량}개"), known)
    assert out == "Xx형태 700*350*1600 SUS304 1개\nAR38 20개"
