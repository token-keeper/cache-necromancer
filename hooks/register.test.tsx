import { expect, mock, test } from 'claude-code/testing'
import type { Engine, MockClock } from 'claude-code/testing'
import type { AgentInfo, AgentStatus, On, TurnUsage } from 'claude-code'

const PLUGIN = 'cache-necromancer'
const SURFACES = ['terminal', 'desktop'] as const
const T0 = 1_000_000
const MIN = 60_000
const WARN = '캐시 10분 남음'
const EXPIRED = '캐시 만료 — 다음 입력은 캐시를 새로 만듦'
const CACHED: TurnUsage = { model: 'm', input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 100, cache_creation_input_tokens: 0 }

type World = { clock: MockClock; toasts: string[]; usage: TurnUsage | null; agents: AgentInfo[] }
type Env = Readonly<Record<string, string>>
type Files = Readonly<Record<string, string>>

const CONFIG = '/home/t/.cache-necromancer/config.toml'
// 대부분의 테스트는 한국어 설정으로 돈다. 기본값(en)·다른 언어는 따로 확인한다
const KO: Files = { [CONFIG]: '[general]\nlanguage = "ko"\n' }

// 엔진 자리: 띠는 'below' 텍스트, 모델 요청은 world.usage 를 응답 사용량으로, 에이전트 목록은 world.agents 를 돌려준다.
// 설정 파일은 files 에 있는 경로만 읽히고, 없으면 읽기가 실패한다 (= 파일 없음)
function setup(on: On, env: Env = { HOME: '/home/t' }, files: Files = KO): World {
  const w: World = { clock: mock.clock(on, { now: T0 }), toasts: [], usage: CACHED, agents: [] }
  on('agent.list', () => ({ value: w.agents }))
  mock.env(on, env)
  on('fs.read', (_$, e) => {
    const text = files[e.path]
    if (text === undefined) throw new Error(`ENOENT: ${e.path}`)
    return { value: text }
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('ui.toast', (_$, e) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  on('turn.step', async function* (_$, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: w.usage ? ('end_turn' as const) : null, usage: w.usage }
  })
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>below</Text>
  })
  return w
}

const start = ($: Engine) => $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })

async function step($: Engine, w: World, opts: { agentId?: string; usage?: TurnUsage | null } = {}) {
  w.usage = opts.usage === undefined ? CACHED : opts.usage
  const s = $.turn.step({ turnId: 't', index: 0, model: 'm', messageCount: 1, ...(opts.agentId ? { agentId: opts.agentId } : {}) })
  for await (const _ of s) {
    // 청크 없음
  }
}

const band = (over: { isWorking?: boolean; hasSurvey?: boolean } = {}) => ({
  hasSurvey: false,
  isWorking: false,
  maxRows: 20,
  bodyColumns: 80,
  scroll: { offset: 0, bodyRows: 19 },
  view: {},
  ...over,
})

// 두 surface에 띠를 그려 캐시 줄(글자·색)을 읽는다. 두 surface 결과는 같아야 한다
async function shown($: Engine, over: { isWorking?: boolean; hasSurvey?: boolean } = {}) {
  const seen = []
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'AbovePrompt', props: band(over) })
    const line = (await ui.findAll({ type: 'Text' })).find(t => t.text !== 'below')
    seen.push({ text: line?.text, color: line?.props['color'], tree: await ui.drawn() })
    await ui.unmount()
  }
  expect(seen[1]).toEqual(seen[0])
  return seen[0]
}

test('요청 전에는 tick이 돌아도 띠에 아무것도 더하지 않는다 (아래 그대로)', async ($, on) => {
  const w = setup(on)
  await start($)
  await w.clock.advance(5000)
  const s = await shown($)
  expect(s?.text).toBeUndefined()
  expect(s?.tree).toMatchObject({ type: 'Text', children: ['below'] })
  expect(w.toasts).toEqual([])
})

test('요청 49초 뒤 59:11, 남색 띠(wdis와 같은 규격)가 위·아래 트리가 밑', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(49_000)
  const s = await shown($)
  expect(s).toMatchObject({ text: '캐시 59:11 남음', color: '#b8c4d4' })
  expect(s?.tree).toMatchObject({
    type: 'Box',
    props: { flexDirection: 'column' },
    children: [
      { type: 'Box', props: { backgroundColor: '#1f2d3d', marginX: 1, paddingX: 2, width: 78 } },
      { type: 'Text', children: ['below'] },
    ],
  })
})

