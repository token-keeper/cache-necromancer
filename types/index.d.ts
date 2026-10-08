/** epoch ms, 없으면 null */
export type CacheNecromancerTime = number | null

/**
 * 띠에 그릴 캐시 줄 (tick이 계산, render는 읽기만). tone 은 토스트 판정, color 는 남은 시간 10분 구간 글자색,
 * extra 는 카운트다운 뒤에 ' · ' 로 붙는 정보 (폭이 좁으면 앞에서부터 생략)
 */
export type CacheNecromancerLabel = { text: string; tone: 'normal' | 'warning' | 'error'; color: string; extra: string[] } | null

/** Python 이 쓰는 이 세션의 marker 파일에서 읽은 값. 없음·깨짐이면 null */
export type CacheNecromancerMarker = {
  /** wake_count — 마지막 사용자 입력 뒤 깨우기(manual 은 예산 없는 알림 포함) 횟수 */
  wakeCount: number
  /** set_budget_remaining */
  budgetRemaining: number
  /** set_budget_total */
  budgetTotal: number
  /** set_charged_at_ns — 마지막 /cn:set 충전 시각 */
  chargedAtNs: number
  /** last_user_activity_at_ns — 마지막 진짜 사용자 입력 시각 */
  userActivityAtNs: number
} | null

/** ~/.cache-necromancer/config.toml 에서 세션 시작 때 읽은 값 */
export type CacheNecromancerConfig = {
  /** [general] cache_ttl_minutes */
  ttlMinutes: number
  /** [general] refresh_interval_minutes — 이만큼 지나면 경고 + 깨우기 */
  warnAfterMinutes: number
  /** [display] countdown */
  countdown: boolean
  /** [general] language — 띠·토스트 문구 언어 (Python 쪽 lib/i18n.py 와 같은 4종, 기본 en) */
  language: CacheNecromancerLanguage
  /** [wake] arm (없으면 legacy [general] mode — hybrid·auto 는 always) */
  arm: 'manual' | 'always'
  /** [general] max_refresh_count — always 의 목숨 상한 */
  maxRefreshCount: number
  /** [notify] enabled (없으면 legacy 매핑) — 켜지면 깨우기 전에 grace 만큼 기다린다 */
  notify: boolean
  /** [wake] grace_seconds (없으면 legacy [refresh] hybrid_wait_seconds) */
  graceSeconds: number
}

export type CacheNecromancerLanguage = 'ko' | 'en' | 'ja' | 'zh'

declare module 'claude-code' {
  interface PluginState {
    'cache-necromancer': {
      /** 메인 대화에서 캐시를 실제로 읽거나 쓴 마지막 요청의 시작 시각 */
      base: CacheNecromancerTime
      /** 경고 토스트를 보낸 기준 시각 */
      warnedFor: CacheNecromancerTime
      /** 만료 토스트를 보낸 기준 시각 */
      expiredFor: CacheNecromancerTime
      /** refresh.py --now 를 실행한 기준 시각 (기준 시각당 1회) */
      wokeFor: CacheNecromancerTime
      /** 지금 띠에 그릴 줄 */
      label: Shaped<CacheNecromancerLabel>
      /** 세션 시작 때 읽은 설정 */
      config: Shaped<CacheNecromancerConfig>
      /** 마지막으로 읽은 marker (띠 뒤 정보용) */
      marker: CacheNecromancerMarker
      /** marker 를 마지막으로 읽은 시각 (null = 다음 tick 에 다시 읽음) */
      markerReadAt: CacheNecromancerTime
      /** tick 실패를 디버그 로그에 이미 남겼는지 (첫 1회만 남긴다) */
      tickErrorLogged: boolean
      /** 깨우기 실패를 디버그 로그에 이미 남겼는지 (첫 1회만 남긴다) */
      wakeErrorLogged: boolean
    }
  }
}
