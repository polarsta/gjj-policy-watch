# -*- coding: utf-8 -*-
"""2026-09-14 公积金政策巡检 + 商机案例 + 负面舆情 + 人事变动 自动化
数据库版本：1.6.0 → 1.6.1

覆盖变更（已知差异见本脚本顶部的 CITY_UPDATES / NEW_CASES 字典）：
1. 武汉汉八条（公积金首套纯商贷提取月度化、异地公积金无限制）
2. 宜昌商转公合作行扩至邮储（9月16日施行）
3. 昆明 2026 年度缴存基数（上限 32543 元，下限一类区 2270 元）
4. case_library 新增 case-057 ~ case-062（共 6 条）
5. latest_insight 同步
6. 数据库版本号 + generated_at 时间戳

输出文件：
- gjj_policy_database.json（v1.6.1，1 空格缩进，保留原始 EOF 状态）
- research/cases.json（2 空格缩进）
- site/gjj_policy_database.json（2 空格缩进，UTF-8 BOM，保留原始 EOF 状态）

不输出（由各自脚本/手工负责）：
- negative_news/*（由 build_negative_news.py 负责）
- 商机案例库.md（手工追加）
- personnel-changes.json（手工追加）
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE, "gjj_policy_database.json")
CASES_PATH = os.path.join(BASE, "research", "cases.json")
SITE_MIRROR = os.path.join(BASE, "site", "gjj_policy_database.json")


def detect_indent(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    in_str = False
    esc = False
    indents = []
    line_start = True
    for ch in text:
        if line_start and not in_str and ch in (" ", "\t"):
            indents.append(ch)
            continue
        if ch == '"' and not esc:
            in_str = not in_str
        if ch == "\\" and in_str:
            esc = not esc
        else:
            esc = False
        line_start = (ch == "\n")
    spaces = [len(x) for x in indents if x != "\t"]
    return min(spaces) if spaces else 1


def detect_eof_newline(path):
    with open(path, "rb") as f:
        data = f.read()
    return data.endswith(b"\n")


def atomic_write(path, text, eof_nl):
    if not eof_nl and text.endswith("\n"):
        text = text[:-1]
    if eof_nl and not text.endswith("\n"):
        text = text + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


CITY_UPDATES = {
    "武汉": {
        "last_updated": "2026-09-08",
        "loan": {
            "note": "2026-09-04 《关于进一步优化我市房地产政策措施的通知》（汉八条）由市住建局等五部门联合发布，公积金条款：①首套纯商贷自住房正常还款满 6 个月即可每月提取一次公积金，累计金额不超过该笔商贷金额（突破原「每年一次」限制）；②全国任一城市公积金缴存职工在汉购买自住房均可申请公积金贷款，亮「住房公积金个人业务办理电子码」即办，不限缴存地、户籍地，无需纸质缴存证明；③武汉都市圈缴存职工在汉买新建商品房，可自愿选择向武汉公积金中心或缴存地中心申请贷款，享受同等贷款最高额度政策。通知自公布之日起执行。",
            "conditions_append": "汉八条公积金新规：①全国任一城市缴存职工在汉买自住房均可申请公积金贷款（亮电子码即办），不受缴存地/户籍地限制；②武汉都市圈缴存职工可选本地或缴存地中心申请，享受同等额度；③首套纯商贷自住房每月可提取公积金（满 6 个月后）。",
            "matrix_patch": {
                "商转公": {
                    "status": "支持",
                    "condition": "2026-05-26 起实施商转公（已有）；汉八条进一步将异地公积金贷款范围扩展至「全国任一城市缴存职工」、不再限制缴存地/户籍地",
                    "source_link": "https://zrzyhgh.wuhan.gov.cn/zwdt/gzdt/202609/t20260908_2844924.shtml",
                    "source_type": "官方媒体",
                },
            },
            "sources_append": [
                {
                    "title": "武汉出台八项措施优化房地产政策 新城区购房可享 1% 补助（湖北日报）",
                    "url": "https://zrzyhgh.wuhan.gov.cn/zwdt/gzdt/202609/t20260908_2844924.shtml",
                    "date": "2026-09-08",
                },
            ],
        },
        "withdrawal": {
            "note": "2026-09-04 汉八条公积金条款：仅使用个人住房商业贷款的首套自住房，正常还款满 6 个月即可办理提取，之后每月可提取一次，累计金额不超过该笔商贷金额。",
            "matrix_patch": {
                "按月冲还商贷": {
                    "status": "支持",
                    "condition": "汉八条（2026-09-04）：仅使用个人住房商业贷款的首套自住房，正常还款 6 个月后即可办理，之后每月可提取一次，累计金额不超过该笔商贷金额",
                    "source_link": "https://zrzyhgh.wuhan.gov.cn/zwdt/gzdt/202609/t20260908_2844924.shtml",
                    "source_type": "官方媒体",
                },
            },
            "sources_append": [
                {
                    "title": "武汉出台八项措施优化房地产政策 新城区购房可享 1% 补助（湖北日报）",
                    "url": "https://zrzyhgh.wuhan.gov.cn/zwdt/gzdt/202609/t20260908_2844924.shtml",
                    "date": "2026-09-08",
                },
            ],
        },
        "deposit": {
            "note_append": "；汉八条不调整缴存基数，仅优化提取与异地贷款",
        },
    },
    "宜昌": {
        "last_updated": "2026-09-14",
        "loan": {
            "note": "2026-09-14 宜昌住房公积金中心发布《关于进一步扩大商业银行购房按揭贷款转公积金贷款（公积金贷款代偿商业购房贷款）业务范围的通知》：在原合作行（建/工/农/中/交/三峡农商/湖北/汉口/招商 共 9 家）基础上新增邮储银行开展商转公业务，自 2026-09-16 起施行。",
            "matrix_patch": {
                "商转公": {
                    "status": "支持",
                    "condition": "2026-09-16 起新增邮储银行，商转公合作行扩至 10 家（建/工/农/中/交/三峡农商/湖北银行/汉口/招商/邮储）",
                    "source_link": "http://gjj.yichang.gov.cn/content-55762-6545-1.html",
                    "source_type": "政府网站",
                },
            },
            "sources_append": [
                {
                    "title": "关于进一步扩大商业银行购房按揭贷款转公积金贷款（公积金贷款代偿商业购房贷款）业务范围的通知",
                    "url": "http://gjj.yichang.gov.cn/content-55762-6545-1.html",
                    "date": "2026-09-14",
                },
            ],
        },
    },
    "昆明": {
        "last_updated": "2026-09-11",
        "deposit": {
            "base_upper": 32543,
            "base_lower": 2270,
            "note": "2026-09-08 昆明市住房公积金管理中心发布 2026 年度缴存基数调整通知：上限执行标准为 32543 元（较 2025 年度的 32470 元上调 73 元）；下限按一类区 2270 元、二类区 2120 元、三类区 1970 元执行（一类区为五华/盘龙/官渡/西山及呈贡/高新区/度假区/经开/空港；二类区为石林/宜良/嵩明/安宁/晋宁/东川/寻甸/禄劝及阳宗海；三类区为倘甸/轿子山）。存量在职职工按本人 2025 年度月平均工资核定；新参加工作/新调入职工从当月起缴。",
            "sources_replace": [
                {
                    "title": "昆明住房公积金缴存基数上限调至 32543 元（昆明日报转载）",
                    "url": "https://zixun.kunming.cn/c/9479432.shtml",
                    "date": "2026-09-11",
                },
            ],
            "sources_append": [
                {
                    "title": "昆明：2026 年度住房公积金缴存基数上下限调整（云南发布/今日头条）",
                    "url": "https://www.toutiao.com/article/7684094436061643316/",
                    "date": "2026-09-11",
                },
            ],
        },
    },
}


NEW_CASES = [
    {
        "id": "case-057",
        "title": "宜昌：邮储银行新晋公积金商转公受托行，宜昌中心10家受托银行打通商转公最后一公里",
        "city": "宜昌",
        "province": "湖北",
        "theme": "银行受托与商转公",
        "parties": ["宜昌住房公积金中心", "中国邮政储蓄银行（宜昌/湖北分行）", "原9家受托银行（建/工/农/中/交/三峡农商/湖北/汉口/招商）"],
        "policy_background": "宜昌中心持续推进商转公业务扩面、降低缴存职工转贷资金压力；2026-09-14 在原合作行范围基础上新增邮储银行开展商转公，标志商转公受托行体系进一步覆盖大型国有商业银行。",
        "summary": "2026-09-14 宜昌住房公积金中心发布《关于进一步扩大商业银行购房按揭贷款转公积金贷款业务范围的通知》：在原有建/工/农/中/交/三峡农商行/湖北银行/汉口银行/招商银行共9家受托行基础上，新增中国邮政储蓄银行开展商转公业务，自2026-09-16起正式施行。缴存职工办理商转公可选择的受托渠道由9家扩展至10家，五大国有银行全面接入。",
        "practices": [
            "国有大行全覆盖：商转公受托行由9家增至10家，建/工/农/中/交/邮六大行齐备，缴存职工可根据贷款偏好、所在区域、利率折扣、审批效率自由选择。",
            "流程与时限公开：通知明确贷款条件、办事指南、0717-12329 咨询热线、官网查询路径，确保转贷信息公开透明。",
            "银行侧合作抓手：邮储银行新接入后，宜昌分行可重点对接商贷客户中「想转公积金又怕流程繁」的缴存职工，推送「商转公无自筹结清」贴息差价测算表，提高组合贷与商转公渗透率。",
        ],
        "sources": [
            {
                "title": "关于进一步扩大商业银行购房按揭贷款转公积金贷款（公积金贷款代偿商业购房贷款）业务范围的通知",
                "url": "http://gjj.yichang.gov.cn/content-55762-6545-1.html",
                "date": "2026-09-14",
            },
        ],
        "confidence": "高",
    },
    {
        "id": "case-058",
        "title": "梧州：商转公顺位抵押模式合作银行扩至11家，地方银行/农商行/北部湾银行同步接入",
        "city": "梧州",
        "province": "广西",
        "theme": "银行受托与商转公",
        "parties": ["梧州市住房公积金管理中心", "11家合作商业银行（含工/农/中/建/交、桂林/柳州/广西北部湾、苍梧农商行、梧州市区农信联社、邮储）"],
        "policy_background": "今年7月以来梧州市公积金中心在原「自筹结清」商转公模式基础上推出「顺位抵押」新模式，无需缴存职工一次性自筹结清原商贷即可办理转贷；通过与合作银行签订「顺位抵押」商转公协议确保公积金贷款资金到账后银行快速结清原商贷、完成注销、实现抵押权顺位自动上升至第一顺位。",
        "summary": "2026-09-08 梧州市住房公积金管理中心公告更新商转公顺位抵押业务合作银行名单：截至2026-09-08已与中心合作的商业银行扩至11家——工/农/中/建/交、桂林银行、柳州银行、广西苍梧农村商业银行、梧州市区农村信用合作联社、邮储银行（广西区梧州市分行）、广西北部湾银行，各家银行覆盖梧州市本级及苍梧/岑溪/藤县/蒙山等辖内区域。截至9月3日，全市顺位抵押商转公贷款发放97笔3478.5万元，为缴存职工节省房贷利息134.44万元；累计发放商转公贷款210笔、总金额7037.3万元。",
        "practices": [
            "地方银行深度参与：与建/工/农/中/交等大行并行，桂林/柳州/广西北部湾/农商行/农信联社等地方银行一并接入顺位抵押渠道，匹配梧州作为广西东大门的地市级金融生态。",
            "保留双模式并行：继续保留「自筹结清」模式作为补充，缴存职工可结合自身经济情况灵活选择，降低单点模式带来的体验落差。",
            "银行侧合作抓手：股份制银行与农商行可重点服务县域客户与微小企业主，配套「顺位抵押」组合贷产品；针对住房按揭余额较低但公积金账户余额较高的缴存人，提供「商转公+顺位抵押+短贷结清」全流程包装方案。",
        ],
        "sources": [
            {
                "title": "持续拓宽业务模式 有效降低转贷成本（梧州市人民政府门户站转载 邓超妍 杨钲钰）",
                "url": "http://www.wuzhou.gov.cn/zjwz/zwdt_1/bmdt/t28123997.shtml",
                "date": "2026-09-08",
            },
            {
                "title": "梧州市住房公积金管理中心关于更新商转公顺位抵押业务合作银行名单的公告",
                "url": "https://gxwzgjj.gov.cn/xwzx/tzgg/5224.htm",
                "date": "2026-09-08",
            },
        ],
        "confidence": "高",
    },
    {
        "id": "case-059",
        "title": "长春公积金图们分理处：延边州内9家主流银行打通顺位抵押通道，边境缴存职工零垫付办理商转公",
        "city": "长春（延边·图们）",
        "province": "吉林",
        "theme": "银行受托与商转公",
        "parties": ["长春市住房公积金管理中心图们分理处", "延边州内9家主流商业银行（含工/农/中/建、交、邮储/吉林/农村信用社等）"],
        "policy_background": "图们分理处地处边境，把破解转贷资金筹措堵点列入年度攻坚重点，针对缴存职工办理商转公普遍「先得自己垫几十万结清商贷」的心理障碍，联合州内商业银行推顺位抵押模式实现零垫付办理。",
        "summary": "2026年二季度以来，长春市住房公积金管理中心图们分理处聚焦缴存职工办理商转公的难点、堵点，通过线上答疑+问卷调研+主动推介挖潜机制，密集对接延边州内各商业银行（累计沟通10余次），逐一破解合作流程适配、顺位抵押登记办理、资金安全划转等关键环节，成功打通州内9家主流商业银行的顺位抵押办理通道——铁路、电力、边防等行业职工无需先行自筹资金结清原商贷即可办理转贷；目前图们分理处商转公放款规模已稳步突破1000万元。今年上半年工作人员累计走进15家缴存单位（含珲春边境管理大队、大唐珲春热电厂、珲春高铁站等），精准宣讲、对边境职工上门送策。",
        "practices": [
            "边境一线专列沟通机制：分理处主动对接铁路/电力/边防等行业系统，针对边城缴存职工「不熟悉政策、怕白跑路、怕资料造假」等顾虑，提供一对一上门宣讲与材料预审。",
            "存量挖潜：线上答疑+问卷调研+主动推介三件套：对临柜办理商贷提取的职工现场测算转贷额度；对历史办理过商贷提取的职工逐一电话回访；针对新开户满6个月的缴存单位主动推介。",
            "银行侧合作抓手：针对边境职工收入稳定但首付压力大的特点，地方银行/邮储/农信系可对接「商转公顺位抵押+装修分期+家庭信用贷」的组合产品；与公积金中心共享「商贷已结清」客户白名单推动二次营销。",
        ],
        "sources": [
            {
                "title": "图们分理处 深耕服务一线 释放商转公红利（长春市住房公积金管理中心）",
                "url": "http://zfgjj.changchun.gov.cn/shouye/zwdt/202609/t20260908_3510783.html",
                "date": "2026-09-08",
            },
        ],
        "confidence": "高",
    },
    {
        "id": "case-060",
        "title": "华夏银行太原分行：与太原公积金中心十五年深度战略合作，公积金委托贷款规模超30亿元",
        "city": "太原",
        "province": "山西",
        "theme": "银行受托与商转公",
        "parties": ["华夏银行太原分行", "太原市住房公积金管理中心（含杏花岭分理处驻点）"],
        "policy_background": "山西日报2026-09-08专题报道：华夏银行太原分行自2011年起即与太原市住房公积金管理中心开启深度战略合作，依规开立公积金业务专用账户、签订专项业务合作协议，选派专职人员进驻公积金中心杏花岭分理处驻点办公，是太原公积金委托贷款体系内的核心受托行之一。",
        "summary": "2026-09-08 华夏银行太原分行15年深耕公积金委托贷款一线：业务范围覆盖公积金贷款、组合贷咨询受理、贷款投放、部分/全额提前还款、商转公业务、公积金抵押客户不动产登记证明办理、贷款结清解押等全链条配套服务；截至2026-06-30累计服务市民6500余户、发放公积金委托贷款超30亿元。分行精心选配驻点专员、构建线下实体柜台+线上服务渠道全天候综合服务模式，整合作业环节、压缩办理时限，做到只跑一次。同时集约化高效运转，依托集中一体化办理推动公积金业务高质量发展。",
        "practices": [
            "驻点专员模式：选派经验丰富、业务过硬的专职人员进驻公积金中心分理处驻点办公15年，承担公积金贷款全流程代办，把银行窗口直接搬到公积金大厅。",
            "全链条配套：从首付到不动产登记、再到贷款结清解押全环节一站受理，减少客户在银行、公积金、不动产登记中心之间往返。",
            "银行侧合作抓手：股份制银行（华夏）以专业深耕+驻点服务组合替代简单接入委托，积累受托品牌；其他分行可借鉴此模式主动对接本地公积金中心争取驻点、扩大受托份额。",
        ],
        "sources": [
            {
                "title": "深耕公积金业务 以金融力量守护百姓安居梦（华夏银行太原分行／山西日报转载，新浪看点）",
                "url": "https://k.sina.cn/article_7517400647_1c0126e47059096z5a.html",
                "date": "2026-09-08",
            },
        ],
        "confidence": "高",
    },
    {
        "id": "case-061",
        "title": "建设银行佛山分行：组建张富清服务队常态走进园区，首季公积金开户220+户、代扣代缴100+户",
        "city": "佛山",
        "province": "广东",
        "theme": "社区宣讲与扩面服务",
        "parties": ["中国建设银行佛山分行", "佛山市住房公积金管理中心", "广东商讯平台（佛山产业园区与协会商会）"],
        "policy_background": "佛山建行积极响应住建部及地方公积金中心扩面号召，组建张富清服务队常态化开展「入企宣导、缴存扩面」专项行动，针对中小微企业、灵活就业群体政策不熟、流程不熟等痛点，把专业政策梳理为通俗易懂的实操指引，配套一站式综合金融服务。",
        "summary": "2026-09-08 今日头条（广东商讯刊发）：中国建设银行佛山分行携手佛山市住房公积金管理中心，组建张富清服务队，常态化走进产业园区开展「入企宣导、缴存扩面」专项行动，精准推送公积金惠民政策，打通政策落地最后一公里；走进协会商会面向100+家企业系统解读公积金灵活缴存、便捷提取、个税抵扣等利好政策。2026年首季累计服务企业开立公积金账户超220户、落地代扣代缴企业超100户、服务个人公积金提取超600人次。建行摒弃条文式解读，依托综合金融优势实现公积金账户开立、资金划转、日常运维、信贷支持等一站式办理。",
        "practices": [
            "党建品牌+扩面业务融合：借张富清服务队党建品牌把公积金扩面服务包装成常态化可识别动作，单季开户220+户、代扣代缴100+户、提取600+人次。",
            "入园进企+协会商会双通道批量拓客：以产业园区为链式节点，以协会商会为行业节点，单次覆盖100+企业，单位获客成本极低。",
            "银行侧合作抓手：依托综合金融优势把开户—代扣—提取—信贷全链条打通；中小微企业主/灵活就业群体可同步推送公积金缴存贷、家庭信用贷和新市民住房按揭，形成二次转化。",
        ],
        "sources": [
            {
                "title": "中国建设银行佛山分行公积金开户超220户暖人心（广东商讯／今日头条）",
                "url": "https://www.toutiao.com/article/7683113597548495360/",
                "date": "2026-09-08",
            },
        ],
        "confidence": "高",
    },
    {
        "id": "case-062",
        "title": "郑州航空港区：公积金党建+网格+服务联合工作机制，3家受托银行6个支行下沉17个乡镇",
        "city": "郑州（航空港区）",
        "province": "河南",
        "theme": "数字化与场景金融",
        "parties": ["郑州住房公积金管理中心航空港区管理部", "区城运中心党支部", "航空港区3家受托银行6个支行党支部"],
        "policy_background": "港区管理部以党建引领业务创新，联动区城运中心党支部、3家受托银行6个支行党支部建立联合工作机制，分批次对港区17个乡镇（办事处）、1个IT产业园区近2000名网格长（员）开展公积金业务培训；14名党员以公积金专管员、协理员身份入驻全域网格，将服务触角延伸至基层一线。",
        "summary": "今年以来郑州住房公积金管理中心航空港区管理部推行公积金服务进网格模式：从窗口办到网格办，下沉到社区、企业和群众家中。三个典型案例包括：①企业开户不用跑腿——专管员上门当场办结航空港区腾景光通讯技术有限公司开户；②政策宣讲送进企业——组建流动服务队上门开展公积金政策专场宣讲（走进万达重工等）；③特殊群体上门帮办——为怀孕九个月的职工李女士提供公积金提取上门服务。下一步港区管理部将持续深化党建+网格+服务工作模式，常态化开展网格政策宣讲、便民服务、帮办代办。",
        "practices": [
            "党建+网格+银行三方联动：把公积金专管员、受托银行客户经理与社区网格员队伍捏成一股绳，网格问题在原地化解。",
            "下沉服务半径：把窗口等变为上门办，覆盖17乡镇+1个IT产业园区、2000+名网格长（员）+14名公积金协理员。",
            "银行侧合作抓手：受托银行6个支行可借助网格员队伍开展按揭贷款预审、组合贷预签约；针对万达重工等大型园区企业开展集中获客+联合审批批量授信。",
        ],
        "sources": [
            {
                "title": "公积金服务进网格，企业群众少跑路（顶端新闻）",
                "url": "https://m.topnews.cn/news/145EDEE148BE4A72",
                "date": "2026-09",
            },
        ],
        "confidence": "高",
    },
]


def merge_sources(target_list, new_list, mode="append"):
    seen = {(s.get("url", "") or "").lower() for s in target_list}
    out = list(target_list)
    for s in new_list:
        u = (s.get("url", "") or "").lower()
        if u and u not in seen:
            out.append(s)
            seen.add(u)
    return out


def update_city(city_obj, plan):
    new_last = plan.get("last_updated")
    if new_last:
        city_obj["last_updated"] = new_last

    d_plan = plan.get("deposit")
    if d_plan:
        d = city_obj.setdefault("deposit", {})
        if "base_upper" in d_plan:
            d["base_upper"] = d_plan["base_upper"]
        if "base_lower" in d_plan:
            d["base_lower"] = d_plan["base_lower"]
        if "note" in d_plan:
            d["note"] = d_plan["note"]
        elif "note_append" in d_plan:
            old = d.get("note", "")
            if d_plan["note_append"] and d_plan["note_append"] not in old:
                d["note"] = old + d_plan["note_append"]
        if "sources_replace" in d_plan:
            d["sources"] = list(d_plan["sources_replace"])
        if "sources_append" in d_plan:
            d["sources"] = merge_sources(d.get("sources", []), d_plan["sources_append"])

    w_plan = plan.get("withdrawal")
    if w_plan:
        w = city_obj.setdefault("withdrawal", {})
        if "note" in w_plan:
            w["note"] = w_plan["note"]
        if "matrix_patch" in w_plan:
            m = w.setdefault("matrix", {})
            for k, v in w_plan["matrix_patch"].items():
                m[k] = v
        if "sources_append" in w_plan:
            w["sources"] = merge_sources(w.get("sources", []), w_plan["sources_append"])

    l_plan = plan.get("loan")
    if l_plan:
        l = city_obj.setdefault("loan", {})
        if "note" in l_plan:
            l["note"] = l_plan["note"]
        if "matrix_patch" in l_plan:
            m = l.setdefault("matrix", {})
            for k, v in l_plan["matrix_patch"].items():
                m[k] = v
        if "conditions_append" in l_plan:
            old = (l.get("conditions", "") or "").strip()
            addition = l_plan["conditions_append"].strip()
            if old:
                l["conditions"] = (old + "\n" + addition).strip()
            else:
                l["conditions"] = addition
        if "sources_append" in l_plan:
            l["sources"] = merge_sources(l.get("sources", []), l_plan["sources_append"])


def patch_cases(case_library_cases, new_cases):
    existing_ids = {c["id"] for c in case_library_cases}
    out = list(case_library_cases)
    for c in new_cases:
        if c["id"] in existing_ids:
            out = [x for x in out if x["id"] != c["id"]]
            out.append(c)
        else:
            out.append(c)
    return out


def main():
    indent = detect_indent(DB_PATH)
    eof_nl = detect_eof_newline(DB_PATH)
    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    cities = db.get("cities", [])
    city_index = {c["city"]: c for c in cities}
    for cn, plan in CITY_UPDATES.items():
        if cn not in city_index:
            print("[warn] 未找到目标城市，跳过：%s" % cn)
            continue
        update_city(city_index[cn], plan)
        print("  已更新城市：%s" % cn)

    cl = db.get("case_library", {})
    if isinstance(cl, dict):
        old_cases = cl.get("cases", [])
        new_cases = patch_cases(old_cases, NEW_CASES)
        added = [c["id"] for c in NEW_CASES if c["id"] not in {x["id"] for x in old_cases}]
        if added:
            cl["cases"] = new_cases
            cl["case_count"] = len(new_cases)
            cl["updated_at"] = "2026-09-14"
            themes = sorted({c["theme"] for c in new_cases if c.get("theme")})
            cl["themes"] = themes
            cl["latest_insight"] = (
                "【2026-09-14 商机研判】本周巡检命中 3 城政策更新：武汉汉八条公积金条款——首套纯商贷提取月度化、全国异地公积金在汉不卡缴存地；宜昌商转公合作行扩至邮储银行（10 家）；昆明 2026 年度缴存基数上限提至 32543 元。负面舆情持续向骗提新变种演化，虚假诉讼、伪造诊断书骗提成为 9 月新热点。案例库新增 6 条：宜昌/梧州/长春/太原/佛山/郑州分别从商转公扩面、地方银行接入、边境缴存服务、长周期驻点合作、园区扩面、网格+党建等维度展示银行已从单一受托走向驻点+扩面+网格+党建多形态并行；结合 9 月 20 日新条例施行，银行端在装修/物业费提取、灵活就业扩面、装修分期/物业分期场景的金融适配需提前布局。"
            )
            print("  案例库写入：原 %d 条 → 新 %d 条（新增 %s）" % (
                len(old_cases), len(new_cases), ", ".join(added)))

    db["version"] = "1.6.1"
    db["generated_at"] = "2026-09-14T10:00:00+08:00"

    out_text = json.dumps(db, ensure_ascii=False, indent=indent)
    atomic_write(DB_PATH, out_text, eof_nl)
    print("  %s 已更新为 v%s" % (os.path.basename(DB_PATH), db["version"]))

    # 同步 site 镜像（2 空格 + UTF-8 BOM）
    site_eof_nl = detect_eof_newline(SITE_MIRROR)
    with open(SITE_MIRROR, "r", encoding="utf-8-sig") as f:
        site_db = json.load(f)
    site_db["cities"] = db.get("cities", [])
    site_db["case_library"] = db.get("case_library", {})
    site_db["version"] = db["version"]
    site_db["generated_at"] = db["generated_at"]
    site_db["schema_note"] = db.get("schema_note", "")
    site_db["database"] = db.get("database", "")
    site_db["city_count"] = db.get("city_count", 134)
    if "national_regulations" in db:
        site_db["national_regulations"] = db["national_regulations"]
    if "annual_reports" in db:
        site_db["annual_reports"] = db["annual_reports"]
    site_text = json.dumps(site_db, ensure_ascii=False, indent=2)
    if not site_eof_nl and site_text.endswith("\n"):
        site_text = site_text[:-1]
    if site_eof_nl and not site_text.endswith("\n"):
        site_text += "\n"
    with open(SITE_MIRROR, "w", encoding="utf-8-sig") as f:
        f.write(site_text)
    print("  %s 已同步" % os.path.basename(SITE_MIRROR))

    if os.path.exists(CASES_PATH):
        cases_eof_nl = detect_eof_newline(CASES_PATH)
        with open(CASES_PATH, "r", encoding="utf-8") as f:
            cases_list = json.load(f)
        # cases.json 中无顶层 id 字段，按 title 去重后追加；同时按 case-id 后缀生成可追溯 index
        new_titles = {c["title"] for c in NEW_CASES}
        out_cases = [c for c in cases_list if c.get("title") not in new_titles]
        # 先追加，按现有顺序保留，新增 6 条放最后
        out_cases.extend(NEW_CASES)
        cases_text = json.dumps(out_cases, ensure_ascii=False, indent=2)
        if not cases_eof_nl and cases_text.endswith("\n"):
            cases_text = cases_text[:-1]
        if cases_eof_nl and not cases_text.endswith("\n"):
            cases_text += "\n"
        with open(CASES_PATH, "w", encoding="utf-8") as f:
            f.write(cases_text)
        print("  research/cases.json 同步（%d → %d 条）" % (len(cases_list), len(out_cases)))

    print("\n[done] 全部完成")


if __name__ == "__main__":
    main()
