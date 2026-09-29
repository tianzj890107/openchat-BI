# -*- coding: utf-8 -*-
"""Generate the 1920x1080 business panorama poster as SVG."""
import pathlib

W, H = 1920, 1080
FONT = "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif"

# --- geometry ---------------------------------------------------------------
M = 32                      # outer margin
PANEL_X = M
PANEL_W = 1808              # right edge 1840, right corridor 1840..1920
TITLE_X = PANEL_X + 16
BOX_X0 = 220
BOX_W_TOTAL = 1604          # 220 .. 1824
BOX_H = 58
ROW_H = 120
ROW_GAP = 22
ROW_Y0 = 94

CORRIDOR_R = 1880
CORRIDOR_L = 18

LEGEND = ("粗实线 · 主链路", "细实线 · 常规流转", "虚线 · 条件分支与回退",
          "红色块 · 安全与合规", "绿色块 · 数据与知识", "橙色块 · 分析与洞察")

BANDS = [
    dict(key="b1", title="① 用户与会话", sub="从提问到理解需求",
         color="#1565C0", fill="#F5FAFF", box="#E3F2FD", text="#0D47A1",
         boxes=[["工作台提问"], ["移动端提问"], ["报表页追问"], ["角色与分析视角"],
                ["会话上下文", "多轮记忆"], ["问题意图理解"], ["指标与口径识别"],
                ["范围识别", "时间 · 组织 · 阈值"]]),
    dict(key="b2", title="② 安全与合规把关", sub="先于一切业务处理",
         color="#C62828", fill="#FFF5F5", box="#FFEBEE", text="#B71C1C",
         boxes=[["安全与合规把关", "先于一切业务处理"], ["凭据索取识别"],
                ["破坏性操作识别"], ["内部环境探测识别"],
                ["绕过审批与越权识别"], ["拒绝并给出合规指引"],
                ["敏感信息不外泄", "全程可追溯"]]),
    dict(key="b3", title="③ 数据与知识底座", sub="口径 · 知识 · 经营数据",
         color="#2E7D32", fill="#F4FBF4", box="#E8F5E9", text="#1B5E20",
         boxes=[["业务本体知识", "术语 · 对象 · 关系"], ["指标定义与口径库"],
                ["经营数据", "销售 · 采购 · 存货", "财务 · 质量 · 交付"],
                ["计划与预算数据"], ["业务规则与校验规则"],
                ["口径与统计范围说明"], ["数据来源说明"]]),
    dict(key="b4", title="④ 分析与洞察", sub="从事实到行动建议",
         color="#EF6C00", fill="#FFF9F0", box="#FFF3E0", text="#E65100",
         boxes=[["事实与明细查询"], ["异常与波动定位"], ["根因分析"],
                ["行动建议与措施"], ["预测与情景推演"], ["证据与假设标注"]]),
    dict(key="b5", title="⑤ 交付与呈现", sub="结论 · 图表 · 说明",
         color="#6A1B9A", fill="#FBF3FD", box="#F3E5F5", text="#4A148C",
         boxes=[["结论与证据"], ["图表与表格"], ["报告与看板"],
                ["限制与假设说明"], ["后续跟进建议"], ["合规拒绝答复"]]),
    dict(key="b6", title="⑥ 质量与发布把关", sub="未达标不交付",
         color="#455A64", fill="#F7F9FA", box="#ECEFF1", text="#263238",
         boxes=[["口径一致性复核"], ["证据充分性复核"],
                ["真实性守护", "不夸大因果 · 代理指标说明"],
                ["多次运行一致性复核"], ["发布质量把关"], ["未达标不交付"]]),
    dict(key="b7", title="图例", sub="线条与色块含义",
         color="#90A4AE", fill="#FFFFFF", box="#FAFAFA", text="#37474F",
         boxes=[[t] for t in LEGEND]),
]


def row_y(i):
    return ROW_Y0 + i * (ROW_H + ROW_GAP)