test('답변 중엔 표시하지 않고(아래 그대로), 설문이 있으면 양보한다', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(1000)
  expect((await shown($))?.text).toBe('캐시 59:59 남음')
  const working = await shown($, { isWorking: true })
  expect(working?.text).toBeUndefined()
  expect(working?.tree).toMatchObject({ type: 'Text', children: ['below'] })
  const survey = await shown($, { hasSurvey: true })
  expect(survey?.text).toBeUndefined()
  expect(survey?.tree).toMatchObject({ type: 'Text', children: ['below'] })
})

test('50분 경과: 경고색(#ffb454) + 경고 토스트 1회, 이후 중복 없음', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN - 1000)
  expect(await shown($)).toMatchObject({ text: '캐시 10:01 남음', color: '#b8c4d4' })
  expect(w.toasts).toEqual([])
  await w.clock.advance(1000)
  expect(await shown($)).toMatchObject({ text: '캐시 10:00 남음', color: '#ffb454' })
  expect(w.toasts).toEqual([WARN])
  await w.clock.advance(2 * MIN)
  expect(w.toasts).toEqual([WARN])
})

test('60분 경과: 만료색(#ff7b7b) 캐시 만료 + 만료 토스트 1회, 이후 중복 없음', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(60 * MIN)
  expect(await shown($)).toMatchObject({ text: '캐시 만료', color: '#ff7b7b' })
  expect(w.toasts).toEqual([WARN, EXPIRED])
  await w.clock.advance(2 * MIN)
  expect(w.toasts).toEqual([WARN, EXPIRED])
})

test('새 요청이 나가면 60:00부터 다시 세고 경고도 다시 울린다', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(61 * MIN + 500)
  expect(w.toasts).toEqual([WARN, EXPIRED])
  await step($, w)
  await w.clock.advance(500)
  expect((await shown($))?.text).toBe('캐시 60:00 남음')
  await w.clock.advance(50 * MIN)
  expect(w.toasts).toEqual([WARN, EXPIRED, WARN])
})

for (const [name, opts] of [
  ['서브에이전트 요청', { agentId: 'agent-1' }],
  ['실패한 요청(usage 없음)', { usage: null }],
  ['캐시를 읽지도 쓰지도 않은 요청', { usage: { ...CACHED, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } }],
] as const) {
  test(`${name}은 기준 시각을 바꾸지 않는다`, async ($, on) => {
    const w = setup(on)
    await start($)
    await step($, w)
    await w.clock.advance(10_000)
    await step($, w, opts)
    await w.clock.advance(39_000)
    expect((await shown($))?.text).toBe('캐시 59:11 남음')
  })
}

test('캐시를 새로 쓴 요청(cache_creation만)도 기준 시각이 된다', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w, { usage: { ...CACHED, cache_read_input_tokens: 0, cache_creation_input_tokens: 50 } })
  await w.clock.advance(49_000)
  expect((await shown($))?.text).toBe('캐시 59:11 남음')
})

test('session.end(/clear) 뒤에는 표시하지 않는다', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(1000)
  expect((await shown($))?.text).toBe('캐시 59:59 남음')
  await $.session.end({ reason: 'clear', sessionId: 's', resume: { id: 's' } })
  expect((await shown($))?.text).toBeUndefined()
  await w.clock.advance(3000)
  expect((await shown($))?.text).toBeUndefined()
})

test('띠가 떠 있는 동안 1초마다 글자가 바뀌어 다시 그려진다 (label 구독)', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'AbovePrompt', props: band() })
    const before = (await ui.find({ type: 'Text', text: /캐시/ }))?.text
    await w.clock.advance(1000)
    const after = (await ui.find({ type: 'Text', text: /캐시/ }))?.text
    expect(after).not.toBe(before)
    expect(after).toMatch(/^캐시 \d\d:\d\d 남음$/)
    await ui.unmount()
  }
})

// ── 설정 연동 (~/.cache-necromancer/config.toml, 세션 시작 때 읽음) ──

test('cache_ttl_minutes·refresh_interval_minutes 를 읽어 남은 시간·경고 시점·문구를 정한다', async ($, on) => {
  const toml = [
    '[general]',
    'language = "ko"',
    'refresh_interval_minutes = 25   # 경고까지',
    'cache_ttl_minutes = 30',
    '[wake]',
    'cache_ttl_minutes = 5           # 다른 섹션의 같은 키는 무시',
  ].join('\n')
  const w = setup(on, undefined, { [CONFIG]: toml })
  await start($)
  await step($, w)
  await w.clock.advance(49_000)
  expect(await shown($)).toMatchObject({ text: '캐시 29:11 남음', color: '#b8c4d4' })
  await w.clock.advance(25 * MIN - 49_000)
  expect(await shown($)).toMatchObject({ text: '캐시 05:00 남음', color: '#ffb454' })
  expect(w.toasts).toEqual(['캐시 5분 남음'])
  await w.clock.advance(5 * MIN)
  expect((await shown($))?.text).toBe('캐시 만료')
  expect(w.toasts).toEqual(['캐시 5분 남음', EXPIRED])
})

