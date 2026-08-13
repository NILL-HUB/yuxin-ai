import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import AgentThought from "../AgentThought.vue";
import { QueueEvent } from "@/config";

vi.mock("@/hooks/use-audio", () => ({
  useAudioPlayer: () => ({
    activeMessageId: { value: "" },
    activeThoughtId: { value: "" },
    activeStreamType: { value: "" },
    thoughtAudioLoading: { value: false },
    startThoughtAudioStream: vi.fn(),
    stopAudioStream: vi.fn(),
  }),
}));

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => (key.startsWith("chat.thought.events.") ? key.split(".").pop() : key),
  }),
}));

vi.mock("@arco-design/web-vue", () => ({
  Message: { warning: vi.fn(), success: vi.fn() },
}));

const mountThought = (props: Record<string, unknown> = {}) =>
  mount(AgentThought, {
    props: {
      loading: false,
      agent_thoughts: [
        {
          id: "thought-1",
          event: QueueEvent.agentThought,
          thought: "????????????????????",
          latency: 1.2,
        },
        {
          id: "thought-2",
          event: QueueEvent.agentAction,
          tool: "create_app",
          tool_input: { timeline: { todos: [{ content: "??????", status: "done" }] } },
          observation: "???????",
          latency: 0.8,
        },
      ],
      default_visible: true,
      ...props,
    },
    global: { stubs: { "icon-copy": true, "icon-pause": true, "icon-play-circle": true, "icon-loading": true } },
  });

describe("AgentThought AICSS render", () => {
  it("renders the reasoning header and tool call cards", () => {
    const wrapper = mountThought();
    expect(wrapper.find(".agent-thought__header").exists()).toBe(true);
    expect(wrapper.find(".agent-thought__cards").exists()).toBe(true);
    expect(wrapper.findAll(".agent-thought-card")).toHaveLength(2);
    expect(wrapper.findAll(".aicss-tool-call")).toHaveLength(2);
    expect(wrapper.find(".aicss-tool-call__status-dot").exists()).toBe(true);
    expect(wrapper.text()).toContain("????????????????????");
    expect(wrapper.text()).toContain("create_app");
  });

  it("filters orchestrator routing observability from user thought cards", () => {
    const wrapper = mountThought({
      agent_thoughts: [
        {
          id: "routing-1",
          event: QueueEvent.agentThought,
          thought: "Orchestrator routing decision",
          observation: JSON.stringify({
            intent: "tool_task",
            execution_mode: "single_agent_with_tools",
            recommended_model_tier: "2",
          }),
          tool: "orchestrator",
          tool_input: {
            intent: "tool_task",
          },
          latency: 0,
        },
        {
          id: "thought-1",
          event: QueueEvent.agentThought,
          thought: "先检查磁盘空间，再生成清理计划",
          latency: 1.2,
        },
      ],
    });

    expect(wrapper.findAll(".agent-thought-card")).toHaveLength(1);
    expect(wrapper.text()).not.toContain("tool_task");
    expect(wrapper.text()).not.toContain("Orchestrator routing decision");
    expect(wrapper.text()).toContain("先检查磁盘空间，再生成清理计划");
  });
});
