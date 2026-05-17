import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Layout from './Layout';
import { api } from '../api/client';
import { HeaderProvider } from '../context/HeaderContext';

vi.mock('../api/client', () => ({
  api: {
    getAuthStatus: vi.fn(),
  },
}));

function renderAt(route, { navClientWidth = 200, itemWidth = 90 } = {}) {
  // Stub layout metrics. JSDOM returns 0 for layout reads, so we have to
  // make the nav look like it overflows in order to exercise the centering
  // path; otherwise we stay on the scrollIntoView branch.
  const origGetBCR = Element.prototype.getBoundingClientRect;
  Object.defineProperty(HTMLElement.prototype, 'scrollWidth', {
    configurable: true,
    get() {
      if (this.getAttribute('aria-label') === 'Main') return itemWidth * 4 + 30;
      return 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get() {
      if (this.getAttribute('aria-label') === 'Main') return navClientWidth;
      return itemWidth;
    },
  });
  Element.prototype.getBoundingClientRect = function getBCR() {
    if (this.getAttribute('aria-label') === 'Main') {
      return { left: 100, top: 0, width: navClientWidth, height: 40 };
    }
    if (this.getAttribute('aria-current') === 'page') {
      // Active item's screen position varies by route; the tests below
      // override this for the route under test.
      return { left: this._mockLeft ?? 100, top: 0, width: itemWidth, height: 40 };
    }
    return origGetBCR.call(this);
  };
  const result = render(
    <MemoryRouter initialEntries={[route]}>
      <HeaderProvider>
        <Layout onOpenSettings={vi.fn()} />
      </HeaderProvider>
    </MemoryRouter>,
  );
  return { ...result, restore: () => { Element.prototype.getBoundingClientRect = origGetBCR; } };
}

describe('Layout — active-nav scroll on mount', () => {
  beforeEach(() => {
    vi.mocked(api.getAuthStatus).mockResolvedValue({ connected: false });
  });

  it('does not scroll the nav when the active item is already at the left edge (/ → Spotify ID)', () => {
    const { container, restore } = renderAt('/');
    const nav = container.querySelector('nav[aria-label="Main"]');
    const active = nav.querySelector('[aria-current="page"]');
    // First nav item sits at the start of the nav scroller (left === navRect.left).
    active.getBoundingClientRect = () => ({ left: 100, top: 0, width: 90, height: 40 });
    // Re-run the effect: rerender or trigger a microtask. The effect ran on
    // mount with whatever rect was active; since first-item left === nav left,
    // scrollLeft should remain 0.
    expect(nav.scrollLeft).toBe(0);
    restore();
  });

  it('centers the active item inside the nav when deep-linked to /upscale', () => {
    // Active item is the 4th pill — its screen-left is well to the right of
    // the nav's screen-left. Computed offset within nav = 300px; centered
    // target = 300 - (200-90)/2 = 245. scrollLeft should be >= 200 (visible).
    const navClientWidth = 200;
    const itemWidth = 90;
    const origGetBCR = Element.prototype.getBoundingClientRect;
    Object.defineProperty(HTMLElement.prototype, 'scrollWidth', {
      configurable: true,
      get() {
        if (this.getAttribute('aria-label') === 'Main') return itemWidth * 4 + 30;
        return 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get() {
        if (this.getAttribute('aria-label') === 'Main') return navClientWidth;
        return itemWidth;
      },
    });
    Element.prototype.getBoundingClientRect = function getBCR() {
      if (this.getAttribute('aria-label') === 'Main') {
        return { left: 100, top: 0, width: navClientWidth, height: 40 };
      }
      if (this.getAttribute('aria-current') === 'page') {
        return { left: 400, top: 0, width: itemWidth, height: 40 };
      }
      return origGetBCR.call(this);
    };
    const { container } = render(
      <MemoryRouter initialEntries={['/upscale']}>
        <HeaderProvider>
          <Layout onOpenSettings={vi.fn()} />
        </HeaderProvider>
      </MemoryRouter>,
    );
    const nav = container.querySelector('nav[aria-label="Main"]');
    // offsetInNav = (400 - 100) + 0 = 300; target = 300 - (200-90)/2 = 245
    expect(nav.scrollLeft).toBe(245);
    Element.prototype.getBoundingClientRect = origGetBCR;
  });
});
