import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DebateStream } from './DebateStream';
import type { Agent, Message } from '@/lib/assemblyTypes';

const agents: Agent[] = [
  {
    id: 'a1',
    name: 'Agent One',
    role: '',
    avatar: null,
    color: 'red',
    status: 'idle',
    currentScore: 0,
  },
];

const messages: Message[] = [
  { id: 'm1', agentId: 'a1', content: 'Hello', round: 0, type: 'generation', scoreImpact: 0 },
];

describe('DebateStream', () => {
  it('renders messages and agent name', () => {
    render(<DebateStream messages={messages} agents={agents} mode="live" />);
    expect(screen.getByText('Agent One')).toBeInTheDocument();
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('toggles auto-scroll label', () => {
    const onToggle = vi.fn();
    render(
      <DebateStream
        messages={messages}
        agents={agents}
        mode="live"
        autoScroll={true}
        onToggleAutoScroll={onToggle}
      />
    );
    const btn = screen.getByText(/Auto-scroll: ON/);
    fireEvent.click(btn);
    expect(onToggle).toHaveBeenCalledWith(false);
  });
});
