import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type {
  CacheNecromancerConfig,
  CacheNecromancerLabel,
  CacheNecromancerLanguage,
  CacheNecromancerMarker,
  CacheNecromancerTime,
} from '../types'

const DEFAULT_CONFIG: CacheNecromancerConfig = {
  ttlMinutes: 60,
  warnAfterMinutes: 50,
  countdown: true,
  language: 'en',
  arm: 'manual',
  maxRefreshCount: 10,
  notify: true,
  graceSeconds: 60,
}

const base = atom({ plugin: 'cache-necromancer', key: 'base' } as const, null as CacheNecromancerTime)
const warnedFor = atom({ plugin: 'cache-necromancer', key: 'warnedFor' } as const, null as CacheNecromancerTime)
const expiredFor = atom({ plugin: 'cache-necromancer', key: 'expiredFor' } as const, null as CacheNecromancerTime)
const wokeFor = atom({ plugin: 'cache-necromancer', key: 'wokeFor' } as const, null as CacheNecromancerTime)
// label·config 는 v0.11.0 에서 모양이 바뀌었다(extra·color / arm·notify 등). shape 태그가 다르면 리로드 전(옛 코드)이 남긴 값은
// 없는 것으로 읽혀 초기값에서 시작한다. 모양을 다시 바꾸면 태그도 올린다
const label = atom({ plugin: 'cache-necromancer', key: 'label' } as const, null as CacheNecromancerLabel, { shape: 'v0.11' })
const config = atom({ plugin: 'cache-necromancer', key: 'config' } as const, DEFAULT_CONFIG, { shape: 'v0.11' })
const marker = atom({ plugin: 'cache-necromancer', key: 'marker' } as const, null as CacheNecromancerMarker)
const markerReadAt = atom({ plugin: 'cache-necromancer', key: 'markerReadAt' } as const, null as CacheNecromancerTime)
const tickErrorLogged = atom({ plugin: 'cache-necromancer', key: 'tickErrorLogged' } as const, false)
const wakeErrorLogged = atom({ plugin: 'cache-necromancer', key: 'wakeErrorLogged' } as const, false)

const MIN_MS = 60 * 1000
// scripts/refresh.py 의 PING_PREFIX 와 같다 (on_user_prompt.py 도 이 문자열로 ping 을 거른다)
const PING_PREFIX = '[cn:keepalive'
// 띠 배경과 카운트다운 글자색. 남은 시간 10분 구간마다 한 색 (60~50분 회청 → 파랑 → 초록 → 노랑 → 주황 → 10~0분·만료 빨강).
// 배경 #1f2d3d 대비(WCAG): 7.92 · 7.72 · 9.11 · 9.40 · 7.93 · 5.58 :1 — 모두 4.5:1 이상.
// 경계는 표시 초 기준으로 위 구간에 넣는다 (50:00 은 회청, 49:59 부터 파랑). ttl 이 60분이 아니어도 남은 분으로만 정한다
const STRIP = '#1f2d3d'
const LEVEL_COLOR = ['#ff7b7b', '#ffb454', '#f2d16b', '#8fe3a1', '#8ec5ff', '#b8c4d4'] as const
const EXPIRED_COLOR = '#ff7b7b'
// 뒤 정보(살린 횟수·목숨·예산)는 남은 시간과 무관해 회청 그대로 둔다 (7.92:1)
const EXTRA_COLOR = '#b8c4d4'
// 띠가 숨는 백그라운드 에이전트 상태 (idle·종료는 사용자 입력을 막지 않으므로 제외)
const BUSY_AGENT = new Set(['pending', 'running', 'waiting'])
// 띠 뒤 정보(살린 횟수·목숨·예산)의 구분자와, marker 파일을 다시 읽는 간격
const SEP = ' · '
const MARKER_EVERY_MS = 5000
// lib/session_id.py 의 _VALID_PATTERN — 이 모양이 아닌 id 는 Python 이 해시한 파일명을 쓰므로 읽지 않는다
const SID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/

// 이 모듈 로드에서 타이머를 걸었는지 / 설정을 읽었는지.
// /reload-plugins 뒤엔 session.start 가 오지 않을 수 있어(2026-10-07 실측) 모듈 스코프로 둔다 — 새로 로드되면 처음부터
let isStarted = false
let isConfigLoaded = false

// 문구는 lib/i18n.py 의 언어·용어를 따른다 (기본 en)
const TEXT: Record<
  CacheNecromancerLanguage,
  {
    left: (mmss: string) => string
    warn: (minutes: number) => string
    expired: string
    expiredToast: string
    wakeOff: string
    revived: (n: number) => string
    lives: (n: number, hhmm: string) => string
    budget: (n: number, hhmm: string) => string
  }
