export default  {
      title: 'Feature Flags',
      description: 'Manage platform feature flags and enabled states',
      flagCount: 'Flag count',
      warningCount: 'Warnings',
      rollback: 'Rollback action',
      name: 'Flag',
      descriptionLabel: 'Description',
      riskLevel: 'Risk level',
      fallbackBehavior: 'Fallback behavior',
      enabled: 'Enabled',
      on: 'On',
      off: 'Off',
      loadFailed: 'Failed to load feature flags',
      updateFailed: 'Failed to update feature flag',
      poolGovernanceGroup: 'Pool governance',
      poolGovernanceGroupDesc: 'Controls the progressive rollout stages of tool pool governance',
      businessGroup: 'Business Flags',
      challengeNeedsChannel:
        'Challenge verification requires at least one channel (email or phone) enabled',
      distributionGroup: 'Feature Flags',
      distributionGroupDesc:
        'Centrally manage feature toggles; newly added feature switches are consolidated into this list',
      otherGroup: 'Other orchestration flags',
      priorityHint:
        'Priority: Block all > Block sensitive > Observe only (higher priority overrides lower)',
      riskLevels: {
        high: 'High',
        medium: 'Medium',
        low: 'Low',
        unknown: 'Unknown',
      },
      flagNames: {
        ENABLE_ORCHESTRATOR: 'Orchestrator',
        ENABLE_AGENT_METADATA_ROUTING: 'Agent metadata routing',
        ENABLE_TOOL_POOL_RETRIEVAL: 'Tool pool retrieval',
        ENABLE_COST_MODEL_ROUTING: 'Cost model routing',
        ENABLE_MODEL_ASSIGNMENT_POLICY: 'Model assignment policy',
        ENABLE_MULTI_AGENT_EXECUTION: 'Multi-agent routing planning',
        ENABLE_RESULT_SYNTHESIZER: 'Task plan detail',
        ENABLE_ROUTING_LOGS: 'Routing logs',
        ENABLE_AUTO_DEEP_THINKING: 'Auto deep thinking',
        ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY: 'Pool governance - Observe only',
        ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE: 'Pool governance - Block sensitive',
        ENABLE_POOL_GOVERNANCE_BLOCK_ALL: 'Pool governance - Block all',
        ENABLE_CONDUCTOR: 'Conductor decision layer',
        ENABLE_DISTRIBUTION: 'Distribution system',
        AUTH_EMAIL_ENABLED: 'Email login/registration channel',
        AUTH_PHONE_ENABLED: 'Phone login/registration channel',
        AUTH_LOGIN_CHALLENGE_ENABLED: 'New-IP login verification',
      },
      flagDesc: {
        ENABLE_ORCHESTRATOR: 'Enable orchestration router for home intent dispatch',
        ENABLE_AGENT_METADATA_ROUTING: 'Use agent metadata to select candidate agent pools',
        ENABLE_TOOL_POOL_RETRIEVAL: 'Use governed tool pool retrieval for tool candidates',
        ENABLE_COST_MODEL_ROUTING: 'Use cost policy to select model tier and budget hints',
        ENABLE_MODEL_ASSIGNMENT_POLICY:
          'Enable model tier assignment based on routing decision and context',
        ENABLE_MULTI_AGENT_EXECUTION:
          'Allow multi-agent planning in routing decisions; execution layer runs parallel/sequential sub-agents from the TaskPlan',
        ENABLE_RESULT_SYNTHESIZER:
          'Generate detailed task planning metadata; result synthesis execution is not wired',
        ENABLE_ROUTING_LOGS: 'Generate detailed routing logs (hits, cost, fallback info)',
        ENABLE_AUTO_DEEP_THINKING:
          'LLM intent detection auto-triggers deep thinking (disable to fall back to keywords + manual switch)',
        ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY:
          'Stage 1: pool governance gate observes only without blocking (default enabled)',
        ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE:
          'Stage 2: pool governance gate blocks sensitive/dangerous tools only',
        ENABLE_POOL_GOVERNANCE_BLOCK_ALL:
          'Stage 3: pool governance gate enforces full policy filtering',
        ENABLE_CONDUCTOR:
          'Use LLM conductor to replace rule-based orchestration with structured orchestration plans',
        ENABLE_DISTRIBUTION:
          'When enabled, invite code is required at registration and first-level commissions settle; when disabled, invite code is optional and no new commissions are generated',
        AUTH_EMAIL_ENABLED:
          'Enables email+password login, email code login/registration/forgot-password/rebinding and challenge verification',
        AUTH_PHONE_ENABLED:
          'Enables phone+code login, phone code registration/binding and challenge verification',
        AUTH_LOGIN_CHALLENGE_ENABLED:
          'Requires email or phone verification on new-IP login; accounts without a verified channel pass through and log a security event',
      },
      enableEffect: {
        ENABLE_ORCHESTRATOR:
          'Home conversations will go through orchestration flow for intent dispatch, agent selection, tool selection and model assignment, enabling staged routing capabilities',
        ENABLE_AGENT_METADATA_ROUTING:
          'Use agent metadata (capability tags, pool ownership) to filter candidate agent pools, improving agent match accuracy',
        ENABLE_TOOL_POOL_RETRIEVAL:
          'Use governed tool pool retrieval for candidate tools, returning only tools that pass governance policies',
        ENABLE_COST_MODEL_ROUTING:
          'Use cost policy to select model tier and budget, matching the most economical model to task complexity',
        ENABLE_MODEL_ASSIGNMENT_POLICY:
          'Dynamically assign model tier based on routing decision and context, optimizing cost and performance',
        ENABLE_MULTI_AGENT_EXECUTION:
          'Routing decisions may output multi-agent modes; execution layer downgrades to single_agent',
        ENABLE_RESULT_SYNTHESIZER: 'TaskPlanner generates a detailed task plan summary',
        ENABLE_ROUTING_LOGS:
          'Generate detailed routing logs recording agent hits, tool hits, cost and fallback info for observability',
        ENABLE_AUTO_DEEP_THINKING:
          'LLM identifies intent and auto-triggers deep thinking, complex questions get deeper analysis',
        ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY:
          'Pool governance gate enters observe mode, logs tool calls without blocking, for governance data collection',
        ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE:
          'Pool governance gate blocks tools marked as sensitive/dangerous, preventing high-risk tool invocation',
        ENABLE_POOL_GOVERNANCE_BLOCK_ALL:
          'Pool governance gate enforces full policy filtering, all tools must pass governance policy to be invoked',
        ENABLE_CONDUCTOR:
          'Home assistant prioritizes the conductor LLM for intent, complexity, agent dispatch and model tier matching',
        ENABLE_DISTRIBUTION:
          'New registrations must fill in an invite code; first-level commissions settle to the inviter on subordinate recharge/purchase',
        AUTH_EMAIL_ENABLED:
          'Login page shows "email code" method; registration page shows "email code registration"',
        AUTH_PHONE_ENABLED:
          'Login page shows "phone code" method; registration page shows "phone code registration"; security settings support phone binding',
        AUTH_LOGIN_CHALLENGE_ENABLED:
          'On new-IP login, sends a code via enabled and verified channels (email/phone); choose first when both are enabled',
      },
      disableEffect: {
        ENABLE_ORCHESTRATOR:
          'Orchestration routing is disabled and returns a direct answer without entering Agent/tool pools',
        ENABLE_AGENT_METADATA_ROUTING:
          'Skip agent metadata filtering and return an empty agent subset',
        ENABLE_TOOL_POOL_RETRIEVAL: 'Skip tool pool retrieval and return an empty tool subset',
        ENABLE_COST_MODEL_ROUTING:
          'Skip cost policy, use default model tier, may cause simple tasks to use expensive models',
        ENABLE_MODEL_ASSIGNMENT_POLICY:
          'Skip model assignment policy, all tasks use the same model tier, no dynamic optimization',
        ENABLE_MULTI_AGENT_EXECUTION: 'Routing decisions always use single-agent mode',
        ENABLE_RESULT_SYNTHESIZER: 'Use a simplified task plan summary',
        ENABLE_ROUTING_LOGS:
          'Stop generating routing logs, routing logs page will have no new data, cannot trace routing decisions',
        ENABLE_AUTO_DEEP_THINKING:
          'Fall back to keyword matching + manual switch, deep thinking only triggers on explicit user request',
        ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY:
          'Pool governance gate fully disabled, no longer observes or blocks any tool calls',
        ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE:
          'Pool governance gate no longer blocks sensitive tools, only observes (if observe mode is enabled)',
        ENABLE_POOL_GOVERNANCE_BLOCK_ALL:
          'Pool governance gate no longer enforces full policy, falls back to sensitive blocking or observe mode',
        ENABLE_CONDUCTOR: 'Fall back to rule-based orchestration (OrchestratorService)',
        ENABLE_DISTRIBUTION:
          'Invite code becomes optional at registration; existing commission records are kept',
        AUTH_EMAIL_ENABLED:
          'Email verification codes are no longer used for login/registration/challenge; existing email still works for password login',
        AUTH_PHONE_ENABLED:
          'Phone verification codes are no longer used for login/registration/binding; bound phone still works as a password-login identifier',
        AUTH_LOGIN_CHALLENGE_ENABLED:
          'New-IP login no longer requires secondary verification and passes through',
      },
      confirm: {
        enableTitle: 'Confirm Enable: {name}',
        disableTitle: 'Confirm Disable: {name}',
        riskLabel: 'Risk Level',
        actionLabel: 'Action',
        enableAction: 'Enable',
        disableAction: 'Disable',
        effectLabel: 'Impact',
        fallbackLabel: 'Fallback Strategy',
        enableTip: 'Enabling will perform the following behavior:',
        disableTip: 'Disabling will have the following impact:',
        cancel: 'Cancel',
        confirm: 'Confirm',
        confirmEnable: 'Confirm Enable',
        confirmDisable: 'Confirm Disable',
      },
      fallback: {
        direct_answer: 'Direct answer',
        skip_agent_subset: 'Skip agent filtering',
        skip_tool_subset: 'Skip tool filtering',
        safe_cheap_policy: 'Safe low-cost policy',
        default_tier: 'Default model tier',
        single_or_direct: 'Single agent or direct answer',
        empty_summary: 'Empty summary',
        skip_routing_log_payload: 'Skip routing logs',
        keyword_matching_manual_switch: 'Keyword matching + manual switch',
        observe_only: 'Observe only, no blocking',
        no_commission: 'No commission settlement',
        orchestrator: 'Rule-based orchestrator',
        disabled: 'Disabled',
        block: 'Block',
      },
    }
