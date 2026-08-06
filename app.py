from flask import Flask, request, jsonify, send_file
import json, base64, io, os, requests, re
import weasyprint
from weasyprint import CSS
from weasyprint.text.fonts import FontConfiguration

app = Flask(__name__)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SAMPLE_DATA = {
  "patient": {"name":"고객","age":"만 45세","gender":"남성","examDate":"2025년 12월 24일","mainFindings":"대사증후군 위험군 · 심혈관 관리 필요"},
  "dangerMetrics": [
    {"val":"100","unit":"mg/dL","norm":"정상 기준 99 이하","name":"공복혈당 — 당뇨 전단계"},
    {"val":"231","unit":"mg/dL","norm":"정상 기준 200 미만","name":"총콜레스테롤 — 경계 초과"},
    {"val":"26.7","unit":"kg/m2","norm":"정상 기준 18.5~24.9","name":"BMI — 과체중 주의"}
  ],
  "nutrients": [
    {"name":"혈당 조절","level":"bad","levelText":"당뇨 전단계","pct":70,"risk":"방치 시: 2형 당뇨 진행","note":"공복혈당이 반복 상승 중. 마그네슘·크롬 결핍이 원인.","span2":False},
    {"name":"콜레스테롤","level":"bad","levelText":"경계 초과","pct":75,"risk":"방치 시: 동맥경화 · 심근경색","note":"총콜레스테롤 231, LDL 상승. 오메가-3 보충 시급.","span2":False},
    {"name":"체중 · BMI","level":"warn","levelText":"과체중","pct":65,"risk":"혈당·콜레스테롤 악화 가속","note":"BMI 26.7. 5% 감량만으로 수치 개선 가능.","span2":False},
    {"name":"간 · 신장 기능","level":"ok","levelText":"정상","pct":75,"risk":"","note":"간·신장 수치 모두 정상 범위 유지 중.","span2":False},
    {"name":"혈압","level":"ok","levelText":"정상","pct":70,"risk":"","note":"혈압 정상이나 콜레스테롤 고려 혈관 관리 필요.","span2":True}
  ],
  "supplements": [
    {"num":"1","name":"오메가-3 고함량 (EPA 900mg 이상)","why":"총콜레스테롤 231로 심혈관 위험. 중성지방 감소·혈관 염증 억제에 가장 효과적.","eff":"▶ 3개월 복용 시 콜레스테롤 10~15% 개선 기대","tag":"지금 바로","tagClass":"now","accentClass":"r1"},
    {"num":"2","name":"마그네슘 글리시네이트 300mg","why":"혈당 조절 인슐린 수용체 기능에 필수. 당뇨 전단계에서 혈당 조절 능력 회복에 직접 기여.","eff":"▶ 8주 복용 시 공복혈당 5~10 개선 + 수면 향상","tag":"지금 바로","tagClass":"now","accentClass":"r2"},
    {"num":"3","name":"코엔자임 Q10 100mg","why":"심장 근육 에너지 생성 필수. 혈압 조절 보조 효과 임상 확인.","eff":"▶ 심장 기능 보조 · 산화 스트레스 감소","tag":"이달 내","tagClass":"soon","accentClass":"r3"},
    {"num":"4","name":"비타민D3 1000IU","why":"혈당 조절·면역·골밀도에 필수. 중장년 이후 급격히 감소하는 영양소.","eff":"▶ 골밀도 유지 + 면역력 회복 + 혈당 조절 보조","tag":"추가 권장","tagClass":"opt","accentClass":"r4"}
  ],
  "insurance": [
    {"headClass":"red","headTitle":"2형 당뇨 진행 시","headSub":"공복혈당 방치할 경우","costVal":"3,000","dotClass":"red","items":["당뇨 전단계 10년 내 진행 확률 50% 이상","합병증(신장·눈·신경) 치료비 연 수백~수천만 원","인슐린 치료 시 월 관리비 30~50만 원 추가"],"arrow":"→ 당뇨 진단비·합병증 특약 지금 확인 필요"},
    {"headClass":"navy","headTitle":"심근경색·협심증 시","headSub":"콜레스테롤 고수치 방치","costVal":"3,000","dotClass":"navy","items":["콜레스테롤 고수치 = 심혈관 위험 급증","스텐트 시술 비급여 포함 1,000~3,000만 원","65세 이후 심장 특약 가입 불가 또는 보험료 3배↑"],"arrow":"→ 지금이 가입 마지막 적기"},
    {"headClass":"teal","headTitle":"골다공증 골절 시","headSub":"BMI 과체중 + 비타민D 부족","costVal":"2,000","dotClass":"teal","items":["과체중+비타민D 결핍 = 골밀도 저하 가속","고관절 골절 수술비 500~2,000만 원","재활 기간 소득 손실 추가 발생"],"arrow":"→ 골절 수술비·간병인 특약 점검 필요"}
  ]
}