> = {
  ko: {
    left: t => `캐시 ${t} 남음`,
    warn: n => `캐시 ${n}분 남음`,
    expired: '캐시 만료',
    expiredToast: '캐시 만료 — 다음 입력은 캐시를 새로 만듦',
    wakeOff: '캐시 깨우기 꺼짐 — refresh_interval_minutes 가 cache_ttl_minutes 이상',
    revived: n => `${n}번 살림`,
    lives: (n, t) => `목숨 ${n} (${t}까지)`,
    budget: (n, t) => `깨우기 ${n}회 남음 (${t}까지)`,
  },
  en: {
    left: t => `Cache ${t} left`,
    warn: n => `Cache: ${n} min left`,
    expired: 'Cache expired',
    expiredToast: 'Cache expired — your next input rebuilds it',
    wakeOff: 'Cache wake off — refresh_interval_minutes is not below cache_ttl_minutes',
    revived: n => `Revived ${n}×`,
    lives: (n, t) => `Lives ${n} (until ${t})`,
    budget: (n, t) => `Wakes ${n} left (until ${t})`,
  },
  ja: {
    left: t => `キャッシュ残り ${t}`,
    warn: n => `キャッシュ残り${n}分`,
    expired: 'キャッシュ期限切れ',
    expiredToast: 'キャッシュ期限切れ — 次の入力でキャッシュを作り直します',
    wakeOff: 'キャッシュの自動延長は無効 — refresh_interval_minutes が cache_ttl_minutes 以上',
    revived: n => `${n}回蘇生`,
    lives: (n, t) => `残機 ${n} (${t}まで)`,
    budget: (n, t) => `wake 残り${n}回 (${t}まで)`,
  },
  zh: {
    left: t => `缓存剩余 ${t}`,
    warn: n => `缓存剩余 ${n} 分钟`,
    expired: '缓存已过期',
    expiredToast: '缓存已过期 — 下次输入将重新创建缓存',
    wakeOff: '缓存唤醒已关闭 — refresh_interval_minutes 不小于 cache_ttl_minutes',
    revived: n => `已复活 ${n} 次`,
    lives: (n, t) => `剩余 ${n} 命 (至 ${t})`,
    budget: (n, t) => `剩余 ${n} 次 wake (至 ${t})`,
  },
}

const pad = (n: number) => String(n).padStart(2, '0')