test('[display] countdown = false 면 띠에 아무것도 안 그리고 토스트도 없다', async ($, on) => {
  const w = setup(on, undefined, { [CONFIG]: '[display]\nrecap_style = "box"\ncountdown = false\n' })
  await start($)
  await step($, w)
  await w.clock.advance(61 * MIN)
  const s = await shown($)
  expect(s?.text).toBeUndefined()
  expect(s?.tree).toMatchObject({ type: 'Text', children: ['below'] })
  expect(w.toasts).toEqual([])
})

test('CN_ROOT 가 있으면 그 아래 config.toml 을 읽는다', async ($, on) => {
  const w = setup(on, { HOME: '/home/t', CN_ROOT: '/custom' }, {
    '/custom/config.toml': '[general]\nlanguage = "ko"\ncache_ttl_minutes = 30\n',
    [CONFIG]: '[general]\ncache_ttl_minutes = 45\n',
  })
  await start($)
  await step($, w)
  await w.clock.advance(49_000)
  expect((await shown($))?.text).toBe('캐시 29:11 남음')
})

for (const [name, toml] of [
  ['파일 없음', undefined],
  ['깨진 파일', '[general\ncache_ttl_minutes = = 30\ncountdown = maybe\nlanguage = ko'],
  ['범위 밖·문자열 값', '[general]\ncache_ttl_minutes = 0\nrefresh_interval_minutes = "50"\nlanguage = "fr"\n[display]\ncountdown = "false"\n'],
] as const) {
  test(`설정을 못 읽으면 기본값(60분·50분 경고·표시·en) — ${name}`, async ($, on) => {
    const w = setup(on, undefined, toml === undefined ? {} : { [CONFIG]: toml })
    await start($)
    await step($, w)
    await w.clock.advance(49_000)
    expect((await shown($))?.text).toBe('Cache 59:11 left')
  })
}

test('헤더 모양이 깨진 줄에서 섹션을 끊어, 앞 섹션 키로 잘못 읽지 않는다', async ($, on) => {
  const toml = '[general]\nlanguage = "ko"\n[[broken\ncache_ttl_minutes = 30\n'
  const w = setup(on, undefined, { [CONFIG]: toml })
  await start($)
  await step($, w)
  await w.clock.advance(49_000)
  expect((await shown($))?.text).toBe('캐시 59:11 남음')
})

// 타이머 수를 세려고 mock.clock 대신 clock.every 를 직접 받는다 (같은 이벤트를 두 번 등록할 수 없다)
async function timersAfterStart($: Engine, on: On, files: Files): Promise<number> {
  let timers = 0
  mock.env(on, { HOME: '/home/t' })
  on('fs.read', (_$, e) => {
    const text = files[e.path]
    if (text === undefined) throw new Error(`ENOENT: ${e.path}`)
    return { value: text }
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('clock.every', () => {
    timers += 1
    return { value: undefined }
  })
  await start($)
  return timers
}

test('countdown = false 면 1초 타이머 자체를 걸지 않는다', async ($, on) => {
  expect(await timersAfterStart($, on, { [CONFIG]: '[display]\ncountdown = false\n' })).toBe(0)
})

test('countdown 기본값이면 타이머를 1개 건다 (위 테스트의 대조군)', async ($, on) => {
  expect(await timersAfterStart($, on, {})).toBe(1)
})

test('countdown = false 로 다시 시작하면(리로드) 남아 있던 띠를 바로 지운다', async ($, on) => {
  const files: Record<string, string> = { ...KO }
  const w = setup(on, undefined, files)
  await start($)
  await step($, w)
  await w.clock.advance(1000)
  expect((await shown($))?.text).toBe('캐시 59:59 남음')
  files[CONFIG] = '[display]\ncountdown = false\n'
  await start($) // 시계를 움직이지 않는다 — tick 이 아니라 session.start 가 지워야 한다
  expect((await shown($))?.text).toBeUndefined()
})

// 테스트 환경에는 setTimeout 이 있지만 hooks 모듈 타입(lib: es2023, DOM 없음)에는 선언이 없다
declare function setTimeout(callback: () => void, ms: number): unknown
const wait = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms))

