import { atom, read, update } from 'claude-code'
import type { EngineInterface, ProcessRunResult, Register, Timer } from 'claude-code'

import type {
  CacheNecromancerConfig,
  CacheNecromancerItem,
  CacheNecromancerLabel,
  CacheNecromancerLanguage,
  CacheNecromancerMarker,
  CacheNecromancerNote,
  CacheNecromancerTime,
} from '../types'

const DEFAULT_CONFIG: CacheNecromancerConfig = {
  ttlMinutes: 60,
  warnAfterMinutes: 50,
  countdown: true,
  language: 'en',
  autoWakes: 2,
}

const base = atom({ plugin: 'cache-necromancer', key: 'base' } as const, null as CacheNecromancerTime)
const warnedFor = atom({ plugin: 'cache-necromancer', key: 'warnedFor' } as const, null as CacheNecromancerTime)
const expiredFor = atom({ plugin: 'cache-necromancer', key: 'expiredFor' } as const, null as CacheNecromancerTime)
const wokeFor = atom({ plugin: 'cache-necromancer', key: 'wokeFor' } as const, null as CacheNecromancerTime)
// v0.13.0 에서 숫자(chargedAt)가 깨우기 자격 서명 문자열로 바뀌었다. 옛 숫자 값은 shape 가 달라 null(리로드 직후)로 읽힌다
const wokeCharge = atom({ plugin: 'cache-necromancer', key: 'wokeCharge' } as const, null as string | null, { shape: 'v0.13' })
// label·config 는 v0.12.0 에서 모양이 바뀌었다(arm·notify·grace 삭제, autoWakes 추가). shape 태그가 다르면 리로드 전(옛 코드)이 남긴 값은
// 없는 것으로 읽혀 초기값에서 시작한다. 모양을 다시 바꾸면 태그도 올린다
const label = atom({ plugin: 'cache-necromancer', key: 'label' } as const, null as CacheNecromancerLabel, { shape: 'v0.12' })
const config = atom({ plugin: 'cache-necromancer', key: 'config' } as const, DEFAULT_CONFIG, { shape: 'v0.12' })
const marker = atom({ plugin: 'cache-necromancer', key: 'marker' } as const, null as CacheNecromancerMarker)
const markerReadAt = atom({ plugin: 'cache-necromancer', key: 'markerReadAt' } as const, null as CacheNecromancerTime)
const tickErrorLogged = atom({ plugin: 'cache-necromancer', key: 'tickErrorLogged' } as const, false)
const wakeErrorLogged = atom({ plugin: 'cache-necromancer', key: 'wakeErrorLogged' } as const, false)
const commandErrorLogged = atom({ plugin: 'cache-necromancer', key: 'commandErrorLogged' } as const, false)
const configErrorLogged = atom({ plugin: 'cache-necromancer', key: 'configErrorLogged' } as const, false)
// 설정 패널: 전체 설정 항목(--json 의 items), 이 세션 상태 줄(cn_set.py 무인자), 알림 줄(저장됨·실패)
const items = atom({ plugin: 'cache-necromancer', key: 'items' } as const, [] as CacheNecromancerItem[])
const sessionLine = atom({ plugin: 'cache-necromancer', key: 'sessionLine' } as const, '')
const paneNote = atom({ plugin: 'cache-necromancer', key: 'paneNote' } as const, null as CacheNecromancerNote)

const MIN_MS = 60 * 1000
// scripts/refresh.py 의 PING_PREFIX 와 같다 (on_user_prompt.py 도 이 문자열로 ping 을 거른다)
const PING_PREFIX = '[cn:keepalive'
// 띠 배경과 카운트다운 글자색. 남은 시간 10분 구간마다 한 색 (60~50분 회청 → 파랑 → 초록 → 노랑 → 주황 → 10~0분·만료 빨강).
// 배경 #1f2d3d 대비(WCAG): 7.92 · 7.72 · 9.11 · 9.40 · 7.93 · 5.58 :1 — 모두 4.5:1 이상.
// 경계는 표시 초 기준으로 위 구간에 넣는다 (50:00 은 회청, 49:59 부터 파랑). ttl 이 60분이 아니어도 남은 분으로만 정한다
const STRIP = '#1f2d3d'
const LEVEL_COLOR = ['#ff7b7b', '#ffb454', '#f2d16b', '#8fe3a1', '#8ec5ff', '#b8c4d4'] as const
const EXPIRED_COLOR = '#ff7b7b'
// 뒤 정보(살린 횟수·남은 깨우기)는 남은 시간과 무관해 회청 그대로 둔다 (7.92:1)
const EXTRA_COLOR = '#b8c4d4'
// 띠가 숨는 백그라운드 에이전트 상태 (idle·종료는 사용자 입력을 막지 않으므로 제외)
const BUSY_AGENT = new Set(['pending', 'running', 'waiting'])
// 띠 뒤 정보(살린 횟수·남은 깨우기)의 구분자와, marker 파일을 다시 읽는 간격
const SEP = ' · '
const MARKER_EVERY_MS = 5000
// 띠 오른쪽 설정 버튼이 차지하는 칸: 앞 1칸 + 터미널의 `[ ⚙ ]` (⚙ 는 터미널에 따라 1~2칸이라 2칸으로 잡는다)
const GEAR_COLS = 7
// lib/session_id.py 의 _VALID_PATTERN — 이 모양이 아닌 id 는 Python 이 해시한 파일명을 쓰므로 읽지 않는다
const SID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/

