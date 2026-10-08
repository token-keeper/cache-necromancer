import { expect, mock, test } from 'claude-code/testing'
import type { Engine, MockClock } from 'claude-code/testing'
import type { AgentInfo, AgentStatus, On, ProcessRunResult, SessionCompactTrigger, SessionMessage, TurnUsage } from 'claude-code'

const PLUGIN = 'cache-necromancer'
const SURFACES = ['terminal', 'desktop'] as const
const T0 = 1_000_000
const MIN = 60_000
const WARN = '캐시 10분 남음'
const EXPIRED = '캐시 만료 — 다음 입력은 캐시를 새로 만듦'
const CACHED: TurnUsage = { model: 'm', input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 100, cache_creation_input_tokens: 0 }
const SUMMARY: SessionMessage = { role: 'user', text: 'summary', toolUses: [] }

type World = {
  clock: MockClock
  toasts: string[]
  usage: TurnUsage | null
  agents: AgentInfo[]
  // compact 를 거부할 사유(있으면 skip), agent.list 를 붙잡아 둘 관문(tick 경합 재현용)
  compactSkip?: string
  gate?: Promise<void>
  // 깨우기: refresh.py 실행 기록·결과, 제출된 프롬프트, 디버그 로그. runGate 가 있으면 실행을 붙잡아 둔다(grace 재현)
  runs: { argv: readonly string[]; stdin?: string; timeoutMs?: number }[]
  run: Pick<ProcessRunResult, 'exitCode' | 'stderr'>
  runGate?: Promise<void>
  runError?: Error
  submits: string[]
  logs: string[]
  // $.session.id 가 돌려줄 id (marker 파일명)
  sid: string
}
type Env = Readonly<Record<string, string>>
type Files = Readonly<Record<string, string>>

const CONFIG = '/home/t/.cache-necromancer/config.toml'
// 대부분의 테스트는 한국어 설정으로 돈다. 기본값(en)·다른 언어는 따로 확인한다
const KO: Files = { [CONFIG]: '[general]\nlanguage = "ko"\n' }

