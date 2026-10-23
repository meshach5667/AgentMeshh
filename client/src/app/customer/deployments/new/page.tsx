'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { DeployForm } from '@/components/deployments/DeployForm';
import { EmptyState, ErrorState, Notice, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useModel } from '@/hooks/useModels';
import { errorMessage } from '@/lib/errors';

function NewDeployment() {
  const modelId = useSearchParams().get('model');
  const { data: model, isLoading, error } = useModel(modelId);

  if (!modelId) return <EmptyState action={{ href: '/customer/models', label: 'Choose a model' }}>No model selected.</EmptyState>;
  if (isLoading) return <PageSkeleton />;
  if (error || !model) return <ErrorState message={errorMessage(error, 'Model not found')} />;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title={`Deploy ${model.name}`} description="AgentMesh picks a node with enough free capacity and starts the model there." />
      {model.is_community && (
        <Notice tone="warning" title="Unreviewed community model">
          You imported this model from Hugging Face. It runs only on nodes whose providers accept community models, so
          there may be fewer nodes with room for it. Memory figures are estimated from the file size.
        </Notice>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Configuration</CardTitle>
          <CardDescription>
            <Link href="/customer/models" className="underline underline-offset-4">
              Back to the catalog
            </Link>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DeployForm model={model} />
        </CardContent>
      </Card>
    </div>
  );
}

export default function NewDeploymentPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <NewDeployment />
    </Suspense>
  );
}