// 이 모듈 로드에서 타이머를 걸었는지, 설정을 해석한 config.toml 텍스트(null = 아직)·마지막으로 확인한 시각·실행 중인 읽기.
// /reload-plugins 뒤엔 session.start 가 오지 않을 수 있어(2026-10-07 실측) 모듈 스코프로 둔다 — 새로 로드되면 처음부터
// (atom 에 두면 리로드 직전 실행 중이던 표시가 남아 새 모듈이 영영 못 읽을 수 있다)
let isStarted = false
let configText: string | null = null
let configCheckedAt: number | null = null
let configJob: Promise<void> | null = null
// 설정 패널 알림 줄을 지울 타이머 (새 알림이 뜨면 앞 것을 취소)
let noteTimer: Timer | null = null

// 문구는 lib/i18n.py 의 언어·용어를 따른다 (기본 en)
const TEXT: Record<
  CacheNecromancerLanguage,
  {
    left: (mmss: string) => string
    warn: (minutes: number) => string
    expired: string
    expiredToast: string
    noWindow: string
    revived: (n: number) => string
    remaining: (n: number, hhmm: string) => string
    off: string
    // 설정 패널 (/cn:config·띠 ⚙). 항목 라벨·옵션 글자는 cn_config.py --json 이 언어별로 준다
    title: string
    session: string
    sessionButtons: readonly [string, string, string, string, string]
    settings: string
    saved: string
    failed: string
    opened: string
    openFailed: string
  }
> = {
  ko: {
    left: t => `캐시 ${t} 남음`,
    warn: n => `캐시 ${n}분 남음`,
    expired: '캐시 만료',
    expiredToast: '캐시 만료 — 다음 입력은 캐시를 새로 만듦',
    noWindow: '캐시 깨우기 꺼짐 — refresh_interval_minutes 가 cache_ttl_minutes 이상',
    revived: n => `${n}번 살림`,
    remaining: (n, t) => `깨우기 ${n}회 남음 (${t}까지)`,
    off: '깨우기 꺼짐',
    title: 'Cache Necromancer 설정',
    session: '이 세션',
    sessionButtons: ['끄기', '자동', '1시간', '2시간', '4시간'],
    settings: '전체 설정',
    saved: '저장됨 · 열린 세션 모두에 바로 반영',
    failed: '실패',
    opened: '설정 패널을 열었습니다',
    openFailed: '설정 패널을 띄울 수 없음 — /cn:config 를 입력해 보세요',
  },
  en: {
    left: t => `Cache ${t} left`,
    warn: n => `Cache: ${n} min left`,
    expired: 'Cache expired',
    expiredToast: 'Cache expired — your next input rebuilds it',
    noWindow: 'Cache wake off — refresh_interval_minutes is not below cache_ttl_minutes',
    revived: n => `Revived ${n}×`,
    remaining: (n, t) => `${n} ${n === 1 ? 'wake' : 'wakes'} left (until ${t})`,
    off: 'Wake off',
    title: 'Cache Necromancer settings',
    session: 'This session',
    sessionButtons: ['Off', 'Auto', '1 hour', '2 hours', '4 hours'],
    settings: 'Settings',
    saved: 'Saved · applied to every open session right away',
    failed: 'Failed',
    opened: 'Opened the settings panel',
    openFailed: 'Could not show the settings panel — try typing /cn:config',
  },
  ja: {
    left: t => `キャッシュ残り ${t}`,
    warn: n => `キャッシュ残り${n}分`,
    expired: 'キャッシュ期限切れ',
    expiredToast: 'キャッシュ期限切れ — 次の入力でキャッシュを作り直します',
    noWindow: 'キャッシュの自動延長は無効 — refresh_interval_minutes が cache_ttl_minutes 以上',
    revived: n => `${n}回蘇生`,
    remaining: (n, t) => `残り${n}回 (${t}まで)`,
    off: '自動延長オフ',
    title: 'Cache Necromancer 設定',
    session: 'このセッション',
    sessionButtons: ['オフ', '自動', '1時間', '2時間', '4時間'],
    settings: '全体設定',
    saved: '保存しました · 開いているすべてのセッションにすぐ反映',
    failed: '失敗',
    opened: '設定パネルを開きました',
    openFailed: '設定パネルを表示できません — /cn:config を入力してみてください',
  },
  zh: {
    left: t => `缓存剩余 ${t}`,
    warn: n => `缓存剩余 ${n} 分钟`,
    expired: '缓存已过期',
    expiredToast: '缓存已过期 — 下次输入将重新创建缓存',
    noWindow: '缓存唤醒已关闭 — refresh_interval_minutes 不小于 cache_ttl_minutes',
    revived: n => `已复活 ${n} 次`,
    remaining: (n, t) => `还剩 ${n} 次唤醒 (至 ${t})`,
    off: '唤醒已关闭',
    title: 'Cache Necromancer 设置',
    session: '本会话',
    sessionButtons: ['关闭', '自动', '1小时', '2小时', '4小时'],
    settings: '全局设置',
    saved: '已保存 · 立即应用到所有打开的会话',
    failed: '失败',
    opened: '已打开设置面板',
    openFailed: '无法显示设置面板 — 请尝试输入 /cn:config',
  },
}

const pad = (n: number) => String(n).padStart(2, '0')

// 다른 스크립트들과 같은 위치: $CN_ROOT 또는 ~/.cache-necromancer
async function cnRoot($: EngineInterface): Promise<string | undefined> {
  const home = await $.env.get('HOME')
  return (await $.env.get('CN_ROOT')) || (home ? `${home}/.cache-necromancer` : undefined)
}