// 엔진 자리: 띠는 'below' 텍스트, 모델 요청은 world.usage 를 응답 사용량으로, 에이전트 목록은 world.agents 를 돌려준다.
// 설정 파일은 files 에 있는 경로만 읽히고, 없으면 읽기가 실패한다 (= 파일 없음)
function setup(on: On, env: Env = { HOME: '/home/t' }, files: Files = KO): World {
  const w: World = {
    clock: mock.clock(on, { now: T0 }),
    toasts: [],
    usage: CACHED,
    agents: [],
    runs: [],
    run: { exitCode: 2, stderr: `${PING}\n` },
    submits: [],
    logs: [],
    sid: 'sid-1',
  }
  on('agent.list', async () => {
    await w.gate
    return { value: w.agents }
  })
  mock.env(on, env)
  on('fs.read', (_$, e) => {
    const text = files[e.path]
    if (text === undefined) throw new Error(`ENOENT: ${e.path}`)
    return { value: text }
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('session.compact', () => (w.compactSkip === undefined ? { messages: [SUMMARY] } : { skip: w.compactSkip }))
  on('ui.toast', (_$, e) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  on('turn.step', async function* (_$, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: w.usage ? ('end_turn' as const) : null, usage: w.usage }
  })
  on('ui.render', { component: 'PromptHint' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>below</Text>
  })
  on('session.id', () => ({ value: w.sid }))
  on('process.run', async (_$, e) => {
    w.runs.push({ argv: e.argv, stdin: e.init?.stdin, timeoutMs: e.init?.timeoutMs })
    await w.runGate
    if (w.runError) throw w.runError
    return { value: { stdout: '', isStdoutTruncated: false, isStderrTruncated: false, ...w.run } }
  })
  on('prompt.submit', (_$, e) => {
    w.submits.push(e.text)
    return { text: e.text }
  })
  on('ui.log', (_$, e) => {
    w.logs.push(e.text)
    return { value: undefined }
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

// columns: 터미널 폭(e.viewport.columns), null 이면 viewport 없이 그린다
type BandOver = { isWorking?: boolean; isDraft?: boolean; columns?: number | null }

// 입력창 아래 힌트 줄(PromptHint) 자리에 그리는 mount 대상
const band = (surface: (typeof SURFACES)[number], over: BandOver = {}) => {
  const { columns = 80, isWorking = false, isDraft = false } = over
  return {
    plugin: PLUGIN,
    surface,
    component: 'PromptHint' as const,
    props: { isDraft, isWorking, hint: '? for shortcuts' },
    ...(columns === null ? {} : { viewport: { columns, rows: 24 } }),
  }
}

// 두 surface에 띠를 그려 캐시 줄(글자·색)을 읽는다. 두 surface 결과는 같아야 한다.
// 줄은 바깥 Text(전체 글자) 안에 카운트다운 Text·뒤 정보 Text 를 중첩한다: text 는 바깥 글자, color 는 카운트다운 색, extraColor 는 뒤 정보 색
async function shown($: Engine, over: BandOver = {}) {
  const seen = []
  for (const surface of SURFACES) {
    const ui = await $.ui.mount(band(surface, over))
    const [outer, countdown, extra] = (await ui.findAll({ type: 'Text' })).filter(t => t.text !== 'below')
    seen.push({
      text: outer?.text,
      color: countdown?.props['color'],
      extraColor: extra?.props['color'],
      tree: await ui.drawn(),
    })
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

test('답변 중·폭을 모를 때(viewport 없음)는 표시하지 않고(아래 그대로), 글자 치는 중에는 표시한다', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(1000)
  expect((await shown($))?.text).toBe('캐시 59:59 남음')
  for (const over of [{ isWorking: true }, { columns: null }] as const) {
    const hidden = await shown($, over)
    expect(hidden?.text).toBeUndefined()
    expect(hidden?.tree).toMatchObject({ type: 'Text', children: ['below'] })
  }
  expect((await shown($, { isDraft: true }))?.text).toBe('캐시 59:59 남음')
})

test('띠 폭 W 는 터미널 폭 - 2, 엔진 힌트 줄은 띠 아래', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(1000)
  expect((await shown($, { columns: 120 }))?.tree).toMatchObject({
    type: 'Box',
    props: { flexDirection: 'column' },
    children: [{ type: 'Box', props: { width: 118 } }, { type: 'Text', children: ['below'] }],
  })
})

test('50분 경과: 경고 토스트 1회, 이후 중복 없음 (색은 남은 시간 구간대로)', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN - 1000)
  expect(await shown($)).toMatchObject({ text: '캐시 10:01 남음', color: '#ffb454' })
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
    const ui = await $.ui.mount(band(surface))
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
  expect(await shown($)).toMatchObject({ text: '캐시 29:11 남음', color: '#f2d16b' })
  await w.clock.advance(25 * MIN - 49_000)
  expect(await shown($)).toMatchObject({ text: '캐시 05:00 남음', color: '#ff7b7b' })
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

test('countdown = false 여도 1초 타이머를 1개 건다 (깨우기용)', async ($, on) => {
  expect(await timersAfterStart($, on, { [CONFIG]: '[display]\ncountdown = false\n' })).toBe(1)
})

test('countdown 기본값이면 타이머를 1개 건다', async ($, on) => {
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
// 같은 이유로 import.meta.url(테스트 런타임은 ESM)의 선언을 더한다
declare global {
  interface ImportMeta {
    readonly url: string
  }
}
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

// ── /compact 직후 띠 비움 ──
const compact = ($: Engine, trigger: SessionCompactTrigger, agentId?: string) =>
  $.session.compact({ trigger, messages: [SUMMARY], ...(agentId ? { agentId } : {}) })

for (const trigger of ['manual', 'plugin'] as const) {
  test(`${trigger} compact 뒤에는 띠를 비우고, 다음 캐시 요청부터 60:00 으로 다시 센다`, async ($, on) => {
    const w = setup(on)
    await start($)
    await step($, w)
    await w.clock.advance(1000)
    expect((await shown($))?.text).toBe('캐시 59:59 남음')
    await compact($, trigger)
    expect((await shown($))?.text).toBeUndefined()
    await w.clock.advance(3000)
    expect((await shown($))?.text).toBeUndefined()
    await step($, w)
    await w.clock.advance(1000)
    expect((await shown($))?.text).toBe('캐시 59:59 남음')
  })
}

for (const [name, run] of [
  ['거부된(skip) compact', ($: Engine, w: World) => ((w.compactSkip = 'blocked'), compact($, 'manual'))],
  ['서브에이전트 compact', ($: Engine) => compact($, 'manual', 'agent-1')],
  ['auto compact(답변 도중)', ($: Engine) => compact($, 'auto')],
  ['precompute', ($: Engine) => compact($, 'precompute')],
] as const) {
  test(`${name}은 띠를 그대로 둔다`, async ($, on) => {
    const w = setup(on)
    await start($)
    await step($, w)
    await w.clock.advance(1000)
    await run($, w)
    expect((await shown($))?.text).toBe('캐시 59:59 남음')
    await w.clock.advance(1000)
    expect((await shown($))?.text).toBe('캐시 59:58 남음')
  })
}

test('compact 순간 진행 중이던 tick 이 옛 글자를 다시 써도 띠는 되살아나지 않는다', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(1000)
  // tick 을 base 를 읽은 뒤(agent.list)에서 붙잡아 두고 그 사이에 compact
  let release = () => {}
  w.gate = new Promise(resolve => (release = resolve))
  await w.clock.advance(1000)
  await compact($, 'manual')
  release()
  await wait(20)
  expect((await shown($))?.text).toBeUndefined()
  w.gate = undefined
  await w.clock.advance(1000)
  expect((await shown($))?.text).toBeUndefined()
})

// ── 깨우기: 캐시 마지막 적중 + refresh_interval 에 refresh.py --now, exit 2 면 ping 을 프롬프트로 ──
const PING = "[cn:keepalive 10:00, 1/3] reply with exactly 'ok @10:00 (1/3)'. No tools, no analysis. Use minimal output tokens."
const STDIN = JSON.stringify({ session_id: 'sid-1' })

test('refresh_interval 이 지나면 refresh.py --now 를 1회 돌리고, exit 2 면 stderr 를 프롬프트로 낸다', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN - 1000)
  expect(w.runs).toEqual([])
  await w.clock.advance(1000)
  await wait(20)
  expect(w.runs).toHaveLength(1)
  expect(w.runs[0]).toMatchObject({ argv: [expect.any(String), expect.any(String), '--now'], stdin: STDIN, timeoutMs: 10 * MIN })
  expect(w.runs[0]?.argv[0]).toBe('python3')
  expect(w.submits).toEqual([PING])
  // 같은 기준 시각으로는 다시 하지 않는다
  await w.clock.advance(5 * MIN)
  await wait(20)
  expect(w.runs).toHaveLength(1)
  // 깨우기 turn 이 캐시를 읽으면 기준 시각이 갱신되어 다음 주기로 이어진다
  await step($, w)
  await w.clock.advance(50 * MIN)
  await wait(20)
  expect(w.runs).toHaveLength(2)
  expect(w.submits).toEqual([PING, PING])
})

test('실행하는 스크립트는 로드된 플러그인 디렉터리($.plugin.root)의 scripts/refresh.py 다', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN)
  await wait(20)
  // 이 테스트 파일(hooks/register.test.tsx) 옆 플러그인 디렉터리 = 테스트가 로드한 플러그인의 root
  const pluginRoot = decodeURIComponent(import.meta.url.replace(/^file:\/\//, '')).replace(/\/hooks\/[^/]+$/, '')
  expect(w.runs[0]?.argv[1]).toBe(`${pluginRoot}/scripts/refresh.py`)
})

test('grace 동안(실행이 끝나기 전) tick 이 계속 돌아도 중복 실행하지 않는다', async ($, on) => {
  const w = setup(on)
  let release = () => {}
  w.runGate = new Promise(resolve => (release = resolve))
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN)
  await w.clock.advance(30_000)
  await wait(20)
  expect(w.runs).toHaveLength(1)
  expect(w.submits).toEqual([])
  release()
  await wait(20)
  expect(w.runs).toHaveLength(1)
  expect(w.submits).toEqual([PING])
})

test('겹친 tick(앞 tick 이 끝나기 전에 다음 tick)이 동시에 판정해도 1회만 실행한다', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN - 1000)
  // tick 을 agent.list 에서 붙잡아 50:00 이후 tick 여러 개를 쌓은 뒤 한꺼번에 푼다
  let release = () => {}
  w.gate = new Promise(resolve => (release = resolve))
  await w.clock.advance(3000)
  release()
  await wait(20)
  w.gate = undefined
  expect(w.runs).toHaveLength(1)
  expect(w.submits).toEqual([PING])
})

test('stderr 에 경고 줄이 섞여도 ping 줄만 프롬프트로 낸다', async ($, on) => {
  const w = setup(on)
  w.run = { exitCode: 2, stderr: `[cn:warn] invalid wake.arm: 'x' — fallback to 'manual'\n${PING}\n[cn:warn] other\n` }
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN)
  await wait(20)
  expect(w.submits).toEqual([PING])
})

