/* =========================================================================
 * 公积金政策监控台 · 前端逻辑
 * 数据源（网页版，自动更新，四级回退 + 版本纠偏）：
 *   1. jsDelivr CDN（@最新提交SHA，经 GitHub API 解析，实时最新）
 *   2. GitHub Raw    → raw.githubusercontent.com/.../main/gjj_policy_database.json
 *   3. jsDelivr CDN（@main，可能有数小时缓存）
 *   4. 静态镜像       → 部署目录内 gjj_policy_database.json（打包时快照）
 *   任一远程源成功后与本地镜像比对版本，自动采用较新者，防止 CDN 缓存回退。
 * ========================================================================= */
'use strict';

const DATA_SOURCES = [
  { name: 'jsDelivr CDN', url: 'https://cdn.jsdelivr.net/gh/polarsta/gjj-policy-watch@main/gjj_policy_database.json' },
  { name: 'GitHub Raw', url: 'https://raw.githubusercontent.com/polarsta/gjj-policy-watch/main/gjj_policy_database.json' },
  { name: '本地镜像', url: 'gjj_policy_database.json' }
];
/* jsDelivr 对 @main 分支有数小时缓存（可能拿到旧版数据）。
 * 先用 GitHub API 解析 main 最新提交 SHA，再请求 jsDelivr @<sha>（不可变地址，实时最新）；
 * API 不可达时按 GitHub Raw → jsDelivr @main → 本地镜像 顺序回退。 */
async function resolveDataSources() {
  const list = [];
  try {
    const ctrl = new AbortController();
    const tm = setTimeout(() => ctrl.abort(), 6000);
    const r = await fetch('https://api.github.com/repos/polarsta/gjj-policy-watch/commits/main', { signal: ctrl.signal, cache: 'no-store' });
    clearTimeout(tm);
    if (r.ok) {
      const j = await r.json();
      if (j && j.sha) list.push({ name: 'jsDelivr CDN（最新提交）', url: `https://cdn.jsdelivr.net/gh/polarsta/gjj-policy-watch@${j.sha}/gjj_policy_database.json` });
    }
  } catch (e) { console.warn('最新提交解析失败，走常规源:', e.message); }
  list.push(
    { name: 'GitHub Raw', url: 'https://raw.githubusercontent.com/polarsta/gjj-policy-watch/main/gjj_policy_database.json' },
    { name: 'jsDelivr CDN', url: 'https://cdn.jsdelivr.net/gh/polarsta/gjj-policy-watch@main/gjj_policy_database.json' },
    { name: '本地镜像', url: 'gjj_policy_database.json' }
  );
  return list;
}
const REPO_URL = 'https://github.com/polarsta/gjj-policy-watch';
const SEC_NAME = { deposit: '缴存', withdrawal: '提取', loan: '贷款', general: '综合' };
const SEC_CLS = { deposit: 'b-dep', withdrawal: 'b-wit', loan: 'b-loan', general: 'b-nat' };

let DB = null;            // 原始数据库
let CITIES = [];          // 城市数组
let CASES = [];           // 案例数组
let FEAT = {};            // city -> 特征对象
let LOCAL_REC = [];       // 本地新增记录
let NAT_POLICIES = [];    // 挖掘出的全国性政策
let CUR_SRC = '';         // 当前数据源名
let BR_CITY = null;       // 分行当前城市
let BR_RANGE = 0;         // 分行时间筛选（天，0=全部）
let HQ_RANGE = 365;       // 总行速览时间范围
let MX_DIM = 'all';       // 矩阵维度（all=全部三合一）

/* ---------------- 工具 ---------------- */
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = n => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const clip = (s, n) => { s = String(s || '').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(t._tm); t._tm = setTimeout(() => t.classList.remove('on'), 2600); }
function fmtNum(n) { return (n == null || n === '') ? '—' : Number(n).toLocaleString('zh-CN'); }
/* 版本号比较：'1.2.0' > '1.1.0' 返回正数；无法解析时退化为字符串比较 */
function verCompare(a, b) {
  const pa = String(a || '0').split('.').map(x => parseInt(x, 10) || 0);
  const pb = String(b || '0').split('.').map(x => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d;
  }
  return 0;
}

/* ---------------- 数据加载 ---------------- */
async function loadDB(forceRefresh) {
  const pill = $('#src-pill'), txt = $('#src-txt');
  let lastErr = null;
  const sources = await resolveDataSources();
  for (const src of sources) {
    try {
      const ctrl = new AbortController();
      const tm = setTimeout(() => ctrl.abort(), 20000);
      const r = await fetch(src.url + (src.url.includes('?') ? '&' : '?') + '_t=' + Date.now(), { signal: ctrl.signal, cache: 'no-store' });
      clearTimeout(tm);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      if (!j || !Array.isArray(j.cities) || !j.cities.length) throw new Error('数据结构不完整');
      // 防 CDN 缓存回退：若本地镜像版本更新（部署时打包的快照），优先采用较新者
      if (src.name !== '本地镜像') {
        try {
          const lr = await fetch('gjj_policy_database.json?_t=' + Date.now(), { cache: 'no-store' });
          if (lr.ok) {
            const lj = await lr.json();
            if (lj && verCompare(lj.version, j.version) > 0) {
              CUR_SRC = `本地镜像（较新，${src.name} 缓存为旧版）`;
              pill.classList.add('ok'); pill.href = REPO_URL;
              txt.textContent = `已连接·${CUR_SRC} v${lj.version || ''} ${lj.generated_at || ''}`;
              return lj;
            }
          }
        } catch (le) { /* 本地镜像不可读则用远程 */ }
      }
      CUR_SRC = src.name;
      pill.classList.add('ok'); pill.href = REPO_URL;
      txt.textContent = `已连接·${src.name} v${j.version || ''} ${j.generated_at || ''}`;
      return j;
    } catch (e) { lastErr = e; console.warn('数据源失败:', src.name, e.message); }
  }
  pill.classList.add('bad'); txt.textContent = '数据源连接失败';
  throw lastErr || new Error('所有数据源均不可用');
}

/* ---------------- 城市口径（任务4：134城，以年报库为准；排除「全国」等非城市条目） ---------------- */
function canonicalCities(db) {
  // 归一化城市名（去 市/州/县/区/盟/地区 后缀），兼容「吉林」vs「吉林市」等命名差异
  const norm = s => String(s || '').replace(/(地区|[市州县盟区]+)$/, '');
  let list = (db.cities || []).filter(c => c.city !== '全国');
  const ar = db.annual_reports && db.annual_reports.cities;
  if (Array.isArray(ar) && ar.length) {
    const keep = new Set(ar.map(x => norm(x.city)));
    list = list.filter(c => keep.has(norm(c.city)));
  }
  return list;
}

/* ---------------- 来源分类 ---------------- */
const OFFICIAL_MEDIA = ['people.com.cn', 'xinhuanet', 'news.cn', 'cnr.cn', 'cctv.com', 'chinanews.com', 'gmw.cn', 'ce.cn', 'stdaily.com', 'caixin.com', 'cls.cn', 'thepaper.cn', 'yicai.com', 'jiemian.com', '21jingji.com', 'cjn.cn', 'fznews.com.cn', 'tidenews.com.cn', 'bjnews.com.cn', 'beijingdaily', 'shobserver', 'nanfangdaily', 'sznews.com', 'dayoo.com', 'ycwb.com', 'cqdaily', 'scdaily', 'zjol.com.cn', 'hxnews.com', 'cb.com.cn', 'house.cnr.cn'];
const BANK_MEDIA = ['icbc.com.cn', 'ccb.com', 'abchina.com', 'boc.cn', 'cmbchina.com', 'citic', 'cib.com.cn', 'spdb.com.cn', 'cmbc.com.cn', 'pingan.com', 'bankcomm.com', 'cebbank.com', 'hxb.com.cn', 'cgbchina.com.cn', 'psbc.com'];
function srcType(url, title) {
  const u = (url || '').toLowerCase();
  if (!u) return { t: '其他', c: 'b-src' };
  if (u.includes('mp.weixin.qq.com')) return { t: '官方公众号', c: 'b-wit' };
  if (BANK_MEDIA.some(d => u.includes(d))) return { t: '同业报道', c: 'b-nat' };
  if (u.includes('.gov.cn') || /(^|\.)gjj\.|zfgjj|gjjxx\.|fsgjj|gjj\.gov/.test(u)) return { t: '官网', c: 'b-dep' };
  if (OFFICIAL_MEDIA.some(d => u.includes(d))) return { t: '官方媒体', c: 'b-good' };
  return { t: '其他', c: 'b-src' };
}

/* ---------------- 政策信号（利好/中性/风险） ---------------- */
function signalOf(text) {
  const t = String(text || '');
  if (/收紧|暂停|下调(额度|上限|比例)|降低(额度|上限)|取消.{0,6}(提取|优惠|上浮)|不予|限制.{0,4}(提取|贷款)/.test(t)) return { t: '风险', c: 'b-risk', k: 'risk' };
  if (/上浮|提高|上调|新增|支持|优化|放宽|扩大|扩围|下调.{0,4}利率|降低首付|延长|增加|取消.{0,4}(限制|限购)|惠民|便利|零材料|既提又贷|首付直付|灵活就业/.test(t)) return { t: '利好', c: 'b-good', k: 'good' };
  return { t: '中性', c: 'b-mid', k: 'mid' };
}

/* ---------------- 特征提取引擎 ----------------
 * 返回 { key: {st:'y'|'p'|'n'|'u', txt:依据} } ；st: ✓支持 ◐部分/有条件 ✗不支持 —待采集
 */
const F_KEYS = {
  deposit: [
    ['flex_dep', '灵活就业缴存'], ['defer', '缓缴政策']
  ],
  withdrawal: [
    ['buy_once', '购房一次性提取'], ['rent_limit', '租房提取限额'],
    ['rent_multi', '多孩租房上浮'], ['decor', '住房装修提取'], ['elevator', '加装电梯提取'],
    ['parking', '车位购置提取'], ['illness', '大病救助提取'], ['both', '既提又贷'],
    ['first_pay', '首付直付'], ['mutual', '代际互助'], ['prop_fee', '物业费提取'], ['repay_mode', '按月冲还商贷']
  ],
  loan: [
    ['sd_diff', '单/双职工额度差异'], ['fs_diff', '首套/二套额度差异'], ['green', '绿色建筑上浮'],
    ['kid2', '二孩家庭上浮'], ['kid3', '三孩家庭上浮'], ['talent', '人才/青年上浮'],
    ['mutual_loan', '家庭共享额度(代际互助)'], ['s2g', '商转公'], ['age30', '最长贷龄30年']
  ]
};
/* ---- 结构化政策矩阵（v1.5.0+）维度名映射：特征键 → 数据库矩阵维度名 ---- */
const MX_DIM_NAME = {
  withdrawal: {
    buy_once: '购房一次性提取', rent_limit: '租房提取限额', rent_multi: '多孩租房上浮',
    decor: '住房装修提取', elevator: '加装电梯提取', parking: '车位购置提取',
    illness: '大病救助提取', both: '既提又贷', first_pay: '首付直付',
    mutual: '代际互助', prop_fee: '物业费提取', repay_mode: '按月冲还商贷'
  },
  loan: {
    sd_diff: '单双职工额度差异', fs_diff: '首套二套额度差异', green: '绿色建筑上浮',
    kid2: '二孩家庭上浮', kid3: '三孩家庭上浮', talent: '人才青年上浮',
    mutual_loan: '家庭共享额度代际互助', s2g: '商转公', age30: '最长贷龄30年'
  }
};
/* 矩阵状态 → 前端状态码：未确认/未检索到/未采集到相关信息 一律视为待核实(u) */
const MX_ST = { '支持': 'y', '有条件支持': 'p', '不支持': 'n' };
function hit(text, kws) { return kws.some(k => text.includes(k)); }
function neg(text, kws) { return kws.some(k => new RegExp('(不支持|不可|不能|未(开通|支持|开展)|暂不|除外).{0,8}' + k).test(text) || new RegExp(k + '.{0,6}(不支持|暂未|未开通)').test(text)); }

function extractFeatures(c) {
  const w = c.withdrawal || {}, l = c.loan || {}, d = c.deposit || {};
  const wText = [(w.conditions || []).join('；'), w.rent_limit, w.note].filter(Boolean).join('。');
  const lText = [l.max_single, l.max_family, l.rate_first, l.rate_second, l.conditions, l.note].filter(Boolean).join('。');
  const all = wText + '。' + lText + '。' + (d.note || '');
  const hasW = !!(wText.trim()), hasL = !!(lText.trim());
  const F = {};
  const set = (k, st, txt) => { F[k] = { st, txt: clip(txt || '', 120) }; };
  const judge = (text, pos, scope, base) => {
    if (!scope) return ['u', '待采集'];
    if (neg(text, pos)) return ['n', base];
    if (hit(text, pos)) return [/(部分|有条件|试点|限额|符合|可申请|视情况|阶段性)/.test(text) ? 'p' : 'y', base];
    return ['u', '待采集'];
  };
  // ---- 提取维度 ----
  let r;
  r = judge(wText, ['购房', '购买自住住房', '购买住房'], hasW, (w.conditions || []).find(x => x.includes('购')) || '购房提取');
  set('buy_once', hasW && hit(wText, ['购房', '购买自住住房', '购买住房']) ? (neg(wText, ['购房提取']) ? 'n' : 'y') : r[0], r[1]);
  r = judge(wText, ['物业费', '物业服务费'], hasW, '物业费提取'); set('prop_fee', r[0], r[1]);
  set('rent_limit', hasW && /租房/.test(wText) && /(元|租金|限额|上限)/.test(wText) ? 'y' : (hasW ? 'u' : 'u'), clip(w.rent_limit, 60) || '待采集');
  r = judge(wText, ['多子女', '多孩', '二孩', '三孩'], hasW, clip((w.rent_limit || '') + ' ' + (w.note || ''), 80));
  set('rent_multi', r[0] === 'u' && /(多子女|多孩|二孩|三孩)/.test(wText) ? 'y' : r[0], r[1]);
  r = judge(wText, ['装修'], hasW, '住房装修提取'); set('decor', r[0], r[1]);
  r = judge(wText, ['加装电梯', '电梯'], hasW, '老旧小区加装电梯提取'); set('elevator', r[0], r[1]);
  r = judge(wText, ['车位'], hasW, '专属车位购置提取'); set('parking', r[0], r[1]);
  r = judge(wText, ['大病', '重大疾病', '重病'], hasW, '重大疾病救助提取'); set('illness', r[0], r[1]);
  r = judge(all, ['既提又贷', '又提又贷', '可提可贷'], hasW || hasL, '既提又贷（提取不影响贷款）'); set('both', r[0], r[1]);
  r = judge(all, ['首付直付', '支付购房首付', '提取.{0,4}首付', '首付提取', '首付款'], hasW, '提取公积金直付首付');
  set('first_pay', r[0] === 'u' && new RegExp('首付').test(wText) && /(直付|支付|提取)/.test(wText) ? 'y' : r[0], r[1]);
  r = judge(all, ['代际互助', '代际', '父母.{0,4}(子女|提取)', '直系亲属', '家庭共济'], hasW || hasL, '代际互助'); set('mutual', r[0], r[1]);
  r = judge(wText, ['月冲', '按月冲', '按月提取还贷', '逐月', '按月提取', '对冲还贷', '按月划扣', '委托按月', '月对冲'], hasW, '按月冲还贷/按月提取还贷'); set('repay_mode', r[0], r[1]);
  // ---- 贷款维度 ----
  const ms = String(l.max_single || ''), mf = String(l.max_family || '');
  const numOf = s => { const m = s.replace(/,/g, '').match(/(\d+(?:\.\d+)?)\s*万/); return m ? parseFloat(m[1]) : null; };
  const n1 = numOf(ms), n2 = numOf(mf);
  set('sd_diff', (n1 != null && n2 != null) ? (Math.abs(n1 - n2) > 1 ? 'y' : 'n') : (ms || mf ? 'p' : 'u', hasL ? 'p' : 'u'), `单职工:${clip(ms, 30)} / 双职工:${clip(mf, 30)}`);
  const rateDiff = /二套/.test(lText) && /(上浮|高于|不低于|增加)/.test(lText);
  set('fs_diff', hasL ? (rateDiff || /首套.{0,12}二套/.test(lText) ? 'y' : 'p') : 'u', `首套:${clip(l.rate_first, 26)} / 二套:${clip(l.rate_second, 26)}`);
  r = judge(lText, ['绿色建筑', '装配式', '节能环保'], hasL, '绿色建筑/装配式贷款额度上浮'); set('green', r[0], r[1]);
  r = judge(lText, ['二孩', '多子女', '多孩'], hasL, '多孩家庭额度上浮'); set('kid2', r[0], r[1]);
  r = judge(lText, ['三孩', '三子女', '三个及以上子女', '三孩及以上'], hasL, '三孩家庭额度上浮'); set('kid3', r[0], r[1]);
  r = judge(lText, ['人才', '青年', '高层次', '新市民'], hasL, '人才/青年等特殊上浮'); set('talent', r[0], r[1]);
  r = judge(lText, ['代际互助', '家庭共享', '家庭共济', '父母.{0,4}共同', '直系亲属'], hasL, '家庭共享额度/代际互助贷款'); set('mutual_loan', r[0], r[1]);
  r = judge(lText, ['商转公'], hasL, '商业贷款转公积金贷款'); set('s2g', r[0], r[1]);
  set('age30', hasL ? (/30\s*年/.test(lText) ? 'y' : 'u') : 'u', '最长贷款期限30年');
  // ---- 缴存维度 ----
  const dText = [(d.ratio || ''), (d.period || ''), (d.note || ''), ((d.conditions || []).join('；'))].filter(Boolean).join('。');
  const hasD = !!dText.trim();
  const flexM = dText.match(/灵活就业[^；;。]*/);
  r = judge(dText, ['灵活就业'], hasD, flexM ? flexM[0] : '灵活就业人员自愿缴存');
  set('flex_dep', r[0], r[1]);
  // 缓缴政策（v1.3.1+：读取每城 deferral 结构化字段：supported/legal_basis/max_period/sources）
  const df = c.deferral || {};
  if (df.supported === true) set('defer', 'y', clip((df.legal_basis || '支持缓缴') + (df.max_period ? '｜期限：' + df.max_period : ''), 170));
  else if (df.supported === false) set('defer', 'n', clip(df.legal_basis || '不支持缓缴', 120));
  else set('defer', 'u', '待采集');
  /* ================= 结构化政策矩阵覆盖（v1.5.0+ 权威数据源） =================
   * 提取 12 维 ← withdrawal.matrix[维度]（status/condition/detail/sources[]）
   * 贷款 9 维 ← loan.matrix[维度]（status/condition/source_link/source_type）
   * 缴存     ← deposit.flexible_contribution / deposit.deferred_payment
   * 特征对象扩展字段：url(政策原文) src(来源名) srcDate srcType dim(维度名) */
  const wmx = w.matrix || {}, lmx = l.matrix || {};
  for (const k in MX_DIM_NAME.withdrawal) {
    const rec = wmx[MX_DIM_NAME.withdrawal[k]];
    if (!rec || !rec.status) continue;
    const s0 = (rec.sources || [])[0] || {};
    F[k] = {
      st: MX_ST[rec.status] || 'u',
      txt: clip(rec.detail || rec.condition || '', 220),
      url: s0.url || '', src: s0.title || '', srcDate: s0.date || '', srcType: s0.type || '',
      dim: MX_DIM_NAME.withdrawal[k]
    };
  }
  for (const k in MX_DIM_NAME.loan) {
    const rec = lmx[MX_DIM_NAME.loan[k]];
    if (!rec || !rec.status) continue;
    F[k] = {
      st: MX_ST[rec.status] || 'u',
      txt: clip(rec.condition || '', 220),
      url: rec.source_link || '', src: '', srcDate: '', srcType: rec.source_type || '',
      dim: MX_DIM_NAME.loan[k]
    };
  }
  const fc = d.flexible_contribution || {};
  if (fc.status) F.flex_dep = {
    st: MX_ST[fc.status] || 'u',
    txt: clip(fc.note || fc.condition || '', 220),
    url: fc.source_url || '', src: fc.source_name || '', srcDate: fc.source_date || '', srcType: '',
    dim: '灵活就业缴存'
  };
  const dfp = d.deferred_payment || {};
  if (dfp.status) F.defer = {
    st: MX_ST[dfp.status] || 'u',
    txt: clip(dfp.note || dfp.legal_basis || dfp.condition || '', 220),
    url: dfp.source_url || '', src: dfp.source_name || '', srcDate: dfp.source_date || '', srcType: '',
    dim: '缓缴政策'
  };
  return F;
}
const ST_TXT = { y: '✓', p: '◐', n: '✗', u: '—' };
const ST_NAME = { y: '支持', p: '部分支持/有条件', n: '不支持', u: '待核实' };
const stHtml = st => `<span class="st st-${st}" title="${ST_NAME[st]}">${ST_TXT[st]}</span>`;

