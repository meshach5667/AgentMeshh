export type UserRole = 'provider' | 'customer' | 'operator' | 'admin';
export interface User { id: string; email: string; role: UserRole; is_active: boolean; created_at: string; }
export interface Provider { id: string; user_id: string; payout_status: string; balance: number; }
export interface Customer { id: string; user_id: string; }