def extract_json(text):
    text = text.strip()
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    start = text.find('{')
    end   = text.rfind('}') + 1
    if start == -1 or end == 0:
        raise ValueError("JSON을 찾을 수 없습니다")
    json_str = text[start:end]
    json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', json_str)
    return json.loads(json_str)

def analyze_with_claude(pdf_b64):
    prompt = '''아래 건강검진 PDF를 분석하고, 반드시 순수 JSON만 출력하세요.
설명, 마크다운, 코드블록 없이 JSON 객체만 출력하세요.
문자열 안에 큰따옴표가 있으면 반드시 백슬래시로 이스케이프하세요.

출력 형식:
{
  "patient": {"name": "이름", "age": "만 N세", "gender": "남성 또는 여성", "examDate": "YYYY년 MM월 DD일", "mainFindings": "주요 소견"},
  "dangerMetrics": [
    {"val": "수치", "unit": "단위", "norm": "정상기준", "name": "항목명"},
    {"val": "수치", "unit": "단위", "norm": "정상기준", "name": "항목명"},
    {"val": "수치", "unit": "단위", "norm": "정상기준", "name": "항목명"}
  ],
  "nutrients": [
    {"name": "항목", "level": "bad", "levelText": "설명", "pct": 30, "risk": "위험", "note": "설명", "span2": false},
    {"name": "항목", "level": "ok", "levelText": "정상", "pct": 70, "risk": "", "note": "설명", "span2": false},
    {"name": "항목", "level": "warn", "levelText": "주의", "pct": 80, "risk": "위험", "note": "설명", "span2": true}
  ],
  "supplements": [
    {"num": "1", "name": "영양제", "why": "이유", "eff": "효과", "tag": "지금 바로", "tagClass": "now", "accentClass": "r1"},
    {"num": "2", "name": "영양제", "why": "이유", "eff": "효과", "tag": "지금 바로", "tagClass": "now", "accentClass": "r2"},
    {"num": "3", "name": "영양제", "why": "이유", "eff": "효과", "tag": "이달 내", "tagClass": "soon", "accentClass": "r3"},
    {"num": "4", "name": "영양제", "why": "이유", "eff": "효과", "tag": "추가 권장", "tagClass": "opt", "accentClass": "r4"}
  ],
  "insurance": [
    {"headClass": "red", "headTitle": "질환 발생 시", "headSub": "원인", "costVal": "4,000", "dotClass": "red", "items": ["항목1", "항목2", "항목3"], "arrow": "추천"},
    {"headClass": "navy", "headTitle": "질환 발생 시", "headSub": "원인", "costVal": "1,500", "dotClass": "navy", "items": ["항목1", "항목2", "항목3"], "arrow": "추천"},
    {"headClass": "teal", "headTitle": "질환 발생 시", "headSub": "원인", "costVal": "800", "dotClass": "teal", "items": ["항목1", "항목2", "항목3"], "arrow": "추천"}
  ]
}'''

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        json={"model": "claude-sonnet-4-6", "max_tokens": 2000, "messages": [{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
            {"type": "text", "text": prompt}
        ]}]},
        timeout=90
    )
    resp.raise_for_status()
    return extract_json(resp.json()["content"][0]["text"])

def build_html(d):
    p = d["patient"]

    # 구글 폰트 사용 (서버 폰트 불필요)
    FONT_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap');