const LANGUAGES: readonly unknown[] = ['ko', 'en', 'ja', 'zh']
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const isMinutes = (v: unknown): v is number => Number.isInteger(v) && (v as number) >= 1

// cn_config.py --json 의 config 가 CacheNecromancerConfig 모양인지만 본다 (값 검증은 Python 몫). 아니면 null
function toConfig(data: unknown): CacheNecromancerConfig | null {
  const c = isRecord(data) ? data['config'] : undefined
  if (!isRecord(c)) return null
  const { ttlMinutes, warnAfterMinutes, autoWakes, countdown, language } = c
  if (!isMinutes(ttlMinutes) || !isMinutes(warnAfterMinutes) || !Number.isInteger(autoWakes)) return null
  if (typeof countdown !== 'boolean' || !LANGUAGES.includes(language)) return null
  return { ttlMinutes, warnAfterMinutes, autoWakes: autoWakes as number, countdown, language: language as CacheNecromancerLanguage }
}

// --json 의 items 중 패널 한 줄 모양인 것만 (없으면 빈 목록)
function toItems(data: unknown): CacheNecromancerItem[] {
  const list: unknown[] = isRecord(data) && Array.isArray(data['items']) ? data['items'] : []
  const isText = (v: unknown): v is string => typeof v === 'string'
  const isOption = (o: unknown) => isRecord(o) && isText(o['value']) && isText(o['text'])
  return list.filter(
    (it): it is CacheNecromancerItem =>
      isRecord(it) && isText(it['id']) && isText(it['label']) && isText(it['current']) && Array.isArray(it['options']) && it['options'].every(isOption),
  )
}

// 설정 파일 텍스트, 없거나 못 읽으면 ''
async function readConfigText($: EngineInterface): Promise<string> {
  try {
    const root = await cnRoot($)
    return root ? await $.fs.read(`${root}/config.toml`) : ''
  } catch {
    return ''
  }
}

// config.toml 텍스트가 처음이거나 바뀌었으면(force 면 무조건) Python(lib/config.py)이 해석한 값(cn_config.py --json)으로 갈아 끼운다.
// 해석기는 Python 하나. 실행 실패·출력이 깨지면 이전 설정을 두고(처음이면 DEFAULT_CONFIG) 다음 주기에 다시 한다
async function loadConfig($: EngineInterface, force: boolean): Promise<void> {
  const text = await readConfigText($)
  if (!force && text === configText) return
  try {
    const r = await $.process.run(['python3', `${$.plugin.root}/scripts/cn_config.py`, '--json'], { timeoutMs: 10_000 })
    if (r.exitCode !== 0) throw new Error(`exit ${r.exitCode}`)
    const data: unknown = JSON.parse(r.stdout)
    const cfg = toConfig(data)
    if (cfg === null) throw new Error('unexpected --json output')
    await update($, items, () => toItems(data))
    await applyConfig($, cfg, configText === null)
    // atom 갱신까지 끝난 뒤에 "읽음"으로 적는다 (중간에 실패하면 다음 주기에 다시 한다)
    configText = text
  } catch (error) {
    await logConfigOnce($, `config load failed (${errorText(error)})`)
  }
}

// 겹친 tick·session.start 가 --json 을 중복 실행하지 않게 실행 중인 작업을 모듈에 둔다 (도중엔 그 작업을 기다린다).
// force(패널 저장 직후)는 실행 중인 작업 뒤에 한 번 더 돌려, 저장 전 텍스트로 시작한 작업이 결과를 덮지 않게 한다
function syncConfig($: EngineInterface, force = false): Promise<void> {
  if (configJob !== null && !force) return configJob
  // 앞 작업이 실패(reject)해도 이번 읽기는 돈다
  const run = () => loadConfig($, force)
  const job = (configJob ?? Promise.resolve()).then(run, run)
  configJob = job
  void job
    .finally(() => {
      if (configJob === job) configJob = null
    })
    .catch(() => undefined)
  return job
}

// 설정을 atom 에 둔다. countdown 이 꺼지면 남은 띠 값을 바로 지우고, 깨우기 창(경고 ~ 만료)이 비면 알린다 —
// 이 모듈의 첫 읽기이거나 창이 있다가 없어졌을 때만 (주기마다 반복하지 않는다)
async function applyConfig($: EngineInterface, cfg: CacheNecromancerConfig, isFirst: boolean): Promise<void> {
  const hasNoWindow = (c: CacheNecromancerConfig) => c.warnAfterMinutes >= c.ttlMinutes
  const prev = await read($, config)
  await update($, config, () => cfg)
  if (!cfg.countdown) await update($, label, () => null)
  if (hasNoWindow(cfg) && (isFirst || !hasNoWindow(prev))) $.ui.toast(TEXT[cfg.language].noWindow)
}

// Python(lib/marker.py)이 쓰는 이 세션의 marker 에서 깨우기 횟수·덮어쓰기·끔만 읽는다. 없음·깨짐·id 모양 밖이면 null
async function loadMarker($: EngineInterface): Promise<CacheNecromancerMarker> {
  try {
    const sid = await $.session.id()
    const root = await cnRoot($)
    if (!root || !SID_PATTERN.test(sid)) return null
    const data: unknown = JSON.parse(await $.fs.read(`${root}/marker/${sid}.json`))
    if (typeof data !== 'object' || data === null || Array.isArray(data)) return null
    const fields = data as Record<string, unknown>
    const int = (key: string) => (Number.isInteger(fields[key]) ? (fields[key] as number) : 0)
    return {
      wakeCount: int('wake_count'),
      budgetRemaining: int('set_budget_remaining'),
      budgetTotal: int('set_budget_total'),
      wakeOff: fields['wake_off'] === true,
      // ns 라 Number 정밀도를 넘지만 바뀌었는지만 보므로 상관없다
      chargedAt: typeof fields['set_charged_at_ns'] === 'number' ? fields['set_charged_at_ns'] : 0,
    }
  } catch {
    return null
  }
}