// tick 실패: 시계를 직접 쥐고(주기마다 테스트가 풀어 줌) clock.now 를 실패시킨다
test('tick 이 실패하면 첫 실패만 디버그 로그에 남기고 이후는 조용하다', async ($, on) => {
  let now = T0
  let isFailing = false
  const periods: (() => void)[] = []
  const logs: { text: string; to: string }[] = []
  mock.env(on, { HOME: '/home/t' })
  on('fs.read', () => ({ value: '[general]\nlanguage = "ko"\n' }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('agent.list', () => ({ value: [] }))
  on('clock.now', () => {
    if (isFailing) throw new Error('clock down')
    return { value: now }
  })
  on('clock.every', () => new Promise(resolve => periods.push(() => resolve({ value: undefined }))))
  on('ui.log', (_$, e) => {
    logs.push({ text: e.text, to: e.to })
    return { value: undefined }
  })
  on('turn.step', async function* (_$, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn' as const, usage: CACHED }
  })
  const fire = async () => {
    const period = periods.shift()
    expect(period).toBeDefined()
    period?.()
    // 다음 주기를 청할 때까지(= fn 실행) 기다린 뒤, 그 tick 의 실패 처리까지 끝나도록 조금 더 기다린다
    for (let i = 0; i < 20 && periods.length === 0; i++) await wait(5)
    await wait(20)
  }
  await start($)
  const s = $.turn.step({ turnId: 't', index: 0, model: 'm', messageCount: 1 })
  for await (const _ of s) {
    // 청크 없음
  }
  now += 1000
  isFailing = true
  await fire()
  await fire()
  await fire()
  expect(logs).toHaveLength(1)
  expect(logs[0]).toMatchObject({ to: 'debug' })
  expect(logs[0]?.text).toMatch(/countdown tick failed \(.+\); later failures are not logged/)
})

for (const [lang, line, warn, expired, expiredToast] of [
  ['en', 'Cache 59:11 left', 'Cache: 10 min left', 'Cache expired', 'Cache expired — your next input rebuilds it'],
  ['ko', '캐시 59:11 남음', '캐시 10분 남음', '캐시 만료', '캐시 만료 — 다음 입력은 캐시를 새로 만듦'],
  ['ja', 'キャッシュ残り 59:11', 'キャッシュ残り10分', 'キャッシュ期限切れ', 'キャッシュ期限切れ — 次の入力でキャッシュを作り直します'],
  ['zh', '缓存剩余 59:11', '缓存剩余 10 分钟', '缓存已过期', '缓存已过期 — 下次输入将重新创建缓存'],
] as const) {
  test(`language = "${lang}" 이면 띠·토스트 문구가 그 언어로 나온다`, async ($, on) => {
    const w = setup(on, undefined, { [CONFIG]: `[general]\nlanguage = "${lang}"\n` })
    await start($)
    await step($, w)
    await w.clock.advance(49_000)
    expect((await shown($))?.text).toBe(line)
    await w.clock.advance(60 * MIN)
    expect((await shown($))?.text).toBe(expired)
    expect(w.toasts).toEqual([warn, expiredToast])
  })
}

// ── 백그라운드 에이전트가 도는 동안은 숨김 ──
const agent = (status: AgentStatus): AgentInfo => ({ id: `a-${status}`, description: 'lane', type: 'general-purpose', status })

for (const status of ['pending', 'running', 'waiting'] as const) {
  test(`백그라운드 에이전트가 ${status} 이면 띠를 숨기고, 끝나면 다시 보인다`, async ($, on) => {
    const w = setup(on)
    await start($)
    await step($, w)
    w.agents = [agent('idle'), agent(status)]
    await w.clock.advance(1000)
    const hidden = await shown($)
    expect(hidden?.text).toBeUndefined()
    expect(hidden?.tree).toMatchObject({ type: 'Text', children: ['below'] })
    w.agents = [agent('idle'), agent('completed'), agent('failed'), agent('killed')]
    await w.clock.advance(1000)
    expect((await shown($))?.text).toBe('캐시 59:58 남음')
  })
}

test('에이전트가 도는 동안에도 경고·만료 토스트는 울린다 (캐시 시계는 흐른다)', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  w.agents = [agent('running')]
  await w.clock.advance(60 * MIN)
  expect((await shown($))?.text).toBeUndefined()
  expect(w.toasts).toEqual([WARN, EXPIRED])
})
