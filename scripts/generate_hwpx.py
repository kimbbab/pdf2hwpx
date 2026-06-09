#!/usr/bin/env python3
import html
import json
import re
import sys
import zipfile
from pathlib import Path


PAGE_HORZSIZE = "42520"


def main():
    if len(sys.argv) != 3:
        print("usage: generate_hwpx.py exam.json output.hwpx", file=sys.stderr)
        raise SystemExit(2)

    data_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    data = json.loads(data_path.read_text(encoding="utf-8"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_hwpx(data, out_path)


def write_hwpx(data, out_path):
    section = build_section(data)
    preview = build_preview_text(data)

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        zf.writestr("version.xml", version_xml())
        zf.writestr("settings.xml", settings_xml())
        zf.writestr("META-INF/container.xml", container_xml())
        zf.writestr("META-INF/manifest.xml", manifest_xml())
        zf.writestr("Contents/content.hpf", content_hpf_xml())
        zf.writestr("Contents/header.xml", header_xml())
        zf.writestr("Contents/section0.xml", section)
        zf.writestr("Preview/PrvText.txt", preview)


def build_section(data):
    paragraphs = []
    title = data.get("title") or "시험지 풀이해설"
    paragraphs.append(paragraph([{"t": title}], char="1", height=1400))
    info = data.get("info") or {}
    meta = " / ".join(str(info.get(key, "")).strip() for key in ("school", "grade", "range") if info.get(key))
    if meta:
        paragraphs.append(paragraph([{"t": meta}], char="0"))
    paragraphs.append(paragraph([{"t": ""}], char="0"))

    for problem in data.get("problems", []):
        number = problem.get("number", "")
        topic = problem.get("topic") or "미분류"
        difficulty = problem.get("difficulty") or "중"
        prefix = [{"t": f"{number}. [{topic} / {difficulty}] "}]
        paragraphs.append(paragraph(prefix + list(problem.get("parts") or []), char="0"))

        choices = problem.get("choices") or []
        symbols = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"]
        for idx, choice in enumerate(choices):
            label = symbols[idx] if idx < len(symbols) else f"{idx + 1})"
            paragraphs.append(paragraph([{"t": f"{label} "}] + list(choice), char="0"))

        answer = problem.get("answer") or ""
        if answer:
            paragraphs.append(paragraph([{"t": f"정답: {answer}"}], char="2"))
        explanation = problem.get("explanation_parts") or []
        if explanation:
            paragraphs.append(paragraph([{"t": "해설: "}] + list(explanation), char="0"))
        paragraphs.append(paragraph([{"t": ""}], char="0"))

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">'
        + "".join(paragraphs)
        + "</hs:sec>"
    )


def paragraph(parts, char="0", height=1000):
    runs = []
    current = []
    for part in normalize_parts(parts):
        if part.get("br"):
            if current:
                runs.append(run(current, char))
                current = []
            runs.append(line_break())
            continue
        current.append(part)
    if current:
        runs.append(run(current, char))
    if not runs:
        runs.append(f'<hp:run charPrIDRef="{char}"><hp:t/></hp:run>')
    return (
        '<hp:p id="2147483648" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        + "".join(runs)
        + make_lineseg(height)
        + "</hp:p>"
    )


def run(parts, char):
    content = []
    for part in parts:
        if "eq" in part:
            content.append(equation_xml(to_hwp_eq(part["eq"])))
        else:
            content.append(f"<hp:t>{xml(part.get('t', ''))}</hp:t>")
    return f'<hp:run charPrIDRef="{char}">' + "".join(content) + "</hp:run>"


def line_break():
    return '<hp:run charPrIDRef="0"><hp:t/></hp:run>'


def equation_xml(script):
    width = max(1200, min(30000, 470 * len(script) + 900))
    return (
        '<hp:equation id="0" zOrder="0" numberingType="EQUATION" textWrap="TOP_AND_BOTTOM" '
        'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" version="Equation Version 60" '
        'baseLine="85" textColor="#000000" baseUnit="1100" lineMode="CHAR" font="HYhwpEQ">'
        f'<hp:sz width="{width}" widthRelTo="ABSOLUTE" height="1125" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
        'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" '
        'vertOffset="0" horzOffset="0"/>'
        '<hp:outMargin left="56" right="56" top="0" bottom="0"/>'
        f"<hp:script>{xml(script)}</hp:script>"
        "</hp:equation>"
    )


def make_lineseg(height):
    baseline = int(height * 0.85)
    return (
        '<hp:linesegarray>'
        f'<hp:lineseg textpos="0" vertpos="0" vertsize="{height}" textheight="{height}" '
        f'baseline="{baseline}" spacing="600" horzpos="0" horzsize="{PAGE_HORZSIZE}" flags="393216"/>'
        '</hp:linesegarray>'
    )


def normalize_parts(parts):
    out = []
    for part in parts or []:
        if not isinstance(part, dict):
            out.append({"t": str(part)})
        elif part.get("br") is True:
            out.append({"br": True})
        elif isinstance(part.get("eq"), str):
            out.append({"eq": part["eq"]})
        elif isinstance(part.get("math"), str):
            out.append({"eq": part["math"]})
        elif isinstance(part.get("t"), str):
            out.append({"t": part["t"]})
        elif isinstance(part.get("text"), str):
            out.append({"t": part["text"]})
    return out


def to_hwp_eq(value):
    s = str(value).strip().strip("$")
    s = s.replace("×", r"\times ").replace("÷", r"\div ")
    s = replace_superscripts(s)
    s = replace_frac(s)
    s = re.sub(r"\\(?:d|t)?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"{\1} over {\2}", s)
    s = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt {\1}", s)
    s = (
        s.replace(r"\times", " times ")
        .replace(r"\cdot", " times ")
        .replace(r"\div", " div ")
        .replace(r"\left", "")
        .replace(r"\right", "")
        .replace(r"\leq", " <= ")
        .replace(r"\geq", " >= ")
        .replace(r"\neq", " != ")
        .replace(r"\ne", " != ")
    )
    s = re.sub(r"\\(?:mathrm|text|operatorname)\{([^{}]+)\}", r"\1", s)
    s = re.sub(r"\^\{([^{}]+)\}", r"^{\1}", s)
    s = re.sub(r"\^([A-Za-z0-9+\-])", r"^{\1}", s)
    s = re.sub(r"_\{([^{}]+)\}", r"_{\1}", s)
    s = re.sub(r"_([A-Za-z0-9+\-])", r"_{\1}", s)
    s = s.replace("\\", "")
    s = re.sub(r"([0-9A-Za-z}\)])(times|div|over)(?=[0-9A-Za-z{(\[])", r"\1 \2 ", s)
    s = re.sub(r"(times|div|over)(?=[0-9A-Za-z{(\[])", r"\1 ", s)
    s = re.sub(r"\s+(times|div|over|<=|>=|!=)\s+", r" \1 ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or str(value)


def replace_superscripts(s):
    mapping = {
        "⁰": "^{0}",
        "¹": "^{1}",
        "²": "^{2}",
        "³": "^{3}",
        "⁴": "^{4}",
        "⁵": "^{5}",
        "⁶": "^{6}",
        "⁷": "^{7}",
        "⁸": "^{8}",
        "⁹": "^{9}",
    }
    for src, dst in mapping.items():
        s = s.replace(src, dst)
    return s


def replace_frac(s):
    pattern = re.compile(r"\\(?:d|t)?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
    while True:
        next_s = pattern.sub(lambda m: "{" + to_hwp_eq(m.group(1)) + "} over {" + to_hwp_eq(m.group(2)) + "}", s)
        if next_s == s:
            return s
        s = next_s


def build_preview_text(data):
    lines = [str(data.get("title") or "시험지 풀이해설")]
    for problem in data.get("problems", []):
        lines.append(f"{problem.get('number')}. {plain_text(problem.get('parts') or [])}")
        if problem.get("answer"):
            lines.append(f"정답: {problem.get('answer')}")
    return "\n".join(lines)


def plain_text(parts):
    chunks = []
    for part in normalize_parts(parts):
        if part.get("br"):
            chunks.append("\n")
        elif "eq" in part:
            chunks.append(str(part["eq"]))
        else:
            chunks.append(str(part.get("t", "")))
    return "".join(chunks)


def header_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" version="1.0">
  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
  <hh:refList>
    <hh:fontfaces itemCnt="1">
      <hh:fontface lang="HANGUL" fontCnt="1"><hh:font id="0" face="함초롬바탕" type="TTF"/></hh:fontface>
    </hh:fontfaces>
    <hh:borderFills itemCnt="1">
      <hh:borderFill id="0" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"/>
    </hh:borderFills>
    <hh:charProperties itemCnt="3">
      <hh:charPr id="0" height="1000" textColor="#000000" shadeColor="NONE" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/></hh:charPr>
      <hh:charPr id="1" height="1400" textColor="#000000" shadeColor="NONE" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:bold/></hh:charPr>
      <hh:charPr id="2" height="1000" textColor="#1f5f3d" shadeColor="NONE" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:bold/></hh:charPr>
    </hh:charProperties>
    <hh:paraProperties itemCnt="1">
      <hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"><hh:align horizontal="JUSTIFY" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/><hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hh:paraPr>
    </hh:paraProperties>
    <hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties>
  </hh:refList>
</hh:head>"""


def content_hpf_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<opf:package xmlns:opf="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <opf:metadata><opf:title>시험지-hwp변환</opf:title><opf:language>ko</opf:language></opf:metadata>
  <opf:manifest>
    <opf:item id="header" href="header.xml" media-type="application/xml"/>
    <opf:item id="section0" href="section0.xml" media-type="application/xml"/>
  </opf:manifest>
  <opf:spine><opf:itemref idref="section0"/></opf:spine>
</opf:package>"""


def container_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></rootfiles>
</container>"""


def manifest_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<manifest xmlns="urn:oasis:names:tc:opendocument:xmlns:manifest">
  <file-entry full-path="/" media-type="application/hwp+zip"/>
  <file-entry full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
  <file-entry full-path="Contents/header.xml" media-type="application/xml"/>
  <file-entry full-path="Contents/section0.xml" media-type="application/xml"/>
</manifest>"""


def version_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" targetApplication="HWP" major="5" minor="1" micro="0" buildNumber="0"/>"""


def settings_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<ha:settings xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" caretPosition="0"/>"""


def xml(value):
    return html.escape(str(value), quote=True)


if __name__ == "__main__":
    main()
