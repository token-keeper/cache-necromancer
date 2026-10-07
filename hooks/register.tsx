import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { CacheNecromancerConfig, CacheNecromancerLabel, CacheNecromancerLanguage, CacheNecromancerTime } from '../types'

const DEFAULT_CONFIG: CacheNecromancerConfig = { ttlMinutes: 60, warnAfterMinutes: 50, countdown: true, language: 'en' }

const base = atom({ plugin: 'cache-necromancer', key: 'base' } as const, null as CacheNecromancerTime)
const warnedFor = atom({ plugin: 'cache-necromancer', key: 'warnedFor' } as const, null as CacheNecromancerTime)
const expiredFor = atom({ plugin: 'cache-necromancer', key: 'expiredFor' } as const, null as CacheNecromancerTime)
const label = atom({ plugin: 'cache-necromancer', key: 'label' } as const, null as CacheNecromancerLabel)
const config = atom({ plugin: 'cache-necromancer', key: 'config' } as const, DEFAULT_CONFIG)
const tickErrorLogged = atom({ plugin: 'cache-necromancer', key: 'tickErrorLogged' } as const, false)

const MIN_MS = 60 * 1000
// 띠 배경과 글자색. 배경 #1f2d3d 대비: 기본 7.9:1, 경고 7.9:1, 만료 5.6:1 (모두 4.5:1 이상)
const STRIP = '#1f2d3d'
const TONE_COLOR = { normal: '#b8c4d4', warning: '#ffb454', error: '#ff7b7b' } as const
// 띠가 숨는 백그라운드 에이전트 상태 (idle·종료는 사용자 입력을 막지 않으므로 제외)
const BUSY_AGENT = new Set(['pending', 'running', 'waiting'])

// 문구는 lib/i18n.py 의 언어·용어를 따른다 (기본 en)
const TEXT: Record<
  CacheNecromancerLanguage,
  { left: (mmss: string) => string; warn: (minutes: number) => string; expired: string; expiredToast: string }
> = {
  ko: {
    left: t => `캐시 ${t} 남음`,
    warn: n => `캐시 ${n}분 남음`,
    expired: '캐시 만료',
    expiredToast: '캐시 만료 — 다음 입력은 캐시를 새로 만듦',
  },
  en: {
    left: t => `Cache ${t} left`,
    warn: n => `Cache: ${n} min left`,
    expired: 'Cache expired',
    expiredToast: 'Cache expired — your next input rebuilds it',
  },
  ja: {
    left: t => `キャッシュ残り ${t}`,
    warn: n => `キャッシュ残り${n}分`,
    expired: 'キャッシュ期限切れ',
    expiredToast: 'キャッシュ期限切れ — 次の入力でキャッシュを作り直します',
  },
  zh: {
    left: t => `缓存剩余 ${t}`,
    warn: n => `缓存剩余 ${n} 分钟`,
    expired: '缓存已过期',
    expiredToast: '缓存已过期 — 下次输入将重新创建缓存',
  },
}

const pad = (n: number) => String(n).padStart(2, '0')

// Python 쪽 lib/config.py 와 같은 파일에서 필요한 4개 키만 읽는 최소 TOML 파서.
// 분은 1 이상 정수, countdown 은 불리언, language 는 4종 문자열만 받고,
// 그 밖의 값·다른 섹션의 같은 키는 무시해 기본값을 둔다.
function parseConfig(text: string): CacheNecromancerConfig {
  const cfg = { ...DEFAULT_CONFIG }
  let section = ''
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
  }
  return cfg
}

// 다른 스크립트들과 같은 위치: $CN_ROOT 또는 ~/.cache-necromancer. 없거나 못 읽으면 기본값.
async function loadConfig($: EngineInterface): Promise<CacheNecromancerConfig> {
  try {
    const home = await $.env.get('HOME')
    const root = (await $.env.get('CN_ROOT')) || (home ? `${home}/.cache-necromancer` : undefined)
    if (!root) return DEFAULT_CONFIG
    return parseConfig(await $.fs.read(`${root}/config.toml`))
  } catch {
    return DEFAULT_CONFIG
  }
}

