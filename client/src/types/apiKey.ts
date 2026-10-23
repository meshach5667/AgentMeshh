export interface ApiKey {
  id: string;
  name: string;
  /** First characters of the key, safe to display. */
  prefix: string;
  scopes: string[];
  deployment_id: string | null;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface CreatedApiKey extends ApiKey {
  /** The secret; returned once at creation. */
  key: string;
}