test('exit 2 여도 ping 줄이 없으면 프롬프트를 내지 않는다', async ($, on) => {
  const w = setup(on)
  w.run = { exitCode: 2, stderr: '[cn:warn] only a warning\n' }
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN)
  await wait(20)
  expect(w.runs).toHaveLength(1)
  expect(w.submits).toEqual([])
})

for (const exitCode of [0, 1] as const) {
  test(`exit ${exitCode} 이면 stderr 에 ping 줄이 있어도 프롬프트를 내지 않는다`, async ($, on) => {
    const w = setup(on)
    w.run = { exitCode, stderr: `${PING}\n` }
    await start($)
    await step($, w)
    await w.clock.advance(51 * MIN)
    await wait(20)
    expect(w.runs).toHaveLength(1)
    expect(w.submits).toEqual([])
  })
}

// 시계를 직접 쥔다: 주기는 테스트가 하나씩 풀고, 그 사이 시각은 tick 없이 옮긴다 (리로드·잠자기 복귀 뒤 첫 tick 재현)
function heldClock(on: On) {
  const c = { now: T0, periods: [] as (() => void)[], runs: 0 }
  mock.env(on, { HOME: '/home/t' })
  on('fs.read', () => ({ value: '[general]\nlanguage = "ko"\n' }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('agent.list', () => ({ value: [] }))
  on('ui.toast', () => ({ value: undefined }))
  on('clock.now', () => ({ value: c.now }))
  on('clock.every', () => new Promise(resolve => c.periods.push(() => resolve({ value: undefined }))))
  on('process.run', () => {
    c.runs += 1
    return { value: { stdout: '', stderr: '', exitCode: 0, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('turn.step', async function* (_$, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn' as const, usage: CACHED }
  })
  const fire = async () => {
    c.periods.shift()?.()
    await wait(30)
  }
  return { c, fire }
}

for (const [name, gap, runs] of [
  ['캐시가 이미 만료된 기준 시각(ttl 경과 후 첫 tick)이면 깨우지 않는다', 61 * MIN, 0],
  ['첫 tick 이 정확히 ttl 이면(경계) 깨우지 않는다', 60 * MIN, 0],
  ['첫 tick 이 깨우기 창(경고 ~ 만료) 안이면 깨운다 (대조군)', 55 * MIN, 1],
] as const) {
  test(name, async ($, on) => {
    const { c, fire } = heldClock(on)
    await start($)
    const s = $.turn.step({ turnId: 't', index: 0, model: 'm', messageCount: 1 })
    for await (const _ of s) {
      // 청크 없음
    }
    c.now = T0 + gap
    await fire()
    await fire()
    expect(c.runs).toBe(runs)
  })
}

// 시계를 50분씩 두 번 움직여(1초 주기 약 6000회) 스위트에서 가장 무겁다 — 부하 시 기본 5초 상한에 걸려 넉넉히 둔다
test('process.run 이 실패해도 tick·띠는 계속 돌고 디버그 로그는 1회만 남긴다', { timeoutMs: 15000 }, async ($, on) => {
  const w = setup(on)
  w.runError = new Error('spawn python3 ENOENT')
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN)
  await wait(20)
  expect(w.runs).toHaveLength(1)
  expect(w.submits).toEqual([])
  expect(w.logs).toHaveLength(1)
  // 엔진은 실패한 process.run 을 자기 말로 감싸 reject 한다
  expect(w.logs[0]).toMatch(/^cache-necromancer: wake failed \(.+\); later failures are not logged$/)
  await w.clock.advance(1000)
  expect((await shown($))?.text).toBe('캐시 09:59 남음')
  // 다음 기준 시각의 실패는 로그를 더하지 않는다
  await step($, w)
  await w.clock.advance(50 * MIN)
  await wait(20)
  expect(w.runs).toHaveLength(2)
  expect(w.logs).toHaveLength(1)
})

for (const [name, clear] of [
  ['session.end(/clear)', ($: Engine) => $.session.end({ reason: 'clear', sessionId: 's', resume: { id: 's' } })],
  ['manual compact', ($: Engine) => compact($, 'manual')],
] as const) {
  test(`${name} 뒤에는 기준 시각이 없어 깨우지 않는다`, async ($, on) => {
    const w = setup(on)
    await start($)
    await step($, w)
    await w.clock.advance(10 * MIN)
    await clear($)
    await w.clock.advance(60 * MIN)
    await wait(20)
    expect(w.runs).toEqual([])
  })
}

test('countdown = false 여도 깨우기는 동작하고 띠는 없다', async ($, on) => {
  const w = setup(on, undefined, { [CONFIG]: '[display]\ncountdown = false\n' })
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN)
  await wait(20)
  expect(w.runs).toHaveLength(1)
  expect(w.submits).toEqual([PING])
  expect((await shown($))?.text).toBeUndefined()
})

test('refresh_interval_minutes ≥ cache_ttl_minutes 면 세션 시작 때 "깨우기 꺼짐" 토스트 1회, 깨우지 않는다', async ($, on) => {
  const w = setup(on, undefined, { [CONFIG]: '[general]\nlanguage = "ko"\nrefresh_interval_minutes = 60\ncache_ttl_minutes = 60\n' })
  await start($)
  expect(w.toasts).toEqual(['캐시 깨우기 꺼짐 — refresh_interval_minutes 가 cache_ttl_minutes 이상'])
  await step($, w)
  await w.clock.advance(61 * MIN)
  await wait(20)
  expect(w.runs).toEqual([])
  expect(w.toasts).toEqual(['캐시 깨우기 꺼짐 — refresh_interval_minutes 가 cache_ttl_minutes 이상', EXPIRED])
})

// ── 띠 뒤 정보: 살린 횟수·목숨·예산 (Python 이 쓰는 marker 를 읽음) ──
const MARKER = '/home/t/.cache-necromancer/marker/sid-1.json'
// 기대 시각은 런타임 로컬 시각대로 계산한다 (mod 와 같은 Date 기준)
const hhmm = (ms: number) => {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
// 기준 시각(step 시점 T0) + n × (50분 + grace) + 60분. 알림 기본 켜짐·grace 60초
const until = (n: number, graceSec = 60) => hhmm(T0 + n * (50 * MIN + graceSec * 1000) + 60 * MIN)
const ALWAYS = '[general]\nlanguage = "ko"\nmax_refresh_count = 5\n[wake]\narm = "always"\n'
const MANUAL = '[general]\nlanguage = "ko"\n[wake]\narm = "manual"\n'

async function bandWith($: Engine, on: On, toml: string, mark: string | undefined, over: BandOver = {}) {
  const w = setup(on, undefined, { [CONFIG]: toml, ...(mark === undefined ? {} : { [MARKER]: mark }) })
  await start($)
  await step($, w)
  await w.clock.advance(49_000)
  return (await shown($, over))?.text
}

for (const [name, toml, mark, tail] of [
  ['always: 목숨 = max_refresh_count - wake_count', ALWAYS, '{"wake_count": 0}', ` · 목숨 5 (${until(5)}까지)`],
  ['always 깨운 직후: 살린 횟수 + 줄어든 목숨', ALWAYS, '{"wake_count": 2}', ` · 2번 살림 · 목숨 3 (${until(3)}까지)`],
  ['always 목숨 0', ALWAYS, '{"wake_count": 7}', ` · 7번 살림 · 목숨 0 (${until(0)}까지)`],
  ['manual 예산 있음', MANUAL, '{"set_budget_remaining": 3, "set_budget_total": 3}', ` · 깨우기 3회 남음 (${until(3)}까지)`],
  ['manual 예산 소비 중', MANUAL, '{"wake_count": 1, "set_budget_remaining": 2, "set_budget_total": 3}', ` · 1번 살림 · 깨우기 2회 남음 (${until(2)}까지)`],
  ['manual 예산 없음(알림만 센 wake_count 는 살린 횟수 아님)', MANUAL, '{"wake_count": 2}', ''],
  ['legacy [general] mode = "hybrid" 는 always', '[general]\nlanguage = "ko"\nmode = "hybrid"\nmax_refresh_count = 5\n', '{}', ` · 목숨 5 (${until(5)}까지)`],
  ['[wake] arm 이 legacy mode 보다 우선', '[general]\nlanguage = "ko"\nmode = "auto"\n[wake]\narm = "manual"\n', '{}', ''],
  ['marker 없음', ALWAYS, undefined, ''],
  ['marker 깨짐', ALWAYS, '{"wake_count": ', ''],
  ['marker 가 객체 아님', ALWAYS, '[1, 2]', ''],
] as const) {
  test(`띠 뒤 정보 — ${name}`, async ($, on) => {
    expect(await bandWith($, on, toml, mark)).toBe(`캐시 59:11 남음${tail}`)
  })
}

test('기본 설정(en·manual)·예산 있음 문구', async ($, on) => {
  expect(await bandWith($, on, '', '{"wake_count": 1, "set_budget_remaining": 1, "set_budget_total": 2}')).toBe(
    `Cache 59:11 left · Revived 1× · Wakes 1 left (until ${until(1)})`,
  )
})

for (const [lang, line] of [
  ['ja', `キャッシュ残り 59:11 · 2回蘇生 · 残機 3 (${until(3)}まで)`],
  ['zh', `缓存剩余 59:11 · 已复活 2 次 · 剩余 3 命 (至 ${until(3)})`],
] as const) {
  test(`띠 뒤 정보 문구 — ${lang}`, async ($, on) => {
    const toml = `[general]\nlanguage = "${lang}"\nmax_refresh_count = 5\n[wake]\narm = "always"\n`
    expect(await bandWith($, on, toml, '{"wake_count": 2}')).toBe(line)
  })
}

test('session id 가 marker 파일명 모양이 아니면 읽지 않는다', async ($, on) => {
  const w = setup(on, undefined, { [CONFIG]: ALWAYS, '/home/t/.cache-necromancer/marker/../x.json': '{}' })
  w.sid = '../x'
  await start($)
  await step($, w)
  await w.clock.advance(49_000)
  expect((await shown($))?.text).toBe('캐시 59:11 남음')
})

// "캐시 59:11 남음"(15칸) · "2번 살림"(+11) · "목숨 3 (HH:MM까지)"(+21). 글자 폭 = columns - 6
for (const [columns, tail] of [
  [53, ` · 2번 살림 · 목숨 3 (${until(3)}까지)`],
  [52, ` · 목숨 3 (${until(3)}까지)`],
  [42, ` · 목숨 3 (${until(3)}까지)`],
  [41, ''],
] as const) {
  test(`폭이 좁으면 살린 횟수 → 목숨 순으로 뺀다 (columns ${columns})`, async ($, on) => {
    expect(await bandWith($, on, ALWAYS, '{"wake_count": 2}', { columns })).toBe(`캐시 59:11 남음${tail}`)
  })
}

test('만료되면 뒤 정보를 붙이지 않는다', async ($, on) => {
  const w = setup(on, undefined, { [CONFIG]: ALWAYS, [MARKER]: '{"wake_count": 0}' })
  await start($)
  await step($, w)
  await w.clock.advance(60 * MIN)
  expect((await shown($))?.text).toBe('캐시 만료')
})

test('marker 가 바뀌면 5초 안에 띠에 반영한다', async ($, on) => {
  const files: Record<string, string> = { [CONFIG]: ALWAYS, [MARKER]: '{"wake_count": 0}' }
  const w = setup(on, undefined, files)
  await start($)
  await step($, w)
  await w.clock.advance(1000)
  expect((await shown($))?.text).toBe(`캐시 59:59 남음 · 목숨 5 (${until(5)}까지)`)
  files[MARKER] = '{"wake_count": 1}'
  await w.clock.advance(5000)
  expect((await shown($))?.text).toBe(`캐시 59:54 남음 · 1번 살림 · 목숨 4 (${until(4)}까지)`)
})

test('깨우기를 마치면 다음 tick 에 marker 를 바로 다시 읽는다', async ($, on) => {
  const files: Record<string, string> = { [CONFIG]: ALWAYS, [MARKER]: '{"wake_count": 0}' }
  const w = setup(on, undefined, files)
  w.run = { exitCode: 0, stderr: '' }
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN - 1000)
  // refresh.py 가 marker 를 바꾼 것처럼
  files[MARKER] = '{"wake_count": 1}'
  await w.clock.advance(1000)
  await wait(20)
  expect(w.runs).toHaveLength(1)
  await w.clock.advance(1000)
  expect((await shown($))?.text).toBe(`캐시 09:59 남음 · 1번 살림 · 목숨 4 (${until(4)}까지)`)
})

// ── 리로드: session.start 없이 render·turn.step 만 와도 타이머가 걸린다 (모듈 로드당 1개) ──
function countTimers(on: On): { timers: number } {
  const c = { timers: 0 }
  mock.env(on, { HOME: '/home/t' })
  on('fs.read', () => ({ value: '[general]\nlanguage = "ko"\n' }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('clock.now', () => ({ value: T0 }))
  // 첫 주기를 풀지 않아 타이머 1개 = 호출 1번
  on('clock.every', () => {
    c.timers += 1
    return new Promise<never>(() => {})
  })
  on('ui.render', { component: 'PromptHint' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>below</Text>
  })
  on('turn.step', async function* (_$, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn' as const, usage: CACHED }
  })
  return c
}

async function mountBand($: Engine) {
  const ui = await $.ui.mount(band('terminal'))
  await ui.unmount()
}

async function stepOnce($: Engine) {
  for await (const _ of $.turn.step({ turnId: 't', index: 0, model: 'm', messageCount: 1 })) {
    // 청크 없음
  }
}

test('리로드 뒤 띠만 그려져도(render) 타이머를 1개 걸고, 다시 그려도 늘지 않는다', async ($, on) => {
  const c = countTimers(on)
  await mountBand($)
  await mountBand($)
  expect(c.timers).toBe(1)
})

test('리로드 뒤 요청(turn.step)만 와도 타이머를 1개 걸고, render·session.start 가 더 와도 늘지 않는다', async ($, on) => {
  const c = countTimers(on)
  await stepOnce($)
  await stepOnce($)
  expect(c.timers).toBe(1)
  await mountBand($)
  await start($)
  expect(c.timers).toBe(1)
})

test('session.start 없이 시작해도 첫 tick 이 설정을 읽어 띠·깨우기가 동작한다', async ($, on) => {
  const w = setup(on)
  await step($, w)
  await w.clock.advance(49_000)
  expect((await shown($))?.text).toBe('캐시 59:11 남음')
  await w.clock.advance(50 * MIN - 49_000)
  await wait(20)
  expect(w.runs).toHaveLength(1)
  expect(w.submits).toEqual([PING])
})

test('render 로 먼저 기동한 타이머도 띠를 갱신하고 깨우기(process.run·prompt.submit)를 한다', async ($, on) => {
  const w = setup(on)
  expect((await shown($))?.text).toBeUndefined()
  await step($, w)
  await w.clock.advance(49_000)
  expect((await shown($))?.text).toBe('캐시 59:11 남음')
  await w.clock.advance(50 * MIN - 49_000)
  await wait(20)
  expect(w.runs).toHaveLength(1)
  expect(w.submits).toEqual([PING])
  expect(w.logs).toEqual([])
})

// ── 옛 코드(0.10.0)가 남긴 모양의 label 이 host 에 남은 채 리로드 ──
for (const withStart of [true, false]) {
  test(`0.10.0 모양 label({text,tone})이 남아 있어도 띠·깨우기가 동작한다 (session.start ${withStart ? '옴' : '안 옴'})`, async ($, on) => {
    const w = setup(on)
    let isStale = true
    // shape 태그 없이 저장된 옛 값을 label 을 새로 쓰기 전까지 돌려준다
    on('state.get', (_$, e, next) => {
      if (isStale && e.key === 'label') return { value: { value: { text: '캐시 10:00 남음', tone: 'normal' }, version: 1 } }
      return next(e)
    })
    on('state.set', (_$, e, next) => {
      if (e.key === 'label') isStale = false
      return next(e)
    })
    if (withStart) await start($)
    await step($, w)
    await w.clock.advance(49_000)
    await wait(20)
    expect((await shown($))?.text).toBe('캐시 59:11 남음')
    await w.clock.advance(50 * MIN - 49_000)
    await wait(30)
    expect(w.runs).toHaveLength(1)
    expect(w.logs).toEqual([])
  })
}

test('manual: 충전 뒤 사용자가 돌아온 다음의 알림은 살린 횟수로 세지 않는다', async ($, on) => {
  // /cn:set 3 → 1회 깨움 → 복귀(on_user_prompt: wake_count·remaining·total 0) → 다음 자리비움 알림 1회(wake_count 1)
  const mark = '{"wake_count": 1, "set_budget_remaining": 0, "set_budget_total": 0, "set_charged_at_ns": 100, "last_user_activity_at_ns": 200}'
  expect(await bandWith($, on, MANUAL, mark)).toBe('캐시 59:11 남음')
})

test('manual: /cn:set 직후 "하나만 더" 입력 뒤 떠나 깨우면 소비한 예산만큼 살린 횟수', async ($, on) => {
  // 충전(100) → 깨우기 전 입력(200, 예산·total 유지, wake_count 0) → 자리비움 중 2회 깨움
  const mark = '{"wake_count": 2, "set_budget_remaining": 1, "set_budget_total": 3, "set_charged_at_ns": 100, "last_user_activity_at_ns": 200}'
  expect(await bandWith($, on, MANUAL, mark)).toBe(`캐시 59:11 남음 · 2번 살림 · 깨우기 1회 남음 (${until(1)}까지)`)
})

// ── 생존 시각의 grace: 알림이 켜져 있으면 깨우기마다 grace 만큼 늦다 (lib/config.py 와 같은 legacy 매핑) ──
// 모두 always·목숨 4. general·wake 섹션은 각 경우에 맞춰 직접 적는다
const G = '[general]\nlanguage = "ko"\nmax_refresh_count = 4\n'
for (const [name, toml, grace] of [
  ['[notify] enabled = false 면 grace 없음', `${G}[notify]\nenabled = false\n[wake]\narm = "always"\ngrace_seconds = 300\n`, 0],
  ['[wake] grace_seconds = 300', `${G}[wake]\narm = "always"\ngrace_seconds = 300\n`, 300],
  ['legacy [refresh] hybrid_wait_seconds', `${G}[wake]\narm = "always"\n[refresh]\nhybrid_wait_seconds = 120\n`, 120],
  ['[wake] grace_seconds 가 legacy 보다 우선', `${G}[wake]\narm = "always"\ngrace_seconds = 30\n[refresh]\nhybrid_wait_seconds = 120\n`, 30],
  ['legacy mode = "auto" 는 알림 없음', `${G}mode = "auto"\n`, 0],
  ['legacy system_notification = false', `${G}mode = "hybrid"\n[notify]\nsystem_notification = false\n`, 0],
] as const) {
  test(`생존 시각 grace — ${name}`, async ($, on) => {
    expect(await bandWith($, on, toml, '{}')).toBe(`캐시 59:11 남음 · 목숨 4 (${until(4, grace)}까지)`)
  })
}

// ── 카운트다운 글자색: 남은 시간 10분 구간 6단계 (경계는 위 구간), 뒤 정보는 회청 ──
for (const [left, color] of [
  ['59:59', '#b8c4d4'],
  ['50:00', '#b8c4d4'],
  ['49:59', '#8ec5ff'],
  ['40:00', '#8ec5ff'],
  ['39:59', '#8fe3a1'],
  ['30:00', '#8fe3a1'],
  ['29:59', '#f2d16b'],
  ['20:00', '#f2d16b'],
  ['19:59', '#ffb454'],
  ['10:00', '#ffb454'],
  ['09:59', '#ff7b7b'],
  ['00:01', '#ff7b7b'],
] as const) {
  test(`남은 ${left} 이면 글자색 ${color}`, async ($, on) => {
    const w = setup(on)
    await start($)
    await step($, w)
    const [mm = 0, ss = 0] = left.split(':').map(Number)
    await w.clock.advance(60 * MIN - (mm * 60 + ss) * 1000)
    expect(await shown($)).toMatchObject({ text: `캐시 ${left} 남음`, color })
  })
}

test('ttl 이 60분보다 길어도 남은 분으로 색을 정한다 (90분 ttl: 89:00 회청, 45:00 파랑)', async ($, on) => {
  const w = setup(on, undefined, { [CONFIG]: '[general]\nlanguage = "ko"\ncache_ttl_minutes = 90\nrefresh_interval_minutes = 80\n' })
  await start($)
  await step($, w)
  await w.clock.advance(MIN)
  expect(await shown($)).toMatchObject({ text: '캐시 89:00 남음', color: '#b8c4d4' })
  await w.clock.advance(44 * MIN)
  expect(await shown($)).toMatchObject({ text: '캐시 45:00 남음', color: '#8ec5ff' })
})

test('뒤 정보는 카운트다운 색과 무관하게 회청(#b8c4d4)', async ($, on) => {
  const w = setup(on, undefined, { [CONFIG]: ALWAYS, [MARKER]: '{"wake_count": 0}' })
  await start($)
  await step($, w)
  await w.clock.advance(55 * MIN)
  expect(await shown($)).toMatchObject({ text: `캐시 05:00 남음 · 목숨 5 (${until(5)}까지)`, color: '#ff7b7b', extraColor: '#b8c4d4' })
})