function labelFor(at: number, now: number, cfg: CacheNecromancerConfig): CacheNecromancerLabel {
  const left = cfg.ttlMinutes * MIN_MS - (now - at)
  const text = TEXT[cfg.language]
  if (left <= 0) return { text: text.expired, tone: 'error' }
  const sec = Math.ceil(left / 1000)
  const isWarning = left <= (cfg.ttlMinutes - cfg.warnAfterMinutes) * MIN_MS
  return { text: text.left(`${pad(Math.floor(sec / 60))}:${pad(sec % 60)}`), tone: isWarning ? 'warning' : 'normal' }
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
  const cfg = await read($, config)
  const at = await read($, base)
  const next = at === null || !cfg.countdown ? null : labelFor(at, await $.clock.now(), cfg)
  // 백그라운드 에이전트가 도는 동안은 띠만 숨긴다. 캐시 시계는 흐르므로 토스트 판정은 계속한다
  const shown = next !== null && (await hasBusyAgent($)) ? null : next

  // 글자가 바뀔 때만 쓴다. 쓰면 label을 읽은 띠가 다시 그려진다
  if ((await read($, label))?.text !== shown?.text) await update($, label, () => shown)

  if (at === null || next === null) return
  // 이 기준 시각으로 아직 안 알렸을 때만 토스트. 판정과 기록을 update 콜백 한 번에 (겹친 tick 중복 방지)
  let isFirst = false
  const claim = (prev: CacheNecromancerTime) => {
    isFirst = prev !== at
    return at
  }
  if (next.tone === 'error' && (await read($, expiredFor)) !== at) {
    await update($, expiredFor, claim)
    if (isFirst) $.ui.toast(TEXT[cfg.language].expiredToast)
  }
  if (next.tone === 'warning' && (await read($, warnedFor)) !== at) {
    await update($, warnedFor, claim)
    if (isFirst) $.ui.toast(TEXT[cfg.language].warn(cfg.ttlMinutes - cfg.warnAfterMinutes))
  }
}

// tick 은 표시용 best-effort: 실패(리로드·종료 직후 등)는 다음 tick 이 다시 계산한다.
// 원인 추적용으로 첫 실패만 디버그 로그에 남기고 이후는 조용히 넘긴다
async function logFirstTickError($: EngineInterface, error: unknown): Promise<void> {
  if (await read($, tickErrorLogged)) return
  await update($, tickErrorLogged, () => true)
  const reason = error instanceof Error ? error.message : String(error)
  $.ui.log(`cache-necromancer: countdown tick failed (${reason}); later failures are not logged`, { to: 'debug' })
}

export const register: Register = on => {
  // 설정은 세션 시작 때 한 번 읽는다 (Python 훅과 같은 "설정 변경 후 새 세션" 규칙).
  // 리로드 때도 다시 fire되므로 타이머는 여기서만 건다 (이전 환경의 타이머는 엔진이 버림)
  on('session.start', async ($, e, next) => {
    const cfg = await loadConfig($)
    await update($, config, () => cfg)
    if (cfg.countdown) {
      $.clock.every(1000, () => void tick($).catch(error => logFirstTickError($, error).catch(() => undefined)))
    } else {
      // 띠도 토스트도 없으므로 타이머를 걸지 않는다. 리로드 전에 남은 띠 값은 지운다
      await update($, label, () => null)
    }
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    await update($, base, () => null)
    await update($, label, () => null)
    return next(e)
  })

  // 요청 시작 시각을 잡아 두고, 응답이 와서 캐시를 실제로 읽거나 쓴 경우에만 기준 시각으로 삼는다 (서브에이전트 제외)
  on('turn.step', async function* ($, e, next) {
    const at = e.agentId === undefined ? await $.clock.now() : null
    const r = yield* next(e)
    const u = r.usage
    if (at !== null && u !== null && u.cache_read_input_tokens + u.cache_creation_input_tokens > 0) {
      await update($, base, () => at)
    }
    return r
  })

  // 대기 상태일 때 프롬프트 위 띠 맨 위에 캐시 줄 한 줄. 아래(다른 플러그인·엔진)가 그린 것은 그 밑에 둔다
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    // 답변이 끝난 대기 상태에서만 표시, 설문에는 양보
    if (e.props.isWorking || e.props.hasSurvey) return next(e)
    const line = await read($, label)
    if (line === null) return next(e)

    const below = await next(e)
    const { Box, Text } = $.ui.resolve(e)
    // what-did-i-say 띠와 같은 규격(marginX 1·폭 W·paddingX 2)이라 위아래로 붙으면 한 사각형이 된다
    const W = Math.max(1, e.props.bodyColumns - 2)
    return (
      <Box flexDirection="column">
        <Box backgroundColor={STRIP} marginX={1} paddingX={2} width={W}>
          <Text color={TONE_COLOR[line.tone]}>{line.text}</Text>
        </Box>
        {below}
      </Box>
    )
  })
}
