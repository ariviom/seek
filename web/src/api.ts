export type Health = {
  status: string;
  database: {
    path: string;
    journal_mode: string;
    foreign_keys: boolean;
    busy_timeout_ms: number;
    sqlite_vec: string;
    fts5: boolean;
  };
};

// Relative URLs so requests follow any reverse-proxy path prefix.
export async function getHealth(): Promise<Health> {
  const response = await fetch("api/health");
  if (!response.ok) throw new Error(`health check failed: ${response.status}`);
  return (await response.json()) as Health;
}