// 로컬 시각 HH:MM
function hhmm(ms: number): string {
  const d = new Date(ms)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 띠 카운트다운 뒤에 붙일 것: 이번 자리비움에 살린 횟수, 그리고 깨우기 꺼짐 또는 남은 깨우기 횟수와 생존 시각.
// 남은 횟수는 lib/wake_plan.py remaining_wakes 와 같다 (덮어쓰기 중엔 충전 남은 것, 아니면 auto_wakes - wake_count).
// 생존 시각 = 기준 시각 + 남은 횟수 × refresh_interval + ttl (survive_until_ns 와 같은 식)
// 남은 깨우기 횟수 (lib/wake_plan.py remaining_wakes 와 같다). marker 없음·끔이면 0.
// 깨우기 창이 없으면(refresh_interval ≥ ttl) 깨울 수 없으니 0 (wake_plan 과 같은 규칙)
function remainingWakes(cfg: CacheNecromancerConfig, m: CacheNecromancerMarker): number {
  if (m === null || m.wakeOff || cfg.warnAfterMinutes >= cfg.ttlMinutes) return 0
  return m.budgetTotal > 0 ? m.budgetRemaining : Math.max(0, cfg.autoWakes - m.wakeCount)
}

// 깨우기 자격 서명: 충전·끔·자동 횟수 중 하나라도 바뀌면 달라진다 (ns 는 Number 정밀도를 넘어 더하지 않고 글자로 잇는다)
const wakeSign = (cfg: CacheNecromancerConfig, m: CacheNecromancerMarker) =>
  `${m?.chargedAt ?? 0}|${m?.wakeOff === true}|${cfg.autoWakes}`

function extraFor(at: number, cfg: CacheNecromancerConfig, m: CacheNecromancerMarker): string[] {
  if (m === null) return []
  const text = TEXT[cfg.language]
  const extra = m.wakeCount > 0 ? [text.revived(m.wakeCount)] : []
  if (m.wakeOff) return [...extra, text.off]
  const remaining = remainingWakes(cfg, m)
  if (remaining > 0) {
    extra.push(text.remaining(remaining, hhmm(at + remaining * cfg.warnAfterMinutes * MIN_MS + cfg.ttlMinutes * MIN_MS)))
  }
  return extra
}

// 터미널 칸 수 (한글·CJK·전각은 2칸)
const WIDE = /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6]/
const cols = (s: string) => [...s].reduce((n, ch) => n + (WIDE.test(ch) ? 2 : 1), 0)
// extra 가 없는 값(shape 태그 이전 코드가 남긴 것 등)도 카운트다운만으로 다룬다
const joined = (line: NonNullable<CacheNecromancerLabel>) => [line.text, ...(line.extra ?? [])].join(SEP)

// 폭 안에 들어오게 뒤 정보를 앞에서부터(살린 횟수 → 남은 깨우기) 뺀다. 카운트다운은 남기고, 남은 뒤 정보를 돌려준다
function fit(line: NonNullable<CacheNecromancerLabel>, width: number): string[] {
  const extra = [...(line.extra ?? [])]
  while (extra.length > 0 && cols(joined({ ...line, extra })) > width) extra.shift()
  return extra
}

// 만료 뒤에는 뒤 정보를 붙이지 않는다 (생존 시각이 이미 지난 값이라)
function labelFor(at: number, now: number, cfg: CacheNecromancerConfig, m: CacheNecromancerMarker): CacheNecromancerLabel {
  const left = cfg.ttlMinutes * MIN_MS - (now - at)
  const text = TEXT[cfg.language]
  if (left <= 0) return { text: text.expired, tone: 'error', color: EXPIRED_COLOR, extra: [] }
  const sec = Math.ceil(left / 1000)
  // 토스트 시점은 색과 별개로 refresh_interval 기준 그대로
  const isWarning = left <= (cfg.ttlMinutes - cfg.warnAfterMinutes) * MIN_MS
  return {
    text: text.left(`${pad(Math.floor(sec / 60))}:${pad(sec % 60)}`),
    tone: isWarning ? 'warning' : 'normal',
    color: LEVEL_COLOR[Math.min(LEVEL_COLOR.length - 1, Math.floor(sec / 600))] ?? EXPIRED_COLOR,
    extra: extraFor(at, cfg, m),
  }
}

// 리더 턴이 끝나도 백그라운드 에이전트가 돌고 있으면 아직 "모든 작업이 끝난" 게 아니다
async function hasBusyAgent($: EngineInterface): Promise<boolean> {
  try {
    return (await $.agent.list()).some(agent => BUSY_AGENT.has(agent.status))
  } catch {
    return false
  }
}

