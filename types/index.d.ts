/** epoch ms, 없으면 null */
export type CacheNecromancerTime = number | null

/**
 * 띠에 그릴 캐시 줄 (tick이 계산, render는 읽기만). tone 은 토스트 판정, color 는 남은 시간 10분 구간 글자색,
 * extra 는 카운트다운 뒤에 ' · ' 로 붙는 정보 (폭이 좁으면 앞에서부터 생략)
 */
export type CacheNecromancerLabel = { text: string; tone: 'normal' | 'warning' | 'error'; color: string; extra: string[] } | null

/** Python 이 쓰는 이 세션의 marker 파일에서 읽은 값. 없음·깨짐이면 null */
export type CacheNecromancerMarker = {
  /** wake_count — 이번 자리비움(마지막 사용자 입력 뒤)에 실제로 깨운 횟수 */
  wakeCount: number
  /** set_budget_remaining */
  budgetRemaining: number
  /** set_budget_total — /cn:set N 충전량 (>0 이면 덮어쓰기 중). 충전 뒤 깨우기가 있은 다음 사용자가 돌아오면 Python 이 0 으로 비운다 */
  budgetTotal: number
  /** wake_off === true — /cn:set 0·off 로 이 세션 깨우기를 끔 */
  wakeOff: boolean
  /** set_charged_at_ns (없으면 0) — 충전이 바뀌었는지 보는 데만 쓴다 (Number 정밀도 손실 무관) */
  chargedAt: number
} | null

/** ~/.cache-necromancer/config.toml 을 Python 이 해석한 값 (cn_config.py --json 의 config). 파일이 바뀌면 몇 초 안에 다시 읽는다 */
export type CacheNecromancerConfig = {
  /** [general] cache_ttl_minutes */
  ttlMinutes: number
  /** [general] refresh_interval_minutes — 이만큼 지나면 경고 + 깨우기 */
  warnAfterMinutes: number
  /** [display] countdown */
  countdown: boolean
  /** [general] language — 띠·토스트 문구 언어 (Python 쪽 lib/i18n.py 와 같은 4종, 기본 en) */
  language: CacheNecromancerLanguage
  /** [general] auto_wakes — 자리비움마다 자동 깨우기 최대 횟수 (0~10, 아니면 2) */
  autoWakes: number
}

export type CacheNecromancerLanguage = 'ko' | 'en' | 'ja' | 'zh'

/** cn_config.py --json 의 items 한 줄 — 설정 패널 "전체 설정"의 항목 (문구는 Python 이 언어별로 준다) */
export type CacheNecromancerItem = {
  /** section.key — cn_config.py --set 에 그대로 넘긴다 */
  id: string
  label: string
  /** 지금 값 (bool 은 "true"/"false"). 옵션 밖 값이면 어떤 버튼도 강조하지 않는다 */
  current: string
  options: { value: string; text: string }[]
}

/** 설정 패널 아래 알림 줄 (저장됨·이 세션 버튼 결과는 4초 뒤 지움, 실패는 빨강) */
export type CacheNecromancerNote = { text: string; isError: boolean } | null

declare module 'claude-code' {
  interface PluginState {
    'cache-necromancer': {
      /** 메인 대화에서 캐시를 실제로 읽거나 쓴 마지막 요청의 시작 시각 */
      base: CacheNecromancerTime
      /** 경고 토스트를 보낸 기준 시각 */
      warnedFor: CacheNecromancerTime
      /** 만료 토스트를 보낸 기준 시각 */
      expiredFor: CacheNecromancerTime
      /** refresh.py --now 를 실행한 기준 시각 (기준 시각당 1회, 깨우기 자격이 바뀌면 재판정) */
      wokeFor: CacheNecromancerTime
      /**
       * 이 기준 시각으로 마지막 깨우기가 끝난 뒤의 깨우기 자격 서명 `chargedAt|wakeOff|autoWakes` — 남은 깨우기가 있고 서명이 달라지면
       * 1회 더 판정한다. null = 실행 중·리로드 직후 (재판정 안 함)
       */
      wokeCharge: Shaped<string | null>
      /** 지금 띠에 그릴 줄 */
      label: Shaped<CacheNecromancerLabel>
      /** 지금 쓰는 설정 (config.toml 이 바뀌면 몇 초 안에 갱신) */
      config: Shaped<CacheNecromancerConfig>
      /** 마지막으로 읽은 marker (띠 뒤 정보·충전 재판정용) */
      marker: CacheNecromancerMarker
      /** marker 를 마지막으로 읽은 시각 (null = 다음 tick 에 다시 읽음) */
      markerReadAt: CacheNecromancerTime
      /** tick 실패를 디버그 로그에 이미 남겼는지 (첫 1회만 남긴다) */
      tickErrorLogged: boolean
      /** 깨우기 실패를 디버그 로그에 이미 남겼는지 (첫 1회만 남긴다) */
      wakeErrorLogged: boolean
      /** /cn:* 명령 실행 실패를 디버그 로그에 이미 남겼는지 (첫 1회만 남긴다) */
      commandErrorLogged: boolean
      /** 설정 읽기(cn_config.py --json) 실패를 디버그 로그에 이미 남겼는지 (첫 1회만 남긴다) */
      configErrorLogged: boolean
      /** 설정 패널 전체 설정 항목 (마지막 --json 의 items) */
      items: CacheNecromancerItem[]
      /** 설정 패널 "이 세션" 상태 줄 (cn_set.py 무인자 출력) */
      sessionLine: string
      /** 설정 패널 알림 줄 */
      paneNote: CacheNecromancerNote
    }
  }
}
