'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';

type ButtonProps = React.ComponentProps<typeof Button>;

/** Two-step button for destructive actions: the first click asks, the second performs. */
export function ConfirmButton({
  onConfirm,
  confirmLabel = 'Confirm',
  children,
  disabled,
  variant = 'destructive',
  ...props
}: Omit<ButtonProps, 'onClick'> & { onConfirm: () => void; confirmLabel?: string }) {
  const [asking, setAsking] = useState(false);
  if (asking) {
    return (
      <span className="inline-flex items-center gap-1">
        <Button
          {...props}
          variant="destructive"
          disabled={disabled}
          onClick={() => {
            setAsking(false);
            onConfirm();
          }}
        >
          {confirmLabel}
        </Button>
        <Button size={props.size} variant="ghost" onClick={() => setAsking(false)}>
          Cancel
        </Button>
      </span>
    );
  }
  return (
    <Button {...props} variant={variant} disabled={disabled} onClick={() => setAsking(true)}>
      {children}
    </Button>
  );
}