async function tick($: EngineInterface): Promise<void> {
  // 설정 파일은 기준 시각과 무관하게 몇 초 간격으로 본다. session.start 없이(리로드 뒤 render·turn.step 으로) 시작했으면 첫 tick 이 읽는다
  const now = await $.clock.now()
  if (configCheckedAt === null || now - configCheckedAt >= MARKER_EVERY_MS) {
    configCheckedAt = now
    await syncConfig($)
  }
  const cfg = await read($, config)
  const at = await read($, base)
  // marker 는 Python 이 Stop·사용자 입력·깨우기·/cn:set 때 바꾼다. 기준 시각이 있으면 띠 표시와 무관하게 몇 초 간격으로 읽는다 (충전 재판정)
  const readAt = await read($, markerReadAt)
  if (at !== null && (readAt === null || now - readAt >= MARKER_EVERY_MS)) {
    await update($, markerReadAt, () => now)
    const m = await loadMarker($)
    await update($, marker, () => m)
  }
  const next = at === null || !cfg.countdown ? null : labelFor(at, now, cfg, await read($, marker))
  // 백그라운드 에이전트가 도는 동안은 띠만 숨긴다. 캐시 시계는 흐르므로 토스트 판정은 계속한다
  const shown = next !== null && (await hasBusyAgent($)) ? null : next

  // 글자가 바뀔 때만 쓴다. 쓰면 label을 읽은 띠가 다시 그려진다
  const prev = await read($, label)
  if ((prev && joined(prev)) !== (shown && joined(shown))) await update($, label, () => shown)

  if (at === null) return
  // 이 기준 시각으로 아직 안 했을 때만 깨우기·토스트. 판정과 기록을 update 콜백 한 번에 (겹친 tick 중복 방지)
  let isFirst = false
  const claim = (prev: CacheNecromancerTime) => {
    isFirst = prev !== at
    return at
  }
  // 깨우기는 띠(countdown)와 무관하게 판정한다. 실행이 끝나기 전에 tick 이 계속 돌아도 claim 이 막는다.
  // 이미 만료된 캐시(리로드 직후 오래된 기준 시각, 잠자기 복귀 등)는 깨워도 재생성 비용만 나므로 건너뛴다
  const age = now - at
  if (age >= cfg.warnAfterMinutes * MIN_MS && age < cfg.ttlMinutes * MIN_MS) {
    const m = await read($, marker)
    const sign = wakeSign(cfg, m)
    if ((await read($, wokeFor)) !== at) {
      // wokeCharge = null 은 "실행 중" 표시. claim 보다 먼저 적어, claim 직후 겹친 tick 이 아래 재판정으로 새지 않게 한다.
      // 실행이 끝나면 wake() 가 Python 이 본 자격 서명을 적는다
      await update($, wokeCharge, () => null)
      await update($, wokeFor, claim)
      if (isFirst) startWake($)
    } else if (remainingWakes(cfg, m) > 0) {
      // 이 기준 시각으로 이미 판정했는데(깨우지 않고 끝남 등) 그 뒤 남은 깨우기가 있고 자격 서명이 바뀌면 1회 더 판정한다
      // (/cn:set 충전, [자동]·/cn:set auto 로 끔 해제, auto_wakes 변경). 실제 남은 횟수는 refresh.py 가 다시 확인한다.
      // 실행 중(null)·리로드 직후(null 로 시작)는 하지 않는다. 판정과 기록을 update 콜백 한 번에 (겹친 tick 중복 방지)
      let isRecharge = false
      await update($, wokeCharge, prev => {
        isRecharge = prev !== null && prev !== sign
        return isRecharge ? null : prev
      })
      if (isRecharge) startWake($)
    }
  }
  if (next === null) return
  if (next.tone === 'error' && (await read($, expiredFor)) !== at) {
    await update($, expiredFor, claim)
    if (isFirst) $.ui.toast(TEXT[cfg.language].expiredToast)
  }
  if (next.tone === 'warning' && (await read($, warnedFor)) !== at) {
    await update($, warnedFor, claim)
    if (isFirst) $.ui.toast(TEXT[cfg.language].warn(cfg.ttlMinutes - cfg.warnAfterMinutes))
  }
}

const startWake = ($: EngineInterface) =>
  void wake($).catch(error => logWakeOnce($, `wake failed (${errorText(error)})`).catch(() => undefined))

// 캐시 마지막 적중 + refresh_interval 이 지나면 refresh.py --now 를 돌린다. 재확인·남은 횟수와 marker 기록은
// Python 몫이고, exit 2 면 stderr 중 ping 줄만 프롬프트로 낸다 ([cn:warn] 같은 경고 줄은 뺀다). 그 turn 이 캐시를 읽으면 turn.step 이 base 를 갱신해 다음 주기로 이어진다
// 진행 중인 turn·이미 돌아온 경우는 Python 이 마지막 Stop 뒤 사용자 입력으로 보고 건너뛴다
async function wake($: EngineInterface): Promise<void> {
  let r: ProcessRunResult
  try {
    r = await $.process.run(['python3', `${$.plugin.root}/scripts/refresh.py`, '--now'], {
      stdin: JSON.stringify({ session_id: await $.session.id() }),
      // grace 대기가 없어져 바로 끝난다. 상한은 넉넉히 1분
      timeoutMs: 60_000,
    })
  } finally {
    // 실패해도 "실행 중"을 풀어야 재판정이 다시 가능하다. 깨우기가 marker 를 바꿨을 수 있으니 바로 다시 읽고,
    // Python 이 이번 판정에 쓴 자격 서명을 적는다 (그 뒤 서명이 또 바뀔 때만 재판정)
    const m = await loadMarker($)
    await update($, marker, () => m)
    const sign = wakeSign(await read($, config), m)
    await update($, wokeCharge, () => sign)
  }
  const ping = r.stderr
    .split(/\r?\n/)
    .filter(line => line.includes(PING_PREFIX))
    .join('\n')
    .trim()
  if (r.exitCode === 2 && ping) {
    const res = await $.prompt.submit({ text: ping })
    if (res.drop !== undefined) await logWakeOnce($, `ping dropped (${res.drop})`)
  }
}

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

