import { AuthGuard } from '@/components/auth/AuthGuard';
import { DashboardLayout } from '@/components/layout/DashboardLayout';

export default function OperatorLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard roles={['operator', 'admin']}>
      <DashboardLayout>{children}</DashboardLayout>
    </AuthGuard>
  );
}