/* ---------------- 政策明细弹层（地区分类矩阵 / 分行资格矩阵共用） ----------------
 * 悬停色块：弹出深色浮层（状态 + 维度·城市 + 政策明细 + 官方来源）；
 * 点击色块：有原文链接则新窗口跳转，无链接则弹出浮层。 */
function mxTipEl() {
  let t = $('#mx-tip');
  if (!t) {
    t = document.createElement('div');
    t.id = 'mx-tip';
    document.body.appendChild(t);
    t.addEventListener('mouseenter', () => clearTimeout(t._tm));
    t.addEventListener('mouseleave', () => { t.style.display = 'none'; });
  }
  return t;
}
function mxTipHtml(city, label, ft) {
  const st = ft.st || 'u';
  const txt = ft.txt && ft.txt !== '待采集' ? esc(ft.txt) : '官方尚未公开该维度明细，待核实。';
  const srcLine = ft.src ? `<div>来源：${esc(clip(ft.src, 60))}${ft.srcDate ? `（${esc(ft.srcDate)}）` : ''}${ft.srcType ? ` · ${esc(ft.srcType)}` : ''}</div>` : '';
  const linkLine = ft.url
    ? `<div style="margin-top:4px"><a href="${esc(ft.url)}" target="_blank" rel="noopener">查看政策原文 ↗</a><span style="color:#8fa3b8">　（点击色块也可直达）</span></div>`
    : '<div style="margin-top:4px;color:#8fa3b8">暂无公开原文链接</div>';
  return `<div class="tp-st tp-${st}">${ST_TXT[st]} ${ST_NAME[st]}</div>
    <div class="tp-dim">${esc(label || ft.dim || '')} · ${esc(city)}</div>
    <div class="tp-txt">${txt}</div>
    <div class="tp-src">${srcLine}${linkLine}</div>`;
}
function mxTipShow(html, anchor) {
  const t = mxTipEl();
  clearTimeout(t._tm);
  t.innerHTML = html;
  t.style.display = 'block';
  const r = anchor.getBoundingClientRect();
  const tw = t.offsetWidth, th = t.offsetHeight;
  let x = r.left + r.width / 2 - tw / 2;
  x = Math.max(8, Math.min(x, window.innerWidth - tw - 8));
  let y = r.bottom + 8;
  if (y + th > window.innerHeight - 8) y = Math.max(8, r.top - th - 8);
  t.style.left = x + 'px';
  t.style.top = y + 'px';
}
function mxTipHideLater() { const t = mxTipEl(); clearTimeout(t._tm); t._tm = setTimeout(() => { t.style.display = 'none'; }, 200); }
function bindMatrixTips() {
  document.addEventListener('mouseover', e => {
    const td = e.target.closest('td.mx-cell');
    if (!td) return;
    const ft = (FEAT[td.dataset.city] || {})[td.dataset.dim] || { st: 'u' };
    mxTipShow(mxTipHtml(td.dataset.city, td.dataset.label, ft), td);
  });
  document.addEventListener('mouseout', e => { if (e.target.closest('td.mx-cell')) mxTipHideLater(); });
  document.addEventListener('click', e => {
    const td = e.target.closest('td.mx-cell');
    if (!td) return;
    const ft = (FEAT[td.dataset.city] || {})[td.dataset.dim];
    if (ft && ft.url) window.open(ft.url, '_blank', 'noopener');
    else mxTipShow(mxTipHtml(td.dataset.city, td.dataset.label, ft || { st: 'u' }), td);
  });
}

/* ---------------- 全国性政策挖掘 ---------------- */
function mineNational(db) {
  const out = []; const seen = new Set();
  // 0) 全国性法规库（v1.2.0+ 新增 national_regulations 字段）：条例等国家级法规优先入列
  for (const rg of (db.national_regulations && db.national_regulations.regulations) || []) {
    const k = 'reg-' + (rg.id || rg.title);
    if (seen.has(k)) continue; seen.add(k);
    const cats = (rg.key_changes || []).map(x => x.category).filter(Boolean);
    out.push({
      title: rg.title,
      desc: `要点：${cats.join('｜')}${rg.effective_date ? `。${rg.effective_date} 起施行` : ''}。`,
      org: rg.issued_by || '国务院', date: rg.publish_date || rg.sign_date || '',
      url: (rg.sources && rg.sources[0] && rg.sources[0].url) || '',
      srcTitle: (rg.sources && rg.sources[0] && rg.sources[0].title) || '',
      key: k, type: 'regulation', reg: rg
    });
  }
  // 1) 央行 2025-05-08 降息（从各城利率字段挖掘到的全国性事实）
  let cutCity = null,cutUrl = null,cutTitle = null;
  for (const c of db.cities) {
    const rf = c.loan && c.loan.rate_first || '';
    if (rf.includes('2025-05-08') || rf.includes('2025年5月8日')) {
      cutCity = cutCity || c.city;
      const s = (c.loan.sources || [])[0];
      if (s && s.url && !cutUrl) { cutUrl = s.url; cutTitle = s.title; }
    }
  }
  if (cutCity) {
    out.push({
      title: '中国人民银行：下调个人住房公积金贷款利率 0.25 个百分点',
      desc: `自2025年5月8日起，5年以下（含）首套利率2.1%、5年以上首套2.6%，全国统一执行（${db.cities.filter(c => ((c.loan || {}).rate_first || '').includes('2025')).length}+ 城利率字段已同步）。`,
      org: '中国人民银行', date: '2025-05-08', url: cutUrl || '', srcTitle: cutTitle || '', key: 'pbc-rate'
    });
    seen.add('pbc-rate');
  }
  // 2) 案例库政策背景中的中央部署
  for (const cs of (db.case_library && db.case_library.cases) || []) {
    const bg = cs.policy_background || '';
    if (/国务院|住建部|人民银行|中央/.test(bg) && cs.sources && cs.sources[0]) {
      const k = 'case-' + cs.id;
      if (seen.has(k)) continue; seen.add(k);
      out.push({
        title: clip(bg.replace(/^贯彻/, '').replace(/。.*$/, ''), 42) || cs.title,
        desc: clip(bg, 110) + `（落地案例：${cs.title}）`,
        org: '中央部署 · 地方落地', date: cs.date || '', url: cs.sources[0].url, srcTitle: cs.sources[0].title, key: k
      });
    }
  }
  // 3) 各城市 source 中明确指向中央机构的
  const kw = /国务院|人民银行|央行|住建部|财政部|中央/;
  const got = new Map();
  for (const c of db.cities) {
    for (const sec of ['deposit', 'withdrawal', 'loan']) {
      for (const s of ((c[sec] || {}).sources || [])) {
        const t = s.title || '';
        if (kw.test(t) && s.url && s.url.length > 12 && !s.url.endsWith('gov.cn/')) {
          const k = t + '|' + s.url;
          if (!got.has(k)) got.set(k, { title: t, url: s.url, date: s.date || '', cities: [] });
          got.get(k).cities.push(c.city);
        }
      }
    }
  }
  for (const [k, v] of got) {
    if (seen.has(k) || out.length >= 8) break;
    seen.add(k);
    out.push({ title: clip(v.title, 46), desc: `涉及：${[...new Set(v.cities)].slice(0, 8).join('、')} 等城市`, org: '中央/省级部门', date: v.date, url: v.url, srcTitle: v.title, key: k });
  }
  return out.slice(0, 8);
}

/* ---------------- 本地新增记录 ---------------- */
function loadLocal() { try { LOCAL_REC = JSON.parse(localStorage.getItem('gjj_local_rec') || '[]'); } catch (e) { LOCAL_REC = []; } }
function saveLocal() { localStorage.setItem('gjj_local_rec', JSON.stringify(LOCAL_REC)); }