// Python 쪽 lib/config.py 와 같은 파일에서 필요한 키만 읽는 최소 TOML 파서.
// 분은 1 이상 정수, max_refresh_count 는 0 이상 정수, countdown 은 불리언, language 는 4종 문자열만 받고,
// 그 밖의 값·다른 섹션의 같은 키는 무시해 기본값을 둔다.
// arm·notify·grace 는 lib/config.py 의 _resolve_axes 와 같게: 신 키([wake] arm·grace_seconds, [notify] enabled)가 우선,
// 없으면 legacy([general] mode: hybrid·auto → always, auto 는 알림 없음 / [notify] system_notification / [refresh] hybrid_wait_seconds)
function parseConfig(text: string): CacheNecromancerConfig {
  const cfg = { ...DEFAULT_CONFIG }
  let section = ''
  let arm: string | undefined
  let mode: string | undefined
  let enabled: boolean | undefined
  let systemNotification: boolean | undefined
  let grace: number | undefined
  let legacyGrace: number | undefined
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/#.*/, '').trim()
    const header = /^\[\s*([A-Za-z0-9_.-]+)\s*\]$/.exec(line)
    if (header) {
      section = header[1] ?? ''
      continue
    }
    // 헤더 모양이 깨진 줄도 새 섹션의 시작으로 보고, 앞 섹션의 키가 이어 붙지 않게 끊는다
    if (line.startsWith('[')) {
      section = ''
      continue
    }
    const pair = /^([A-Za-z0-9_-]+)\s*=\s*(\S+)$/.exec(line)
    if (!pair) continue
    const [, key, value = ''] = pair
    const minutes = /^\d+$/.test(value) && Number(value) >= 1 ? Number(value) : undefined
    if (section === 'general' && key === 'cache_ttl_minutes' && minutes) cfg.ttlMinutes = minutes
    if (section === 'general' && key === 'refresh_interval_minutes' && minutes) cfg.warnAfterMinutes = minutes
    if (section === 'display' && key === 'countdown' && (value === 'true' || value === 'false')) {
      cfg.countdown = value === 'true'
    }
    const lang = /^(["'])(ko|en|ja|zh)\1$/.exec(value)?.[2] as CacheNecromancerLanguage | undefined
    if (section === 'general' && key === 'language' && lang) cfg.language = lang
    if (section === 'general' && key === 'max_refresh_count' && /^\d+$/.test(value)) cfg.maxRefreshCount = Number(value)
    const str = /^(["'])(.*)\1$/.exec(value)?.[2]
    if (section === 'wake' && key === 'arm') arm = str ?? value
    if (section === 'general' && key === 'mode') mode = str
    const bool = value === 'true' || value === 'false' ? value === 'true' : undefined
    if (section === 'notify' && key === 'enabled') enabled = bool
    if (section === 'notify' && key === 'system_notification') systemNotification = bool
    const seconds = /^\d+$/.test(value) ? Number(value) : undefined
    if (section === 'wake' && key === 'grace_seconds') grace = seconds
    if (section === 'refresh' && key === 'hybrid_wait_seconds') legacyGrace = seconds
  }
  const isLegacyMode = mode === 'hybrid' || mode === 'auto' || mode === 'notify'
  cfg.arm = (arm ?? (mode === 'hybrid' || mode === 'auto' ? 'always' : 'manual')) === 'always' ? 'always' : 'manual'
  // 구 auto 는 system_notification 과 무관하게 알림 없음
  const legacyEnabled = mode === 'auto' ? false : (systemNotification ?? (isLegacyMode ? true : undefined))
  cfg.notify = enabled ?? legacyEnabled ?? true
  cfg.graceSeconds = grace ?? legacyGrace ?? 60
  return cfg
}

// 다른 스크립트들과 같은 위치: $CN_ROOT 또는 ~/.cache-necromancer
async function cnRoot($: EngineInterface): Promise<string | undefined> {
  const home = await $.env.get('HOME')
  return (await $.env.get('CN_ROOT')) || (home ? `${home}/.cache-necromancer` : undefined)
}

// 없거나 못 읽으면 기본값
async function loadConfig($: EngineInterface): Promise<CacheNecromancerConfig> {
  try {
    const root = await cnRoot($)
    if (!root) return DEFAULT_CONFIG
    return parseConfig(await $.fs.read(`${root}/config.toml`))
  } catch {
    return DEFAULT_CONFIG
  }
}

// 설정을 읽어 atom 에 둔다. 리로드 전에 남은 띠 값은 바로 지우고,
// 깨우기 창(경고 ~ 만료)이 비어 깨우기가 영영 없으면 알린다
async function applyConfig($: EngineInterface): Promise<void> {
  isConfigLoaded = true
  const cfg = await loadConfig($)
  await update($, config, () => cfg)
  if (!cfg.countdown) await update($, label, () => null)
  if (cfg.warnAfterMinutes >= cfg.ttlMinutes) $.ui.toast(TEXT[cfg.language].wakeOff)
}

// Python(lib/marker.py)이 쓰는 이 세션의 marker 에서 깨우기 횟수·예산만 읽는다. 없음·깨짐·id 모양 밖이면 null
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

// 띠 카운트다운 뒤에 붙일 것: 마지막 사용자 입력 뒤 살린 횟수, 그리고 always 면 남은 목숨, manual 이면 남은 예산.
// 생존 시각 = 기준 시각 + 남은 횟수 × (refresh_interval + 알림 켜짐이면 grace) + ttl.
// 깨우기마다 refresh.py 가 알림 뒤 grace 만큼 기다렸다 ping 하므로 다음 기준 시각이 그만큼 늦다
function extraFor(at: number, cfg: CacheNecromancerConfig, m: CacheNecromancerMarker): string[] {
  if (m === null) return []
  const text = TEXT[cfg.language]
  const cycleMs = cfg.warnAfterMinutes * MIN_MS + (cfg.notify ? cfg.graceSeconds * 1000 : 0)
  const until = (n: number) => hhmm(at + n * cycleMs + cfg.ttlMinutes * MIN_MS)
  // wake_count 는 사용자 입력 때 0 으로 돌아간다. manual 은 예산 없는 알림도 세므로 소비한 예산만큼만 깨운 것.
  // 충전 뒤 깨우기가 있은 다음 사용자가 돌아오면 Python(on_user_prompt)이 set_budget_total 도 0 으로 비운다
  const revived = cfg.arm === 'always' ? m.wakeCount : Math.min(m.wakeCount, m.budgetTotal - m.budgetRemaining)
  const extra = revived > 0 ? [text.revived(revived)] : []
  if (cfg.arm === 'always') {
    const lives = Math.max(0, cfg.maxRefreshCount - m.wakeCount)
    extra.push(text.lives(lives, until(lives)))
  } else if (m.budgetRemaining > 0) {
    extra.push(text.budget(m.budgetRemaining, until(m.budgetRemaining)))
  }
  return extra
}

// 터미널 칸 수 (한글·CJK·전각은 2칸)
const WIDE = /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6]/
const cols = (s: string) => [...s].reduce((n, ch) => n + (WIDE.test(ch) ? 2 : 1), 0)
// extra 가 없는 값(shape 태그 이전 코드가 남긴 것 등)도 카운트다운만으로 다룬다
const joined = (line: NonNullable<CacheNecromancerLabel>) => [line.text, ...(line.extra ?? [])].join(SEP)

// 폭 안에 들어오게 뒤 정보를 앞에서부터(살린 횟수 → 목숨·예산) 뺀다. 카운트다운은 남기고, 남은 뒤 정보를 돌려준다
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
  // session.start 없이(리로드 뒤 render·turn.step 으로) 시작했으면 첫 tick 이 설정을 읽는다
  if (!isConfigLoaded) await applyConfig($)
  const cfg = await read($, config)
  const at = await read($, base)
  const now = at === null ? 0 : await $.clock.now()
  // marker 는 Python 이 Stop·사용자 입력·깨우기 때 바꾼다. 띠를 그릴 때만 몇 초 간격으로 읽는다
  const readAt = await read($, markerReadAt)
  if (at !== null && cfg.countdown && (readAt === null || now - readAt >= MARKER_EVERY_MS)) {
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
  // 깨우기는 띠(countdown)와 무관하게 판정한다. grace 동안 tick 이 계속 돌아도 claim 이 막는다.
  // 이미 만료된 캐시(리로드 직후 오래된 기준 시각, 잠자기 복귀 등)는 깨워도 재생성 비용만 나므로 건너뛴다
  const age = now - at
  if (age >= cfg.warnAfterMinutes * MIN_MS && age < cfg.ttlMinutes * MIN_MS && (await read($, wokeFor)) !== at) {
    await update($, wokeFor, claim)
    if (isFirst) void wake($).catch(error => logWakeOnce($, `wake failed (${errorText(error)})`).catch(() => undefined))
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

// 캐시 마지막 적중 + refresh_interval 이 지나면 refresh.py --now 를 돌린다. 재확인·예산·알림·grace 와 marker 기록은
// Python 몫이고, exit 2 면 stderr 중 ping 줄만 프롬프트로 낸다 ([cn:warn] 같은 경고 줄은 뺀다). 그 turn 이 캐시를 읽으면 turn.step 이 base 를 갱신해 다음 주기로 이어진다
// 진행 중인 turn·이미 돌아온 경우는 Python 이 마지막 Stop 뒤 사용자 입력으로 보고 건너뛴다
async function wake($: EngineInterface): Promise<void> {
  const r = await $.process.run(['python3', `${$.plugin.root}/scripts/refresh.py`, '--now'], {
    stdin: JSON.stringify({ session_id: await $.session.id() }),
    // grace 길이는 Python 이 설정에서 정하므로 process.run 상한(10분)을 그대로 쓴다. 끝나면 바로 돌아온다
    timeoutMs: 10 * MIN_MS,
  })
  const ping = r.stderr
    .split(/\r?\n/)
    .filter(line => line.includes(PING_PREFIX))
    .join('\n')
    .trim()
  // 깨우기·알림이 marker 를 바꿨으니 다음 tick 이 다시 읽는다
  await update($, markerReadAt, () => null)
  if (r.exitCode === 2 && ping) await $.prompt.submit({ text: ping })
}

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

// 깨우기도 best-effort: 첫 실패만 디버그 로그에 남긴다
async function logWakeOnce($: EngineInterface, text: string): Promise<void> {
  if (await read($, wakeErrorLogged)) return
  await update($, wakeErrorLogged, () => true)
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

export const register: Register = on => {
  // 설정은 세션 시작 때 읽는다 (Python 훅과 같은 "설정 변경 후 새 세션" 규칙).
  // 리로드 뒤엔 session.start 가 안 올 수 있어 ui.render·turn.step 도 타이머를 건다 (먼저 오는 쪽 1회, 설정은 첫 tick 이 읽음)
  on('session.start', async ($, e, next) => {
    await applyConfig($)
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
    const { Box, Text } = $.ui.resolve(e)
    // what-did-i-say 띠와 같은 규격(marginX 1·폭 W·paddingX 2)이라 위아래로 붙으면 한 사각형이 된다
    const W = Math.max(1, columns - 2)
    const extra = fit(line, W - 4)
    return (
      <Box flexDirection="column">
        <Box backgroundColor={STRIP} marginX={1} paddingX={2} width={W}>
          {/* 한 인라인 흐름으로 그리게 중첩한다 (형제 Text 는 폭이 어긋나면 따로 줄어들고, HTML surface 는 앞 공백을 접을 수 있다) */}
          <Text>
            <Text color={line.color ?? EXPIRED_COLOR}>{line.text}</Text>
            {extra.length > 0 ? <Text color={EXTRA_COLOR}>{SEP + extra.join(SEP)}</Text> : null}
          </Text>
        </Box>
        {below}
      </Box>
    )
  })
}