def box_geom(i, n, k):
    bw = (BOX_W_TOTAL - (n - 1) * 10) / n
    x = BOX_X0 + k * (bw + 10)
    y = row_y(i) + (ROW_H - BOX_H) / 2
    return x, y, bw


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


out = []
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" font-family="{FONT}">')
out.append('<defs>')
for name, color in (("m", "#0D47A1"), ("s", "#C62828"), ("c", "#E65100"),
                    ("d", "#2E7D32"), ("g", "#455A64")):
    out.append(f'<marker id="ah-{name}" viewBox="0 0 10 10" refX="9" refY="5" '
               f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
               f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>')
out.append('</defs>')
out.append(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')

# --- title ------------------------------------------------------------------
out.append(f'<text x="{M}" y="52" font-size="30" font-weight="700" fill="#0B2A4A">'
           '智能分析 Agent · 业务全景架构</text>')
out.append(f'<text x="{M}" y="78" font-size="16" fill="#5A6B7B">'
           '业务视角：从一次业务问询，到安全合规把关、数据与知识支撑、分析洞察、'
           '交付呈现与质量发布</text>')

# --- panels + boxes ---------------------------------------------------------
pos = {}
for i, band in enumerate(BANDS):
    y = row_y(i)
    n = len(band["boxes"])
    out.append(f'<rect x="{PANEL_X}" y="{y}" width="{PANEL_W}" height="{ROW_H}" rx="12" '
               f'fill="{band["fill"]}" stroke="{band["color"]}" stroke-width="2"/>')
    out.append(f'<rect x="{PANEL_X}" y="{y}" width="6" height="{ROW_H}" rx="3" '
               f'fill="{band["color"]}"/>')
    out.append(f'<text x="{TITLE_X}" y="{y + 52}" font-size="20" font-weight="700" '
               f'fill="{band["text"]}">{esc(band["title"])}</text>')
    out.append(f'<text x="{TITLE_X}" y="{y + 78}" font-size="13" '
               f'fill="{band["text"]}" opacity="0.75">{esc(band["sub"])}</text>')
    for k, lines in enumerate(band["boxes"]):
        bx, by, bw = box_geom(i, n, k)
        pos[(band["key"], k)] = (bx, by, bw, by + BOX_H / 2)
        out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{BOX_H}" '
                   f'rx="9" fill="{band["box"]}" stroke="{band["color"]}" '
                   f'stroke-width="1.6"/>')
        fs = 15 if len(lines) <= 2 else 13.5
        lh = 19 if len(lines) <= 2 else 17
        y0 = by + BOX_H / 2 - (len(lines) - 1) * lh / 2 + 5.5
        for j, line in enumerate(lines):
            out.append(f'<text x="{bx + bw / 2:.1f}" y="{y0 + j * lh:.1f}" '
                       f'font-size="{fs}" text-anchor="middle" fill="{band["text"]}">'
                       f'{esc(line)}</text>')


def center(key, k):
    bx, by, bw, cy = pos[(key, k)]
    return bx + bw / 2, by, by + BOX_H, cy


def edges(key, k):
    bx, by, bw, cy = pos[(key, k)]
    return bx, bx + bw, by, by + BOX_H, cy


def path(points, color, width, dash=None, marker="ah-m"):
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points)
    da = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
               f'stroke-linejoin="round" stroke-linecap="round"{da} '
               f'marker-end="url(#{marker})"/>')


BLUE, RED, ORANGE, GREEN, GRAY = "#0D47A1", "#C62828", "#E65100", "#2E7D32", "#455A64"

# 1) main spine through the bands
x1, _, b1b, _ = center("b1", 7)
x2, b2t, _, _ = center("b2", 0)
mid1 = (row_y(0) + ROW_H + row_y(1)) / 2
path([(x1, b1b), (x1, mid1), (x2, mid1), (x2, b2t)], BLUE, 5)

_, _, b2b, _ = center("b2", 0)
x3, b3t, _, _ = center("b3", 2)
mid2 = (row_y(1) + ROW_H + row_y(2)) / 2
path([(x2, b2b), (x2, mid2), (x3, mid2), (x3, b3t)], BLUE, 5)

