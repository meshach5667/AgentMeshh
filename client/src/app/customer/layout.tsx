import { AuthGuard } from '@/components/auth/AuthGuard';
import { DashboardLayout } from '@/components/layout/DashboardLayout';

export default function CustomerLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard roles={['customer']}>
      <DashboardLayout>{children}</DashboardLayout>
    </AuthGuard>
  );
}
