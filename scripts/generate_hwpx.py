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
        zf.writestr("META-INF/container.rdf", container_rdf_xml())
        zf.writestr("META-INF/manifest.xml", manifest_xml())
        zf.writestr("Contents/content.hpf", content_hpf_xml())
        zf.writestr("Contents/header.xml", header_xml())
        zf.writestr("Contents/section0.xml", section)
        zf.writestr("Preview/PrvText.txt", preview)


def build_section(data):
    paragraphs = []
    paragraphs.append(section_properties_paragraph())
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
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
        'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head">'
        + "".join(paragraphs)
        + "</hs:sec>"
    )


def section_properties_paragraph():
    sec_pr = (
        '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" '
        'tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="0" memoShapeIDRef="0" '
        'textVerticalWidthHead="0" masterPageCnt="0">'
        '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>'
        '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
        '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" '
        'border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
        '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
        '<hp:pagePr landscape="NARROWLY" width="59528" height="84186" gutterType="LEFT_ONLY">'
        '<hp:margin header="0" footer="0" gutter="0" left="4251" right="4251" top="4251" bottom="4251"/>'
        '</hp:pagePr>'
        '<hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
        '<hp:noteLine length="24662" type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/>'
        '<hp:numbering type="CONTINUOUS" newNum="1"/>'
        '<hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr>'
        '<hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar="." supscript="0"/>'
        '<hp:noteLine length="24662" type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hp:noteSpacing betweenNotes="1984" belowLine="567" aboveLine="850"/>'
        '<hp:numbering type="CONTINUOUS" newNum="1"/>'
        '<hp:placement place="END_OF_DOCUMENT" beneathText="0"/></hp:endNotePr>'
        '<hp:pageBorderFill type="BOTH" borderFillIDRef="0" textBorder="PAPER" '
        'headerInside="0" footerInside="0" fillArea="PAPER">'
        '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/>'
        '</hp:pageBorderFill>'
        '</hp:secPr>'
        '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
    )
    return (
        '<hp:p id="2147483648" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="0">{sec_pr}</hp:run>'
        + make_lineseg(1000)
        + "</hp:p>"
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
        '<hp:shapeComment>수식입니다.</hp:shapeComment>'
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
<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" version="1.4" secCnt="1">
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
<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" version="" unique-identifier="" id="">
  <opf:metadata><opf:title>시험지-hwp변환</opf:title><opf:language>ko</opf:language></opf:metadata>
  <opf:manifest>
    <opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
    <opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
    <opf:item id="settings" href="settings.xml" media-type="application/xml"/>
  </opf:manifest>
  <opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine>
</opf:package>"""


def container_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">
  <ocf:rootfiles>
    <ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
    <ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>
    <ocf:rootfile full-path="META-INF/container.rdf" media-type="application/rdf+xml"/>
  </ocf:rootfiles>
</ocf:container>"""


def container_rdf_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""><pkg:hasPart xmlns:pkg="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" rdf:resource="Contents/header.xml"/></rdf:Description>
  <rdf:Description rdf:about="Contents/header.xml"><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#HeaderFile"/></rdf:Description>
  <rdf:Description rdf:about=""><pkg:hasPart xmlns:pkg="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" rdf:resource="Contents/section0.xml"/></rdf:Description>
  <rdf:Description rdf:about="Contents/section0.xml"><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#SectionFile"/></rdf:Description>
  <rdf:Description rdf:about=""><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#Document"/></rdf:Description>
</rdf:RDF>"""


def manifest_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>"""


def version_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="0" buildNumber="1" os="1" xmlVersion="1.4" application="Hancom Office Hangul"/>"""


def settings_xml():
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">
  <ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>
</ha:HWPApplicationSetting>"""


def xml(value):
    return html.escape(str(value), quote=True)


if __name__ == "__main__":
    main()
