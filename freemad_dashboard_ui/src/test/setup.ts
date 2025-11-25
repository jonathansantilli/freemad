import '@testing-library/jest-dom';
import { vi } from 'vitest';

// jsdom lacks scrollIntoView; provide a no-op mock for tests
Element.prototype.scrollIntoView = vi.fn();
