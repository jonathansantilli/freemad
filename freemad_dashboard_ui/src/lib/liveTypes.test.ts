import { describe, it, expect } from 'vitest';
import { applyEvent, AgentStatus, initialSnapshot } from './liveTypes';

describe('liveTypes.applyEvent', () => {
  it('updates agent status through generate flow', () => {
    const s0 = initialSnapshot('r');
    const s1 = applyEvent(s0, { kind: 'agent_generate_started', agent_id: 'a' });
    expect(s1.agents['a'].status).toBe(AgentStatus.GENERATING);

    const s2 = applyEvent(s1, {
      kind: 'agent_generate_finished',
      agent_id: 'a',
      answer_id: 'ans',
      decision: 'KEEP',
    });
    expect(s2.agents['a'].status).toBe(AgentStatus.WAITING);
    expect(s2.agents['a'].current_answer_id).toBe('ans');
    expect(s2.agents['a'].last_decision).toBe('KEEP');
  });

  it('increments changes_count on critique finished changed', () => {
    const s0 = initialSnapshot('r');
    const s1 = applyEvent(s0, {
      kind: 'agent_critique_finished',
      agent_id: 'a',
      changed: true,
    });
    expect(s1.agents['a'].changes_count).toBe(1);
  });

  it('marks completion on run_completed', () => {
    const s0 = initialSnapshot('r');
    const s1 = applyEvent(s0, { kind: 'run_completed' });
    expect(s1.completed).toBe(true);
  });
});