// 깨우기도 best-effort: 첫 실패(실행 실패·ping 거부)만 디버그 로그에 남긴다
async function logWakeOnce($: EngineInterface, text: string): Promise<void> {
  if (await read($, wakeErrorLogged)) return
  await update($, wakeErrorLogged, () => true)
  $.ui.log(`cache-necromancer: ${text}; later failures are not logged`, { to: 'debug' })
}

// 설정 읽기도 같다: 첫 실패만 남기고 이전 설정으로 계속한다
async function logConfigOnce($: EngineInterface, text: string): Promise<void> {
  if (await read($, configErrorLogged)) return
  await update($, configErrorLogged, () => true)
  $.ui.log(`cache-necromancer: ${text}; later failures are not logged`, { to: 'debug' })
}

// /cn:* 명령도 같다: 첫 실패만 남기고 옛 경로로 넘긴다
async function logCommandOnce($: EngineInterface, text: string): Promise<void> {
  if (await read($, commandErrorLogged)) return
  await update($, commandErrorLogged, () => true)
  $.ui.log(`cache-necromancer: ${text}; later failures are not logged`, { to: 'debug' })
}

// tick 은 표시용 best-effort: 실패(리로드·종료 직후 등)는 다음 tick 이 다시 계산한다.
// 원인 추적용으로 첫 실패만 디버그 로그에 남기고 이후는 조용히 넘긴다
async function logFirstTickError($: EngineInterface, error: unknown): Promise<void> {
  if (await read($, tickErrorLogged)) return
  await update($, tickErrorLogged, () => true)
  $.ui.log(`cache-necromancer: countdown tick failed (${errorText(error)}); later failures are not logged`, { to: 'debug' })
}

// 1초 타이머는 모듈 로드당 1개. 리로드는 이전 환경의 타이머를 엔진이 버리고 이 모듈을 새로 읽는다.
// countdown 이 꺼져도 깨우기 때문에 타이머는 돈다. state 를 쓰지 않으므로 ui.render 안에서도 부를 수 있다
function ensureTimer($: EngineInterface): void {
  if (isStarted) return
  isStarted = true
  $.clock.every(1000, () => void tick($).catch(error => logFirstTickError($, error).catch(() => undefined)))
}

// /cn:* 명령 → 실행할 스크립트와 인자. 엔진이 넘기는 이름이 짧은 형식·네임스페이스형 어느 쪽이든 받는다.
// (Python UserPromptExpansion 훅 scripts/on_status_command.py 와 같은 표 — 그쪽은 mods 없는 Claude Code 용 대체 경로)
const COMMANDS: Record<string, (args: string) => string[]> = {}
for (const prefix of ['', 'cache-necromancer:']) {
  // cn:set 은 첫 토큰만 (나머지는 무시)
  COMMANDS[`${prefix}cn:set`] = args => ['cn_set.py', ...args.trim().split(/\s+/).filter(Boolean).slice(0, 1)]
  COMMANDS[`${prefix}cn:status`] = () => ['cn_status.py']
  // 설정은 패널(Pane)로 연다. 못 열 때만 TUI 실행 방법 안내
  COMMANDS[`${prefix}cn:config`] = () => ['cn_config.py', '--hint']
}
// 스크립트 출력 끝의 stderr 는 이만큼만 붙인다
const STDERR_LINES = 10

// /cn:* 를 Python 스크립트로 직접 실행해 그 출력을 명령 결과로 답한다 (next 를 부르지 않아 명령 본문·모델 turn 없음).
// 세션 id 는 스크립트가 읽는 CLAUDE_CODE_SESSION_ID 로 넘긴다 (process.run 의 env 는 host 환경 위에 덧씌움 — HOME·PATH·CN_ROOT 는 그대로).
// exit≠0 이면 stdout 뒤에 exit 코드와 stderr 끝부분을 붙인다
async function runScript($: EngineInterface, argv: readonly string[]): Promise<ProcessRunResult> {
  const [script = '', ...args] = argv
  return $.process.run(['python3', `${$.plugin.root}/scripts/${script}`, ...args], {
    env: { CLAUDE_CODE_SESSION_ID: await $.session.id() },
    timeoutMs: 10_000,
  })
}

async function runCommand($: EngineInterface, argv: readonly string[]): Promise<string> {
  const r = await runScript($, argv)
  const out = r.stdout.trimEnd() || '(empty)'
  if (r.exitCode === 0) return out
  const err = r.stderr.trimEnd().split(/\r?\n/).slice(-STDERR_LINES).join('\n')
  return `${out}\n\n[exit ${r.exitCode}]${err ? `\n[stderr]\n${err}` : ''}`
}

// ── 설정 패널 (Pane): 이 세션 깨우기(cn_set.py)와 전체 설정(cn_config.py --set) ──
const PANE = 'cn-config'
const SESSION_ARGS = ['off', 'auto', '1h', '2h', '4h'] as const
// 성공 알림 줄(저장됨·이 세션 버튼 결과)을 보이는 시간
const NOTE_MS = 4000
const firstLine = (text: string) => text.trim().split(/\r?\n/)[0] ?? ''

// 스크립트 실패(exit≠0) 사유 한 줄: stderr 중 설정 경고([cn:warn])가 아닌 첫 줄, 없으면 stdout 첫 줄(cn_set 의 marker 저장 실패 안내는 stdout),
// 둘 다 없으면 "실패". 설정 파일의 잘못된 값 경고가 실제 실패 사유를 가리지 않게 한다
const failText = async ($: EngineInterface, r: ProcessRunResult) =>
  r.stderr
    .split(/\r?\n/)
    .map(line => line.trim())
    .find(line => line !== '' && !line.startsWith('[cn:warn]')) ||
  firstLine(r.stdout) ||
  TEXT[(await read($, config)).language].failed

