/** epoch ms, 없으면 null */
export type CacheNecromancerTime = number | null

/** 띠에 그릴 캐시 줄 (tick이 계산, render는 읽기만) */
export type CacheNecromancerLabel = { text: string; tone: 'normal' | 'warning' | 'error' } | null

/** ~/.cache-necromancer/config.toml 에서 세션 시작 때 읽은 값 */
export type CacheNecromancerConfig = {
  /** [general] cache_ttl_minutes */
  ttlMinutes: number
  /** [general] refresh_interval_minutes — 이만큼 지나면 경고 */
  warnAfterMinutes: number
  /** [display] countdown */
  countdown: boolean
  /** [general] language — 띠·토스트 문구 언어 (Python 쪽 lib/i18n.py 와 같은 4종, 기본 en) */
  language: CacheNecromancerLanguage
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
      /** 지금 띠에 그릴 줄 */
      label: CacheNecromancerLabel
      /** 세션 시작 때 읽은 설정 */
      config: CacheNecromancerConfig
    }
  }
}
