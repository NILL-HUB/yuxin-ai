export default {
  title: 'Global Control Config',
  description:
    'Centralized management of platform-wide behavior: model runtime fallback, external media fetching, conversation checkpoints, skill catalog sync, image request policy, vision fallback model, and the desktop client connection address.',
  loadFailed: 'Failed to load global control config',
  saved: 'Global control config saved',
  saveFailed: 'Failed to save global control config',
  save: 'Save All Config',
  sections: {
    runtimeFallback: {
      title: 'Model Runtime Fallback',
      description: 'Controls automatic retry behavior when model requests fail.',
    },
    mediaFetch: {
      title: 'External Media Fetching',
      description: 'Controls fetching external images and other media in conversations, plus the estimated size cap when none is reported.',
    },
    agentCheckpoint: {
      title: 'Conversation Checkpoint',
      description: 'Controls whether conversation-level checkpoints are enabled for saving and restoring conversation state.',
    },
    skillCatalogSync: {
      title: 'Skill Catalog Sync',
      description: 'Controls whether the skill catalog is auto-synced to the knowledge base on startup.',
    },
    imageRequestPolicy: {
      title: 'Image Request Policy',
      description: 'Controls how image generation requests are handled when the bound model is unavailable.',
    },
    visionFallback: {
      title: 'Vision Fallback Model',
      description: 'Sets the fallback model for vision understanding, used when the primary model is unavailable.',
    },
    modelKeyPool: {
      title: 'Model key pool',
      description: 'Controls the circuit-breaker threshold and cooldown recovery for model keys.',
    },
    desktopClient: {
      title: 'Desktop Client Connection',
      description: 'Sets the API server address for the desktop client. Leave empty to connect to the current server origin.',
    },
  },
  fields: {
    enabled: 'Enabled',
    retryAttempts: 'Retry attempts',
    retryAttemptsHint: 'Times to retry failed model requests. Default: 5. Must be greater than 0.',
    retryAttemptsInvalid: 'Retry attempts must be greater than 0',
    maxBytesMb: 'Media size cap (MB)',
    maxBytesMbHint: 'Estimated media size limit when the source reports none. Default: 512 MB. Must be greater than 0.',
    maxBytesMbInvalid: 'Media size cap must be greater than 0',
    policy: 'Request Policy',
    policyHint: 'strict: use the bound model only; auto_upgrade: automatically upgrade to a higher tier model when the bound model is unavailable.',
    policyStrict: 'Strict (strict)',
    policyAutoUpgrade: 'Auto Upgrade (auto_upgrade)',
    provider: 'Provider',
    providerPlaceholder: 'e.g. openai',
    model: 'Model',
    modelPlaceholder: 'e.g. gpt-4o',
    failureThreshold: 'Failure threshold (times)',
    failureThresholdHint: 'A key is tripped after this many consecutive failures. Default 3, must be greater than 0.',
    failureThresholdInvalid: 'Failure threshold must be greater than 0',
    cooldownSeconds: 'Cooldown recovery (seconds)',
    cooldownSecondsHint: 'A tripped key recovers automatically after this duration. Default 300 seconds.',
    apiOrigin: 'Connection Address (API Server)',
    apiOriginPlaceholder: 'e.g. http://127.0.0.1 or https://your-domain.com',
  },
}