// 알림 줄을 쓴다. 앞 알림의 지우기 타이머는 취소하고(같은 글자가 연달아 떠도 새 알림이 제 시간만큼 보이게), clearAfterMs 가 있으면 그 뒤 지운다
async function showNote($: EngineInterface, note: NonNullable<CacheNecromancerNote>, clearAfterMs?: number): Promise<void> {
  noteTimer?.cancel()
  noteTimer = null
  await update($, paneNote, () => note)
  if (clearAfterMs === undefined) return
  noteTimer = $.clock.after(clearAfterMs, () => void update($, paneNote, () => null).catch(() => undefined))
}

// 이 세션 상태 줄 = cn_set.py(무인자) 출력
async function refreshSession($: EngineInterface): Promise<void> {
  const r = await runScript($, ['cn_set.py'])
  const line = r.exitCode === 0 ? r.stdout.trim() : await failText($, r)
  await update($, sessionLine, () => line)
}

// 패널을 연다. 그려졌으면 설정(항목)과 상태 줄을 새로 받는다. 그려지지 못하면(surface 없음 등) 닫고 false, 열기 거부는 throw
async function openPanel($: EngineInterface): Promise<boolean> {
  await update($, paneNote, () => null)
  await update($, sessionLine, () => '')
  const opened = await $.ui.open({ id: PANE, title: TEXT[(await read($, config)).language].title, focus: true, closeOnEscape: true })
  if (!opened.isPlaced) {
    await $.ui.close({ id: PANE })
    return false
  }
  // 상태 줄을 못 받아도(python3 없음 등) 패널은 열린 채 둔다
  await Promise.all([syncConfig($, true), refreshSession($).catch(() => undefined)])
  return true
}

// 패널 열기 실패는 첫 1회만 디버그 로그 (/cn:config 는 그 뒤 --hint 로 넘어간다)
const tryOpenPanel = ($: EngineInterface) =>
  openPanel($).catch(async error => {
    await logCommandOnce($, `panel open failed (${errorText(error)})`)
    return false
  })

// 띠 ⚙: 패널을 못 띄우면(그려지지 못함·거부) 아무 반응 없이 끝나지 않게 /cn:config 를 안내한다
async function openFromBand($: EngineInterface): Promise<void> {
  if (!(await tryOpenPanel($))) $.ui.toast(TEXT[(await read($, config)).language].openFailed)
}

// 이 세션 버튼: cn_set.py <인자> → 결과 첫 줄(충전량·생존 시각 등)을 4초 알림, 상태 줄 다시 받기 + 다음 tick 에 marker 다시 읽기(띠 반영). 실패는 빨간 줄
async function pressSession($: EngineInterface, arg: (typeof SESSION_ARGS)[number]): Promise<void> {
  const r = await runScript($, ['cn_set.py', arg])
  if (r.exitCode !== 0) {
    await showNote($, { text: await failText($, r), isError: true })
  } else {
    await showNote($, { text: firstLine(r.stdout), isError: false }, NOTE_MS)
  }
  await update($, markerReadAt, () => null)
  await refreshSession($)
}

// 전체 설정 버튼: cn_config.py --set → 성공이면 바로 다시 읽어 이 세션에 반영하고(다른 세션은 5초 안에) 상태 줄도 다시 받고 4초 "저장됨", 실패면 빨간 줄
async function pressSetting($: EngineInterface, id: string, value: string): Promise<void> {
  const r = await runScript($, ['cn_config.py', '--set', `${id}=${value}`])
  if (r.exitCode !== 0) {
    await showNote($, { text: await failText($, r), isError: true })
    return
  }
  const before = (await read($, config)).language
  await syncConfig($, true)
  const lang = (await read($, config)).language
  // 상태 줄은 auto_wakes·간격·언어에 따라 달라 다시 받는다. 언어가 바뀌면 같은 id 로 다시 열어 제목만 바꾼다 (closeOnEscape 는 열 때마다 다시 정해진다)
  await refreshSession($).catch(() => undefined)
  if (lang !== before) await $.ui.open({ id: PANE, title: TEXT[lang].title, closeOnEscape: true }).catch(() => undefined)
  await showNote($, { text: TEXT[lang].saved, isError: false }, NOTE_MS)
}

// 버튼 작업이 throw 하면(python3 없음 등) 그 사유를 빨간 줄로
const pressed = ($: EngineInterface, job: Promise<unknown>) =>
  void job.catch(error => showNote($, { text: errorText(error), isError: true }).catch(() => undefined))

