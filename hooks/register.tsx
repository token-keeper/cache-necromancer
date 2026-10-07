import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { CacheNecromancerConfig, CacheNecromancerLabel, CacheNecromancerTime } from '../types'

const DEFAULT_CONFIG: CacheNecromancerConfig = { ttlMinutes: 60, warnAfterMinutes: 50, countdown: true }

const base = atom({ plugin: 'cache-necromancer', key: 'base' } as const, null as CacheNecromancerTime)
const warnedFor = atom({ plugin: 'cache-necromancer', key: 'warnedFor' } as const, null as CacheNecromancerTime)
const expiredFor = atom({ plugin: 'cache-necromancer', key: 'expiredFor' } as const, null as CacheNecromancerTime)
const label = atom({ plugin: 'cache-necromancer', key: 'label' } as const, null as CacheNecromancerLabel)
const config = atom({ plugin: 'cache-necromancer', key: 'config' } as const, DEFAULT_CONFIG)

const MIN_MS = 60 * 1000
// 띠 배경. 기본 글자색은 이 배경 대비 7.9:1 (#9a9a9a는 5.0:1)
const STRIP = '#1f2d3d'
const TONE_COLOR = { normal: '#b8c4d4', warning: 'warning', error: 'error' } as const

const pad = (n: number) => String(n).padStart(2, '0')

// Python 쪽 lib/config.py 와 같은 파일에서 필요한 3개 키만 읽는 최소 TOML 파서.
// 값은 정수(1 이상)·불리언만 받고, 그 밖의 값·다른 섹션의 같은 키는 무시해 기본값을 둔다.
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
    const pair = /^([A-Za-z0-9_-]+)\s*=\s*(\S+)$/.exec(line)
    if (!pair) continue
    const [, key, value = ''] = pair
    const minutes = /^\d+$/.test(value) && Number(value) >= 1 ? Number(value) : undefined
    if (section === 'general' && key === 'cache_ttl_minutes' && minutes) cfg.ttlMinutes = minutes
    if (section === 'general' && key === 'refresh_interval_minutes' && minutes) cfg.warnAfterMinutes = minutes
    if (section === 'display' && key === 'countdown' && (value === 'true' || value === 'false')) {
      cfg.countdown = value === 'true'
    }
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
  if (left <= 0) return { text: '캐시 만료', tone: 'error' }
  const sec = Math.ceil(left / 1000)
  const isWarning = left <= (cfg.ttlMinutes - cfg.warnAfterMinutes) * MIN_MS
  return { text: `캐시 ${pad(Math.floor(sec / 60))}:${pad(sec % 60)} 남음`, tone: isWarning ? 'warning' : 'normal' }
}

async function tick($: EngineInterface): Promise<void> {
  const cfg = await read($, config)
  const at = await read($, base)
  const next = at === null || !cfg.countdown ? null : labelFor(at, await $.clock.now(), cfg)

  // 글자가 바뀔 때만 쓴다. 쓰면 label을 읽은 띠가 다시 그려진다
  if ((await read($, label))?.text !== next?.text) await update($, label, () => next)

  if (at === null || next === null) return
  // 이 기준 시각으로 아직 안 알렸을 때만 토스트. 판정과 기록을 update 콜백 한 번에 (겹친 tick 중복 방지)
  let isFirst = false
  const claim = (prev: CacheNecromancerTime) => {
    isFirst = prev !== at
    return at
  }
  if (next.tone === 'error' && (await read($, expiredFor)) !== at) {
    await update($, expiredFor, claim)
    if (isFirst) $.ui.toast('캐시 만료 — 다음 입력은 캐시를 새로 만듦')
  }
  if (next.tone === 'warning' && (await read($, warnedFor)) !== at) {
    await update($, warnedFor, claim)
    if (isFirst) $.ui.toast(`캐시 ${cfg.ttlMinutes - cfg.warnAfterMinutes}분 남음`)
  }
}

export const register: Register = on => {
  // 설정은 세션 시작 때 한 번 읽는다 (Python 훅과 같은 "설정 변경 후 새 세션" 규칙).
  // 리로드 때도 다시 fire되므로 타이머는 여기서만 건다 (이전 환경의 타이머는 엔진이 버림)
  on('session.start', async ($, e, next) => {
    const cfg = await loadConfig($)
    await update($, config, () => cfg)
    $.clock.every(1000, () => void tick($))
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
