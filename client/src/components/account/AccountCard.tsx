'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/hooks/useAuth';
import { dateTime } from '@/lib/format';

export function AccountCard() {
  const { user } = useAuth();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Account</CardTitle>
        <CardDescription>Changing your email or password is not available in the dashboard yet.</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid max-w-md grid-cols-[8rem_1fr] gap-y-2 text-sm">
          <dt className="text-muted-foreground">Email</dt>
          <dd>{user?.email}</dd>
          <dt className="text-muted-foreground">Role</dt>
          <dd className="capitalize">{user?.role}</dd>
          <dt className="text-muted-foreground">Member since</dt>
          <dd>{dateTime(user?.created_at)}</dd>
        </dl>
      </CardContent>
    </Card>
  );
}