export const register: Register = on => {
  // /cn:* 를 mod 가 먼저 처리한다. Python 훅(decision=block)으로 막으면 막힌 명령이 입력창에 다시 들어가 매번 지워야 했다.
  // 실행 자체가 실패하면(python3 없음 등) 옛 경로(명령 본문·Python 훅)로 넘긴다
  for (const command of Object.keys(COMMANDS)) {
    on('command.run', { command }, async ($, e, next) => {
      const argv = COMMANDS[e.command]?.(e.args)
      if (argv === undefined) return next(e)
      try {
        // /cn:config 는 설정 패널을 연다. 못 열면 지금처럼 실행 방법 안내(--hint)
        if (e.command.endsWith('cn:config') && (await tryOpenPanel($))) return { text: TEXT[(await read($, config)).language].opened }
        return { text: await runCommand($, argv) }
      } catch (error) {
        await logCommandOnce($, `/${e.command} failed (${errorText(error)}), falling back`).catch(() => undefined)
        return next(e)
      }
    })
  }


  // 설정은 세션 시작 때 읽고, 그 뒤엔 tick 이 파일이 바뀌었는지 보며 다시 읽는다 (열린 세션 모두에 바로 반영).
  // 리로드 뒤엔 session.start 가 안 올 수 있어 ui.render·turn.step 도 타이머를 건다 (먼저 오는 쪽 1회, 설정은 첫 tick 이 읽음)
  on('session.start', async ($, e, next) => {
    await syncConfig($)
    ensureTimer($)
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    await update($, base, () => null)
    await update($, label, () => null)
    await update($, markerReadAt, () => null)
    return next(e)
  })

  // 메인 대화의 /compact(또는 플러그인 compact)가 실제로 끝나면 띠를 비운다. 다음 답변의 turn.step 이 기준 시각을 다시 잡는다.
  // 거부된 compact(skip)·서브에이전트 것·auto(답변 도중 자동)·precompute(아무것도 설치 안 함)는 그대로 둔다
  on('session.compact', async ($, e, next) => {
    const r = await next(e)
    if (r.skip === undefined && e.agentId === undefined && (e.trigger === 'manual' || e.trigger === 'plugin')) {
      await update($, base, () => null)
      await update($, label, () => null)
    }
    return r
  })

  // 요청 시작 시각을 잡아 두고, 응답이 와서 캐시를 실제로 읽거나 쓴 경우에만 기준 시각으로 삼는다 (서브에이전트 제외)
  on('turn.step', async function* ($, e, next) {
    ensureTimer($)
    const at = e.agentId === undefined ? await $.clock.now() : null
    const r = yield* next(e)
    const u = r.usage
    if (at !== null && u !== null && u.cache_read_input_tokens + u.cache_creation_input_tokens > 0) {
      await update($, base, () => at)
    }
    return r
  })

  // 대기 상태일 때 입력창 아래 힌트 줄 자리에 캐시 줄 한 줄. 아래(다른 플러그인·엔진 힌트 줄)가 그린 것은 그 밑에 둔다.
  // 입력창 위(AbovePrompt)에 두면 / 명령 목록이 띠 위로 밀려 뜬다
  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    ensureTimer($)
    // 답변이 끝난 대기 상태에서만 표시 (글자 치는 중에는 그대로 둔다). 폭을 모르면(surface 가 아직 안 잼) 그리지 않는다
    const columns = e.viewport?.columns
    if (e.props.isWorking || columns === undefined) return next(e)
    const line = await read($, label)
    // 기준 시각이 비었으면(/clear·/compact 직후) 숨긴다. 그 순간 진행 중이던 tick 이 옛 글자를 다시 써도 다음 tick 이 지운다
    if (line === null || (await read($, base)) === null) return next(e)

    const below = await next(e)
    const { Box, Text, Button } = $.ui.resolve(e)
    // what-did-i-say 띠와 같은 규격(marginX 1·폭 W·paddingX 2)이라 위아래로 붙으면 한 사각형이 된다
    const W = Math.max(1, columns - 2)
    const extra = fit(line, W - 4 - GEAR_COLS)
    return (
      <Box flexDirection="column">
        <Box backgroundColor={STRIP} marginX={1} paddingX={2} width={W} justifyContent="space-between">
          {/* 한 인라인 흐름으로 그리게 중첩한다 (형제 Text 는 폭이 어긋나면 따로 줄어들고, HTML surface 는 앞 공백을 접을 수 있다) */}
          <Text>
            <Text color={line.color ?? EXPIRED_COLOR}>{line.text}</Text>
            {extra.length > 0 ? <Text color={EXTRA_COLOR}>{SEP + extra.join(SEP)}</Text> : null}
          </Text>
          <Button key="cn-gear" label="⚙" onPress={() => pressed($, openFromBand($))} />
        </Box>
        {below}
      </Box>
    )
  })

  // 설정 패널 본문: 이 세션(상태 줄 + 버튼) → 전체 설정(항목마다 라벨 + 옵션 버튼, 지금 값은 primary) → 알림 줄
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const text = TEXT[(await read($, config)).language]
    const rows = await read($, items)
    const note = await read($, paneNote)
    return (
      <Box flexDirection="column">
        <Text bold>{text.session}</Text>
        <Text>{await read($, sessionLine)}</Text>
        <Box flexWrap="wrap" columnGap={1}>
          {SESSION_ARGS.map((arg, i) => (
            <Button key={`session:${arg}`} label={text.sessionButtons[i] ?? arg} onPress={() => pressed($, pressSession($, arg))} />
          ))}
        </Box>
        <Box marginTop={1}>
          <Text bold>{text.settings}</Text>
        </Box>
        {rows.map(item => (
          <Box key={item.id} flexDirection="column">
            <Text>{item.label}</Text>
            <Box flexWrap="wrap" columnGap={1}>
              {item.options.map(o => (
                <Button
                  key={`${item.id}=${o.value}`}
                  label={o.text}
                  {...(o.value === item.current ? { variant: 'primary' as const } : {})}
                  onPress={() => pressed($, pressSetting($, item.id, o.value))}
                />
              ))}
            </Box>
          </Box>
        ))}
        {note === null ? null : <Text color={note.isError ? 'error' : 'success'}>{note.text}</Text>}
      </Box>
    )
  })
}
