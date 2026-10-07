import { expect, mock, test } from 'claude-code/testing'
import type { Engine, MockClock } from 'claude-code/testing'
import type { On, TurnUsage } from 'claude-code'

const PLUGIN = 'cache-necromancer'
const SURFACES = ['terminal', 'desktop'] as const
const T0 = 1_000_000
const MIN = 60_000
const WARN = '캐시 10분 남음'
const EXPIRED = '캐시 만료 — 다음 입력은 캐시를 새로 만듦'
const CACHED: TurnUsage = { model: 'm', input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 100, cache_creation_input_tokens: 0 }

type World = { clock: MockClock; toasts: string[]; usage: TurnUsage | null }
type Env = Readonly<Record<string, string>>
type Files = Readonly<Record<string, string>>

// 엔진 자리: 띠는 'below' 텍스트, 모델 요청은 world.usage 를 응답 사용량으로 돌려준다.
// 설정 파일은 files 에 있는 경로만 읽히고, 없으면 읽기가 실패한다 (= 파일 없음)
function setup(on: On, env: Env = { HOME: '/home/t' }, files: Files = {}): World {
  const w: World = { clock: mock.clock(on, { now: T0 }), toasts: [], usage: CACHED }
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
    const line = await ui.find({ type: 'Text', text: /캐시/ })
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

test('50분 경과: warning 색 + 경고 토스트 1회, 이후 중복 없음', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(50 * MIN - 1000)
  expect(await shown($)).toMatchObject({ text: '캐시 10:01 남음', color: '#b8c4d4' })
  expect(w.toasts).toEqual([])
  await w.clock.advance(1000)
  expect(await shown($)).toMatchObject({ text: '캐시 10:00 남음', color: 'warning' })
  expect(w.toasts).toEqual([WARN])
  await w.clock.advance(2 * MIN)
  expect(w.toasts).toEqual([WARN])
})

test('60분 경과: error 색 캐시 만료 + 만료 토스트 1회, 이후 중복 없음', async ($, on) => {
  const w = setup(on)
  await start($)
  await step($, w)
  await w.clock.advance(60 * MIN)
  expect(await shown($)).toMatchObject({ text: '캐시 만료', color: 'error' })
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
const CONFIG = '/home/t/.cache-necromancer/config.toml'

test('cache_ttl_minutes·refresh_interval_minutes 를 읽어 남은 시간·경고 시점·문구를 정한다', async ($, on) => {
  const toml = [
    '[general]',
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
  expect(await shown($)).toMatchObject({ text: '캐시 05:00 남음', color: 'warning' })
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
    '/custom/config.toml': '[general]\ncache_ttl_minutes = 30\n',
    [CONFIG]: '[general]\ncache_ttl_minutes = 45\n',
  })
  await start($)
  await step($, w)
  await w.clock.advance(49_000)
  expect((await shown($))?.text).toBe('캐시 29:11 남음')
})

for (const [name, toml] of [
  ['깨진 파일', '[general\ncache_ttl_minutes = = 30\ncountdown = maybe'],
  ['범위 밖·문자열 값', '[general]\ncache_ttl_minutes = 0\nrefresh_interval_minutes = "50"\n[display]\ncountdown = "false"\n'],
] as const) {
  test(`설정을 못 읽으면 기본값(60분·50분 경고·표시) — ${name}`, async ($, on) => {
    const w = setup(on, undefined, { [CONFIG]: toml })
    await start($)
    await step($, w)
    await w.clock.advance(49_000)
    expect((await shown($))?.text).toBe('캐시 59:11 남음')
  })
}