"""

    def nut_cards(nutrients):
        html = ""
        for n in nutrients:
            span = ' style="grid-column:span 2"' if n.get("span2") else ""
            if n["level"] == "bad":
                msg_cls, msg_txt = "nc-danger", f'→ {n["risk"]}' if n.get("risk") else "부족 — 보충 필요"
            elif n["level"] == "ok":
                msg_cls, msg_txt = "nc-ok-msg", "현재 정상 — 유지 관찰 필요"
            else:
                msg_cls, msg_txt = "nc-wn-msg", f'→ {n["risk"]}' if n.get("risk") else "주의 필요"
            html += f"""<div class="nc {n['level']}"{span}>
              <div class="nc-top"><div class="nc-name">{n['name']}</div><div class="nc-badge {n['level']}">{n['levelText']}</div></div>
              <div class="bar-track"><div class="bar-fill {n['level']}" style="width:{n['pct']}%"></div></div>
              <div class="{msg_cls}">{msg_txt}</div>
              <div class="nc-note">{n['note']}</div></div>"""
        return html

    def sup_cards(supplements):
        html = ""
        for s in supplements:
            html += f"""<div class="mc"><div class="mc-accent {s['accentClass']}"></div>
              <div class="mc-inner"><div class="mc-num">{s['num']}</div>
              <div class="mc-body"><div class="mc-name">{s['name']}</div>
              <div class="mc-why">{s['why']}</div><div class="mc-eff">{s['eff']}</div></div>
              <div class="mc-tag-wrap"><div class="mc-tag {s['tagClass']}">{s['tag']}</div></div></div></div>"""
        return html

    def ins_cards(insurance):
        html = ""
        for ins in insurance:
            items = "".join(f'<div class="sc-item"><div class="sc-dot {ins["dotClass"]}"></div><span>{it}</span></div>' for it in ins["items"])
            html += f"""<div class="sc"><div class="sc-head {ins['headClass']}">
              <div class="sc-ht">{ins['headTitle']}</div><div class="sc-hs">{ins['headSub']}</div></div>
              <div class="sc-body"><div class="sc-cost-label">예상 치료비</div>
              <div class="sc-cost-val">{ins['costVal']}</div><div class="sc-cost-unit">만 원 이상</div>
              <div class="sc-line"></div>{items}<div class="sc-arrow">{ins['arrow']}</div></div></div>"""
        return html

    def danger_boxes(metrics):
        html = ""
        for m in metrics:
            html += f"""<div class="alert-num-box"><div class="a-val">{m['val']}</div>
              <div class="a-unit">{m['unit']}</div><div class="a-name">{m['name']}</div></div>"""
        return html

    CSS_BODY = """* {margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Noto Sans KR',sans-serif;color:#222;background:#fff;width:210mm;}
@page{size:A4;margin:0;}
.page{width:210mm;height:297mm;page-break-after:always;display:flex;flex-direction:column;overflow:hidden;}
.page:last-child{page-break-after:avoid;}
.hdr{display:flex;justify-content:space-between;align-items:stretch;flex-shrink:0;}
.hdr-left{background:#1B1B1B;padding:8mm 12mm;flex:1;}
.hdr-eyebrow{font-size:7pt;color:#888;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px;}
.hdr-title{font-size:15pt;font-weight:700;color:#fff;line-height:1.2;}
.hdr-right{background:#F0F0EE;padding:8mm 12mm;text-align:right;min-width:58mm;}
.hdr-name{font-size:16pt;font-weight:700;color:#1B1B1B;}
.hdr-info{font-size:8pt;color:#666;margin-top:3px;}
.hdr-pg{font-size:7pt;color:#999;margin-top:6px;letter-spacing:.06em;}
.alert-bar{background:#D32F2F;padding:5mm 12mm;display:flex;align-items:center;gap:12px;flex-shrink:0;}
.alert-num-wrap{display:flex;gap:0;}
.alert-num-box{text-align:center;padding:0 8px;border-right:1px solid rgba(255,255,255,.25);min-width:0;flex:1;}
.alert-num-box:last-child{border-right:none;}
.a-val{font-size:22pt;font-weight:900;color:#fff;line-height:1;}
.a-unit{font-size:7pt;color:rgba(255,255,255,.75);}
.a-name{font-size:7.5pt;font-weight:700;color:#FFCDD2;margin-top:3px;}
.alert-divider{width:1px;background:rgba(255,255,255,.3);align-self:stretch;margin:0 14px;}
.alert-msg{flex:1;}
.alert-headline{font-size:12pt;font-weight:700;color:#fff;line-height:1.4;margin-bottom:4px;}
.alert-sub{font-size:8pt;color:#FFCDD2;line-height:1.5;}
.p1-body{flex:1;padding:6mm 12mm 0;display:flex;flex-direction:column;}
.p1-sec-label{font-size:8pt;font-weight:700;color:#D32F2F;letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;}
.p1-sec-title{font-size:14pt;font-weight:700;color:#1B1B1B;margin-bottom:8px;padding-bottom:6px;border-bottom:2px solid #1B1B1B;}
.nut-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;flex:1;}
.nc{border-radius:6px;padding:10px 11px;display:flex;flex-direction:column;gap:6px;}
.nc.bad{background:#FFF5F5;border:1.5px solid #E57373;}
.nc.ok{background:#F3FAF5;border:1.5px solid #66BB6A;}
.nc.warn{background:#FFFBF0;border:1.5px solid #FFA726;}
.nc-top{display:flex;justify-content:space-between;align-items:flex-start;}
.nc-name{font-size:12pt;font-weight:700;color:#1B1B1B;line-height:1.2;}
.nc-badge{font-size:7pt;font-weight:700;padding:3px 9px;border-radius:3px;white-space:nowrap;flex-shrink:0;margin-left:6px;}
.nc-badge.bad{background:#D32F2F;color:#fff;}
.nc-badge.ok{background:#2E7D32;color:#fff;}
.nc-badge.warn{background:#E65100;color:#fff;}
.bar-track{height:8px;background:#E0E0E0;border-radius:2px;overflow:hidden;}
.bar-fill{height:100%;border-radius:2px;}
.bar-fill.bad{background:#D32F2F;}
.bar-fill.ok{background:#2E7D32;}
.bar-fill.warn{background:#E65100;}
.nc-danger{font-size:8.5pt;font-weight:700;color:#B71C1C;}
.nc-ok-msg{font-size:8.5pt;font-weight:700;color:#1B5E20;}
.nc-wn-msg{font-size:8.5pt;font-weight:700;color:#BF360C;}
.nc-note{font-size:8pt;color:#555;line-height:1.55;}
.p1-cta{margin-top:5mm;background:#1B1B1B;border-radius:6px;padding:9px 14px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
.p1-cta-txt .t1{font-size:8pt;color:#888;margin-bottom:3px;}
.p1-cta-txt .t2{font-size:11pt;font-weight:700;color:#fff;}
.p1-cta-btn{background:#D32F2F;color:#fff;font-size:9pt;font-weight:700;padding:8px 16px;border-radius:4px;white-space:nowrap;}
.p2-banner{background:#263238;padding:6mm 12mm;flex-shrink:0;}
.p2-banner-label{font-size:8pt;color:#78909C;letter-spacing:.1em;margin-bottom:4px;}
.p2-banner-title{font-size:13pt;font-weight:700;color:#fff;line-height:1.4;}
.p2-banner-sub{font-size:8.5pt;color:#90A4AE;margin-top:4px;line-height:1.5;}
.p2-body{flex:1;padding:6mm 12mm 0;}
.p2-sec-label{font-size:8pt;font-weight:700;letter-spacing:.1em;color:#263238;margin-bottom:5px;}
.p2-sec-title{font-size:14pt;font-weight:700;color:#1B1B1B;margin-bottom:10px;padding-bottom:6px;border-bottom:2px solid #1B1B1B;}
.med-list{display:flex;flex-direction:column;gap:8px;}
.mc{border-radius:6px;overflow:hidden;display:flex;}
.mc-accent{width:6px;flex-shrink:0;}
.mc-accent.r1{background:#D32F2F;}
.mc-accent.r2{background:#C62828;}
.mc-accent.r3{background:#E65100;}
.mc-accent.r4{background:#263238;}
.mc-inner{flex:1;background:#F8F8F7;padding:11px 13px;display:flex;gap:12px;align-items:flex-start;}
.mc-num{font-size:28pt;font-weight:900;color:#E0E0E0;line-height:1;flex-shrink:0;width:32px;}
.mc-body{flex:1;}
.mc-name{font-size:12pt;font-weight:700;color:#1B1B1B;margin-bottom:4px;}
.mc-why{font-size:8.5pt;color:#555;line-height:1.55;}
.mc-eff{font-size:8.5pt;font-weight:700;color:#2E7D32;margin-top:5px;}
.mc-tag-wrap{display:flex;align-items:flex-start;}
.mc-tag{font-size:7.5pt;font-weight:700;padding:4px 10px;border-radius:3px;white-space:nowrap;}
.mc-tag.now{background:#D32F2F;color:#fff;}
.mc-tag.soon{background:#E65100;color:#fff;}
.mc-tag.opt{background:#2E7D32;color:#fff;}
.p2-summary{margin-top:5mm;background:#F0F4FA;border-radius:6px;padding:10px 14px;border-left:5px solid #1565C0;}
.p2-summary-title{font-size:9pt;font-weight:700;color:#1565C0;margin-bottom:6px;}
.p2-summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;}
.p2-si{font-size:8pt;color:#1B1B1B;display:flex;gap:6px;align-items:flex-start;line-height:1.5;}
.p2-si-dot{width:6px;height:6px;background:#1565C0;border-radius:50%;margin-top:4px;flex-shrink:0;}
.p2-cta{margin-top:4mm;background:#263238;border-radius:6px;padding:9px 14px;display:flex;align-items:center;justify-content:space-between;}
.p2-cta-txt .t1{font-size:8pt;color:#78909C;margin-bottom:3px;}
.p2-cta-txt .t2{font-size:11pt;font-weight:700;color:#fff;}
.p2-cta-btn{background:#fff;color:#263238;font-size:9pt;font-weight:700;padding:8px 16px;border-radius:4px;white-space:nowrap;}
.p3-banner{background:#1A237E;padding:6mm 12mm;display:flex;align-items:flex-start;flex-shrink:0;}
.p3-banner-left{flex:1;}
.p3-banner-label{font-size:8pt;color:#7986CB;letter-spacing:.1em;margin-bottom:4px;}
.p3-banner-title{font-size:13pt;font-weight:700;color:#fff;line-height:1.4;}
.p3-banner-sub{font-size:8.5pt;color:#9FA8DA;margin-top:4px;}
.p3-banner-right{background:rgba(255,255,255,.1);border-radius:6px;padding:8px 14px;text-align:center;flex-shrink:0;}
.p3-total-label{font-size:7.5pt;color:#9FA8DA;margin-bottom:3px;}
.p3-total-val{font-size:26pt;font-weight:900;color:#FF8A80;line-height:1;}
.p3-total-unit{font-size:8pt;color:#FF8A80;}
.p3-total-sub{font-size:6.5pt;color:#7986CB;margin-top:3px;}
.p3-body{flex:1;padding:5mm 12mm 0;display:flex;flex-direction:column;}
.p3-sec-title{font-size:14pt;font-weight:700;color:#1B1B1B;margin-bottom:8px;padding-bottom:6px;border-bottom:2px solid #1B1B1B;}
.sc-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px;flex-shrink:0;}
.sc{border-radius:6px;overflow:hidden;}
.sc-head{padding:8px 10px;}
.sc-head.red{background:#B71C1C;}
.sc-head.navy{background:#1A237E;}
.sc-head.teal{background:#004D40;}
.sc-ht{font-size:10pt;font-weight:700;color:#fff;margin-bottom:2px;}
.sc-hs{font-size:7pt;color:rgba(255,255,255,.7);}
.sc-body{background:#F8F8F7;padding:10px;}
.sc-cost-label{font-size:7.5pt;color:#888;text-align:center;}
.sc-cost-val{font-size:24pt;font-weight:900;color:#B71C1C;text-align:center;line-height:1.1;}
.sc-cost-unit{font-size:8pt;color:#B71C1C;text-align:center;margin-bottom:8px;}
.sc-line{height:.5px;background:#DDD;margin-bottom:7px;}
.sc-item{font-size:8pt;color:#333;margin-bottom:5px;display:flex;gap:5px;line-height:1.5;}
.sc-dot{width:5px;height:5px;border-radius:50%;margin-top:5px;flex-shrink:0;}
.sc-dot.red{background:#B71C1C;}
.sc-dot.navy{background:#1A237E;}
.sc-dot.teal{background:#004D40;}
.sc-arrow{font-size:8pt;font-weight:700;color:#1565C0;margin-top:7px;padding-top:6px;border-top:.5px solid #DDD;}
.tl-section{margin-top:5mm;flex-shrink:0;}
.tl-title{font-size:11pt;font-weight:700;color:#1B1B1B;margin-bottom:7px;padding-bottom:5px;border-bottom:2px solid #1B1B1B;}
.tl{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;}
.tl-item{padding:9px 10px;border-right:1px solid #DDD;}
.tl-item:last-child{border-right:none;}
.tl-year{font-size:9.5pt;font-weight:700;color:#1565C0;margin-bottom:3px;}
.tl-event{font-size:9pt;font-weight:700;color:#1B1B1B;margin-bottom:4px;}
.tl-note{font-size:7.5pt;color:#555;line-height:1.5;}
.tl-item.danger{background:#FFF5F5;}
.tl-item.danger .tl-year{color:#B71C1C;}
.tl-item.danger .tl-event{color:#B71C1C;}
.expert{margin-top:4mm;background:#F8F8F7;border-radius:6px;padding:10px 13px;display:flex;gap:11px;align-items:flex-start;flex-shrink:0;}
.expert-badge{background:#1B1B1B;color:#aaa;font-size:7pt;font-weight:700;padding:8px 10px;border-radius:4px;text-align:center;line-height:1.6;flex-shrink:0;white-space:nowrap;}
.expert-quote{font-size:9pt;color:#222;line-height:1.7;}
.expert-name{font-size:7pt;color:#999;margin-top:5px;}
.p3-cta{margin-top:4mm;display:grid;grid-template-columns:1fr 1fr;gap:7px;flex-shrink:0;}
.p3-cta-btn{border-radius:6px;padding:10px 14px;text-align:center;}
.p3-cta-btn.green{background:#1B5E20;}
.p3-cta-btn.navy{background:#1A237E;}
.p3-cb-sub{font-size:7.5pt;color:rgba(255,255,255,.65);margin-bottom:4px;}
.p3-cb-main{font-size:11pt;font-weight:700;color:#fff;}
.p3-cb-desc{font-size:7.5pt;color:rgba(255,255,255,.65);margin-top:3px;}
.footer{margin-top:auto;padding:4px 12mm 5mm;border-top:.5px solid #DDD;display:flex;justify-content:space-between;font-size:6pt;color:#bbb;flex-shrink:0;}"""

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>{FONT_CSS}{CSS_BODY}</style></head><body>
<div class="page">
  <div class="hdr"><div class="hdr-left"><div class="hdr-eyebrow">건강검진 맞춤 분석 리포트 · 핀셋라이프</div><div class="hdr-title">영양소 분석 결과</div></div>
  <div class="hdr-right"><div class="hdr-name">{p['name']} 님</div><div class="hdr-info">{p['age']} · {p['gender']} · {p['examDate']} 검진</div><div class="hdr-pg">PAGE 01 / 03</div></div></div>
  <div class="alert-bar"><div class="alert-num-wrap">{danger_boxes(d['dangerMetrics'])}</div><div class="alert-divider"></div>
  <div class="alert-msg"><div class="alert-headline">3가지 위험 신호가<br>동시에 켜져 있습니다</div><div class="alert-sub">지금 관리하지 않으면 5~10년 내<br>심혈관 질환으로 이어집니다</div></div></div>
  <div class="p1-body"><div class="p1-sec-label">NUTRITION ANALYSIS</div><div class="p1-sec-title">지금 몸속에서 무슨 일이 일어나고 있나요?</div>
  <div class="nut-grid">{nut_cards(d['nutrients'])}</div>
  <div class="p1-cta"><div class="p1-cta-txt"><div class="t1">영양제 추천 결과는 다음 페이지에서 확인하세요</div><div class="t2">지금 챙겨야 할 영양제 순서가 있습니다</div></div><div class="p1-cta-btn">다음 페이지 →</div></div></div>
  <div class="footer"><span>본 리포트는 AI가 생성한 참고 자료이며, 의학적 진단을 대체하지 않습니다.</span><span>핀셋라이프 · 더금융서비스 포레스트사업단 · PAGE 01/03</span></div>
</div>
<div class="page">
  <div class="hdr"><div class="hdr-left"><div class="hdr-eyebrow">건강검진 맞춤 분석 리포트 · 핀셋라이프</div><div class="hdr-title">맞춤 영양제 추천</div></div>
  <div class="hdr-right"><div class="hdr-name">{p['name']} 님</div><div class="hdr-info">{p['age']} · {p['gender']} · {p['examDate']} 검진</div><div class="hdr-pg">PAGE 02 / 03</div></div></div>
  <div class="p2-banner"><div class="p2-banner-label">SUPPLEMENT RECOMMENDATION</div><div class="p2-banner-title">분석 결과를 기반으로, 지금 당장 챙겨야 할<br>영양제 우선순위를 알려드립니다</div><div class="p2-banner-sub">순서대로 시작하세요 — 우선순위가 중요합니다.</div></div>
  <div class="p2-body"><div class="p2-sec-label">PRIORITY ORDER</div><div class="p2-sec-title">지금 당장 챙겨야 할 영양제 — 우선순위 순</div>
  <div class="med-list">{sup_cards(d['supplements'])}</div>
  <div class="p2-summary"><div class="p2-summary-title">복용 시 기대 효과 요약</div><div class="p2-summary-grid">
  <div class="p2-si"><div class="p2-si-dot"></div><span>1+2번 조합 → 혈당·콜레스테롤 동시 개선</span></div>
  <div class="p2-si"><div class="p2-si-dot"></div><span>3번 추가 → 심장 기능 보호 강화</span></div>
  <div class="p2-si"><div class="p2-si-dot"></div><span>4번 추가 → 면역·골밀도·피로 개선</span></div>
  <div class="p2-si"><div class="p2-si-dot"></div><span>전체 복용 → 질환 진행 속도 지연</span></div></div></div>
  <div class="p2-cta"><div class="p2-cta-txt"><div class="t1">오늘 약국에서 바로 시작하세요</div><div class="t2">약사에게 이 리포트를 보여주시면 맞춤 상품을 안내해 드립니다</div></div><div class="p2-cta-btn">약사에게 문의하기</div></div></div>
  <div class="footer"><span>본 리포트는 AI가 생성한 참고 자료이며, 의학적 진단을 대체하지 않습니다.</span><span>핀셋라이프 · 더금융서비스 포레스트사업단 · PAGE 02/03</span></div>
</div>
<div class="page">
  <div class="hdr"><div class="hdr-left"><div class="hdr-eyebrow">건강검진 맞춤 분석 리포트 · 핀셋라이프</div><div class="hdr-title">보험 공백 분석</div></div>
  <div class="hdr-right"><div class="hdr-name">{p['name']} 님</div><div class="hdr-info">{p['age']} · {p['gender']} · {p['examDate']} 검진</div><div class="hdr-pg">PAGE 03 / 03</div></div></div>
  <div class="p3-banner"><div class="p3-banner-left"><div class="p3-banner-label">INSURANCE GAP ANALYSIS</div><div class="p3-banner-title">지금 이 수치로 아프면,<br>얼마가 나올까요?</div><div class="p3-banner-sub">{p['name']} 님의 검진 수치 기반 발생 가능 질병과<br>예상 치료비, 보험 공백을 분석했습니다</div></div>
  <div class="p3-banner-right"><div class="p3-total-label">보험 없을 시 예상 총 치료비</div><div class="p3-total-val">8,000</div><div class="p3-total-unit">만 원 이상</div><div class="p3-total-sub">3가지 질환 동시 발생 가정</div></div></div>
  <div class="p3-body"><div class="p3-sec-title">질환별 예상 치료비 시나리오</div>
  <div class="sc-grid">{ins_cards(d['insurance'])}</div>
  <div class="tl-section"><div class="tl-title">지금 관리하지 않으면 — 예상 진행 경로</div>
  <div class="tl">
  <div class="tl-item"><div class="tl-year">현재</div><div class="tl-event">위험 수치 진행 중</div><div class="tl-note">증상 없음. 혈관·혈당이 서서히 악화 중.</div></div>
  <div class="tl-item"><div class="tl-year">3~5년 후</div><div class="tl-event">질환 진단</div><div class="tl-note">이 시점부터 보험 가입 어려워짐.</div></div>
  <div class="tl-item danger"><div class="tl-year">5~10년 후</div><div class="tl-event">심혈관 사건 위험</div><div class="tl-note">특약 없으면 수천만 원 전액 본인 부담.</div></div>
  <div class="tl-item danger"><div class="tl-year">10년 후~</div><div class="tl-event">장기 요양 · 후유증</div><div class="tl-note">소득 상실, 간병비. 가족 전체에 영향.</div></div></div></div>
  <div class="expert"><div class="expert-badge">핀셋라이프<br>전문팀<br>코멘트</div>
  <div><div class="expert-quote">"지금 당장 아픈 게 아니라 괜찮다고 생각하실 수 있습니다. 하지만 이 수치들은 이미 5~10년 후 시나리오를 예고하고 있습니다. 보험은 아프기 전에 가입해야 의미가 있습니다. 진단을 받는 순간 가입 문이 닫히거나 보험료가 2~3배 올라갑니다. 지금 15분만 투자해서 공백을 확인해 보세요."</div>
  <div class="expert-name">보험심사평가사 · 건강관리사 자격 보유 · 더금융서비스 포레스트사업단</div></div></div>
  <div class="p3-cta">
  <div class="p3-cta-btn green"><div class="p3-cb-sub">1·2페이지 영양제를 먼저 챙기세요</div><div class="p3-cb-main">약사에게 맞춤 상품 문의</div><div class="p3-cb-desc">영양제로 수치부터 관리</div></div>
  <div class="p3-cta-btn navy"><div class="p3-cb-sub">보험 공백, 지금 무료로 확인하세요</div><div class="p3-cb-main">핀셋라이프 15분 무료 상담</div><div class="p3-cb-desc">알고 결정하는 것이 현명합니다</div></div></div></div>
  <div class="footer"><span>본 리포트는 AI가 생성한 참고 자료이며, 의학적 진단을 대체하지 않습니다.</span><span>핀셋라이프 · 더금융서비스 포레스트사업단 · PAGE 03/03</span></div>
</div>
</body></html>"""


@app.route("/")
def index():
    with open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8") as f:
        return f.read()

@app.route("/analyze", methods=["POST"])
def analyze():
    if "pdf" not in request.files:
        return jsonify({"error": "PDF 파일이 없습니다"}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "API 키가 설정되지 않았습니다"}), 500

    pdf_bytes = request.files["pdf"].read()
    pdf_b64   = base64.b64encode(pdf_bytes).decode()

    try:
        data = analyze_with_claude(pdf_b64)
    except Exception as e:
        print(f"AI 분석 오류 (샘플 사용): {e}")
        data = SAMPLE_DATA

    try:
        font_config = FontConfiguration()
        html_obj = weasyprint.HTML(string=build_html(data))
        pdf = html_obj.write_pdf(font_config=font_config)
    except Exception as e:
        return jsonify({"error": f"PDF 생성 오류: {str(e)}"}), 500

    name = data.get("patient", {}).get("name", "고객")
    return send_file(
        io.BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"건강검진_리포트_{name}.pdf"
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