_, _, b3b, _ = center("b3", 2)
x4, b4t, _, _ = center("b4", 0)
mid3 = (row_y(2) + ROW_H + row_y(3)) / 2
path([(x3, b3b), (x3, mid3), (x4, mid3), (x4, b4t)], BLUE, 5)

# 2) analysis chain inside band 4 (drawn in the gaps between boxes)
for a, b in ((0, 1), (1, 2), (2, 3)):
    _, ra, _, _, cy = edges("b4", a)
    lb, _, _, _, _ = edges("b4", b)
    path([(ra + 3, cy), (lb - 8, cy)], BLUE, 4)

xa, _, b4b, _ = center("b4", 3)
x5, b5t, _, _ = center("b5", 0)
mid4 = (row_y(3) + ROW_H + row_y(4)) / 2
path([(xa, b4b), (xa, mid4), (x5, mid4), (x5, b5t)], BLUE, 5)

xa, _, b5b, _ = center("b5", 0)
x6, b6t, _, _ = center("b6", 4)
mid5 = (row_y(4) + ROW_H + row_y(5)) / 2
path([(xa, b5b), (xa, mid5), (x6, mid5), (x6, b6t)], BLUE, 5)

# 3) safety refusal runs down the right corridor
xs, _, s5b, _ = center("b2", 5)
_, _, _, s5cy = center("b5", 5)
top_corridor = (row_y(1) + ROW_H + row_y(2)) / 2
path([(xs, s5b), (xs, top_corridor), (CORRIDOR_R, top_corridor),
      (CORRIDOR_R, s5cy), (1830, s5cy)], RED, 3, dash="9 7", marker="ah-s")

# 4) conditional / rollback (dashed orange, looped under the boxes)
row4 = row_y(3)
lane = row4 + ROW_H - 14
xc0, _, _, b0b, _ = edges("b4", 0)
xc1, _, _, b1b, _ = edges("b4", 1)
path([(xc1, b1b), (xc1, lane), (xc0, lane), (xc0, b0b + 6)], ORANGE, 3,
     dash="8 6", marker="ah-c")
xc3, _, _, b3b, _ = edges("b4", 3)
xc4, _, _, b4b, _ = edges("b4", 4)
path([(xc4, b4b), (xc4, lane), (xc3, lane), (xc3, b3b + 6)], ORANGE, 3,
     dash="8 6", marker="ah-c")
xg, _, g2t, _ = center("b6", 2)
_, _, _, g4cy = center("b4", 0)
left_lane = (row_y(5) + ROW_H + row_y(6)) / 2
path([(xg - 12, g2t + 30), (CORRIDOR_L, g2t + 30), (CORRIDOR_L, g4cy),
      (BOX_X0 - 10, g4cy)], ORANGE, 3, dash="8 6", marker="ah-c")

# 5) data & knowledge feeds (thin green)
x0, _, b30b, _ = center("b3", 0)
path([(x0, b30b), (x0, mid3 - 5), (x4, mid3 - 5), (x4, b4t - 4)], GREEN, 3, marker="ah-d")
x3b, _, b33b, _ = center("b3", 3)
x4e, b4et, _, _ = center("b4", 4)
path([(x3b, b33b), (x3b, mid3 - 5), (x4e, mid3 - 5), (x4e, b4et - 4)], GREEN, 3,
     marker="ah-d")

# 6) quality chain inside band 6
for a, b in ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5)):
    _, ra, _, _, cy = edges("b6", a)
    lb, _, _, _, _ = edges("b6", b)
    path([(ra + 3, cy), (lb - 8, cy)], GRAY, 2)

out.append('</svg>')
path_obj = pathlib.Path(__file__).with_name("10-business-panorama-16x9.svg")
path_obj.write_text("\n".join(out) + "\n", encoding="utf-8")
print("wrote", path_obj, len(out), "elements")
