import React from 'react';
import { render, screen } from '@testing-library/react';
import { Sidebar } from './Sidebar';

let pathname = '/provider/nodes/register';
let role = 'provider';
jest.mock('next/navigation', () => ({ usePathname: () => pathname }));
jest.mock('../../hooks/useAuth', () => ({ useAuth: () => ({ user: { role, email: 'p@example.com' }, logout: jest.fn() }) }));
jest.mock('@/providers/ThemeProvider', () => ({ useTheme: () => ({ theme: 'dark', toggleTheme: jest.fn() }) }));

describe('Sidebar', () => {
  it('shows provider links and marks only the most specific match as current', () => {
    render(<Sidebar />);
    expect(screen.getByText('My Nodes')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Add a Machine' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'My Nodes' })).not.toHaveAttribute('aria-current');
  });

  it('shows operator links for admins, grouped, and only pages that exist', () => {
    role = 'admin';
    pathname = '/operator';
    render(<Sidebar />);
    expect(screen.getByText('Audit Log')).toBeInTheDocument();
    expect(screen.getByText('Finance')).toBeInTheDocument();
    expect(screen.getByText('Admin')).toBeInTheDocument();
    expect(screen.queryByText('Network Map')).toBeNull();
  });
});