/* ================= 总行总览 ================= */
function allSources(c) {
  const out = [];
  for (const sec of ['deposit', 'withdrawal', 'loan'])
    for (const s of ((c[sec] || {}).sources || []))
      out.push({ sec, ...s, city: c.city });
  return out;
}
function collectChanges(rangeDays) {
  const since = daysAgo(rangeDays);
  const rows = [];
  for (const c of CITIES) {
    for (const s of allSources(c)) {
      if (s.date && s.date >= since && s.date <= today()) {
        const secObj = c[s.sec] || {};
        rows.push({
          city: c.city, province: c.province, sec: s.sec, date: s.date,
          title: s.title || '', url: s.url || '',
          note: secObj.note || s.title || '',
          signal: signalOf((secObj.note || '') + (s.title || ''))
        });
      }
    }
  }
  rows.sort((a, b) => b.date.localeCompare(a.date));
  return rows;
}
function renderStats() {
  const totalSrc = CITIES.reduce((n, c) => n + allSources(c).length, 0);
  const provs = new Set(CITIES.map(c => c.province)).size;
  const ch30 = collectChanges(30);
  const ch7 = ch30.filter(r => r.date >= daysAgo(7)).length;
  const secCnt = { deposit: 0, withdrawal: 0, loan: 0 };
  let good = 0, risk = 0;
  for (const r of collectChanges(365)) { secCnt[r.sec]++; if (r.signal.k === 'good') good++; if (r.signal.k === 'risk') risk++; }
  $('#hq-stats').innerHTML = `
    <div class="stat"><div class="n">${CITIES.length}<small> 个</small></div><div class="t">监测城市 · 覆盖 ${provs} 省（区市）</div></div>
    <div class="stat t"><div class="n">${totalSrc}<small> 条</small></div><div class="t">政策来源记录 · 全部附真实链接</div></div>
    <div class="stat g"><div class="n">${ch30.length}<small> 条</small></div><div class="t">近30天新增 · <span style="color:var(--good)">近7天 +${ch7}</span></div></div>
    <div class="stat o"><div class="n">${secCnt.loan}<small> 条</small></div><div class="t">近12月贷款类 · 额度/利率/首付</div></div>
    <div class="stat"><div class="n">${secCnt.withdrawal}<small> 条</small></div><div class="t">近12月提取类 · 租房/购房/电梯</div></div>
    <div class="stat t"><div class="n">${secCnt.deposit}<small> 条</small></div><div class="t">近12月缴存类 · 基数/比例调整</div></div>
    <div class="stat r"><div class="n">${CASES.length}<small> 个</small></div><div class="t">商机案例库 · 银行合作案例</div></div>`;
  $('#hd-sub').textContent = `机构客户部 · 公积金中心客群赋能工具（已接入 ${CITIES.length} 城真实政策数据库并标注来源 · 版本 v${DB.version} · 更新 ${DB.generated_at}）`;
}
/* ---- 政策变化速览 ---- */
function renderNews() {
  const el = $('#hq-news');
  const rows = collectChanges(HQ_RANGE);
  const citySet = new Set(rows.map(r => r.city));
  const secSet = [...new Set(rows.map(r => r.sec))].map(s => SEC_NAME[s]);
  const local = LOCAL_REC.filter(r => !r.date || r.date >= daysAgo(HQ_RANGE));
  const rangeName = { 7: '近7天', 30: '近1个月', 90: '近3个月', 365: '近12个月' }[HQ_RANGE] || '';
  const oppCities = [...citySet].slice(0, 8).join('、');
  el.innerHTML = `<div class="panel">
    <h3>政策变化速览 <span class="badge b-nat">增量监测</span></h3>
    <div class="h-sub">选取过去12个月内官方来源，按时间由近到远置顶最新变化；按天 / 周 / 月汇总本期动态</div>
    <div class="filters">
      <div class="seg" id="hq-range">
        <button data-d="7" ${HQ_RANGE===7?'class="on"':''}>近7天</button>
        <button data-d="30" ${HQ_RANGE===30?'class="on"':''}>近1个月</button>
        <button data-d="90" ${HQ_RANGE===90?'class="on"':''}>近3个月</button>
        <button data-d="365" ${HQ_RANGE===365?'class="on"':''}>近12个月</button>
      </div>
      <span style="flex:1"></span>
      <button class="btn ghost" id="btn-add-rec">➕ 新增记录</button>
      <button class="btn gray" id="btn-export-json">⬇ 导出 JSON</button>
      <button class="btn gray" id="btn-clear-local">🗑 清空本地</button>
    </div>
    <div class="sumbar">📊 <b>${rangeName}总结</b>：本期共 <b>${rows.length}</b> 条政策来源更新，覆盖 <b>${citySet.size}</b> 个城市，涉及板块：<b>${secSet.join(' / ') || '—'}</b>。${rows.length ? `业务机会：${oppCities}${citySet.size > 8 ? '等' : ''}分行可及时对接当地公积金中心客户，围绕新政开展宣讲与产品联动。` : '本期暂无公开更新，已监测城市政策保持稳定。'}</div>
    <div class="ch-cols" id="ch-cols"></div>
  </div>
  <div class="panel"><h3>全国性政策 / 中央动态 <span class="badge b-nat">跨城市 · 置顶</span></h3>
    <div class="h-sub">国务院、住建部、人民银行等全国性政策与部署（从数据库自动挖掘，链接真实可点击）</div>
    <div class="nat-grid" id="nat-grid"></div>
  </div>`;
  const cols = $('#ch-cols');
  let colHtml = '';
  for (const sec of ['deposit', 'withdrawal', 'loan']) {
    const list = rows.filter(r => r.sec === sec);
    const loc = local.filter(r => r.sec === sec);
    const top = list.slice(0, 6);
    colHtml += `<div class="ch-col h-${sec === 'deposit' ? 'dep' : sec === 'withdrawal' ? 'wit' : 'loan'}">
      <div class="ch-col-h">${SEC_NAME[sec]}<span class="cnt">${list.length + loc.length} 条</span></div>`;
    if (!top.length && !loc.length) colHtml += `<div class="empty">本期内暂无${SEC_NAME[sec]}类公开更新</div>`;
    for (const r of loc) colHtml += chItem({ city: r.city || '全国', sec: r.sec, date: r.date || '本地', title: r.title, url: r.url, note: r.note, signal: signalOf(r.note + r.title), local: true });
    for (const r of top) colHtml += chItem(r);
    if (list.length > 6) colHtml += `<span class="more-link" data-sec="${sec}">展开全部 ${list.length} 条 ▾</span>`;
    colHtml += `</div>`;
  }
  cols.innerHTML = colHtml;
  cols._rows = rows;
  $('#nat-grid').innerHTML = NAT_POLICIES.map(p => `
    <div class="nat-card">
      <div class="tt">${esc(p.title)}</div>
      <div class="ds">${esc(p.desc)}</div>
      <div class="mt"><span>${esc(p.org)}</span>${p.date ? `<span>· ${p.date}</span>` : ''}${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div>
    </div>`).join('') || '<div class="empty">暂未挖掘到全国性动态</div>';
}
function chItem(r) {
  const one = clip((r.note || '').replace(/\s+/g, ' ').split(/[。；]/)[0] || r.title, 40);
  return `<div class="ch-item">
    <div class="tt"><span class="badge ${SEC_CLS[r.sec] || 'b-nat'}">${SEC_NAME[r.sec] || '综合'}</span> <b>${esc(r.city)}</b> · ${esc(one)}</div>
    <div class="ds" title="${esc(r.note)}">${esc(clip(r.title, 56))}</div>
    <div class="mt"><span class="badge ${r.signal.c}">${r.signal.t}</span><span>📅 ${r.date}</span>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener" title="${esc(r.title)}">官方原文 ↗</a>` : ''}${r.local ? '<span class="badge b-src">本地</span>' : ''}</div>
  </div>`;
}

/* ---- 政策总览（城市卡片） ---- */
let CARD_F = { kw: '', sec: '', src: '', prov: '' };
function renderCards() {
  const el = $('#hq-cards');
  const provs = [...new Set(CITIES.map(c => c.province))].sort();
  el.innerHTML = `<div class="panel">
    <h3>政策总览 · 三栏卡片 <span class="badge b-city">${CITIES.length} 城</span></h3>
    <div class="h-sub">每城一卡：缴存 / 提取 / 贷款新政策概况 + 一句话变化 + 生效日 + 官方链接一键直达；支持关键词 / 板块 / 来源筛选</div>
    <div class="filters">
      <input type="text" id="cf-kw" placeholder="关键词筛选（城市/政策内容）" value="${esc(CARD_F.kw)}" style="min-width:200px">
      <select id="cf-sec"><option value="">全部板块</option><option value="deposit" ${CARD_F.sec==='deposit'?'selected':''}>缴存</option><option value="withdrawal" ${CARD_F.sec==='withdrawal'?'selected':''}>提取</option><option value="loan" ${CARD_F.sec==='loan'?'selected':''}>贷款</option></select>
      <select id="cf-src"><option value="">全部来源</option><option ${CARD_F.src==='官网'?'selected':''}>官网</option><option ${CARD_F.src==='官方公众号'?'selected':''}>官方公众号</option><option ${CARD_F.src==='官方媒体'?'selected':''}>官方媒体</option><option ${CARD_F.src==='同业报道'?'selected':''}>同业报道</option><option ${CARD_F.src==='其他'?'selected':''}>其他</option></select>
      <select id="cf-prov"><option value="">全部省份</option>${provs.map(p => `<option ${CARD_F.prov===p?'selected':''}>${p}</option>`).join('')}</select>
      <span id="cf-cnt" style="font-size:12.5px;color:var(--sub)"></span>
    </div>
    <div class="city-grid" id="city-grid"></div>
  </div>`;
  const draw = () => {
    const kw = CARD_F.kw.trim().toLowerCase();
    const grid = $('#city-grid');
    let cnt = 0;
    const cards = [];
    for (const c of CITIES) {
      if (CARD_F.prov && c.province !== CARD_F.prov) continue;
      if (kw && !(c.city + c.province + JSON.stringify([c.deposit.note, c.withdrawal.note, c.loan.note])).toLowerCase().includes(kw)) continue;
      const secs = CARD_F.sec ? [CARD_F.sec] : ['deposit', 'withdrawal', 'loan'];
      let rowsHtml = '', shown = 0;
      for (const sec of secs) {
        const o = c[sec] || {};
        const srcs = (o.sources || []).filter(s => !CARD_F.src || srcType(s.url).t === CARD_F.src);
        if (CARD_F.src && !srcs.length) continue;
        shown++;
        const latest = (o.sources || []).map(s => s.date).filter(Boolean).sort().pop() || '';
        const one = clip((o.note || '').split(/[。；]/)[0] || '政策稳定，暂无公开变化', 64);
        const src0 = (srcs[0] || (o.sources || [])[0]) || {};
        rowsHtml += `<div class="cc-row">
          <div class="cc-ic i-${sec === 'deposit' ? 'dep' : sec === 'withdrawal' ? 'wit' : 'loan'}">${SEC_NAME[sec]}</div>
          <div class="cc-bd">
            <div class="one" title="${esc(o.note || '')}">【${SEC_NAME[sec]}】${esc(one)}</div>
            <div class="mt">${latest ? `<span>生效/发布 ${latest}</span>` : ''}${src0.url ? `<span class="badge ${srcType(src0.url).c}">${srcType(src0.url).t}</span><a href="${esc(src0.url)}" target="_blank" rel="noopener">原文 ↗</a>` : '<span style="color:var(--mute)">待补来源</span>'}${(o.sources || []).length > 1 ? `<span style="color:var(--mute)">+${o.sources.length - 1} 条来源</span>` : ''}</div>
          </div>
        </div>`;
      }
      if (!shown) continue;
      cnt++;
      cards.push(`<div class="city-card">
        <div class="cc-h"><span class="nm">${c.city}</span><span class="pv">${c.province} · 更新 ${c.last_updated || '—'}</span>
          <span class="links">${c.official_site ? `<a class="mini-btn" href="${esc(c.official_site)}" target="_blank" rel="noopener">官网 ↗</a>` : ''}<button class="mini-btn" data-city="${c.city}" onclick="gotoBranch('${c.city}')">分行视图</button></span></div>
        ${rowsHtml}</div>`);
    }
    $('#cf-cnt').textContent = `匹配 ${cnt} 城`;
    grid.innerHTML = cards.join('') || '<div class="empty">无匹配城市，请调整筛选条件</div>';
  };
  draw();
  $('#cf-kw').oninput = e => { CARD_F.kw = e.target.value; draw(); };
  $('#cf-sec').onchange = e => { CARD_F.sec = e.target.value; draw(); };
  $('#cf-src').onchange = e => { CARD_F.src = e.target.value; draw(); };
  $('#cf-prov').onchange = e => { CARD_F.prov = e.target.value; draw(); };
}
/* ---- 全国政策总览（缴存/提取/贷款三模块） ---- */
let OV_KW = '';
let OV_CITY = '';
let OV_SEC = '';  // ''=全部 deposit/withdrawal/loan
// 运行数据同比展示模式：'pct'=同比% / 'diff'=较2024增减值（二选一，localStorage 持久化）
let OV_CMP = 'pct';
try { const _m = localStorage.getItem('ov_cmp'); if (_m === 'pct' || _m === 'diff') OV_CMP = _m; } catch (e) { }
function pick(text, kws, len) {
  text = String(text || '');
  for (const k of kws) {
    const i = text.indexOf(k);
    if (i >= 0) return clip(text.slice(Math.max(0, i - 12), i + (len || 42)), len ? len + 14 : 56);
  }
  return '';
}
/* 缓缴期限提炼：把 max_period 长文本提炼为 ≤1年 / ≤2年 / ≤12个月 / ≤N个月 / 待核实 */
function deferPeriod(mp) {
  const t = String(mp || '').trim();
  if (!t) return { short: '待核实', full: '' };
  const unclear = /未检索到|未明确|未见明文|未注明|未单列|未在检索结果中明确/.test(t) && !/不超过|不得超过|最长/.test(t);
  if (unclear) return { short: '待核实', full: t };
  if (/两年|24\s*个?月|不得超过2年|不超过2年|最长.{0,4}2年/.test(t)) return { short: '≤2年', full: t };
  if (/12\s*个月/.test(t) && !/12\s*个?月31日|至.{0,8}12\s*月/.test(t)) return { short: '≤12个月', full: t };
  if (/一年|1\s*年|一个住房公积金(结算)?年度|一个公积金年度|按缴存年度申请/.test(t)) return { short: '≤1年', full: t };
  const m = t.match(/(\d+)\s*个?月/);
  if (m && !/\d{4}\s*年/.test(t.slice(0, t.indexOf(m[0])))) return { short: `≤${m[1]}个月`, full: t };
  if (/半年|6\s*个?月/.test(t) && !/2022年6月/.test(t)) return { short: '≤6个月', full: t };
  return { short: '待核实', full: t };
}
function srcBadges(srcs) {
  if (!srcs || !srcs.length) return '<span style="color:var(--mute)">待补</span>';
  return srcs.slice(0, 2).map(s => `<a class="badge ${srcType(s.url).c}" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.title)}">${srcType(s.url).t} ↗</a>`).join(' ') + (srcs.length > 2 ? `<span style="color:var(--mute);font-size:11px">+${srcs.length - 2}</span>` : '');
}
/* ---- 运行数据同比展示模式切换（同比% / 增减值 二选一） ---- */
function setOvCmp(m) {
  OV_CMP = m;
  try { localStorage.setItem('ov_cmp', m); } catch (e) { }
  renderTables();
}
/* ---- 运行数据一键导出（CSV，含合计行，Excel 可直接打开） ---- */
function exportOvData() {
  const sec = $('#ov-sec-data');
  const rows = (sec && sec._rows) || [];
  if (!rows.length) { toast('暂无可导出的运行数据'); return; }
  const num = o => (o && o.value != null) ? o.value : '';
  const diff = (c, p) => (c && c.value != null && p && p.value != null) ? Math.round((c.value - p.value) * 100) / 100 : '';
  // 同比增幅(%)：以 2025 与 2024 年报绝对值自行计算，保留 1 位小数
  const pctOf = (c, p) => (c && c.value != null && p && p.value != null && p.value)
    ? (Math.round((c.value - p.value) / p.value * 1000) / 10) : '';
  const pctRaw = (c, p) => (c && c.value != null && p && p.value) ? (Math.round((c - p) / p * 1000) / 10) : '';
  const H = ['城市', '省份', '新开户单位(家)', '实缴单位(万家)', '实缴单位同比', '新开户职工(万人)', '实缴职工(万人)',
    '缴存额2025(亿元)', '缴存额同比', '提取额2025(亿元)', '提取额同比(%)', '提取额较2024增减(亿元)',
    '发放贷款2025(亿元)', '发放贷款同比(%)', '发放贷款较2024增减(亿元)', '资金存款2025(亿元)', '资金存款较2024', '2025年报链接', '2024年报链接'];
  const lines = [H];
  let sum = null;
  for (const x of rows) {
    const s = x.stats_2025 || {}, s24 = x.stats_2024 || {}, chg = x.fund_deposit_change || {};
    lines.push([x.city, x.province, num(s.new_units), num(s.active_units), (s.active_units || {}).yoy || '',
      num(s.new_employees), num(s.active_employees), num(s.deposit_amount), (s.deposit_amount || {}).yoy || '',
      num(s.withdraw_amount), pctOf(s.withdraw_amount, s24.withdraw_amount), diff(s.withdraw_amount, s24.withdraw_amount),
      num(s.loan_issued), pctOf(s.loan_issued, s24.loan_issued), diff(s.loan_issued, s24.loan_issued),
      num(s.fund_deposit_balance), chg.text || '',
      (x.report_2025 || {}).url || '', (x.report_2024 || {}).url || '']);
  }
  // 合计行
  const K = ['new_units', 'active_units', 'new_employees', 'active_employees', 'deposit_amount', 'withdraw_amount', 'loan_issued', 'fund_deposit_balance'];
  const t = {}, t24 = {};
  for (const k of K) { let a = 0; for (const x of rows) { const o = (x.stats_2025 || {})[k]; if (o && o.value != null) a += o.value; } t[k] = Math.round(a * 100) / 100; }
  for (const k of ['withdraw_amount', 'loan_issued']) { let a = 0, b = 0; for (const x of rows) { const c = (x.stats_2025 || {})[k] || {}, p = (x.stats_2024 || {})[k] || {}; if (c.value != null && p.value != null) { a += c.value; b += p.value; } } t24[k] = [Math.round(a * 100) / 100, Math.round(b * 100) / 100]; }
  { let a = 0, b = 0; for (const x of rows) { const c = (x.stats_2025 || {}).fund_deposit_balance || {}, p = (x.stats_2024 || {}).fund_deposit_balance || {}; if (c.value != null && p.value != null) { a += c.value; b += p.value; } } t24.fund = [Math.round(a * 100) / 100, Math.round(b * 100) / 100]; }
  const dW = t24.withdraw_amount, dL = t24.loan_issued, dF = t24.fund;
  lines.push(['合计(' + rows.length + '城)', '', t.new_units, t.active_units, '', t.new_employees, t.active_employees,
    t.deposit_amount, '', t.withdraw_amount, pctRaw(dW[0], dW[1]), dW[0] || dW[1] ? Math.round((dW[0] - dW[1]) * 100) / 100 : '',
    t.loan_issued, pctRaw(dL[0], dL[1]), dL[0] || dL[1] ? Math.round((dL[0] - dL[1]) * 100) / 100 : '',
    t.fund_deposit_balance, (dF[0] || dF[1]) ? ((dF[0] - dF[1]) >= 0 ? '增加' : '减少') + Math.abs(Math.round((dF[0] - dF[1]) * 100) / 100) + '亿元' : '', '', '']);
  const csv = '﻿' + lines.map(r => r.map(v => { const s = String(v == null ? '' : v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }).join(',')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  a.download = `公积金运行数据_${rows.length}城_2025年报_${today()}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  toast(`已导出 ${rows.length} 城运行数据（含合计）`);
}
function mxFeatCell(city, f, k, label) {
  /** 矩阵同款特征单元格（地区分类矩阵的数据与样式）：mx-cell 色块 + 悬停明细弹层 + 点击直达政策原文 */
  const ft = (f || {})[k] || { st: 'u' };
  return `<td class="mx-cell${ft.url ? ' has-src' : ''}" data-city="${esc(city)}" data-dim="${k}" data-label="${esc(label)}"><span class="st st-${ft.st}">${ST_TXT[ft.st]}</span></td>`;
}
/* ---- 全国性法规详情卡（住房公积金管理条例等，来自数据库 national_regulations 字段） ---- */
function natRegCardHtml() {
  const regs = (DB && DB.national_regulations && DB.national_regulations.regulations) || [];
  if (!regs.length) return '';
  return regs.map(rg => {
    const kcs = (rg.key_changes || []).map(k =>
      `<div class="reg-kc"><span class="reg-cat">${esc(k.category)}</span><span>${esc(k.change)}</span></div>`).join('');
    const impacts = (rg.impact_on_cities || []).map(i => `<li>${esc(i)}</li>`).join('');
    const watch = (rg.watch_items || []).map(w => `<span class="reg-watch">${esc(w)}</span>`).join('');
    const srcs = (rg.sources || []).map(s =>
      `<a class="badge ${srcType(s.url).c}" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.title)}">${esc(s.type || '来源')} ↗</a>`).join(' ');
    return `<div class="reg-card fold">
      <div class="reg-h">
        <span class="reg-tt">📜 ${esc(rg.title)}</span>
        ${rg.document_no ? `<span class="reg-no">${esc(rg.document_no)}</span>` : ''}
        ${rg.effective_date ? `<span class="reg-eff">⏰ ${rg.effective_date} 起施行</span>` : ''}
        <span style="flex:1"></span>
        <span class="reg-toggle" onclick="this.closest('.reg-card').classList.toggle('fold')">展开 / 收起 ▾</span>
      </div>
      <div class="reg-meta">签署 ${rg.sign_date || '—'} ｜ 公布 ${rg.publish_date || '—'} ｜ 施行 <b>${rg.effective_date || '—'}</b> ｜ ${esc(rg.revision || '')} ｜ 效力级别：${esc(rg.level || '全国性行政法规')}</div>
      <div class="reg-body">
        <div class="reg-sub">本次修订 ${(rg.key_changes || []).length} 大要点</div>
        <div class="reg-grid">${kcs}</div>
        ${impacts ? `<div class="reg-sub">对各地政策的影响</div><ul class="reg-imp">${impacts}</ul>` : ''}
        ${watch ? `<div class="reg-sub">后续关注</div><div>${watch}</div>` : ''}
        <div class="reg-srcs">${srcs}</div>
      </div>
    </div>`;
  }).join('');
}
function renderTables() {
  const el = $('#hq-tables');
  el.innerHTML = `<div class="panel">
    <h3>🌐 全国政策及数据总览 · 各地现行政策与年度运行数据横向对照 <span class="badge b-city">${CITIES.length} 城</span></h3>
    <div class="h-sub">按缴存 / 提取 / 贷款 / 运行数据四模块横向对照各地差异点；点击城市名进入分行视图，「依据」列徽章直达官方原文；数值「待核实」表示官方未公开，以备注与原文为准</div>
    ${natRegCardHtml()}
    <div class="filters" style="row-gap:8px">
      <div class="seg" id="ov-seg" style="display:flex;background:#fff;border:1px solid var(--line);border-radius:20px;overflow:hidden">
        <button data-s="" class="${OV_SEC===''?'on':''}" style="border:none;background:${OV_SEC===''?'var(--blue)':'none'};color:${OV_SEC===''?'#fff':'var(--sub)'};padding:7px 14px;font-size:12.5px;font-weight:600">全部模块</button>
        <button data-s="deposit" style="border:none;background:${OV_SEC==='deposit'?'var(--dep)':'none'};color:${OV_SEC==='deposit'?'#fff':'var(--sub)'};padding:7px 14px;font-size:12.5px;font-weight:600">① 缴存</button>
        <button data-s="withdrawal" style="border:none;background:${OV_SEC==='withdrawal'?'var(--wit)':'none'};color:${OV_SEC==='withdrawal'?'#fff':'var(--sub)'};padding:7px 14px;font-size:12.5px;font-weight:600">② 提取</button>
        <button data-s="loan" style="border:none;background:${OV_SEC==='loan'?'var(--loan)':'none'};color:${OV_SEC==='loan'?'#fff':'var(--sub)'};padding:7px 14px;font-size:12.5px;font-weight:600">③ 贷款</button>
        <button data-s="data" style="border:none;background:${OV_SEC==='data'?'#0e9594':'none'};color:${OV_SEC==='data'?'#fff':'var(--sub)'};padding:7px 14px;font-size:12.5px;font-weight:600">④ 运行数据</button>
      </div>
      <select id="ov-city" style="min-width:130px"><option value="">🏙️ 全部城市</option>${[...new Set(CITIES.map(c => c.province))].sort().map(p => `<optgroup label="${p}">${CITIES.filter(c => c.province === p).map(c => `<option value="${c.city}" ${OV_CITY===c.city?'selected':''}>${c.city}</option>`).join('')}</optgroup>`).join('')}</select>
      <input type="text" id="ov-kw" placeholder="关键词（如「绿色建筑」「月冲」）" value="${esc(OV_KW)}" style="min-width:200px">
      <span style="font-size:12px;color:var(--sub)" id="ov-cnt"></span>
      <span style="flex:1"></span>
      <span style="font-size:12px;color:var(--mute)">差异点：缴存看「比例+基数」｜提取看「用途+月冲/年提+额度」｜贷款看「额度+套数+上浮+共享」｜运行数据看「年报统计」</span>
    </div>
    <div id="ov-body"></div>
  </div>`;
  const draw = () => {
    const kw = OV_KW.trim();
    let rows = CITIES;
    if (OV_CITY) rows = rows.filter(c => c.city === OV_CITY);
    if (kw) rows = rows.filter(c => (c.city + c.province + JSON.stringify(c)).includes(kw));
    $('#ov-cnt').textContent = (kw || OV_CITY) ? `匹配 ${rows.length} 城` : `共 ${rows.length} 城`;
    let html = '';
    /* ======== ① 缴存表 ======== */
    html += `<div id="ov-sec-deposit"><h4 style="margin:14px 0 8px;font-size:14.5px;color:var(--dep)">① 缴存 · 各地现行政策</h4>
    <div class="tbl-wrap" style="margin-bottom:18px"><table class="tb"><thead><tr>
      <th>城市</th><th>单位+个人比例</th><th>灵活就业比例</th><th>基数上限</th><th>基数下限</th><th>允许缓缴年限</th><th>依据</th>
    </tr></thead><tbody>`;
    let lastProv = '';
    for (const c of rows) {
      if (c.province !== lastProv) { lastProv = c.province; html += `<tr class="prov-row"><td colspan="7">${esc(c.province)}</td></tr>`; }
      const d = c.deposit || {};
      // 灵活就业比例：优先从 ratio 提取（如"灵活就业人员10%-24%"），再从 note 找
      let flex = '';
      const rm = ((d.ratio || '') + '；' + (d.note || '')).match(/灵活就业[^；;。]*/);
      if (rm) flex = clip(rm[0], 48);
      // 允许缓缴年限：来自 deferral 结构化字段（v1.3.1+）
      const df2 = c.deferral || {};
      const dp = deferPeriod(df2.max_period);
      const dCell = df2.supported === false
        ? '<span style="color:var(--risk)">不支持</span>'
        : `<span class="badge ${dp.short === '待核实' ? 'b-src' : 'b-dep'}" title="期限：${esc(dp.full || '待核实')}${df2.legal_basis ? '&#10;依据：' + esc(clip(df2.legal_basis, 160)) : ''}">${dp.short}</span>`;
      html += `<tr><td class="city" onclick="gotoBranch('${c.city}')">${c.city}</td>
        <td>${esc(d.ratio || '待核实')}</td><td><div class="cl">${esc(flex)}</div></td>
        <td class="num">${d.base_upper ? fmtNum(d.base_upper) + ' 元' : '待核实'}</td>
        <td class="num">${d.base_lower ? fmtNum(d.base_lower) + ' 元' : '待核实'}</td>
        <td>${dCell}</td>
        <td>${srcBadges(d.sources)}</td></tr>`;
    }
    html += '</tbody></table></div></div>';
    /* ======== ② 提取表 ======== */
    html += `<div id="ov-sec-withdrawal"><h4 style="margin:14px 0 8px;font-size:14.5px;color:var(--wit)">② 提取 · 各地现行政策</h4>
    <div class="tbl-wrap" style="margin-bottom:18px"><table class="tb"><thead><tr>
      <th>城市</th><th>主要提取情形（用途）</th><th>租房月上限</th><th>多孩租房上浮</th><th>首付直付</th><th>依据</th>
    </tr></thead><tbody>`;
    lastProv = '';
    for (const c of rows) {
      if (c.province !== lastProv) { lastProv = c.province; html += `<tr class="prov-row"><td colspan="6">${esc(c.province)}</td></tr>`; }
      const w = c.withdrawal || {}; const f = FEAT[c.city] || {};
      const multi = pick((w.rent_limit || '') + ' ' + (w.note || ''), ['多子女', '多孩', '二孩', '三孩'], 46) || '待核实';
      html += `<tr><td class="city" onclick="gotoBranch('${c.city}')">${c.city}</td>
        <td><div class="cl" title="${esc((w.conditions || []).join('；'))}">${esc(clip((w.conditions || []).join('、'), 90))}</div></td>
        <td><div class="cl" title="${esc(w.rent_limit || '')}">${esc(clip(w.rent_limit, 60))}</div></td>
        <td><div class="cl">${esc(multi)}</div></td>
        ${mxFeatCell(c.city, f, 'first_pay', '首付直付')}
        <td>${srcBadges(w.sources)}</td></tr>`;
    }
    html += '</tbody></table></div></div>';
    /* ======== ③ 贷款表 ======== */
    html += `<div id="ov-sec-loan"><h4 style="margin:14px 0 8px;font-size:14.5px;color:var(--loan)">③ 贷款 · 各地现行政策</h4>
    <div class="tbl-wrap"><table class="tb"><thead><tr>
      <th>城市</th><th>单职工最高贷额</th><th>双职工最高贷额</th><th>首套/二套利率</th><th>余额倍数</th><th>绿色建筑上浮</th><th>二孩上浮</th><th>依据</th>
    </tr></thead><tbody>`;
    lastProv = '';
    for (const c of rows) {
      if (c.province !== lastProv) { lastProv = c.province; html += `<tr class="prov-row"><td colspan="8">${esc(c.province)}</td></tr>`; }
      const l = c.loan || {}; const f = FEAT[c.city] || {};
      const lText = [l.conditions, l.note, l.max_single, l.max_family].filter(Boolean).join(' ');
      const mult = pick(lText, ['倍', '余额'], 60) || '待核实';
      const amtTip = v => esc((v || '') + (l.note ? ' ｜ 备注：' + l.note : ''));
      html += `<tr><td class="city" onclick="gotoBranch('${c.city}')">${c.city}</td>
        <td><div class="cl" title="${amtTip(l.max_single)}">${esc(clip(l.max_single, 60))}</div></td>
        <td><div class="cl" title="${amtTip(l.max_family)}">${esc(clip(l.max_family, 60))}</div></td>
        <td><div class="cl">首套 ${esc(l.rate_first || '—')}<br>二套 ${esc(l.rate_second || '—')}</div></td>
        <td><div class="cl" title="${esc(l.conditions || '')}">${esc(mult)}</div></td>
        ${mxFeatCell(c.city, f, 'green', '绿色建筑上浮')}${mxFeatCell(c.city, f, 'kid2', '二孩家庭上浮')}
        <td>${srcBadges(l.sources)}</td></tr>`;
    }
    html += '</tbody></table></div></div>';
    /* ======== ④ 运行数据表（各市 2025 年报统计，来自 annual_reports 年报库） ======== */
    const ARC = (DB.annual_reports && DB.annual_reports.cities) || [];
    const rowSet = new Set(rows.map(c => c.city));
    // 海南省为省级统一管理机构（全省仅1个独立法人机构，无市级年报），与海口/三亚同组单列一行省级数据；海口/三亚保持放空
    const includeHN = rowSet.has('海口') || rowSet.has('三亚');
    let arRows = ARC.filter(x => rowSet.has(x.city) || (includeHN && x.city === '海南省'));
    if (kw) arRows = arRows.filter(x => (x.city + x.province + (x.note || '')).includes(kw));
    const av = (o, unit) => (o && o.value != null) ? `${fmtNum(o.value)} <small style="color:var(--mute)">${unit || o.unit || ''}</small>` : '<span style="color:var(--mute)">—</span>';
    const yoy = o => (o && o.yoy) ? ` <span class="yoy ${String(o.yoy).startsWith('-') ? 'yoy-dn' : 'yoy-up'}">${String(o.yoy).startsWith('-') ? '▼' : '▲'}${esc(String(o.yoy).replace(/^[+\-]/, ''))}</span>` : '';
    // 与上年度比较值：按 OV_CMP 二选一展示「同比%」或「较2024增减值」（均以 2025 与 2024 年报绝对值为口径自行计算，悬停可见两年绝对值）
    const cmp = (cur, prev) => {
      const c = cur && cur.value, p = prev && prev.value;
      if (c == null || p == null || !p) return '';
      const d = Math.round((c - p) * 100) / 100;
      const pct = Math.round((c - p) / p * 1000) / 10;
      if (Math.abs(d) < 0.005) return ' <span class="yoy" style="color:var(--mute)">— 持平</span>';
      const cls = d < 0 ? 'yoy-dn' : 'yoy-up';
      const tip = `较2024年报：上年 ${fmtNum(p)} 亿元 → 本年 ${fmtNum(c)} 亿元`;
      if (OV_CMP === 'diff') return ` <span class="yoy ${cls}" title="${tip}">${d < 0 ? '▼' : '▲'} ${fmtNum(Math.abs(d))}亿元</span>`;
      return ` <span class="yoy ${cls}" title="${tip}">${d < 0 ? '▼' : '▲'} ${Math.abs(pct)}%</span>`;
    };
    // 数据加总（与导出共用）：2025 各指标合计 + 2024 可比口径合计
    const ovTotals = rows2 => {
      const t = {};
      for (const k of ['new_units', 'active_units', 'new_employees', 'active_employees', 'deposit_amount', 'withdraw_amount', 'loan_issued', 'fund_deposit_balance']) {
        let s = 0, n = 0;
        for (const x of rows2) { const o = (x.stats_2025 || {})[k]; if (o && o.value != null) { s += o.value; n++; } }
        t[k] = { s: Math.round(s * 100) / 100, n };
      }
      for (const k of ['withdraw_amount', 'loan_issued', 'fund_deposit_balance']) {
        let a = 0, b = 0, n = 0;
        for (const x of rows2) {
          const c = (x.stats_2025 || {})[k] || {}, p = (x.stats_2024 || {})[k] || {};
          if (c.value != null && p.value != null) { a += c.value; b += p.value; n++; }
        }
        t[k + '_24'] = { s: Math.round(b * 100) / 100, n, paired: Math.round(a * 100) / 100 };
      }
      return t;
    };
    html += `<div id="ov-sec-data"><h4 style="margin:14px 0 8px;font-size:14.5px;color:#0e9594">④ 运行数据 · 各市 2025 年度运行统计 <span class="badge b-nat">年报库</span> <button onclick="exportOvData()" style="margin-left:8px;border:1px solid #0e9594;background:#0e9594;color:#fff;border-radius:16px;padding:4px 14px;font-size:12px;font-weight:600;cursor:pointer;vertical-align:2px">⬇ 一键导出</button><span style="display:inline-flex;margin-left:8px;vertical-align:2px;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#fff"><span style="font-size:12px;color:var(--mute);padding:4px 6px 4px 10px;background:#fff">提取额、贷款额同比展示</span><button onclick="setOvCmp('pct')" style="border:none;background:${OV_CMP==='pct'?'#0e9594':'none'};color:${OV_CMP==='pct'?'#fff':'var(--sub)'};padding:4px 12px;font-size:12px;font-weight:600;cursor:pointer">同比%</button><button onclick="setOvCmp('diff')" style="border:none;background:${OV_CMP==='diff'?'#0e9594':'none'};color:${OV_CMP==='diff'?'#fff':'var(--sub)'};padding:4px 12px;font-size:12px;font-weight:600;cursor:pointer">增减值</button></span></h4>
    <div class="h-sub" style="margin:-2px 0 8px">来源：各市《住房公积金 2025 年年度报告》；资金存款为公积金中心存款余额（变化量较 2024 年报）；提取额 / 发放贷款的同比变化可按上表头右侧按钮在「同比%（▲/▼X%）」与「增减值（▲/▼X亿元）」间切换（二选一，▲红涨 ▼绿跌，悬停可查看两年绝对值），均以 2025 与 2024 年报绝对值口径自行计算；「—」为未披露</div>
    <div class="tbl-wrap"><table class="tb"><thead>
      <tr class="grp">
        <th rowspan="2" class="g-plain">城市</th>
        <th colspan="5" class="g-dep">缴存</th>
        <th class="g-wit">提取</th>
        <th class="g-loan">贷款</th>
        <th colspan="2" class="g-fund">资金存款</th>
        <th rowspan="2" class="g-plain">年报原文</th>
      </tr>
      <tr>
        <th>新开户单位</th><th>实缴单位</th><th>新开户职工</th><th>实缴职工</th><th>缴存额</th>
        <th>提取额(2025)</th><th>发放贷款(2025)</th><th>资金存款(2025)</th><th>存款较2024</th>
      </tr>
    </thead><tbody>`;
    lastProv = '';
    for (const x of arRows) {
      if (x.province !== lastProv) { lastProv = x.province; html += `<tr class="prov-row"><td colspan="11">${esc(x.province)}</td></tr>`; }
      const s = x.stats_2025 || {};
      const s24 = x.stats_2024 || {};
      const chg = x.fund_deposit_change;
      const cityCell = x.city === '海南省'
        ? `<td class="city" style="cursor:default">${x.city}<div style="font-size:10.5px;font-weight:400;color:var(--mute);line-height:1.5;margin-top:2px">全省共设1个独立法人机构即海南省住房公积金管理局，无独立设置的分支机构，仅提供全省数据</div></td>`
        : `<td class="city" onclick="gotoBranch('${x.city}')">${x.city}</td>`;
      html += `<tr>${cityCell}
        <td class="num">${av(s.new_units, '家')}</td>
        <td class="num">${av(s.active_units, '万家')}${yoy(s.active_units)}</td>
        <td class="num">${av(s.new_employees, '万人')}</td>
        <td class="num">${av(s.active_employees, '万人')}</td>
        <td class="num">${av(s.deposit_amount, '亿元')}${yoy(s.deposit_amount)}</td>
        <td class="num">${av(s.withdraw_amount, '亿元')}${cmp(s.withdraw_amount, s24.withdraw_amount)}</td>
        <td class="num">${av(s.loan_issued, '亿元')}${cmp(s.loan_issued, s24.loan_issued)}</td>
        <td class="num">${av(s.fund_deposit_balance, '亿元')}</td>
        <td>${chg && chg.text ? `<span class="yoy ${chg.direction === '减少' ? 'yoy-dn' : 'yoy-up'}">${chg.direction === '减少' ? '▼' : '▲'} ${esc(chg.text.replace(/^(增加|减少)/, ''))}</span>` : '<span style="color:var(--mute)">—</span>'}</td>
        <td style="white-space:nowrap">${x.report_2025 && x.report_2025.url ? `<a class="badge b-dep" href="${esc(x.report_2025.url)}" target="_blank" rel="noopener" title="${esc(x.report_2025.title)}">2025年报 ↗</a>` : ''}${x.report_2024 && x.report_2024.url ? ` <a class="badge b-src" href="${esc(x.report_2024.url)}" target="_blank" rel="noopener" title="${esc(x.report_2024.title)}">2024 ↗</a>` : ''}</td></tr>`;
    }
    /* ======== 数据加总行（合计当前筛选范围内各城规模） ======== */
    const T = ovTotals(arRows);
    const avN = (v, unit, n) => (v != null && n) ? `${fmtNum(v)} <small style="color:var(--mute)">${unit}</small>` : '<span style="color:var(--mute)">—</span>';
    const cmpN = (c, p, n) => {
      if (!n || !p) return '';
      const d = Math.round((c - p) * 100) / 100;
      const pct = Math.round((c - p) / p * 1000) / 10;
      if (Math.abs(d) < 0.005) return ' <span class="yoy" style="color:var(--mute)">— 持平</span>';
      const cls = d < 0 ? 'yoy-dn' : 'yoy-up';
      const tip = `${n} 城可比口径合计：2024年 ${fmtNum(p)} 亿元 → 2025年 ${fmtNum(c)} 亿元`;
      if (OV_CMP === 'diff') return ` <span class="yoy ${cls}" title="${tip}">${d < 0 ? '▼' : '▲'} ${fmtNum(Math.abs(d))}亿元</span>`;
      return ` <span class="yoy ${cls}" title="${tip}">${d < 0 ? '▼' : '▲'} ${Math.abs(pct)}%</span>`;
    };
    html += `<tr class="sum-row"><td class="city" style="cursor:default">📊 合计 <small style="font-weight:400;color:var(--mute)">${arRows.length} 行</small></td>
      <td class="num">${avN(T.new_units.s, '家', T.new_units.n)}</td>
      <td class="num">${avN(T.active_units.s, '万家', T.active_units.n)}</td>
      <td class="num">${avN(T.new_employees.s, '万人', T.new_employees.n)}</td>
      <td class="num">${avN(T.active_employees.s, '万人', T.active_employees.n)}</td>
      <td class="num">${avN(T.deposit_amount.s, '亿元', T.deposit_amount.n)}</td>
      <td class="num">${avN(T.withdraw_amount.s, '亿元', T.withdraw_amount.n)}${cmpN(T.withdraw_amount_24.paired, T.withdraw_amount_24.s, T.withdraw_amount_24.n)}</td>
      <td class="num">${avN(T.loan_issued.s, '亿元', T.loan_issued.n)}${cmpN(T.loan_issued_24.paired, T.loan_issued_24.s, T.loan_issued_24.n)}</td>
      <td class="num">${avN(T.fund_deposit_balance.s, '亿元', T.fund_deposit_balance.n)}</td>
      <td>${cmpN(T.fund_deposit_balance_24.paired, T.fund_deposit_balance_24.s, T.fund_deposit_balance_24.n) || '<span style="color:var(--mute)">—</span>'}</td>
      <td></td></tr>`;
    html += '</tbody></table></div></div>';
    $('#ov-body').innerHTML = html;
    $('#ov-sec-data')._rows = arRows;
    // 模块显隐
    for (const sec of ['deposit', 'withdrawal', 'loan', 'data']) {
      const box = $('#ov-sec-' + sec);
      if (box) box.style.display = (!OV_SEC || OV_SEC === sec) ? '' : 'none';
    }
  };
  draw();
  $('#ov-kw').oninput = e => { OV_KW = e.target.value; draw(); };
  $('#ov-city').onchange = e => { OV_CITY = e.target.value; draw(); };
  $$('#ov-seg button').forEach(b => b.onclick = () => {
    OV_SEC = b.dataset.s;
    renderTables();
    // 切换后滚动到对应模块
    if (OV_SEC) { const box = $('#ov-sec-' + OV_SEC); if (box) box.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  });
  $('#ov-kw').onkeydown = e => {
    if (e.key === 'Enter') {
      const kw = OV_KW.trim();
      const hit = CITIES.find(c => c.city === kw) || CITIES.find(c => c.city.includes(kw));
      if (hit) {
        // 定位滚动到该行
        const tds = $$('#ov-body td.city');
        const td = tds.find(t => t.textContent === hit.city);
        if (td) { td.scrollIntoView({ behavior: 'smooth', block: 'center' }); td.style.background = '#fff3cd'; setTimeout(() => td.style.background = '', 2200); }
      }
    }
  };
}

/* ---- 地区分类矩阵 ---- */
function renderMatrix() {
  const el = $('#hq-matrix');
  el.innerHTML = `<div class="panel">
    <h3>地区政策特征分类 <span class="badge b-city">矩阵可视化</span></h3>
    <div class="h-sub">数据源：政策分类矩阵（提取12维/贷款9维/缴存2维结构化记录）· 悬停色块查看政策明细与官方依据 · 点击色块跳转政策原文 · 点击城市名查看该市完整画像</div>
    <div class="filters">
      <div class="seg"><button data-dim="all" class="${MX_DIM === 'all' ? 'on' : ''}">全部</button><button data-dim="deposit" class="${MX_DIM === 'deposit' ? 'on' : ''}">缴存维度</button><button data-dim="withdrawal" class="${MX_DIM === 'withdrawal' ? 'on' : ''}">提取维度</button><button data-dim="loan" class="${MX_DIM === 'loan' ? 'on' : ''}">贷款维度</button></div>
      <input type="text" id="mx-kw" placeholder="搜索城市…" style="width:150px">
      <span style="flex:1"></span>
      <div class="legend">${stHtml('y')} 支持 ${stHtml('p')} 部分支持/有条件 ${stHtml('n')} 不支持 ${stHtml('u')} 待核实</div>
    </div>
    <div class="mx-wrap" id="mx-box"></div>
  </div>`;
  const draw = () => {
    const kw = ($('#mx-kw').value || '').trim();
    const keys = MX_DIM === 'all' ? [...F_KEYS.deposit, ...F_KEYS.withdrawal, ...F_KEYS.loan] : F_KEYS[MX_DIM];
    let rows = CITIES;
    if (kw) rows = rows.filter(c => (c.city + c.province).includes(kw));
    let html = '<table class="mx"><thead>';
    if (MX_DIM === 'all') {
      const groups = [['缴存政策', 'var(--dep)', F_KEYS.deposit], ['提取政策', 'var(--wit)', F_KEYS.withdrawal], ['贷款政策', 'var(--loan)', F_KEYS.loan]];
      html += `<tr class="grp"><th rowspan="2">城市</th>${groups.map(g => `<th colspan="${g[2].length}" style="background:${g[1]};color:#fff;text-align:center">${g[0]}</th>`).join('')}</tr>`;
      html += `<tr>${keys.map(k => `<th>${k[1]}</th>`).join('')}</tr></thead><tbody>`;
    } else {
      html += `<tr><th>城市</th>${keys.map(k => `<th>${k[1]}</th>`).join('')}</tr></thead><tbody>`;
    }
    let lastProv = '';
    for (const c of rows) {
      if (c.province !== lastProv) {
        lastProv = c.province;
        const n = rows.filter(x => x.province === c.province).length;
        html += `<tr class="prov"><td colspan="${keys.length + 1}">${esc(c.province)}（${n}）</td></tr>`;
      }
      const f = FEAT[c.city] || {};
      html += `<tr><td class="city" onclick="gotoBranch('${c.city}')">${c.city}</td>${keys.map(k => {
        const ft = f[k[0]] || { st: 'u' };
        return `<td class="mx-cell${ft.url ? ' has-src' : ''}" data-city="${esc(c.city)}" data-dim="${k[0]}" data-label="${esc(k[1])}"><span class="st st-${ft.st}">${ST_TXT[ft.st]}</span></td>`;
      }).join('')}</tr>`;
    }
    $('#mx-box').innerHTML = html + '</tbody></table>';
  };
  draw();
  $$('#hq-matrix [data-dim]').forEach(b => b.onclick = () => { MX_DIM = b.dataset.dim; renderMatrix(); });
  $('#mx-kw').oninput = draw;
}
/* ================= 分行公积金合作资格库（行内数据 2026-08） =================
 * [城市, 公积金中心名称, 归集, 提取, 委贷]（1=已具备，0=尚缺） */
const BANK_QUAL = [
['北京','北京住房公积金管理中心',1,1,1],
['雄安','雄安新区住房管理中心',0,0,1],
['深圳','深圳市住房公积金管理中心',1,1,1],
['惠州','惠州市住房公积金管理中心',0,0,1],
['珠海','珠海市住房公积金管理中心',1,1,1],
['上海','上海市公积金管理中心',0,0,1],
['广州','广州住房公积金管理中心',1,1,1],
['湛江','湛江市住房公积金管理中心',0,1,1],
['清远','清远市住房公积金管理中心',0,1,1],
['南京','江苏省省级机关住房公积金管理分中心',0,1,1],
['南京','南京住房公积金管理中心',0,0,1],
['常州','常州市住房公积金管理中心',0,1,1],
['扬州','扬州市住房公积金管理中心',1,1,1],
['盐城','盐城市住房公积金管理中心',0,1,1],
['泰州','泰州市住房公积金管理中心',0,1,1],
['连云港','连云港市住房公积金管理中心',1,1,1],
['徐州','徐州市住房公积金管理中心',1,1,1],
['镇江','镇江市住房公积金管理中心',1,1,1],
['武汉','武汉住房公积金管理中心',1,1,1],
['宜昌','宜昌住房公积金中心',1,1,1],
['襄阳','襄阳市住房公积金中心',1,1,1],
['黄石','黄石市住房公积金中心',1,1,0],
['十堰','十堰住房公积金中心',1,1,1],
['黄冈','黄冈住房公积金中心',1,1,0],
['孝感','孝感住房公积金中心',1,1,1],
['荆州','荆州住房公积金中心',1,1,0],
['重庆','重庆市住房公积金管理中心',0,0,1],
['西安','陕西省住房资金管理中心',1,1,1],
['西安','西安住房公积金管理中心',1,1,1],
['咸阳','咸阳市住房公积金管理中心',1,1,1],
['宝鸡','宝鸡市住房公积金管理中心',1,1,1],
['榆林','榆林市住房公积金管理中心',1,1,1],
['天津','天津市住房公积金管理中心',0,1,1],
['苏州','苏州市住房公积金管理中心',0,1,1],
['杭州','杭州省直单位住房公积金管理中心',0,0,1],
['杭州','杭州住房公积金管理中心',0,0,1],
['嘉兴','嘉兴市住房公积金管理服务中心',0,1,1],
['湖州','湖州市住房公积金管理中心',0,1,1],
['绍兴','绍兴市住房公积金管理中心',0,0,1],
['义乌','义乌市住房公积金管理中心',0,0,0],
['金华','金华市住房公积金管理中心',1,1,1],
['舟山','舟山市住房公积金管理中心',0,0,0],
['衢州','衢州市住房公积金中心',0,0,1],
['沈阳','辽宁省省直住房资金管理中心',0,0,0],
['沈阳','沈阳住房公积金管理中心',0,0,1],
['鞍山','鞍山市住房公积金管理中心',0,0,0],
['盘锦','盘锦市住房公积金管理中心',0,0,0],
['丹东','丹东市住房公积金管理中心',0,0,0],
['抚顺','抚顺市住房公积金管理中心',0,0,0],
['福州','福建省省直住房公积金管理中心',0,0,0],
['福州','福州市住房公积金管理中心',0,0,0],
['龙岩','龙岩市住房公积金管理中心',1,1,1],
['莆田','莆田市住房公积金管理中心',1,0,1],
['宁德','宁德市住房公积金管理中心',1,1,1],
['三明','三明市住房公积金管理中心',1,1,1],
['乌鲁木齐','乌鲁木齐住房公积金管理中心',1,1,1],
['哈尔滨','哈尔滨住房公积金管理中心省直分中心',0,0,0],
['哈尔滨','哈尔滨住房公积金管理中心',0,1,1],
['大庆','大庆市住房公积金管理中心',0,1,1],
['南昌','江西省住房保障和公积金管理中心',0,1,1],
['南昌','南昌住房公积金管理中心',0,1,1],
['赣州','赣州市住房公积金管理中心',1,1,1],
['九江','九江市住房公积金管理中心',0,1,1],
['上饶','上饶市住房公积金管理中心',1,1,1],
['景德镇','景德镇市住房公积金管理中心',1,1,1],
['兰州','甘肃省住房资金管理中心',0,1,1],
['兰州','兰州住房公积金管理中心',1,0,1],
['东莞','东莞市住房公积金管理中心',1,1,1],
['厦门','厦门市住房公积金中心',1,1,1],
['漳州','漳州市住房公积金中心',1,1,1],
['郑州','河南省省直机关住房资金管理中心',0,0,0],
['郑州','郑州住房公积金管理中心',1,1,1],
['洛阳','洛阳市住房公积金管理中心',1,1,1],
['安阳','安阳市住房公积金管理中心',1,1,1],
['许昌','许昌市住房公积金管理中心',1,1,1],
['南阳','南阳市住房公积金管理中心',1,1,0],
['西宁','西宁住房公积金管理中心省直分中心',0,1,1],
['西宁','西宁住房公积金管理中心',0,1,1],
['合肥','安徽省省直住房公积金管理分中心',0,0,1],
['合肥','合肥市住房公积金管理中心',1,0,1],
['芜湖','芜湖市住房公积金管理中心',1,1,1],
['安庆','安庆市住房公积金管理中心',1,1,1],
['马鞍山','马鞍山市住房公积金管理中心',1,1,1],
['淮北','淮北市住房公积金管理中心',0,0,1],
['淮南','淮南市住房公积金管理中心',0,1,1],
['六安','六安市住房公积金中心',1,1,1],
['佛山','佛山市住房公积金管理中心',0,1,1],
['中山','中山市住房公积金管理中心',1,1,1],
['江门','江门市住房公积金管理中心',0,0,1],
['宁波','宁波市住房公积金管理中心',0,1,1],
['宁波','宁波市住房公积金镇海分中心',0,1,1],
['台州','台州市住房公积金管理中心',1,1,1],
['太原','山西省省级机关住房资金管理中心',0,0,1],
['太原','太原市住房公积金管理中心',0,0,1],
['晋城','晋城市住房公积金管理中心(晋城市住房资金管理中心)',1,1,1],
['吕梁','吕梁市住房公积金管理中心',0,0,0],
['朔州','朔州市住房公积金管理中心',0,0,0],
['昆明','云南省省级职工住房资金管理中心',0,0,1],
['昆明','昆明市住房公积金管理中心',0,0,1],
['丽江','丽江市住房公积金管理中心',1,1,1],
['曲靖','曲靖市住房公积金管理中心',1,1,1],
['红河','红河哈尼族彝族自治州住房公积金管理中心',1,1,1],
['青岛','青岛市住房公积金管理中心(青岛市住房资金管理中心)',1,1,1],
['潍坊','潍坊市住房公积金管理中心',1,1,1],
['日照','日照市住房公积金管理中心',1,1,0],
['成都','四川省省级住房公积金管理中心',0,0,0],
['成都','成都住房公积金管理中心',1,1,1],
['绵阳','绵阳市住房公积金服务中心',1,1,1],
['泸州','泸州市住房公积金管理中心',1,1,1],
['乐山','乐山市住房公积金管理中心',0,0,0],
['呼和浩特','内蒙古自治区住房资金中心',1,1,1],
['呼和浩特','呼和浩特市住房公积金管理中心',0,0,0],
['包头','包头市住房公积金中心',0,0,0],
['呼伦贝尔','呼伦贝尔市住房公积金管理中心',0,0,0],
['鄂尔多斯','鄂尔多斯市住房公积金管理中心',0,0,0],
['无锡','无锡市住房公积金管理中心',0,1,1],
['南通','南通市住房公积金管理中心',1,1,1],
['长春','吉林省直住房公积金管理分中心',0,0,0],
['长春','长春市住房公积金管理中心',0,0,1],
['通化','通化市住房公积金管理中心',0,0,0],
['吉林','吉林市住房公积金管理中心',0,0,0],
['泉州','泉州市住房公积金管理中心',1,1,1],
['南宁','南宁住房公积金管理中心区直分中心',1,1,1],
['南宁','南宁住房公积金管理中心',0,0,1],
['柳州','柳州市住房公积金管理中心',1,1,1],
['温州','温州市住房公积金管理中心',0,0,1],
['贵阳','贵州省住房资金管理中心',0,0,0],
['贵阳','贵阳市住房公积金管理中心',1,1,1],
['遵义','遵义市住房公积金管理中心',0,1,1],
['六盘水','六盘水市住房公积金管理中心',1,1,1],
['银川','宁夏回族自治区住房资金管理中心(银川住房公积金管理中心区直分中心)',0,0,0],
['银川','银川住房公积金管理中心',1,1,1],
['石家庄','河北省直住房资金管理中心',0,0,0],
['石家庄','石家庄住房公积金管理中心',1,1,1],
['廊坊','廊坊市住房公积金管理中心',0,0,1],
['海口','海南省住房公积金管理局',0,0,1],
['唐山','唐山市住房公积金管理中心',1,1,1],
['唐山','唐山市住房公积金管理中心开滦分中心',0,1,1],
['烟台','烟台市住房公积金管理中心',1,1,1],
['威海','威海市住房公积金管理中心',0,0,0],
['济南','济南住房公积金中心',1,1,1],
['东营','东营市住房公积金管理中心',1,1,1],
['东营','胜利油田住房公积金管理中心',1,1,1],
['临沂','临沂市住房公积金管理中心',0,0,0],
['滨州','滨州市住房公积金管理中心',1,0,1],
['济宁','济宁市住房公积金管理中心',1,0,1],
['淄博','淄博市住房公积金管理中心',1,1,1],
['聊城','聊城市住房公积金管理中心',1,0,0],
['大连','大连市住房公积金管理中心',1,1,1],
['营口','营口市住房公积金管理中心',1,1,1],
['锦州','锦州市住房公积金管理中心',1,1,1],
['长沙','湖南省直住房资金管理中心',0,1,1],
['长沙','长沙住房公积金管理中心',0,1,1],
['株洲','株洲市住房公积金管理中心',0,0,0],
['衡阳','衡阳市住房公积金管理中心',1,1,1],
['娄底','娄底市住房公积金管理中心',1,1,1],
['湘潭','湘潭市住房公积金管理中心',0,0,0]
];
const QUAL_DIM = [['gj','归集资格',2],['tq','提取资格',3],['wd','委贷资格',4]];
const QUAL_GAIN = {
  gj: '归集资格对应单位开户、缴存归集、基数调整等源头业务，是对公结算与代发工资的入口。建议分行梳理未合作缴存单位名单，以「归集服务+对公账户+代发」打包方案向中心争取承办资格。',
  tq: '提取资格对应提取审核支付、租房/购房提取线上化等高频个人业务，是沉淀个人客户与支付结算流量的关键。建议以线上化提取通道建设、反欺诈核验能力为抓手营销承办资格。',
  wd: '委贷资格对应公积金贷款发放、回收与贷后管理，直接带来按揭客户与贷款联动收益。建议以贷款发放系统对接、贷后催收协作、组合贷一体化服务为切入争取承办资格。'
};
/* 领导变动数据：来自 GitHub 数据库 research/personnel-changes.json（与政策库同仓，自动更新）。
   加载链路与政策库一致：jsDelivr@最新SHA → GitHub Raw → jsDelivr@main → 本地镜像 research/personnel-changes.json。
   全部不可用时保持空对象，领导变动卡片自动不显示（不出卡）。 */
let LEADER_CHANGES = {};  // city -> 变动记录数组（每条含 _group: confirmed|sup）
let LEADER_META = {};     // 数据集元信息（generated 等）
let LEADER_READY = false;   // 加载流程完成标志（成功或最终失败均置位）
function convertLeaderChanges(j) {
  const out = {};
  for (const it of (j.confirmed_changes || [])) if (it && it.city) (out[it.city] = out[it.city] || []).push(Object.assign({}, it, { _group: 'confirmed' }));
  for (const it of (j.supervising_city_leaders || [])) if (it && it.city) (out[it.city] = out[it.city] || []).push(Object.assign({}, it, { _group: 'sup' }));
  return out;
}
/* 变动类型推断：new=新任 removed=免职/处分 pending=任前公示 mid=中层干部 staff=非领导职务 sup=分管市领导 */
function leaderAct(g) {
  if (g._group === 'sup') return 'sup';
  const c = g.category || '', t = g.content || '';
  if (/拟任|任前公示/.test(t)) return 'pending';
  if (c === '中层干部') return 'mid';
  if (c === '非领导职务') return 'staff';
  if (/开除党籍|双开/.test(t) || (/免/.test(t) && !/任/.test(t))) return 'removed';
  return 'new';
}
async function loadLeaderChanges() {
  const bases = [];
  try {
    const ctrl = new AbortController();
    const tm = setTimeout(() => ctrl.abort(), 5000);
    const r = await fetch('https://api.github.com/repos/polarsta/gjj-policy-watch/commits/main', { signal: ctrl.signal, cache: 'no-store' });
    clearTimeout(tm);
    if (r.ok) { const j = await r.json(); if (j && j.sha) bases.push(`https://cdn.jsdelivr.net/gh/polarsta/gjj-policy-watch@${j.sha}/research/personnel-changes.json`); }
  } catch (e) { /* SHA 解析失败走常规源 */ }
  bases.push(
    'https://raw.githubusercontent.com/polarsta/gjj-policy-watch/main/research/personnel-changes.json',
    'https://cdn.jsdelivr.net/gh/polarsta/gjj-policy-watch@main/research/personnel-changes.json',
    'research/personnel-changes.json'
  );
  for (const u of bases) {
    try {
      const ctrl = new AbortController();
      const tm = setTimeout(() => ctrl.abort(), 12000);
      const r = await fetch(u + '?_t=' + Date.now(), { signal: ctrl.signal, cache: 'no-store' });
      clearTimeout(tm);
      if (!r.ok) continue;
      const j = await r.json();
      if (!j || !Array.isArray(j.confirmed_changes)) continue;
      LEADER_META = j.meta || {};
      LEADER_CHANGES = convertLeaderChanges(j);
      console.log('领导变动数据已加载：', u, '，覆盖', Object.keys(LEADER_CHANGES).length, '城');
      LEADER_READY = true;
      return;
    } catch (e) { console.warn('领导变动数据源失败:', u, e.message); }
  }
  console.warn('领导变动数据不可用，相关卡片不显示');
  LEADER_READY = true;
}
/* ================= 分行视图 ================= */
function cityByName(n) { return CITIES.find(c => c.city === n); }
function gotoBranch(city) {
  $$('.nav button').forEach(b => b.classList.toggle('on', b.dataset.view === 'branch'));
  $$('.view').forEach(v => v.classList.remove('on'));
  $('#view-branch').classList.add('on');
  $('#br-city').value = city;
  renderBranch(city);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
function polItem(o) {
  const st = srcType(o.url);
  const sig = o.signal || signalOf(o.text + o.title);
  return `<div class="pol-item">
    <div class="hd2"><span class="badge ${o.nat ? 'b-nat' : 'b-city'}">${o.nat ? '全国' : esc(o.city)}</span>${o.sec ? `<span class="badge ${SEC_CLS[o.sec]}">${SEC_NAME[o.sec]}</span>` : ''}<span class="badge ${sig.c}">${sig.t}</span><span class="badge ${st.c}">${st.t}</span></div>
    <div class="tt">${esc(clip(o.title, 60))}</div>
    <div class="ds">${esc(clip(o.text, 130))}</div>
    <div class="mt">${o.date ? `<span>发布 ${o.date}</span>` : ''}${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">官方原文 ↗</a>` : ''}</div>
  </div>`;
}
function renderBranch(city) {
  const c = cityByName(city);
  if (!c) { $('#br-local').innerHTML = '<div class="empty">未找到该城市，请从 134 个监测城市中选择</div>'; return; }
  BR_CITY = city;
  const since = BR_RANGE ? daysAgo(BR_RANGE) : null;
  const inRange = d => !since || (d && d >= since);
  // 当地政策
  let items = [];
  for (const sec of ['deposit', 'withdrawal', 'loan']) {
    const o = c[sec] || {};
    const srcs = (o.sources || []).filter(s => inRange(s.date));
    if (!srcs.length && since) continue;
    items.push({
      city: c.city, sec, title: `${c.city}·${SEC_NAME[sec]}政策`, text: o.note || (o.conditions || []).join('；') || '',
      date: (srcs[0] || (o.sources || [])[0] || {}).date || c.last_updated, url: (srcs[0] || (o.sources || [])[0] || {}).url || '',
      _t: (o.sources || []).map(s => s.date).filter(Boolean).sort().pop() || ''
    });
    for (const s of srcs.slice(1)) items.push({ city: c.city, sec, title: s.title, text: o.note || '', date: s.date, url: s.url, _t: s.date });
  }
  items.sort((a, b) => (b._t || '').localeCompare(a._t || ''));
  $('#br-pol-cnt').textContent = `共 ${items.length} 条`;
  $('#br-local').innerHTML = items.map(polItem).join('') || '<div class="empty">所选时间范围内无更新，可切换「全部」查看现行政策</div>';
  // 上位政策
  $('#br-nat').innerHTML = NAT_POLICIES.map(p => polItem({ nat: true, sec: '', title: p.title, text: p.desc, date: p.date, url: p.url, signal: { t: '中性', c: 'b-mid', k: 'mid' } })).join('');
  // 营销建议（资格驱动：目标中心 → 资格攻坚/经营深化 → 当年重点 → 人事关注 → 灵活就业）
  const f = FEAT[city] || {};
  const quals = BANK_QUAL.filter(q => q[0] === city || (city === '北京' && q[0] === '雄安'));
  const cards = [];
  let qualHtml = '';
  if (quals.length) {
    // ① 目标公积金中心（两家及以上全部列出，不展示具体资格情况）
    qualHtml = `<div style="font-size:12.5px;color:var(--sub);margin-bottom:8px">🎯 目标公积金中心（${quals.length} 家）：<b>${quals.map(q => esc(q[1])).join('</b>、<b>')}</b></div>`;
    // ② 逐中心生成优先建议（仅针对缺失资格；三项齐备的中心不出卡）
    for (const q of quals) {
      const miss = QUAL_DIM.filter(d => !q[d[2]]);
      if (miss.length) {
        cards.push({
          t: `🥇 资格攻坚｜${q[1]}：优先营销获取「${miss.map(d => d[1]).join('、')}」`,
          d: `该行目前在${q[1]}尚缺 ${miss.map(d => d[1]).join('、')}。${miss.map(d => QUAL_GAIN[d[0]]).join(' ')} 建议分行排出资格申报时间表，由行领导带队对接中心，争取年内实现资格突破。`
        });
      }
    }
    if (quals.every(q => QUAL_DIM.every(d => q[d[2]]))) {
      cards.push({ t: '✅ 资格齐备｜三类资格均已具备', d: quals.map(q => q[1]).join('、') + ' 的归集、提取、委贷三类资格均已具备。建议分行持续做好三类业务的经营推动：扩大归集单位与缴存职工覆盖以做大客户服务数量，以缴存归集带动资金引流，积极对接公积金存款竞争性存放以获取存款，做优单位代扣与个人提取还款结算服务，巩固合作份额。' });
    }
  }
  // ③ 中心当年重点任务 → 银行服务建议（挖掘本市 2026 年政策动态）
  let yearItems = items;
  if (city === '北京') {
    const xa = cityByName('雄安');
    if (xa) for (const sec of ['deposit', 'withdrawal', 'loan']) {
      const o = xa[sec] || {};
      yearItems = yearItems.concat((o.sources || []).map(src => ({ sec, title: '雄安·' + src.title, text: o.note || '', date: src.date, url: src.url })));
    }
  }
  const year26 = yearItems.filter(o => (o.date || '') >= '2026-01-01');
  const seen = new Set();
  const addTask = (t, d, ev) => { if (seen.has(t)) return; seen.add(t); cards.push({ t, d, ev }); };
  for (const o of year26) {
    if (seen.size >= 2) break;
    const txt = (o.title || '') + ' ' + (o.text || '');
    if (/灵活就业/.test(txt)) addTask('🛠️ 服务当年重点｜灵活就业缴存扩面', '中心年内推进灵活就业人员缴存。建议分行提供批量开户、缴存代扣、线上签约一体化服务包，协助中心完成扩面考核指标，同步承接新市民客群的账户、社保卡与消费金融需求。', o);
    else if (/商转公/.test(txt)) addTask('🛠️ 服务当年重点｜商转公承接', '中心推进商转公业务。建议分行主动开放贷款数据接口配合联网核验，做好存量按揭客户转贷承接与防流失预案。', o);
    else if (/缓缴|纾困/.test(txt)) addTask('🛠️ 服务当年重点｜企业纾困协作', '中心落实缓缴纾困政策。建议分行为困难企业提供缓缴申请辅导、缓缴期间工资代发保障与后续授信衔接方案，协助中心稳企业稳缴存。', o);
    else if (/数字化|线上|一网通办|数据/.test(txt)) addTask('🛠️ 服务当年重点｜数字化共建', '中心推进数字化服务升级。建议分行输出科技能力，参与中心线上服务渠道、数据共享与风控共建，以科技合作带动业务合作。', o);
    else if (/额度|上浮/.test(txt) && o.sec === 'loan') addTask('🛠️ 服务当年重点｜贷款新政落地配套', '中心年内调整贷款额度政策。建议分行同步完成受理系统与额度测算工具升级，协助中心开展新政宣讲进楼盘、进单位活动，以联合服务巩固委贷合作。', o);
    else if (/提取|租房/.test(txt) && o.sec === 'withdrawal') addTask('🛠️ 服务当年重点｜提取服务线上化', '中心年内优化提取政策。建议分行提供提取线上化审核、反欺诈核验与支付清算支持，配合中心提升提取服务体验，沉淀个人客户结算流量。', o);
  }
  // ④ 领导变动触达（数据来自 GitHub 数据库 research/personnel-changes.json，随仓库更新自动获取；无变动城市不出卡）
  const ACT_T = {
    new: p => `👥 领导变动｜${p.persons} 新任（${p.date}）`,
    removed: p => `👥 领导变动｜${p.persons} 免职（${p.date}）`,
    pending: p => `👥 任前公示｜${p.persons}（${p.date}）`,
    mid: p => `👥 中层调整｜${p.persons}（${p.date}）`,
    staff: p => `👥 人事信息｜${p.persons}（${p.date}）`,
    sup: p => `🏛️ 分管市领导调整｜${p.persons}（${p.date}）`
  };
  const ACT_ADV = {
    new: () => '建议分行（属地机构）领导两周内上门拜访新到任领导，介绍我行公积金归集、提取、委贷服务能力与年度合作计划，交流重点服务方案，在新任期起点加深合作关系。',
    removed: () => '建议分行关注该中心领导班子补位安排，保持与中心其他班子成员的常态化业务沟通衔接，确保合作平稳过渡；待补位人选明确后两周内上门拜访，衔接年度合作计划。',
    pending: () => '目前处于任前公示阶段。建议分行关注正式任命进展，待其到任后两周内上门拜访，介绍我行公积金服务能力与年度合作计划，抢占合作先机。',
    mid: () => '属中层干部调整。建议分行安排属地支行负责人走访新任干部，围绕分中心、管理部辖区业务深化日常对接与服务响应。',
    staff: () => '属非领导职务调整，触达价值有限，供分行参考，无需专项拜访。',
    sup: p => `分管市领导对公积金政策方向与管委会决策有重要影响。建议分行通过公积金管委会会议、政府条线汇报等渠道对接${p.persons}，汇报我行公积金金融服务方案与年度合作成果，争取政策与业务支持。`
  };
  for (const g of (LEADER_CHANGES[city] || [])) {
    const act = leaderAct(g);
    const p = { persons: (g.persons || []).join('、') || '相关人员', date: g.date || '' };
    cards.push({
      t: ACT_T[act](p),
      d: (g.content || '') + ' ' + ACT_ADV[act](p) + `（信息来自公开渠道检索，更新至 ${LEADER_META.generated || '—'}，请以官方信息为准）`,
      ev: { title: g.source_name || '公开信息', date: g.date, url: g.url }
    });
  }
  // ⑤ 灵活就业缴存 → 经营补充建议
  if (f.flex_dep && f.flex_dep.st === 'y') {
    cards.push({ t: '🚶 灵活就业缴存｜分行经营补充建议', d: '当地已开展灵活就业人员缴存（' + clip(f.flex_dep.txt || '自愿缴存', 60).replace(/[）)]+$/, '') + '）。建议分行：面向外卖、网约车、个体工商户等群体开展缴存代办与政策宣讲，配套灵活就业专属账户、缴存代扣与小额经营贷联动，将扩面流量转化为个人存贷客群。' });
  }
  if (!cards.length) cards.push({ t: '📡 持续监测', d: '该市政策特征尚在采集中。建议保持对当地公积金中心官网监测，政策更新后系统将自动提示营销切入点。' });
  $('#br-advice').innerHTML =
    (quals.length ? '' : `<div style="font-size:12px;color:var(--risk);margin-bottom:6px">⚠ 该行在该市的公积金合作资格数据未收录，以下建议按政策特征生成，资格情况请人工核对。</div>`) +
    qualHtml +
    cards.slice(0, 8).map(a => `<div class="adv-card"><div class="tt">${a.t}</div><div class="ds">${a.d}${a.ev ? `<div style="margin-top:4px;font-size:11px;color:var(--mute)">依据：${esc(clip(a.ev.title, 50))}${a.ev.date ? '（' + a.ev.date + '）' : ''}${a.ev.url ? ` <a href="${esc(a.ev.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div>` : ''}</div></div>`).join('');
  // 资格矩阵（紧凑表格：分组表头 + 每列一个资格，状态图标一行展示）
  const qGroups = [['缴存', 'var(--dep)', F_KEYS.deposit], ['提取', 'var(--wit)', F_KEYS.withdrawal], ['贷款', 'var(--loan)', F_KEYS.loan]];
  $('#br-feat').innerHTML = `<div class="tbl-wrap"><table class="tb qmx-tb"><thead>
    <tr class="grp">${qGroups.map(g => `<th colspan="${g[2].length}" style="background:${g[1]};color:#fff;text-align:center;letter-spacing:2px">${g[0]}</th>`).join('')}</tr>
    <tr>${qGroups.map(g => g[2].map(k => `<th>${k[1]}</th>`).join('')).join('')}</tr>
    </thead><tbody><tr>${qGroups.map(g => g[2].map(k => { const ft = f[k[0]] || { st: 'u' }; return `<td class="mx-cell${ft.url ? ' has-src' : ''}" data-city="${esc(city)}" data-dim="${k[0]}" data-label="${esc(k[1])}" style="text-align:center"><span class="st st-${ft.st}">${ST_TXT[ft.st]}</span></td>`; }).join('')).join('')}</tr></tbody></table></div>`;
  // 商机追踪：相似城市 + 案例
  const sims = similarCities(city, 10);
  $('#br-case-sub').textContent = `案例库共 ${CASES.length} 个真实案例 · 优先展示本市及政策特征相似地区`;
  $('#br-sim').innerHTML = sims.length ? `<div style="margin-bottom:8px;font-size:12.5px;color:var(--sub)">与当地政策特征相似的城市（可对标学习）：</div>` + sims.map(s => `<span class="chip" onclick="gotoBranch('${s.name}')">${s.name} · 相似${s.score}项</span>`).join('') : '';
  const cityCases = CASES.filter(x => x.city === city);
  const provCases = CASES.filter(x => x.city !== city && x.province === c.province);
  const simSet = new Set(sims.map(s => s.name));
  const simCases = CASES.filter(x => x.city !== city && x.province !== c.province && simSet.has(x.city));
  const other = CASES.filter(x => !cityCases.includes(x) && !provCases.includes(x) && !simCases.includes(x));
  const list = [...cityCases, ...provCases, ...simCases, ...other].slice(0, 6);
  $('#br-cases').innerHTML = list.map(caseCard).join('') || '<div class="empty">案例库暂无相关案例</div>';
}
function caseCard(cs) {
  const s0 = (cs.sources || [])[0] || {};
  return `<div class="case-card">
    <div class="hd2" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:4px"><span class="badge b-city">${esc(cs.city)}</span><span class="badge b-nat">${esc(cs.theme)}</span>${cs.confidence === 'high' ? '<span class="badge b-good">高置信</span>' : ''}</div>
    <div class="tt">${esc(cs.title)}</div>
    <div class="ds"><b>参与方：</b>${esc((cs.parties || []).join('、'))}</div>
    <div class="ds">${esc(clip(cs.summary, 150))}</div>
    <div class="pr"><b>可借鉴做法：</b><ol>${(cs.practices || []).slice(0, 4).map(p => `<li>${esc(p)}</li>`).join('')}</ol></div>
    <div class="mt"><span>📍 ${esc(cs.province || '')}</span><span>📅 ${cs.date || '—'}</span>${s0.url ? `<a href="${esc(s0.url)}" target="_blank" rel="noopener" title="${esc(s0.title)}">真实来源 ↗</a>` : ''}</div>
  </div>`;
}
function similarCities(city, topN) {
  const f0 = FEAT[city]; if (!f0) return [];
  const keys = Object.keys(f0).filter(k => f0[k].st === 'y');
  const out = [];
  for (const c of CITIES) {
    if (c.city === city) continue;
    const f = FEAT[c.city]; if (!f) continue;
    let score = 0;
    for (const k of keys) if (f[k] && f[k].st === 'y') score++;
    if (score >= 2) out.push({ name: c.city, score });
  }
  out.sort((a, b) => b.score - a.score);
  return out.slice(0, topN);
}
/* ---- 一键导出城市简报 ---- */
function exportSheet() {
  if (!BR_CITY) { toast('请先选择城市'); return; }
  const c = cityByName(BR_CITY); if (!c) return;
  const f = FEAT[BR_CITY] || {};
  const d = c.deposit || {}, w = c.withdrawal || {}, l = c.loan || {};
  const cases = CASES.filter(x => x.city === BR_CITY || x.province === c.province).slice(0, 3);
  const rows = (obj, ks) => ks.map(k => `<tr><th style="width:22%">${k[0]}</th><td>${k[1](obj)}</td></tr>`).join('');
  const srcL = o => (o.sources || []).map(s => `<li><a href="${esc(s.url)}">${esc(s.title)}</a>（${s.date || '—'}）</li>`).join('') || '<li>待补充</li>';
  $('#print-sheet').innerHTML = `
    <h1>${c.city} · 住房公积金政策一页简报</h1>
    <div class="p-sub">${c.province} ｜ 数据更新 ${c.last_updated || '—'} ｜ 生成 ${today()} ｜ 来源：gjj-policy-watch 数据库 v${DB.version}（GitHub 自动更新）｜ 公积金政策监控台</div>
    <h2>一、缴存政策</h2><table>${rows(d, [
      ['单位+个人比例', () => esc(d.ratio || '待核实')],
      ['基数上限 / 下限', () => `${d.base_upper ? fmtNum(d.base_upper) + ' 元' : '待核实'} / ${d.base_lower ? fmtNum(d.base_lower) + ' 元' : '待核实'}`],
      ['执行年度', () => esc(d.period || '待核实')],
      ['要点', () => esc(d.note || '—')]
    ])}</table>
    <h2>二、提取政策</h2><table>${rows(w, [
      ['主要情形', () => esc((w.conditions || []).join('、') || '待核实')],
      ['租房月上限', () => esc(w.rent_limit || '待核实')],
      ['要点', () => esc(w.note || '—')]
    ])}</table>
    <h2>三、贷款政策</h2><table>${rows(l, [
      ['单职工 / 双职工上限', () => `${esc(l.max_single || '待核实')} / ${esc(l.max_family || '待核实')}`],
      ['首套利率 / 首付', () => `${esc(l.rate_first || '—')} / ${esc(l.down_payment_first || '—')}`],
      ['二套利率 / 首付', () => `${esc(l.rate_second || '—')} / ${esc(l.down_payment_second || '—')}`],
      ['申请条件', () => esc(l.conditions || '待核实')],
      ['要点', () => esc(l.note || '—')]
    ])}</table>
    <h2>四、政策特征画像</h2><table><tr>${[...F_KEYS.withdrawal.slice(0, 6)].map(k => `<th>${k[1]}</th>`).join('')}</tr><tr>${[...F_KEYS.withdrawal.slice(0, 6)].map(k => `<td style="text-align:center">${ST_TXT[(f[k[0]] || { st: 'u' }).st]} ${ST_NAME[(f[k[0]] || { st: 'u' }).st]}</td>`).join('')}</tr>
    <tr>${[...F_KEYS.loan.slice(0, 6)].map(k => `<th>${k[1]}</th>`).join('')}</tr><tr>${[...F_KEYS.loan.slice(0, 6)].map(k => `<td style="text-align:center">${ST_TXT[(f[k[0]] || { st: 'u' }).st]} ${ST_NAME[(f[k[0]] || { st: 'u' }).st]}</td>`).join('')}</tr></table>
    ${cases.length ? `<h2>五、可对标商机案例</h2>${cases.map(cs => `<div class="p-sec"><b>${esc(cs.title)}</b>（${esc(cs.city)} · ${cs.date || '—'}）<br>${esc(clip(cs.summary, 120))}<br><b>可借鉴：</b>${esc((cs.practices || [])[0] || '—')}</div>`).join('')}` : ''}
    <h2>${cases.length ? '六' : '五'}、官方来源（可点击核验）</h2>
    <div class="p-sec"><b>缴存：</b><ul>${srcL(d)}</ul><b>提取：</b><ul>${srcL(w)}</ul><b>贷款：</b><ul>${srcL(l)}</ul>${c.official_site ? `<div>公积金中心官网：<a href="${esc(c.official_site)}">${esc(c.official_site)}</a></div>` : ''}</div>
    <div class="p-sub" style="margin-top:10px">⚠️ 本简报基于公开政策数据库自动生成，供客户经理拜访公积金中心参考；具体业务以当地公积金中心最新官方文件为准。</div>`;
  window.print();
}

/* ================= 全局搜索 ================= */
function doSuggest(kw) {
  const box = $('#suggest');
  kw = kw.trim();
  if (!kw || !CITIES.length) { box.classList.remove('on'); return; }
  const cityHits = CITIES.filter(c => (c.city + c.province).includes(kw)).slice(0, 6);
  const caseHits = CASES.filter(c => (c.title + c.city + c.theme).includes(kw)).slice(0, 4);
  if (!cityHits.length && !caseHits.length) { box.classList.remove('on'); return; }
  box.innerHTML =
    cityHits.map(c => `<div class="si" data-city="${c.city}"><span class="tag">城市</span><span>${c.city} · ${c.province}</span><span style="margin-left:auto;font-size:11px;color:var(--mute)">进入分行视图 →</span></div>`).join('') +
    caseHits.map(c => `<div class="si case" data-city="${c.city}"><span class="tag">案例</span><span>${esc(clip(c.title, 30))}</span></div>`).join('');
  box.classList.add('on');
  $$('.si', box).forEach(si => si.onclick = () => { box.classList.remove('on'); $('#q').value = ''; gotoBranch(si.dataset.city); });
}
/* ================= 事件与初始化 ================= */
function bindEvents() {
  // 主导航
  $$('.nav button').forEach(b => b.onclick = () => {
    $$('.nav button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    $$('.view').forEach(v => v.classList.remove('on'));
    $('#view-' + b.dataset.view).classList.add('on');
    if (b.dataset.view === 'tables' && !$('#hq-tables')._done) { renderTables(); $('#hq-tables')._done = 1; }
    if (b.dataset.view === 'matrix' && !$('#hq-matrix')._done) { renderMatrix(); $('#hq-matrix')._done = 1; }
    if (b.dataset.view === 'branch' && !BR_CITY) { const def = '深圳'; $('#br-city').value = def; renderBranch(def); }
  });
  // 总行子标签
  $$('#hq-tabs button').forEach(b => b.onclick = () => {
    $$('#hq-tabs button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    for (const t of ['news', 'cards']) $('#hq-' + t).style.display = t === b.dataset.tab ? '' : 'none';
    if (b.dataset.tab === 'cards' && !$('#hq-cards')._done) { renderCards(); $('#hq-cards')._done = 1; }
  });
  // 速览事件委托
  $('#hq-news').addEventListener('click', e => {
    const rg = e.target.closest('#hq-range button');
    if (rg) { HQ_RANGE = +rg.dataset.d; renderNews(); return; }
    const more = e.target.closest('.more-link');
    if (more) {
      const sec = more.dataset.sec;
      const rows = ($('#ch-cols')._rows || []).filter(r => r.sec === sec);
      const col = more.closest('.ch-col');
      more.remove();
      col.insertAdjacentHTML('beforeend', rows.slice(6).map(chItem).join(''));
      return;
    }
    if (e.target.closest('#btn-add-rec')) { $('#modal-mask').classList.add('on'); return; }
    if (e.target.closest('#btn-export-json')) {
      const payload = { exported_at: today(), source: 'gjj-policy-watch 本地记录', records: LOCAL_REC };
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
      a.download = `gjj_local_records_${today()}.json`; a.click();
      toast(`已导出 ${LOCAL_REC.length} 条本地记录`);
      return;
    }
    if (e.target.closest('#btn-clear-local')) {
      if (confirm('确定清空所有本地新增记录？')) { LOCAL_REC = []; saveLocal(); renderNews(); toast('本地记录已清空'); }
    }
  });
  // 新增记录弹窗
  $('#f-cancel').onclick = () => $('#modal-mask').classList.remove('on');
  $('#modal-mask').addEventListener('click', e => { if (e.target.id === 'modal-mask') $('#modal-mask').classList.remove('on'); });
  $('#f-save').onclick = () => {
    const title = $('#f-title').value.trim();
    if (!title) { toast('请填写标题'); return; }
    LOCAL_REC.push({
      city: $('#f-city').value.trim(), sec: $('#f-sec').value, title,
      note: $('#f-note').value.trim() || title, date: $('#f-date').value || today(), url: $('#f-url').value.trim()
    });
    saveLocal(); $('#modal-mask').classList.remove('on');
    ['f-city', 'f-title', 'f-note', 'f-date', 'f-url'].forEach(id => $('#' + id).value = '');
    renderNews(); toast('已保存到本地（localStorage）');
  };
  // 全局搜索
  const q = $('#q');
  q.addEventListener('input', () => doSuggest(q.value));
  q.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const kw = q.value.trim(); if (!kw) return;
    const hit = CITIES.find(c => c.city === kw) || CITIES.find(c => c.city.includes(kw));
    if (hit) { $('#suggest').classList.remove('on'); gotoBranch(hit.city); }
    else {
      // 无匹配城市：跳到全国政策总览并用关键词过滤
      OV_KW = kw;
      $$('.nav button').forEach(x => x.classList.remove('on'));
      const tbBtn = $$('.nav button').find(b => b.dataset.view === 'tables');
      if (tbBtn) tbBtn.classList.add('on');
      $$('.view').forEach(v => v.classList.remove('on'));
      $('#view-tables').classList.add('on');
      renderTables(); $('#hq-tables')._done = 1;
      toast('已在全国政策总览中筛选关键词');
    }
  });
  document.addEventListener('click', e => { if (!e.target.closest('.hd-search')) $('#suggest').classList.remove('on'); });
  // 联网检索
  $('#web-search').onclick = () => {
    const kw = $('#q').value.trim() || '公积金 政策 最新';
    window.open('https://www.baidu.com/s?wd=' + encodeURIComponent(kw + ' 公积金 政策'), '_blank');
  };
  // 分行事件
  $('#br-city').addEventListener('change', e => { const v = e.target.value.trim(); if (cityByName(v)) renderBranch(v); });
  $('#br-city').addEventListener('keydown', e => { if (e.key === 'Enter') { const v = e.target.value.trim(); const hit = cityByName(v) || CITIES.find(c => c.city.includes(v)); if (hit) { $('#br-city').value = hit.city; renderBranch(hit.city); } else toast('未找到该城市'); } });
  $$('#br-range button').forEach(b => b.onclick = () => { $$('#br-range button').forEach(x => x.classList.remove('on')); b.classList.add('on'); BR_RANGE = +b.dataset.d; if (BR_CITY) renderBranch(BR_CITY); });
  $('#br-export').onclick = exportSheet;
}
async function init() {
  loadLocal();
  try {
    DB = await loadDB();
  } catch (e) {
    $('#loading').style.display = 'none';
    $('#err').style.display = 'block';
    $('#err').innerHTML = `<div class="err-box">⚠️ <b>政策数据库连接失败</b><br>已尝试 jsDelivr CDN、GitHub Raw 与本地镜像均不可用（${esc(e.message)}）。<br>请检查网络后刷新；数据源仓库：<a href="${REPO_URL}" target="_blank">${REPO_URL}</a></div>`;
    return;
  }
  CITIES = canonicalCities(DB);
  CASES = (DB.case_library && DB.case_library.cases) || [];
  // v1.5.0 数据兼容：顶层 deferral 已并入 deposit.deferred_payment，为旧读取点提供别名
  for (const c of CITIES) { if (!c.deferral && c.deposit && c.deposit.deferred_payment) c.deferral = c.deposit.deferred_payment; }
  for (const c of CITIES) FEAT[c.city] = extractFeatures(c);
  NAT_POLICIES = mineNational(DB);
  $('#city-list').innerHTML = CITIES.map(c => `<option value="${c.city}">${c.province}</option>`).join('');
  renderStats(); renderNews(); bindEvents(); bindMatrixTips();
  await loadNegNews();
  await loadLeaderChanges();
  renderBoardTopbar(); bindBoardEvents(); renderBoard();
  $('#loading').style.display = 'none';
  $('#view-board').classList.add('on');
  $('#foot').innerHTML = `数据来源：<a href="${REPO_URL}" target="_blank">github.com/polarsta/gjj-policy-watch</a>（网页版数据，仓库更新后页面自动获取最新版）｜ 数据库版本 v${DB.version} · ${DB.generated_at} ｜ 当前经 ${CUR_SRC} 加载 ｜ 信息仅供内部参考，具体业务以当地公积金中心官方文件为准`;
}
document.addEventListener('DOMContentLoaded', init);

/* ================= 政策变化速览看板 V2 ================= */
let BOARD_RANGE = 30;
let BOARD_KW = '';
let NEG_NEWS = [];        // 负面舆情（快照+实时合并）
let NEG_LIVE = false;     // 实时抓取是否成功

/* ---- 负面分类（含后台 negative_news 数据集新版四大类） ---- */
const NEG_CATS = {
  '案件通报': 'rk-case', '骗提套取': 'rk-cheat', '违规查处': 'rk-viol',
  '风险警示': 'rk-warn', '黑中介': 'rk-mid', '风险提示': 'rk-warn',
  '骗提骗贷打击与通报': 'rk-cheat', '违纪违法与监管问责': 'rk-viol',
  '制度争议与负面舆情': 'rk-warn', '服务与运营负面事件': 'rk-case'
};
function negClassify(t) {
  if (/判|刑|起诉|犯罪|诈骗|落马|被查|处分|逮捕/.test(t)) return '案件通报';
  if (/骗提|套取|骗贷|骗取/.test(t)) return '骗提套取';
  if (/违规|处罚|通报|查处|整治|打击|违法/.test(t)) return '违规查处';
  if (/中介|代办|代缴/.test(t)) return '黑中介';
  if (/风险|警示|提醒|警惕|逾期/.test(t)) return '风险警示';
  return '风险提示';
}

/* ---- 加载负面舆情：优先仓库后台更新数据（negative_news/negative_news.json），本地快照兜底 ---- */
let NEG_META = null;      // 后台数据集 meta（generated_at 等）
function normalizeNeg(j) {
  const recs = Array.isArray(j) ? j : (j && Array.isArray(j.records) ? j.records : []);
  return recs.map(r => {
    if (r.source_url || r.severity) {  // 后台新版结构（meta+records）
      const url = r.source_url || '';
      let domain = '';
      try { domain = new URL(url).hostname; } catch (e) {}
      // 日期归一化：'2026-06-01（施行）'→'2026-06-01'；'2026（上半年）'→'2026-06-30'；'2026'（仅年份）→''（日期待确认）
      let date = '';
      const dateRaw = String(r.date || '');
      const m10 = dateRaw.match(/(20\d{2})-(\d{1,2})-(\d{1,2})/);
      if (m10) date = `${m10[1]}-${String(+m10[2]).padStart(2, '0')}-${String(+m10[3]).padStart(2, '0')}`;
      else if (/上半年/.test(dateRaw)) { const y = dateRaw.match(/(20\d{2})/); if (y) date = y[1] + '-06-30'; }
      else if (/下半年/.test(dateRaw)) { const y = dateRaw.match(/(20\d{2})/); if (y) date = y[1] + '-12-31'; }
      // 城市匹配：region 形如 '贵州·毕节' / '浙江·台州（玉环）' / '全国'
      let city = '';
      const region = String(r.region || '');
      for (const c of CITIES) { if (c.city.length >= 2 && region.includes(c.city)) { city = c.city; break; } }
      const sev = r.severity || '中';
      const heat = (sev === '高' ? 7 : sev === '低' ? 3 : 5) + (r.source_type === '政府网站' ? 1 : 0);
      return { title: r.title || '', url, domain, city, date, dateRaw, heat, category: r.category || '风险提示', summary: r.summary || '', srcName: r.source_name || '', severity: sev };
    }
    return r;  // 旧版快照结构原样透传
  }).filter(i => i.title);
}
async function loadNegNews() {
  const sources = [
    { name: 'jsDelivr CDN', url: 'https://cdn.jsdelivr.net/gh/polarsta/gjj-policy-watch@main/negative_news/negative_news.json' },
    { name: 'GitHub Raw', url: 'https://raw.githubusercontent.com/polarsta/gjj-policy-watch/main/negative_news/negative_news.json' },
    { name: '本地镜像', url: 'negative_news.json' }
  ];
  for (const src of sources) {
    try {
      const ctrl = new AbortController();
      const tm = setTimeout(() => ctrl.abort(), 15000);
      const r = await fetch(src.url + (src.url.includes('?') ? '&' : '?') + '_t=' + Date.now(), { signal: ctrl.signal, cache: 'no-store' });
      clearTimeout(tm);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      const items = normalizeNeg(j);
      if (!items.length) throw new Error('舆情数据为空');
      NEG_NEWS = items;
      NEG_META = (j && !Array.isArray(j) && j.meta) || null;
      const lbl = $('#risk-src-label');
      if (lbl) lbl.textContent = src.name === '本地镜像' ? '本地快照' : `后台更新 ${NEG_META && NEG_META.generated_at ? NEG_META.generated_at : ''}·${src.name}`;
      fetchLiveNeg();
      return;
    } catch (e) { console.warn('舆情源失败:', src.name, e.message); }
  }
  NEG_NEWS = NEG_NEWS || [];
  fetchLiveNeg();
}
/* ---- 实时抓取：经公共 CORS 代理抓 360 搜索（失败静默，保留快照） ---- */
async function fetchLiveNeg() {
  const queries = ['公积金 骗提 案件', '公积金 违规 通报', '公积金 风险 警示'];
  const proxies = [
    u => 'https://api.allorigins.win/raw?url=' + encodeURIComponent(u),
    u => 'https://corsproxy.io/?url=' + encodeURIComponent(u)
  ];
  const found = [];
  const seen = new Set(NEG_NEWS.map(i => i.url));
  for (const q of queries) {
    const target = 'https://www.so.com/s?q=' + encodeURIComponent(q);
    let html = null;
    for (const px of proxies) {
      try {
        const ctrl = new AbortController();
        const tm = setTimeout(() => ctrl.abort(), 12000);
        const r = await fetch(px(target), { signal: ctrl.signal });
        clearTimeout(tm);
        if (r.ok) { const t = await r.text(); if (t.includes('res-title')) { html = t; break; } }
      } catch (e) { /* 尝试下一代理 */ }
    }
    if (!html) continue;
    // 按 res-list 块解析（标题+真实链接+日期）
    const blocks = html.match(/<li class="res-list[^"]*"[\s\S]*?<\/li>/g) || [];
    for (const block of blocks) {
      const m = block.match(/data-mdurl="([^"]+)"[^>]*>([\s\S]*?)<\/a>/);
      if (!m) continue;
      const url = m[1];
      const title = m[2].replace(/<[^>]+>/g, '').trim();
      if (title.length < 8 || !url.startsWith('http') || seen.has(url)) continue;
      seen.add(url);
      // 日期：2025年6月5日 / 2025-06-05
      let date = '';
      let dm = block.match(/(20\d{2})年(\d{1,2})月(\d{1,2})日/);
      if (dm) date = `${dm[1]}-${String(+dm[2]).padStart(2,'0')}-${String(+dm[3]).padStart(2,'0')}`;
      else {
        dm = block.match(/(20\d{2})[-/](\d{1,2})[-/](\d{1,2})/);
        if (dm) date = `${dm[1]}-${String(+dm[2]).padStart(2,'0')}-${String(+dm[3]).padStart(2,'0')}`;
      }
      if (date > today()) date = '';
      let city = '';
      for (const c of CITIES) { if (title.includes(c.city)) { city = c.city; break; } }
      let domain = '';
      try { domain = new URL(url).hostname; } catch (e) {}
      const heat = 3 + (/gov\.cn|gjj\./.test(domain) ? 3 : /thepaper|qq\.com|sohu|sina|163\.com/.test(domain) ? 2 : 1) + (/判刑|通报|查处|曝光|严惩/.test(title) ? 1 : 0);
      found.push({ title, url, domain, city, date, heat, category: negClassify(title), live: true });
    }
  }
  if (found.length) {
    NEG_NEWS = [...found, ...NEG_NEWS];
    NEG_LIVE = true;
    const lbl = $('#risk-src-label');
    if (lbl) lbl.textContent = '实时+快照';
    renderBoardRisk();
  }
}

/* ---- 城市卡片数据：三板块各取范围内最新变化 ---- */
function cityModuleData(c, rangeDays) {
  const since = daysAgo(rangeDays);
  const rows = [];
  let latest = '';
  let hasAny = false;
  for (const sec of ['deposit', 'withdrawal', 'loan']) {
    const o = c[sec] || {};
    const srcs = (o.sources || []).filter(s => s.date && s.date >= since && s.date <= today())
      .sort((a, b) => b.date.localeCompare(a.date));
    if (srcs.length) {
      hasAny = true;
      const s0 = srcs[0];
      if (s0.date > latest) latest = s0.date;
      const note = (o.note || '').trim();
      rows.push({
        sec, date: s0.date, url: s0.url || '', srcType: srcType(s0.url || ''),
        text: clip(note || s0.title || '政策有更新', 120)
      });
    } else {
      rows.push({ sec, date: '', url: '', srcType: null, text: '' });
    }
  }
  return { city: c, rows, latest, hasAny };
}

/* ---- 全国政策模块数据 ---- */
function natModuleData(rangeDays) {
  // 时间精确度：与城市模块同一口径，仅保留所选时间跨度内的全国性政策
  const since = daysAgo(rangeDays == null ? 36500 : rangeDays);
  const items = (NAT_POLICIES || [])
    .filter(p => p.date && p.date >= since && p.date <= today())
    .sort((a, b) => b.date.localeCompare(a.date));
  const latest = items.length ? items[0].date : '';
  return { items, latest };
}

/* ---- 顶部统计条 ---- */
function renderBoardTopbar() {
  const totalSrc = CITIES.reduce((n, c) => n + allSources(c).length, 0);
  const monthSince = daysAgo(30);
  let monthCnt = 0;
  const monthCities = new Set();
  for (const c of CITIES) {
    for (const s of allSources(c)) {
      if (s.date && s.date >= monthSince && s.date <= today()) { monthCnt++; monthCities.add(c.city); }
    }
  }
  const natCnt = (NAT_POLICIES || []).length;
  $('#board-topbar').innerHTML = `
    <div class="stat"><div class="n">${totalSrc}<small> 条</small></div><div class="t">监测政策总数 · ${CITIES.length} 城</div></div>
    <div class="stat g"><div class="n">${monthCnt}<small> 条</small></div><div class="t">近30天更新政策</div></div>
    <div class="stat t"><div class="n">${monthCities.size}<small> 个</small></div><div class="t">近30天涉及城市</div></div>
    <div class="stat o"><div class="n">${natCnt}<small> 条</small></div><div class="t">全国性政策动态</div></div>
    <div class="stat r"><div class="n" id="tb-risk-cnt">${riskInRange().length}<small> 条</small></div><div class="t">负面风险舆情预警</div></div>`;
}

/* ---- 城市模块卡片 HTML ---- */
function cmodHtml(mod) {
  const c = mod.city;
  const rowsHtml = mod.rows.map(r => {
    const tagCls = r.sec === 'deposit' ? 'dep' : r.sec === 'withdrawal' ? 'wit' : 'loan';
    if (!r.date) {
      return `<div class="cmod-row"><div class="cmod-tag ${tagCls}">${SEC_NAME[r.sec]}</div>
        <div class="cmod-bd"><div class="txt none">近期暂无变动</div></div></div>`;
    }
    return `<div class="cmod-row"><div class="cmod-tag ${tagCls}">${SEC_NAME[r.sec]}</div>
      <div class="cmod-bd">
        <div class="txt">【${SEC_NAME[r.sec]}】${esc(r.text)}</div>
        <div class="mt"><span>生效 ${r.date}</span><span class="badge ${r.srcType.c}">${r.srcType.t}</span>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div>
      </div></div>`;
  }).join('');
  return `<div class="cmod">
    <div class="cmod-h"><span class="nm">${c.city}</span><span class="upd">近期更新</span>
      <span class="acts">${c.official_site ? `<a href="${esc(c.official_site)}" target="_blank" rel="noopener">官网 ↗</a>` : ''}<button class="full" onclick="gotoBranch('${c.city}')">完整政策</button></span></div>
    ${rowsHtml}</div>`;
}
/* ---- 全国政策模块卡片 HTML ---- */
function natModHtml(nat) {
  const rowsHtml = nat.items.slice(0, 4).map(p => {
    if (p.type === 'regulation' && p.reg) {
      const rg = p.reg;
      const kcs = (rg.key_changes || []).slice(0, 4).map(k =>
        `<div class="mt" style="line-height:1.5"><span class="badge" style="background:#6554c0;color:#fff">${esc(k.category)}</span> <span title="${esc(k.change)}">${esc(clip(k.change, 52))}</span></div>`).join('');
      return `<div class="cmod-row"><div class="cmod-tag" style="background:#6554c0">法规</div>
        <div class="cmod-bd">
          <div class="txt"><b>📜 ${esc(clip(p.title, 40))}</b><br><span style="color:var(--sub)">${esc(rg.document_no || '')}${rg.effective_date ? ` · <b style="color:var(--risk)">${rg.effective_date} 起施行</b>` : ''}</span></div>
          ${kcs}
          <div class="mt"><span>公布 ${p.date}</span>${(rg.sources || []).slice(0, 2).map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.title)}">${esc(s.type || '原文')} ↗</a>`).join('')}</div>
        </div></div>`;
    }
    return `<div class="cmod-row"><div class="cmod-tag" style="background:#6554c0">全国</div>
      <div class="cmod-bd">
        <div class="txt"><b>${esc(clip(p.title, 44))}</b><br>${esc(clip(p.desc, 76))}</div>
        <div class="mt"><span>${esc(p.org || '中央部委')}</span>${p.date ? `<span>· ${p.date}</span>` : ''}${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div>
      </div></div>`;
  }).join('');
  return `<div class="cmod nat">
    <div class="cmod-h"><span class="nm">🌐 全国 · 中央政策</span><span class="upd">置顶关注</span>
      <span class="acts"><a href="https://www.gov.cn" target="_blank" rel="noopener">国务院 ↗</a></span></div>
    ${rowsHtml || '<div class="cmod-row"><div class="cmod-bd"><div class="txt none">本时段暂无全国性新动态（所选时间范围内无全国政策更新，可切换更长时间跨度查看）</div></div></div>'}</div>`;
}

/* ---- 负面舆情渲染 ---- */
let RISK_SORT = 'heat';  // heat=按热度 time=按时间
/* 时间跨度过滤（顶部统计、摘要、右侧列表共用同一口径）：有日期的按日期过滤，无日期的保留 */
function riskInRange() {
  const since = daysAgo(BOARD_RANGE);
  return NEG_NEWS.filter(i => !i.date || (i.date >= since && i.date <= today()));
}
function renderBoardRisk() {
  const kw = BOARD_KW.trim();
  let list = riskInRange();
  // 城市搜索过滤
  if (kw) {
    const hit = CITIES.find(c => c.city.includes(kw));
    if (hit) list = list.filter(i => !i.city || i.city === hit.city || i.title.includes(kw));
    else list = list.filter(i => i.title.includes(kw));
  }
  // 排序
  if (RISK_SORT === 'time') {
    list = [...list].sort((a, b) => (b.date || '0000').localeCompare(a.date || '0000'));
  } else {
    list = [...list].sort((a, b) => (b.heat || 0) - (a.heat || 0) || (b.date || '').localeCompare(a.date || ''));
  }
  $('#board-risk-cnt').textContent = `${list.length} 条`;
  const tbCnt = $('#tb-risk-cnt');
  if (tbCnt && !kw) tbCnt.innerHTML = `${riskInRange().length}<small> 条</small>`;
  if (!list.length) {
    $('#board-risk').innerHTML = '<div class="board-empty">所选时间范围内暂无负面舆情<br><span style="font-size:11px">系统持续监测骗提/违规/案件类风险信号</span></div>';
    return;
  }
  $('#board-risk').innerHTML = list.slice(0, 40).map(i => {
    const cls = NEG_CATS[i.category] || 'rk-warn';
    const dateHtml = i.date ? `<span class="rk-date">${i.date}</span>` : `<span style="font-size:11px;color:var(--mute)">${esc(i.dateRaw || '日期待确认')}</span>`;
    const sevHtml = i.severity ? `<span class="rk-sev rk-sev-${i.severity}">${i.severity}风险</span>` : '';
    return `<div class="risk-item">
      <div class="rk-head"><span class="rk-cat ${cls}">${esc(i.category || '风险提示')}</span>${sevHtml}${i.city ? `<span class="rk-city">${esc(i.city)}</span>` : ''}${i.live ? '<span class="risk-live ok">实时</span>' : ''}${RISK_SORT === 'heat' && i.heat >= 7 ? '<span class="risk-live" style="background:#fde3e3;color:var(--risk)">🔥热</span>' : ''}</div>
      <div class="rk-title">${esc(clip(i.title, 68))}</div>
      ${i.summary ? `<div class="rk-sum">${esc(clip(i.summary, 92))}</div>` : ''}
      <div class="rk-foot">${dateHtml}<span>${esc(i.srcName || i.domain || '')}</span><a href="${esc(i.url)}" target="_blank" rel="noopener">查看 ↗</a></div>
    </div>`;
  }).join('');
}

/* ---- 主渲染 ---- */
function renderBoard() {
  const kw = BOARD_KW.trim().toLowerCase();
  let cities = CITIES;
  if (kw) cities = cities.filter(c => (c.city + c.province).toLowerCase().includes(kw));
  // 构建城市模块
  const mods = [];
  for (const c of cities) {
    const m = cityModuleData(c, BOARD_RANGE);
    if (m.hasAny) mods.push({ type: 'city', sortKey: m.latest, mod: m });
  }
  // 全国模块：按所选时间跨度过滤，且固定置顶（不参与日期混排）
  const nat = natModuleData(BOARD_RANGE);
  // 城市模块按最新生效时间倒序
  mods.sort((a, b) => b.sortKey.localeCompare(a.sortKey));
  // 统计
  const rangeName = { 1: '最近一天', 7: '一周', 30: '一个月', 90: '一个季度', 365: '一年' }[BOARD_RANGE] || '';
  const secCnt = { deposit: 0, withdrawal: 0, loan: 0 };
  mods.forEach(m => { if (m.type === 'city') m.mod.rows.forEach(r => { if (r.date) secCnt[r.sec]++; }); });
  $('#board-summary').innerHTML = `📊 <b>${rangeName}</b>：全国动态 <b>${nat.items.length}</b> 条（固定置顶），<b>${mods.filter(m => m.type === 'city').length}</b> 个城市有政策更新（缴存 ${secCnt.deposit} / 提取 ${secCnt.withdrawal} / 贷款 ${secCnt.loan}），负面舆情 <b>${riskInRange().length}</b> 条预警。${kw ? `当前筛选：「${BOARD_KW}」` : '城市政策按最新生效时间倒序。'}`;
  // 渲染模块（全国政策固定第一；搜索城市时不显示全国模块）
  $('#board-mod-cnt').textContent = `${mods.filter(m => m.type === 'city').length} 城`;
  const natHtml = kw ? '' : natModHtml(nat);
  const cityHtml = mods.map(m => cmodHtml(m.mod)).join('');
  $('#board-modules').innerHTML = (natHtml + cityHtml) || '<div class="board-empty">所选时间范围内无城市政策更新</div>';
  renderBoardRisk();
}

/* ---- 事件 ---- */
function bindBoardEvents() {
  $$('#board-range button').forEach(b => b.onclick = () => {
    $$('#board-range button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    BOARD_RANGE = +b.dataset.d;
    renderBoardTopbar();
    renderBoard();
  });
  $('#board-refresh').onclick = async () => {
    const btn = $('#board-refresh');
    const icon = btn.querySelector('.icon');
    icon.classList.add('refresh-spin');
    btn.disabled = true;
    try {
      DB = await loadDB(true);
      CITIES = canonicalCities(DB);
      CASES = (DB.case_library && DB.case_library.cases) || [];
      for (const c of CITIES) { if (!c.deferral && c.deposit && c.deposit.deferred_payment) c.deferral = c.deposit.deferred_payment; }
      for (const c of CITIES) FEAT[c.city] = extractFeatures(c);
      NAT_POLICIES = mineNational(DB);
      await loadNegNews();
      renderBoardTopbar(); renderBoard(); renderStats();
      toast('✅ 政策库与舆情已更新');
    } catch (e) {
      toast('⚠️ 刷新失败：' + e.message);
    } finally {
      icon.classList.remove('refresh-spin');
      btn.disabled = false;
    }
  };
  $('#board-q').addEventListener('input', e => { BOARD_KW = e.target.value; renderBoard(); });
  // 舆情排序切换
  $$('#risk-sort button').forEach(b => b.onclick = () => {
    $$('#risk-sort button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    RISK_SORT = b.dataset.s;
    renderBoardRisk();
  });
  $('#board-q').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const kw = $('#board-q').value.trim();
      if (kw) {
        const hit = CITIES.find(c => c.city === kw) || CITIES.find(c => c.city.includes(kw));
        if (hit) { BOARD_KW = hit.city; $('#board-q').value = hit.city; renderBoard(); }
      }
    }
  });
}
